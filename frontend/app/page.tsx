"use client";
import Link from "next/link";
import { useState } from "react";

type Job = {
  id: string;
  topic: string;
  status: string;
  result: null | {
    title: string;
    hook: string;
    audience: string;
    script: string;
    duration_seconds: number;
  };
};
const sections = [
  "Overview",
  "Content Pipeline",
  "Agent Status",
  "Financial Overview",
  "System Health",
];
const demoIdeas = [
  "Why small experiments win",
  "Build a smarter morning routine",
  "Three ways to learn faster",
];
export default function Home() {
  const [section, setSection] = useState("Overview");
  const [topic, setTopic] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  async function generate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setNotice("");
    try {
      const response = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic }),
      });
      if (!response.ok)
        throw new Error(
          "Workflow unavailable. Check the backend connection and owner access settings.",
        );
      const job: Job = await response.json();
      setJobs((previous) => [job, ...previous]);
      setNotice("Concept saved to the backend.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="shell">
      <aside>
        <Link className="brand" href="/">
          LC
          <span>
            LAZY
            <br />
            CAPITALIST
          </span>
        </Link>
        <p className="workspace">OWNER WORKSPACE</p>
        <nav aria-label="Main navigation">
          {sections.map((item, i) => (
            <button
              aria-current={section === item ? "page" : undefined}
              className={section === item ? "active" : ""}
              key={item}
              onClick={() => setSection(item)}
            >
              <span className="nav-icon" aria-hidden="true">
                {["◈", "▤", "◎", "↗", "♡"][i]}
              </span>
              {item}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span className="dot" /> Phase 1 · Foundation
          <p>
            Let AI work.
            <br />
            Let money flow.
          </p>
        </div>
      </aside>
      <main>
        <header>
          <span>
            Workspace <b>/ {section}</b>
          </span>
          <span className="badge">DEMO MODE</span>
        </header>
        <div className="page">
          <div className="heading">
            <div>
              <p className="eyebrow">YOUR AUTONOMOUS BUSINESS, IN FOCUS</p>
              <h1>{section}</h1>
              <p className="muted">
                Build the engine. Keep control of every step.
              </p>
            </div>
            <span className="phase">PHASE 01</span>
          </div>
          <div className="banner">
            <span>◉</span>
            <div>
              <strong>A foundation for what comes next.</strong>
              <p>
                Metrics and agent activity below are demo data. The content form
                runs a real backend workflow when connected. No publishing or
                video generation is enabled.
              </p>
            </div>
          </div>
          {(section === "Overview" || section === "Financial Overview") && (
            <>
              <div className="stats">
                <article>
                  <p>Revenue · demo</p>
                  <h2>CHF 0.00</h2>
                  <small>No monetization connected</small>
                </article>
                <article>
                  <p>AI spend · demo</p>
                  <h2>USD 0.00</h2>
                  <small>Mock provider · no paid calls</small>
                </article>
                <article>
                  <p>Content ideas · demo</p>
                  <h2>
                    03 <span>ideas</span>
                  </h2>
                  <small>Ready for a first experiment</small>
                </article>
                <article>
                  <p>Active agents · demo</p>
                  <h2>
                    01 <span>/ 09</span>
                  </h2>
                  <small>Capitalist · simulated status</small>
                </article>
              </div>
              <p className="caption">
                Illustrative figures only. Actual backend usage is available
                through the protected /finance endpoint. CHF and USD are not
                converted or combined.
              </p>
            </>
          )}
          {(section === "Overview" || section === "Content Pipeline") && (
            <div className="columns">
              <section className="panel">
                <div className="panel-title">
                  <h3>Content studio</h3>
                  <span className="pill">MOCK BY DEFAULT</span>
                </div>
                <p className="muted">
                  One topic. A structured concept and a short-form script.
                </p>
                <form onSubmit={generate}>
                  <label htmlFor="topic">
                    What should your next video explore?
                  </label>
                  <textarea
                    id="topic"
                    minLength={3}
                    maxLength={300}
                    required
                    value={topic}
                    onChange={(e) => setTopic(e.target.value)}
                    placeholder="e.g. How to build better habits with small experiments"
                  />
                  <button className="primary" disabled={busy}>
                    {busy ? "Creating concept…" : "Generate concept →"}
                  </button>
                  <p role="status" className="muted">
                    {notice}
                  </p>
                </form>
                {jobs.map((job) => (
                  <article className="result" key={job.id}>
                    <span className="pill">{job.status}</span>
                    <h3>{job.result?.title}</h3>
                    <p>{job.result?.hook}</p>
                    <p>{job.result?.script}</p>
                    <small>
                      {job.result?.duration_seconds}s · {job.result?.audience}
                    </small>
                  </article>
                ))}
              </section>
              <section className="panel">
                <div className="panel-title">
                  <h3>In the pipeline</h3>
                  <span className="pill">DEMO</span>
                </div>
                {demoIdeas.map((idea, i) => (
                  <div className="idea" key={idea}>
                    <span className="number">0{i + 1}</span>
                    <div>
                      <h4>{idea}</h4>
                      <small>Short-form video · Concept</small>
                    </div>
                    <span className="arrow">↗</span>
                  </div>
                ))}
                <div className="empty-note">
                  Your next idea starts with a single topic.
                </div>
              </section>
            </div>
          )}
          {(section === "Overview" || section === "Agent Status") && (
            <section className="panel agents">
              <div className="panel-title">
                <h3>Your team, taking shape</h3>
                <span className="pill">DEMO STATUS</span>
              </div>
              <div className="agent-grid">
                {[
                  "Capitalist",
                  "Creative Genius",
                  "Content Factory",
                  "Auditor",
                ].map((name, i) => (
                  <div key={name}>
                    <span className="agent-symbol">
                      {["◈", "✧", "▤", "◎"][i]}
                    </span>
                    <h4>{name}</h4>
                    <small>
                      <span className={i === 0 ? "dot" : "dot gray"} />
                      {i === 0
                        ? "Foundation workflow"
                        : "Planned · not running"}
                    </small>
                  </div>
                ))}
              </div>
            </section>
          )}
          {section === "System Health" && (
            <section className="panel">
              <h3>System connections</h3>
              {[
                "Backend: configure BACKEND_URL and verify /health",
                "AI: deterministic mock by default",
                "Supabase: schema prepared; not connected",
                "Publishing: disabled",
                "Billing and analytics: not connected",
              ].map((text) => (
                <p className="health" key={text}>
                  {text}
                </p>
              ))}
              <p className="muted">
                This screen does not poll live infrastructure.
              </p>
            </section>
          )}
          <footer>
            <span>LAZY CAPITALIST</span>
            <span>Owner controlled. Built to grow.</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
