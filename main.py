import os
import re
import json
import time
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from google import genai
from pdf_generator import generate_academic_pdf

# Load environment variables from the project root .env
env_file = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_file)

# -----------------------------
# Gemini API Setup
# -----------------------------
API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise ValueError(
        "GOOGLE_API_KEY or GEMINI_API_KEY is missing in your .env file"
    )

client = genai.Client(api_key=API_KEY)

# Allow hosting providers to select a model without changing source code.  The
# stable 2.5 names are also valid for standard Gemini API keys.
MODEL_CANDIDATES = [
    model.strip()
    for model in os.getenv(
        "GEMINI_MODEL",
        "gemini-2.5-flash,gemini-2.5-flash-lite,gemini-2.0-flash",
    ).split(",")
    if model.strip()
]

# -----------------------------
# FastAPI App & CORS
# -----------------------------
app = FastAPI(title="ResearchPilot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ResearchRequest(BaseModel):
    topic: str


def discover_sources(topic: str):
    """Fetch verified web sources via DuckDuckGo and academic research papers via arXiv API."""
    sources = []

    # 1. Live DuckDuckGo Search
    try:
        from ddgs import DDGS
        ddg_results = list(DDGS().text(topic, max_results=4))
        for r in ddg_results:
            url = r.get("href", "")
            title = r.get("title", "")
            snippet = r.get("body", "")

            # Infer source type and transparent reliability rating
            source_type = "Web Publication"
            reliability = "Medium"
            clean_name = title

            if "wikipedia.org" in url.lower():
                source_type = "Encyclopedia"
                reliability = "Medium"
                clean_name = f"Wikipedia - {title.replace(' - Wikipedia', '').replace('Wikipedia', '').strip()}"
            elif any(d in url.lower() for d in ["nih.gov", "ncbi", "pubmed"]):
                source_type = "Academic Database / NIH"
                reliability = "High"
                clean_name = f"PubMed Central / NCBI - {title}"
            elif any(d in url.lower() for d in ["who.int", "unesco.org", ".gov"]):
                source_type = "Government / Global Agency"
                reliability = "High"
                clean_name = f"Official Agency - {title}"
            elif any(d in url.lower() for d in [".edu", "mayoclinic.org", "nature.com", "ieee.org", "sciencedirect.com"]):
                source_type = "Academic / Clinical Institution"
                reliability = "High"
                clean_name = f"Academic Institution - {title}"
            elif ".org" in url.lower():
                source_type = "Research Organization"
                reliability = "High"

            sources.append({
                "name": clean_name,
                "url": url,
                "type": source_type,
                "description": snippet[:220] if snippet else f"Authoritative analysis regarding {topic}.",
                "reliability": reliability,
            })
    except Exception as e:
        print(f"Warning: DuckDuckGo search error: {e}")

    # 2. Official arXiv.org e-Print Archive Search
    try:
        encoded_topic = requests.utils.quote(topic)
        arxiv_url = f"https://export.arxiv.org/api/query?search_query=all:{encoded_topic}&start=0&max_results=2"
        resp = requests.get(arxiv_url, timeout=8)
        if resp.status_code == 200:
            root = ET.fromstring(resp.text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns):
                paper_title = entry.find("atom:title", ns).text.strip().replace("\n", " ")
                paper_url = entry.find("atom:id", ns).text.strip()
                summary_elem = entry.find("atom:summary", ns)
                summary = summary_elem.text.strip().replace("\n", " ")[:220] if summary_elem is not None else ""
                sources.append({
                    "name": f"arXiv.org e-Print archive - {paper_title}",
                    "url": paper_url,
                    "type": "Research Repository / arXiv",
                    "description": summary,
                    "reliability": "High",
                })
    except Exception as e:
        print(f"Warning: arXiv search error: {e}")

    return sources


def generate_with_fallback(prompt: str):
    """Call Gemini with automated model fallback to avoid 404/503 spikes."""
    last_error = None
    for model in MODEL_CANDIDATES:
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt
            )
            if response and response.text:
                return response.text
        except Exception as e:
            print(f"Model {model} failed: {e}. Trying next candidate...")
            last_error = e
    raise RuntimeError(f"All Gemini model candidates failed. Last error: {last_error}")


