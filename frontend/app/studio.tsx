"use client";
import { useState } from "react";
type Job = { id: string; topic: string };
type State = {
  steps: {
    name: string;
    status: string;
    attempts: number;
    error: string | null;
    result: unknown;
  }[];
  simulation: boolean;
};
export default function Studio() {
  const [jobs, setJobs] = useState<Job[]>([]),
    [selected, setSelected] = useState(""),
    [state, setState] = useState<State | null>(null),
    [paused, setPaused] = useState(false),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [costs, setCosts] = useState<unknown>(null);
  async function api(path: string, body?: unknown) {
    const r = await fetch(`/api/jobs?path=${encodeURIComponent(path)}`, {
      method: body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json" },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const result = await r.json();
    if (!r.ok) throw Error(JSON.stringify(result.detail));
    return result;
  }
  async function refresh() {
    try {
      setJobs(await api("/jobs"));
      setCosts(await api("/finance"));
      setPaused((await api("/system")).paused);
    } catch (e) {
      setError(String(e));
    }
  }
  async function act(path: string, body?: unknown) {
    setBusy(true);
    setError("");
    try {
      const result = await api(path, body);
      if (path.includes("/pause")) setPaused(result.paused);
      else setState(result);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel agents">
      <div className="panel-title">
        <h3>Lokales Video-Teststudio</h3>
        <span className="pill">SIMULATION · KEIN YOUTUBE-UPLOAD</span>
      </div>
      <p className="muted">
        Synthetische Testmedien, keine fertige Produktion. Fakten und eigener
        Mehrwert benötigen menschliche Prüfung. Kosten und Einnahmen werden
        nicht simuliert als Ist-Werte ausgewiesen.
      </p>
      <button disabled={busy} onClick={() => void refresh()}>
        Warteschlange aktualisieren
      </button>{" "}
      <button
        disabled={busy}
        onClick={() => void act("/system/pause", { paused: !paused })}
      >
        {paused ? "Fortsetzen" : "Global pausieren"}
      </button>
      <p role="status">{error}</p>
      <details>
        <summary>Kosten und Limits (USD)</summary>
        <pre style={{ whiteSpace: "pre-wrap" }}>
          {JSON.stringify(costs, null, 2)}
        </pre>
      </details>
      <label htmlFor="queue">Gespeicherte Aufträge</label>
      <select
        id="queue"
        value={selected}
        onChange={(e) => {
          setSelected(e.target.value);
          setState(null);
        }}
      >
        <option value="">Auftrag wählen</option>
        {jobs.map((j) => (
          <option key={j.id} value={j.id}>
            {j.topic}
          </option>
        ))}
      </select>
      {selected && (
        <>
          <p>
            <button
              disabled={busy}
              onClick={() => void act(`/jobs/${selected}/workflow`)}
            >
              Status laden
            </button>{" "}
            <button
              disabled={busy || paused}
              onClick={() => void act(`/jobs/${selected}/run`, {})}
            >
              Ausführen / fortsetzen
            </button>{" "}
            <button
              disabled={busy}
              onClick={() => void act(`/jobs/${selected}/reconcile`, {})}
            >
              Unterbrechung abgleichen
            </button>
          </p>
          {state && (
            <>
              <ol>
                {state.steps.map((s) => (
                  <li key={s.name}>
                    {s.name}: {s.status} · Versuche {s.attempts} {s.error}
                    <details>
                      <summary>Ergebnis</summary>
                      <pre style={{ whiteSpace: "pre-wrap" }}>
                        {JSON.stringify(s.result, null, 2)}
                      </pre>
                    </details>
                  </li>
                ))}
              </ol>
              {state.steps.find((s) => s.name === "preview")?.status ===
                "succeeded" && (
                <>
                  <video
                    controls
                    width="240"
                    src={`/api/jobs?path=${encodeURIComponent(`/jobs/${selected}/video`)}`}
                    aria-label="Simulierte Video-Vorschau"
                  />
                  <p>
                    <button
                      disabled={busy || paused}
                      onClick={() => {
                        if (
                          window.confirm(
                            "Qualität, Rechte und Vorschau geprüft? Nur simulierten privaten Upload freigeben?",
                          )
                        )
                          void act(`/jobs/${selected}/approval`, {
                            approved: true,
                            privacy: "private",
                          });
                      }}
                    >
                      Nach Prüfung privat freigeben
                    </button>
                  </p>
                </>
              )}
            </>
          )}
        </>
      )}
      <p className="muted">
        Globale Pause verhindert neue Arbeit; bereits begonnene Schritte können
        abschliessen. YouTube-Adapter: implementiert, deaktiviert und nicht
        verbunden. Fertige Produktion aus dem Skript: noch nicht implementiert.
        Leistungsdaten und Einnahmen: unbekannt.
      </p>
    </section>
  );
}
