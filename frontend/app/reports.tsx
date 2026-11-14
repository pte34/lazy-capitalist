"use client";
import { useState } from "react";
type Report = {
  id: string;
  kind: string;
  period_start: string;
  period_end: string;
  data_as_of: string;
  interim: boolean;
  completeness: string;
  metrics: unknown;
  comparison: unknown;
};
type Delivery = {
  id: string;
  channel: string;
  status: string;
  attempts: number;
  error: string | null;
};
export default function Reports() {
  const [reports, setReports] = useState<Report[]>([]),
    [deliveries, setDeliveries] = useState<Delivery[]>([]),
    [settings, setSettings] = useState<unknown>(null),
    [email, setEmail] = useState(""),
    [phone, setPhone] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false);
  async function api(path: string, body?: unknown) {
    const r = await fetch(`/api/jobs?path=${encodeURIComponent(path)}`, {
      method: body === undefined ? "GET" : "POST",
      headers: {
        "Content-Type": "application/json",
        ...(path === "/reports/test"
          ? { "Idempotency-Key": crypto.randomUUID() }
          : {}),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const data = await r.json();
    if (!r.ok) throw Error(JSON.stringify(data.detail));
    return data;
  }
  async function refresh() {
    setReports(await api("/reports"));
    setDeliveries(await api("/reports/deliveries"));
    setSettings(await api("/reports/settings"));
  }
  async function action(path?: string, body?: unknown) {
    setBusy(true);
    setNotice("");
    try {
      if (path) await api(path, body);
      await refresh();
      setNotice(
        path === "/reports/test"
          ? "Mock-Zustellung verarbeitet. Keine echte Nachricht gesendet."
          : "Berichte aktualisiert.",
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
        <h3>Berichte & Benachrichtigungen</h3>
        <span className="pill">NUR MOCK-ZUSTELLUNG</span>
      </div>
      <p className="muted">
        Täglich 20:00 Europe/Zurich · wöchentlich Sonntag · monatlich letzter
        Kalendertag. Laufender Backend-Prozess prüft jede Minute; maximal 7 Tage
        Nachholung. 20-Uhr-Berichte sind Zwischenstände. Einnahmen und ROI
        bleiben unbekannt.
      </p>
      <button disabled={busy} onClick={() => void action()}>
        Berichte laden
      </button>{" "}
      <button disabled={busy} onClick={() => void action("/reports/run", {})}>
        Fällige Berichte verarbeiten
      </button>
      <p role="status">{notice}</p>
      <details>
        <summary>Benachrichtigungseinstellungen (maskiert)</summary>
        <pre style={{ whiteSpace: "pre-wrap" }}>
          {JSON.stringify(settings, null, 2)}
        </pre>
      </details>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void action("/reports/settings", {
            email: email || null,
            whatsapp: phone || null,
            channels: ["email", "whatsapp"],
            immediate_alerts: true,
            live_delivery: false,
          });
        }}
      >
        <label htmlFor="report-email">E-Mail für Mock-Tests</label>
        <input
          id="report-email"
          type="email"
          maxLength={254}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <label htmlFor="report-phone">WhatsApp für Mock-Tests (E.164)</label>
        <input
          id="report-phone"
          type="tel"
          maxLength={16}
          pattern="\+[1-9][0-9]{7,14}"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          placeholder="+41…"
        />
        <p className="muted">
          Speichern ersetzt beide Empfänger; leere Felder entfernen sie. Keine
          Empfänger aus Git-Profilen. Kein echter Provider eingerichtet.
        </p>
        <button disabled={busy}>Mock-Einstellungen speichern</button>{" "}
        <button
          type="button"
          disabled={busy}
          onClick={() => void action("/reports/test", {})}
        >
          Simulierte Testzustellung
        </button>
      </form>
      <h4 style={{ marginTop: 24 }}>Gespeicherte Berichte</h4>
      {reports.map((r) => (
        <details key={r.id}>
          <summary>
            {r.id} · {r.interim ? "Zwischenstand" : "Kalenderzeitraum beendet"}{" "}
            · Datenstand {r.data_as_of} UTC
          </summary>
          <p>
            {r.period_start} – {r.period_end} UTC
          </p>
          <p>{r.completeness}</p>
          <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
            {JSON.stringify(
              { metrics: r.metrics, comparison: r.comparison },
              null,
              2,
            )}
          </pre>
        </details>
      ))}
      <h4 style={{ marginTop: 24 }}>Zustellhistorie (Simulation)</h4>
      <ul>
        {deliveries.map((d) => (
          <li key={d.id}>
            {d.channel}: {d.status} · Versuche {d.attempts} {d.error}
          </li>
        ))}
      </ul>
    </section>
  );
}