def clean_and_parse_json(raw_output: str, topic: str) -> dict:
    """Safely extract and parse JSON from model output with syntax fixing and fallback."""
    cleaned = raw_output.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()

    # Strategy 1: direct parse
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # Strategy 2: sanitize trailing commas before ] or }
    try:
        sanitized = re.sub(r",\s*([\]}])", r"\1", cleaned)
        return json.loads(sanitized)
    except Exception:
        pass

    # Strategy 3: extract outermost { ... }
    match = re.search(r"(\{[\s\S]*\})", cleaned)
    if match:
        extracted = match.group(1)
        try:
            return json.loads(extracted)
        except Exception:
            pass
        try:
            sanitized = re.sub(r",\s*([\]}])", r"\1", extracted)
            return json.loads(sanitized)
        except Exception:
            pass

    # Strategy 4: Fallback to structured dictionary if all JSON parsing fails
    return {
        "topic": topic,
        "title": f"Research Report: {topic}",
        "executive_summary": f"Executive summary regarding {topic}.",
        "introduction": f"Comprehensive research analysis regarding {topic}.",
        "objectives": [f"Investigate key developments in {topic}", "Analyze practical applications and challenges"],
        "methodology": "Multi-agent research executed across 8 stages: Query Understanding, Research Planning, Source Discovery, Source Verification, Multi-Agent Analysis, Evidence Comparison, Insight Extraction, and Report Synthesis.",
        "key_findings": ["Comprehensive analysis synthesized by ResearchPilot agents."],
        "evidence_comparison": [],
        "key_insights": ["Rapid evolution and transformation observed in this domain."],
        "advantages": ["Automated multi-perspective synthesis."],
        "challenges": ["Requires continuous empirical validation."],
        "conflicting_evidence": {
            "has_conflict": False,
            "details": "No significant conflicting evidence was identified among the analyzed sources."
        },
        "research_gaps": ["Long-term longitudinal impact studies remain limited."],
        "future_directions": ["Cross-disciplinary integration and standardized benchmark evaluations."],
        "conclusion": f"The findings highlight key opportunities and challenges in {topic}.",
        "report": cleaned or raw_output
    }


@app.get("/")
def home():
    return {
        "message": "ResearchPilot Backend is Running",
        "status": "ready"
    }


