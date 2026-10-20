import { useEffect, useState } from "react";
import { portal } from "../../api";
import useLoad from "../../useLoad";
import { usePortal } from "../PortalLayout";
import { ago, Badge, Card, ErrorBox, fmtTime, Kpi, Loading } from "../ui";

export default function Admin() {
  const [tick, setTick] = useState(0);
  const { version, toast } = usePortal();
  const { data, error, loading } = useLoad(() => portal.admin(), [tick, version]);
  const [s, setS] = useState(null);
  const [src, setSrc] = useState("ALL");
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
    toast(r.started ? (src === "ALL" ? "Sync started: all sources" : `Sync started: ${src}`) : `A sync is already running (${r.running})`);
    setTick((t) => t + 1);
  };
  const autoOn = s?.auto_sync !== "false";
  const sch = data.scheduler;
  const schLabel = !sch.auto_sync ? "Paused" : sch.alive ? "Running" : "Not running";
  return (
    <section className="view">
      <div className="pagehead">
        <div><h1>Admin</h1><p>Sources, monitoring configuration and ingestion jobs.</p></div>
        <div className="actions">
          <select className="select" value={src} onChange={(e) => setSrc(e.target.value)}>{data.syncable.map((c) => <option key={c} value={c}>{c === "ALL" ? "ALL sources (one after another)" : c}</option>)}</select>
          <button className="btn primary" disabled={!!data.sync.running} onClick={sync}>{!data.sync.running ? (src === "ALL" ? "Sync All Sources" : "Run Source Sync")
            : data.sync.step === "pipeline" ? "Processing new files…"
            : data.sync.running === "ALL" ? `Syncing ${data.sync.step || "…"} (${data.sync.done + 1}/${data.sync.total})…` : `Syncing ${data.sync.running}…`}</button>
        </div>
      </div>
      <div className="kpis">
        <Kpi label="Connected Sources" value={`${k.connected}/${k.sources}`} small="Crawled sources, last run ok or partial" corner="⇄" />
        <Kpi label="Job Success" value={k.success_pct != null ? `${k.success_pct}%` : "—"} small={`Last 30 days · ${k.partial_runs} partial`} corner="✓" tone="green" />
        <Kpi label="Data Warnings" value={k.warnings} small="Open OCR / schema / identity flags" corner="!" tone="amber" />
        <Kpi label="Auto-sync (every 6 h)" value={schLabel} tone={sch.alive && sch.auto_sync ? "green" : "red"} corner="⏱"
          small={`heartbeat ${sch.heartbeat ? ago(sch.heartbeat) : "never"} · last sync ${k.last_sync_min != null ? (k.last_sync_min < 120 ? `${k.last_sync_min} min` : `${Math.round(k.last_sync_min / 60)} h`) + " ago" : "—"}`} />
      </div>
      <div className="grid2">
        <Card title="Regulatory Sources" sub="Public sources only · polite crawling (1–2 s, backoff)">
          <div className="stack">
            {data.sources.map((x) => (
              <div key={x.code} className="sourceitem">
                <div className="itemmain"><span className="dot" style={{ background: x.last_status === "ok" ? "#22c55e" : x.last_status === "partial" ? "#f59e0b" : "#cbd5e1" }} />
                  <div><strong style={{ fontSize: 12 }}>{x.name}</strong>
                    <small>{x.code} · {x.crawler ? `every ${Math.min(x.schedule_hours, 6)} h` : x.code === "LOCAL_SEED" ? "one-time import" : "no crawler yet"} · {x.sightings} files seen · last run {x.last_run_at ? fmtTime(x.last_run_at) : "never"}
                      {x.next_due && <> · next due {fmtTime(x.next_due)}</>}</small></div></div>
                <span style={{ display: "flex", gap: 5 }}>{x.overdue && <Badge v="overdue" tone="red" />}<Badge v={x.last_status || "not run"} tone={x.last_status ? undefined : "blue"} /></span>
              </div>
            ))}
          </div>
          {data.sync.last && (
            <p className="note" style={{ marginTop: 10 }}>
              Last manual sync: {data.sync.last.source === "ALL" ? "all sources" : data.sync.last.source}{" "}
              {data.sync.last.error ? `failed — ${data.sync.last.error}` : `finished ${fmtTime(data.sync.last.finished)}`}
              {data.sync.last.errors && Object.keys(data.sync.last.errors).length > 0 &&
                <span style={{ color: "var(--red)" }}> · failed: {Object.entries(data.sync.last.errors).map(([c, e]) => `${c} (${e})`).join("; ")}</span>}
            </p>
          )}
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
                    <small>{data.impact_rule}</small></div></div>
                  <span className="pill purple">rules</span>
                </div>
                <div className="alertitem">
                  <div className="itemmain"><div><strong style={{ fontSize: 12 }}>Automatic source sync</strong>
                    <small>Scheduled crawls run only while this is on{sch.alive ? "" : " and the scheduler is running (python -m regtrack.cli schedule)"}</small></div></div>
                  <label className="switch"><input type="checkbox" checked={autoOn} onChange={() => setS({ ...s, auto_sync: autoOn ? "false" : "true" })} /><span className="slider" /></label>
                </div>
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
              <td>{fmtTime(r.started_at)}</td>
              <td>{r.finished_at ? `${Math.max(1, Math.round((new Date(r.finished_at) - new Date(r.started_at)) / 60000))} min` : "running"}</td>
              <td>{r.documents ?? "—"}</td><td>{r.changes ?? "—"}</td><td><Badge v={r.status} /></td></tr>))}
            {!data.runs.length && <tr><td colSpan={7} className="empty">No jobs yet.</td></tr>}
          </tbody>
        </table></div>
      </Card>
    </section>
  );
}
