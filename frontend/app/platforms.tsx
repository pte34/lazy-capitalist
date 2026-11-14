"use client";
import { useState } from "react";
type State = {
  coverage: string;
  events: {
    id: string;
    kind: string;
    platform: string;
    channel_id: string;
    payload: string;
  }[];
  channels: {
    platform: string;
    channel_id: string;
    blocked: number;
    review_note: string | null;
  }[];
  platforms: unknown;
};
export default function Platforms() {
  const [state, setState] = useState<State | null>(null),
    [channel, setChannel] = useState("local-youtube"),
    [kind, setKind] = useState("copyright_strike"),
    [source, setSource] = useState("owner_report"),
    [note, setNote] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false);
  async function api(path: string, body?: unknown) {
    const r = await fetch(`/api/jobs?path=${encodeURIComponent(path)}`, {
      method: body === undefined ? "GET" : "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": crypto.randomUUID(),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const v = await r.json();
    if (!r.ok) throw Error(JSON.stringify(v.detail));
    return v;
  }
  async function act(path: string, body?: unknown) {
    setBusy(true);
    setNotice("");
    try {
      if (path != "/platforms") await api(path, body);
      setState(await api("/platforms"));
      setNotice(
        "Lokaler Plattformstatus gespeichert; keine Plattform kontaktiert.",
      );
    } catch (e) {
      setNotice(String(e));
    } finally {
      setBusy(false);
    }
  }
  const locked = state?.channels.filter((c) => c.blocked) ?? [];
  return (
    <section className="panel agents">
      <div className="panel-title">
        <h3>Plattformwarnungen & Kanalsperren</h3>
        <span className="pill">
          MANUELL · KEINE AUTOMATISCHE STRIKE-ERKENNUNG
        </span>
      </div>
      <p className="muted">
        YouTube ist vorbereitet, Live-Publishing deaktiviert. TikTok und
        Instagram sind spätere Plattformen ohne Adapter. Keine
        Mailbox-Anbindung, kein Scraping. Ein Uploadfehler ist kein Strike.
        Mock-Signale sind synthetisch und können zum Sicherheitstest ebenfalls
        einen Kanal sperren.
      </p>
      <button disabled={busy} onClick={() => void act("/platforms")}>
        Plattformstatus laden
      </button>
      <p role="status">{notice}</p>
      {locked.length > 0 && (
        <div role="alert" className="banner">
          <strong>
            Kritisch: {locked.length} Kanal/Kanäle für weitere
            Veröffentlichungen gesperrt.
          </strong>
        </div>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void act("/platforms/events", {
            platform: "youtube",
            channel_id: channel,
            kind,
            source,
            verification:
              source === "mock_platform_signal" ? "mock" : "owner_reported",
            note,
            occurred_at: new Date().toISOString(),
          });
        }}
      >
        <label htmlFor="signal-channel">
          YouTube-Kanal-ID (lokale Zuordnung)
        </label>
        <input
          id="signal-channel"
          pattern="[A-Za-z0-9_-]{1,64}"
          maxLength={64}
          required
          value={channel}
          onChange={(e) => setChannel(e.target.value)}
        />
        <label htmlFor="signal-kind">Ereignisart</label>
        <select
          id="signal-kind"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
        >
          <option value="copyright_strike">Gemeldeter Copyright-Strike</option>
          <option value="community_strike">
            Gemeldeter Community-Guidelines-Strike
          </option>
          <option value="platform_warning">Plattformwarnung</option>
          <option value="account_restriction">Kontoeinschränkung</option>
          <option value="upload_error">Uploadfehler (kein Strike)</option>
        </select>
        <label htmlFor="signal-source">Quelle / Verifizierung</label>
        <select
          id="signal-source"
          value={source}
          onChange={(e) => setSource(e.target.value)}
        >
          <option value="owner_report">
            Owner-Meldung, nicht API-verifiziert
          </option>
          <option value="mock_platform_signal">Synthetisches Testsignal</option>
        </select>
        <label htmlFor="signal-note">Hinweis zur Meldung</label>
        <textarea
          id="signal-note"
          required
          minLength={3}
          maxLength={500}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <button disabled={busy}>Meldung lokal speichern</button>
      </form>
      {state && (
        <>
          <p className="muted">{state.coverage}</p>
          {state.channels.map((c) => (
            <article key={c.platform + c.channel_id}>
              <p>
                {c.platform} / {c.channel_id}:{" "}
                {c.blocked ? "GESPERRT" : "Owner-geprüft"}
              </p>
              {c.blocked > 0 && (
                <button
                  disabled={busy}
                  onClick={() => {
                    const reason = window.prompt(
                      "Owner-Prüfung: Begründung zur bewussten Entsperrung (mindestens 10 Zeichen)",
                    );
                    if (reason && reason.length >= 10)
                      void act("/platforms/review", {
                        platform: c.platform,
                        channel_id: c.channel_id,
                        owner_confirmed: true,
                        reason,
                      });
                  }}
                >
                  Nach Owner-Prüfung entsperren
                </button>
              )}
            </article>
          ))}
          <h4 style={{ marginTop: 20 }}>Gemeldete Ereignisse</h4>
          {state.events.map((e) => (
            <details key={e.id}>
              <summary>
                {e.platform} / {e.channel_id} · {e.kind}
              </summary>
              <pre style={{ whiteSpace: "pre-wrap" }}>
                {JSON.stringify(JSON.parse(e.payload), null, 2)}
              </pre>
            </details>
          ))}
        </>
      )}
    </section>
  );
}
