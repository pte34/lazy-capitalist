"use client";
import { useState, useRef } from "react";
type Order = {
  id: string;
  status: string;
  plan: unknown;
  costs: unknown;
  research: unknown;
  videos: {
    job_id: string;
    number: number;
    workflow: {
      steps: { name: string; status: string; error: string | null }[];
    };
  }[];
};
export default function CommandCenter() {
  const [text, setText] = useState(
      "Erstelle 5 Videos über aktuelle KI-Trends. Maximal CHF 3 Budget.",
    ),
    [order, setOrder] = useState<Order | null>(null),
    [plan, setPlan] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [ids, setIds] = useState<Order[]>([]);
  const key = useRef({ text: "", id: "" });
  async function api(path: string, body?: unknown, requestKey?: string) {
    const r = await fetch(`/api/jobs?path=${encodeURIComponent(path)}`, {
      method: body === undefined ? "GET" : "POST",
      headers: {
        "Content-Type": "application/json",
        ...(requestKey ? { "Idempotency-Key": requestKey } : {}),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const value = await r.json();
    if (!r.ok) throw Error(JSON.stringify(value.detail));
    return value;
  }
  async function act(path: string, body?: unknown, requestKey?: string) {
    setBusy(true);
    setNotice("");
    try {
      const value = await api(path, body, requestKey);
      if (Array.isArray(value)) setIds(value);
      else {
        setOrder(value);
        setPlan(JSON.stringify(value.plan, null, 2));
      }
      setNotice(
        "Lokaler Auftrag gespeichert. Keine externen Aktionen freigegeben.",
      );
    } catch (e) {
      setNotice(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel agents">
      <div className="panel-title">
        <h3>Command Center</h3>
        <span className="pill">LOKAL · CHF-CAP · KEIN LIVE-PUBLISHING</span>
      </div>
      <p className="muted">
        YouTube: Adapter vorbereitet, deaktiviert. TikTok und Instagram: spätere
        Plattformen ohne Adapter. Aktuelle Trends werden nicht recherchiert;
        Testhypothesen sind synthetisch. CHF wird nicht in USD umgerechnet.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (key.current.text !== text || !key.current.id)
            key.current = { text, id: crypto.randomUUID() };
          void act("/commands", { text }, key.current.id);
        }}
      >
        <label htmlFor="command">Strukturierter Auftragseingang</label>
        <textarea
          id="command"
          maxLength={3000}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <button className="primary" disabled={busy}>
          Auftrag planen
        </button>{" "}
        <button
          type="button"
          disabled={busy}
          onClick={() => void act("/commands")}
        >
          Gespeicherte Aufträge laden
        </button>
      </form>
      <p role="status">{notice}</p>
      {ids.map((o) => (
        <p key={o.id}>
          <button disabled={busy} onClick={() => void act(`/commands/${o.id}`)}>
            {o.id} · {o.status}
          </button>
        </p>
      ))}
      {order && (
        <>
          <h4>
            Auftrag {order.id} · {order.status}
          </h4>
          <label htmlFor="command-plan">
            Editierbarer Plan (Thema, Anzahl, Sprache, Format, CHF-Budget,
            Quellenzeitraum, Plattform, Zielgruppe, Ton, Länge,
            Ein-/Ausschlüsse, Referenzen und eigene Texte)
          </label>
          <textarea
            id="command-plan"
            style={{ minHeight: 300 }}
            value={plan}
            onChange={(e) => setPlan(e.target.value)}
          />
          <p className="muted">
            Referenzen werden nur gespeichert, nicht abgerufen oder als
            Nutzungsrecht gewertet. review_required erst nach bewusster
            Bearbeitung auf false setzen. Eigene Texte werden als nicht
            vertrauenswürdige Daten gerendert, nie ausgeführt.
          </p>
          <button
            disabled={busy}
            onClick={() => {
              try {
                void act(`/commands/${order.id}/plan`, JSON.parse(plan));
              } catch {
                setNotice("Plan ist kein gültiges JSON.");
              }
            }}
          >
            Plan speichern
          </button>{" "}
          <button
            disabled={busy}
            onClick={() => void act(`/commands/${order.id}/approve`, {})}
          >
            Nur lokale Produktion freigeben
          </button>{" "}
          <button
            disabled={busy}
            onClick={() => void act(`/commands/${order.id}/run`, {})}
          >
            Lokal produzieren / fortsetzen
          </button>{" "}
          <button
            disabled={busy}
            onClick={() => void act(`/commands/${order.id}`)}
          >
            Status aktualisieren
          </button>
          <p className="muted">
            Produktionsfreigabe ist keine Veröffentlichungsfreigabe. Dieser
            Auftrag erzeugt nur lokale Vorschauen. Pausen und Teilfehler
            behalten den Fortschritt.
          </p>
          <details open>
            <summary>Kosten und Quellenstatus</summary>
            <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
              {JSON.stringify(
                { costs: order.costs, research: order.research },
                null,
                2,
              )}
            </pre>
          </details>
          <div className="columns">
            {order.videos.map((v) => (
              <article className="panel" key={v.job_id}>
                <h4>
                  Video {v.number} · {v.job_id}
                </h4>
                <ul>
                  {v.workflow.steps.map((s) => (
                    <li key={s.name}>
                      {s.name}: {s.status} {s.error}
                    </li>
                  ))}
                </ul>
                {v.workflow.steps.find((s) => s.name === "preview")?.status ===
                  "succeeded" && (
                  <video
                    aria-label={`Auftragsvideo ${v.number}`}
                    controls
                    width="240"
                    src={`/api/jobs?path=${encodeURIComponent(`/jobs/${v.job_id}/video`)}`}
                  />
                )}
              </article>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
