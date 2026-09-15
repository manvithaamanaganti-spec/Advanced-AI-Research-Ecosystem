import { useState } from "react";
import "./App.css";

function App() {
  const [topic, setTopic] = useState("");
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const startResearch = async () => {
    if (!topic.trim()) {
      setError("Please enter a research topic.");
      return;
    }

    setLoading(true);
    setError("");
    setReport(null);

    try {
      const response = await fetch("http://127.0.0.1:8000/research", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          topic: topic,
        }),
      });

      if (!response.ok) {
        throw new Error("Backend request failed");
      }

      const data = await response.json();

      if (data.success) {
        setReport(data.report);
      } else {
        setError(data.message || "Research failed.");
      }
    } catch (err) {
      setError(
        "Cannot connect to the backend. Make sure FastAPI is running on port 8000."
      );
    }

    setLoading(false);
  };

  return (
    <div className="app">

      <header className="header">
        <h1>ADVANCED AI RESEARCH ECOSYSTEM</h1>
        <p>Agentic AI powered research and intelligence platform</p>
      </header>

      <main>

        <section className="search-section">
          <h2>Enter your research topic</h2>

          <div className="search-box">
            <input
              type="text"
              placeholder="Example: Artificial Intelligence in Healthcare"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
            />

            <button onClick={startResearch} disabled={loading}>
              {loading ? "RESEARCHING..." : "START RESEARCH"}
            </button>
          </div>

          {error && <p className="error">{error}</p>}
        </section>

        <section className="agents">

          <div className="card">
            <div className="icon">🔍</div>
            <h3>Research Planning</h3>
            <p>
              Understand the topic and create a research plan.
            </p>
          </div>

          <div className="card">
            <div className="icon">📚</div>
            <h3>Source Discovery</h3>
            <p>
              Find relevant research sources and information.
            </p>
          </div>

          <div className="card">
            <div className="icon">🧠</div>
            <h3>Multi-Agent Analysis</h3>
            <p>
              Analyze information using specialized AI agents.
            </p>
          </div>

          <div className="card">
            <div className="icon">📊</div>
            <h3>Evidence Comparison</h3>
            <p>
              Compare evidence and identify reliable findings.
            </p>
          </div>

          <div className="card">
            <div className="icon">💡</div>
            <h3>Key Insights</h3>
            <p>
              Extract important insights from the research.
            </p>
          </div>

          <div className="card">
            <div className="icon">📄</div>
            <h3>Research Report</h3>
            <p>
              Generate a structured research report.
            </p>
          </div>

        </section>

        {loading && (
          <section className="loading">
            <h2>🤖 ResearchPilot is working...</h2>
            <p>AI agents are researching your topic.</p>
          </section>
        )}

        {report && (
          <section className="report">

            <h2>📄 Research Report</h2>

            {Object.entries(report).map(([key, value]) => (
              <div className="report-section" key={key}>

                <h3>
                  {key
                    .replace(/_/g, " ")
                    .replace(/\b\w/g, (c) => c.toUpperCase())}
                </h3>

                {Array.isArray(value) ? (
                  <ul>
                    {value.map((item, index) => (
                      <li key={index}>{item}</li>
                    ))}
                  </ul>
                ) : (
                  <p>{String(value)}</p>
                )}

              </div>
            ))}

          </section>
        )}

      </main>

    </div>
  );
}

export default App;