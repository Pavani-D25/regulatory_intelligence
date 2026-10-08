import { useEffect, useState } from "react";
import { portal } from "../../api";
import useLoad from "../../useLoad";
import { usePortal } from "../PortalLayout";
import { Badge, Card, ErrorBox, Kpi, Loading } from "../ui";

const SYNCABLE = ["MORTH_API", "ARAI_AIS", "EGAZETTE", "INDIACODE"];

export default function Admin() {
  const [tick, setTick] = useState(0);
  const { data, error, loading } = useLoad(() => portal.admin(), [tick]);
  const { toast } = usePortal();
  const [s, setS] = useState(null);
  const [src, setSrc] = useState("MORTH_API");
  useEffect(() => { if (data) setS(data.settings); }, [data]);
  useEffect(() => {
    if (!data?.sync?.running) return undefined;
    const t = setTimeout(() => setTick((x) => x + 1), 5000);
    return () => clearTimeout(t);
  }, [data]);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const k = data.kpis;
  const save = async () => { await portal.saveSettings(s); toast("Configuration saved"); setTick((t) => t + 1); };
  const sync = async () => {
    const r = await portal.sync(src);
    toast(r.started ? `Sync started: ${src}` : `A sync is already running (${r.running})`);
    setTick((t) => t + 1);
  };
  const on = (key) => s?.[key] === "true";
  const flip = (key) => setS({ ...s, [key]: on(key) ? "false" : "true" });
  return (
    <section className="view">
      <div className="pagehead">
        <div><h1>Admin</h1><p>Sources, monitoring configuration and ingestion jobs.</p></div>
        <div className="actions">
          <select className="select" value={src} onChange={(e) => setSrc(e.target.value)}>{SYNCABLE.map((c) => <option key={c}>{c}</option>)}</select>
          <button className="btn primary" disabled={!!data.sync.running} onClick={sync}>{data.sync.running ? `Syncing ${data.sync.running}…` : "Run Source Sync"}</button>
        </div>
      </div>
      <div className="kpis">
        <Kpi label="Connected Sources" value={`${k.connected}/${k.sources}`} small="Last run ok or partial" corner="⇄" />
        <Kpi label="Job Success" value={k.success_pct != null ? `${k.success_pct}%` : "—"} small={`Last 30 days · ${k.partial_runs} partial`} corner="✓" tone="green" />
        <Kpi label="Data Warnings" value={k.warnings} small="Open OCR / schema / identity flags" corner="!" tone="amber" />
        <Kpi label="Last Sync" value={k.last_sync_min != null ? (k.last_sync_min < 120 ? `${k.last_sync_min} min` : `${Math.round(k.last_sync_min / 60)} h`) : "—"} small="Since the most recent source run" corner="⏱" />
      </div>
      <div className="grid2">
        <Card title="Regulatory Sources" sub="Public sources only · polite crawling (1–2 s, backoff)">
          <div className="stack">
            {data.sources.map((x) => (
              <div key={x.code} className="sourceitem">
                <div className="itemmain"><span className="dot" style={{ background: x.last_status === "ok" ? "#22c55e" : x.last_status === "partial" ? "#f59e0b" : "#cbd5e1" }} />
                  <div><strong style={{ fontSize: 12 }}>{x.name}</strong>
                    <small>{x.code} · every {x.schedule_hours || "—"} h · {x.sightings} files seen · last run {x.last_run_at ? new Date(x.last_run_at).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "never"}</small></div></div>
                <Badge v={x.last_status || "not run"} tone={x.last_status ? undefined : "blue"} />
              </div>
            ))}
          </div>
          {data.sync.last && <p className="note" style={{ marginTop: 10 }}>Last manual sync: {data.sync.last.source} {data.sync.last.error ? `failed — ${data.sync.last.error}` : `finished ${data.sync.last.finished?.slice(0, 16).replace("T", " ")}`}</p>}
        </Card>
        <Card title="Monitoring Configuration" sub="Saved and used by the portal">
          {s && (
            <>
              <div className="formrow">
                <label className="formlabel">Default owner<input className="input" value={s.default_owner || ""} onChange={(e) => setS({ ...s, default_owner: e.target.value })} /></label>
                <label className="formlabel">Review SLA (days)<input className="input" type="number" min="1" value={s.review_sla_days || ""} onChange={(e) => setS({ ...s, review_sla_days: e.target.value })} /></label>
              </div>
              <div className="stack" style={{ marginTop: 6 }}>
                <div className="alertitem">
                  <div className="itemmain"><div><strong style={{ fontSize: 12 }}>High-impact threshold (rule-based until AI review)</strong>
                    <small>High = {s.high_impact_rule || "technical, with obligations to come, re-approval or recent publication"}</small></div></div>
                  <span className="pill purple">rules</span>
                </div>
                {[["auto_sync", "Automatic source sync", "Scheduler crawls every 6 hours (python -m regtrack.cli schedule)"],
                  ["auto_compliance_task", "Create compliance items", "New obligations appear in the Compliance Matrix automatically"]].map(([key, t, d]) => (
                  <div key={key} className="alertitem">
                    <div className="itemmain"><div><strong style={{ fontSize: 12 }}>{t}</strong><small>{d}</small></div></div>
                    <label className="switch"><input type="checkbox" checked={on(key)} onChange={() => flip(key)} /><span className="slider" /></label>
                  </div>
                ))}
              </div>
              <div className="actions" style={{ marginTop: 12 }}><button className="btn primary" onClick={save}>Save Configuration</button></div>
            </>
          )}
        </Card>
      </div>
      <Card title="Recent Ingestion Jobs" sub="Crawl + pipeline runs">
        <div className="tablewrap"><table>
          <thead><tr><th>Job</th><th>Source</th><th>Started</th><th>Duration</th><th>Files seen</th><th>New files</th><th>Status</th></tr></thead>
          <tbody>{data.runs.map((r) => (
            <tr key={r.id}><td className="mono">#{r.id}</td><td>{r.code}</td>
              <td>{new Date(r.started_at).toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })}</td>
              <td>{r.finished_at ? `${Math.max(1, Math.round((new Date(r.finished_at) - new Date(r.started_at)) / 60000))} min` : "running"}</td>
              <td>{r.documents ?? "—"}</td><td>{r.changes ?? "—"}</td><td><Badge v={r.status} /></td></tr>))}
            {!data.runs.length && <tr><td colSpan={7} className="empty">No jobs yet.</td></tr>}
          </tbody>
        </table></div>
      </Card>
    </section>
  );
}