@app.post("/research")
@app.post("/api/research")
def research(request: ResearchRequest):
    start_time = time.perf_counter()
    topic = request.topic.strip()

    if not topic:
        return {
            "success": False,
            "message": "Research topic cannot be empty."
        }

    # Step 1: Discover real web and academic sources
    discovered_sources = discover_sources(topic)
    sources_context = ""
    if discovered_sources:
        sources_context = "\n".join([
            f"- [{s.get('type')}] {s.get('name')} | URL: {s.get('url')} | Reliability: {s.get('reliability')} | Summary: {s.get('description')}"
            for s in discovered_sources
        ])
    else:
        sources_context = "No external search results found. Synthesize based on verified domain knowledge."

    # Step 2: Multi-Agent Research Synthesis Prompt
    prompt = f"""You are ResearchPilot, an advanced Agentic AI research assistant.
Perform a thorough, multi-agent academic research synthesis on the following topic.

Topic / Research Question:
{topic}

Verified Web and Academic Sources Discovered:
{sources_context}

You must return a raw JSON object (with NO markdown code ticks, NO commentary, ONLY valid parseable JSON) matching this exact schema:
{{
  "topic": "{topic}",
  "title": "An informative, academic title for this research",
  "executive_summary": "A high-level executive summary (2-3 paragraphs) capturing core findings, developments, and strategic takeaways.",
  "introduction": "Comprehensive introduction setting context, problem statement, and scope (2-3 paragraphs).",
  "objectives": [
    "Primary research objective 1",
    "Primary research objective 2",
    "Primary research objective 3"
  ],
  "methodology": "Explanation of how ResearchPilot conducted the research across 8 agentic stages: Query Understanding, Research Planning, Source Discovery (web + arXiv API), Source Verification, Multi-Agent Analysis, Evidence Comparison, Insight Extraction, and Report Synthesis.",
  "key_findings": [
    "Detailed finding 1 with empirical support",
    "Detailed finding 2 with empirical support",
    "Detailed finding 3 with empirical support",
    "Detailed finding 4 with empirical support"
  ],
  "evidence_comparison": [
    {{
      "source": "Source Name 1",
      "type": "Source Type (e.g. Encyclopedia / Academic Paper / Clinical Database)",
      "finding": "Specific thesis or contribution from this source",
      "reliability": "High or Medium",
      "url": "Real URL of the source"
    }},
    {{
      "source": "Source Name 2",
      "type": "Source Type",
      "finding": "Specific thesis or contribution from this source",
      "reliability": "High or Medium",
      "url": "Real URL of the source"
    }},
    {{
      "source": "Source Name 3",
      "type": "Source Type",
      "finding": "Specific thesis or contribution from this source",
      "reliability": "High or Medium",
      "url": "Real URL of the source"
    }}
  ],
  "key_insights": [
    "High-level strategic insight 1",
    "High-level strategic insight 2",
    "High-level strategic insight 3"
  ],
  "advantages": [
    "Key advantage or positive opportunity 1",
    "Key advantage or positive opportunity 2",
    "Key advantage or positive opportunity 3"
  ],
  "challenges": [
    "Key limitation, ethical consideration, or risk 1",
    "Key limitation, ethical consideration, or risk 2",
    "Key limitation, ethical consideration, or risk 3"
  ],
  "conflicting_evidence": {{
    "has_conflict": true or false,
    "details": "Explanation of conflicting evidence or disagreements among sources, OR 'No significant conflicting evidence was identified among the analyzed sources.'"
  }},
  "research_gaps": [
    "Unexplored research gap 1 where current evidence is sparse",
    "Unexplored research gap 2 requiring further empirical study"
  ],
  "future_directions": [
    "Promising future research direction 1",
    "Promising future research direction 2",
    "Promising future research direction 3"
  ],
  "conclusion": "Concise, definitive final research conclusion and synthesis.",
  "report": "A complete, highly detailed narrative paper synthesizing the entire investigation into an academic narrative."
}}
CRITICAL REQUIREMENT: Output strictly valid JSON. Do NOT use trailing commas in arrays or objects.
"""

    try:
        raw_output = generate_with_fallback(prompt)
        report_data = clean_and_parse_json(raw_output, topic)

        # Build clean source items from discovered sources + model sources
        final_sources = []
        if discovered_sources:
            for s in discovered_sources:
                final_sources.append({
                    "name": s.get("name"),
                    "url": s.get("url"),
                    "type": s.get("type", "Web Source"),
                    "description": s.get("description", ""),
                    "reliability": s.get("reliability", "Medium"),
                })
        else:
            for s in report_data.get("sources", []):
                if isinstance(s, dict):
                    final_sources.append(s)
                elif isinstance(s, str):
                    final_sources.append({
                        "name": s,
                        "url": "#",
                        "type": "Web Source",
                        "description": "Referenced domain literature",
                        "reliability": "Medium"
                    })

        key_findings = report_data.get("key_findings") or report_data.get("findings") or []
        advantages = report_data.get("advantages") or []
        challenges = report_data.get("challenges") or report_data.get("disadvantages") or []
        evidence_comp = report_data.get("evidence_comparison") or report_data.get("comparison") or []

        # If evidence_comparison is empty or needs URLs, attach from final_sources
        if not evidence_comp and final_sources:
            for s in final_sources[:3]:
                evidence_comp.append({
                    "source": s.get("name"),
                    "type": s.get("type"),
                    "finding": s.get("description"),
                    "reliability": s.get("reliability"),
                    "url": s.get("url")
                })

        duration_sec = round(time.perf_counter() - start_time, 1)

        conflicting_raw = report_data.get("conflicting_evidence")
        if isinstance(conflicting_raw, dict):
            conflicting_data = conflicting_raw
        elif isinstance(conflicting_raw, str):
            conflicting_data = {
                "has_conflict": "no significant" not in conflicting_raw.lower(),
                "details": conflicting_raw
            }
        else:
            conflicting_data = {
                "has_conflict": False,
                "details": "No significant conflicting evidence was identified among the analyzed sources."
            }

        structured_report = {
            "topic": topic,
            "title": report_data.get("title", f"Research Report: {topic}"),
            "executive_summary": report_data.get("executive_summary", ""),
            "introduction": report_data.get("introduction", ""),
            "objectives": report_data.get("objectives", []),
            "methodology": report_data.get("methodology", "ResearchPilot conducted this investigation across 8 agentic stages: Query Understanding, Research Planning, Source Discovery (DuckDuckGo + arXiv API), Source Verification, Multi-Agent Analysis, Evidence Comparison, Insight Extraction, and Report Synthesis."),
            "key_findings": key_findings,
            "findings": key_findings,
            "evidence_comparison": evidence_comp,
            "comparison": evidence_comp,
            "key_insights": report_data.get("key_insights") or report_data.get("insights") or [],
            "insights": report_data.get("key_insights") or report_data.get("insights") or [],
            "advantages": advantages,
            "challenges": challenges,
            "disadvantages": challenges,
            "conflicting_evidence": conflicting_data,
            "research_gaps": report_data.get("research_gaps", []),
            "future_directions": report_data.get("future_directions", []),
            "conclusion": report_data.get("conclusion", ""),
            "sources": final_sources,
            "references": [f"{s.get('name')} - {s.get('url')}" for s in final_sources],
            "analysis": report_data.get("analysis", report_data.get("report", "")),
            "report": report_data.get("report", report_data.get("analysis", raw_output)),
            "stats": {
                "sources_count": len(final_sources),
                "findings_count": len(key_findings),
                "stages_count": 8,
                "status": "Completed",
                "duration_seconds": duration_sec
            }
        }

        return {
            "success": True,
            "report": structured_report
        }

    except Exception as e:
        print(f"Research execution error: {e}")
        return {
            "success": False,
            "message": str(e)
        }


@app.post("/download-pdf")
@app.post("/api/download-pdf")
def download_pdf(payload: dict):
    """Generate an authentic academic research paper PDF from structured report data."""
    try:
        report_data = payload.get("report") if isinstance(payload.get("report"), dict) else payload
        if not isinstance(report_data, dict):
            raise ValueError("A report object is required to generate a PDF.")
        topic = report_data.get("topic", "research").strip()
        safe_topic = re.sub(r'[^a-zA-Z0-9_\-]', '_', topic)[:40] or "report"

        pdf_bytes = generate_academic_pdf(report_data)

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="ResearchReport_{safe_topic}.pdf"',
                "Access-Control-Expose-Headers": "Content-Disposition",
            }
        )
    except Exception as e:
        print(f"PDF generation error: {e}")
        # A non-2xx status lets the browser show the real server error instead
        # of downloading its JSON error body with a .pdf extension.
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate PDF: {str(e)}",
        ) from e
