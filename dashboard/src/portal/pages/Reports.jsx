import { useState } from "react";
import { portal, reportUrl } from "../../api";
import useLoad from "../../useLoad";
import { usePortal } from "../PortalLayout";
import { ago, Badge, Card, ErrorBox, fmt, fmtTime, Kpi, Loading } from "../ui";

const CARDS = {
  executive: ["▤", "Management summary: tracked regulations, changes, high-impact items, category and topic breakdown, upcoming dates."],
  compliance_gap: ["✓", "Every open or in-progress obligation with owner, evidence, status and due date, from the Compliance Matrix."],
  change_impact: ["Δ", "All detected changes in the last 12 months with type, impact and review status."],
};

export default function Reports() {
  const [tick, setTick] = useState(0);
  const { version, toast, meta, countryName } = usePortal();
  const { data, error, loading } = useLoad(() => portal.reports(), [tick, version]);
  const { data: sch } = useLoad(() => portal.schedules(), [tick, version]);
  const [plan, setPlan] = useState(null);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const gen = (kind, fmt) => {
    window.open(reportUrl(kind, fmt), "_blank");
    toast("Report generated");
    setTimeout(() => setTick((t) => t + 1), 1200);
  };
  const k = data.kpis;
  const act = async (fn, msg) => {
    try { await fn(); toast(msg); setTick((t) => t + 1); return true; } catch (e) { toast(e.message); return false; }
  };
  return (
    <section className="view">
      <div className="pagehead">
        <div><h1>Reports</h1><p>Generate regulatory reports from live data · {countryName} · {data.scope}.</p></div>
      </div>
      <div className="kpis">
        <Kpi label="Generated This Month" value={k.generated_month} small="All report types" corner="▤" />
        <Kpi label="Last Report" value={k.last_generated ? ago(k.last_generated) : "—"} small={k.last_generated ? fmtTime(k.last_generated) : "No report generated yet"} corner="⏱" tone="amber" />
        <Kpi label="Changes Awaiting Review" value={k.awaiting_review} small="Shown in the change report" corner="?" tone="red" />
        <Kpi label="Report Templates" value={k.templates} small="Executive, gap, change impact" corner="T" tone="green" />
      </div>
      <div className="grid3">
        {data.templates.map((t) => (
          <Card key={t.kind} className="reportcard">
            <div className="icon">{CARDS[t.kind][0]}</div>
            <h3>{t.name}</h3>
            <p>{CARDS[t.kind][1]}</p>
            <div className="actions" style={{ marginTop: "auto" }}>
              <button className="btn primary" onClick={() => gen(t.kind, "html")}>Generate</button>
              <button className="btn secondary" onClick={() => gen(t.kind, "csv")}>CSV</button>
            </div>
          </Card>
        ))}
      </div>
      <Card title="Scheduled Reports" sub="Generated automatically and kept as files; listed below when they run"
        right={<button className="btn secondary" onClick={() => setPlan({ kind: "executive", frequency: "weekly", team: meta?.teams?.[0]?.id || "" })}>New Schedule</button>}>
        {plan && (
          <div className="formrow" style={{ gridTemplateColumns: "1fr 1fr 1fr auto", alignItems: "end" }}>
            <label className="formlabel">Report<select className="select" value={plan.kind} onChange={(e) => setPlan({ ...plan, kind: e.target.value })}>
              {(sch?.templates || []).map((t) => <option key={t.kind} value={t.kind}>{t.name}</option>)}</select></label>
            <label className="formlabel">Every<select className="select" value={plan.frequency} onChange={(e) => setPlan({ ...plan, frequency: e.target.value })}>
              {(sch?.frequencies || []).map((f) => <option key={f}>{f}</option>)}</select></label>
            <label className="formlabel">For team<select className="select" value={plan.team} onChange={(e) => setPlan({ ...plan, team: Number(e.target.value) || "" })}>
              <option value="">Choose…</option>{(meta?.teams || []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label>
            <div className="actions" style={{ margin: "10px 0" }}>
              <button className="btn primary" disabled={!plan.team}
                onClick={() => act(() => portal.addSchedule({ kind: plan.kind, frequency: plan.frequency, team_ids: [plan.team] }), "Schedule created").then((ok) => ok && setPlan(null))}>Create</button>
              <button className="btn secondary" onClick={() => setPlan(null)}>Cancel</button>
            </div>
          </div>
        )}
        <div className="tablewrap"><table>
          <thead><tr><th>Report</th><th>Every</th><th>For</th><th>Next run</th><th>Last run</th><th>Status</th><th /></tr></thead>
          <tbody>{(sch?.schedules || []).map((s) => (
            <tr key={s.id}><td><strong>{s.template}</strong></td><td>{s.frequency}</td><td>{s.teams.join(", ")}</td>
              <td>{fmt(s.next_run_at)}</td><td>{s.last_run_at ? fmt(s.last_run_at) : "—"}</td>
              <td><button className="btn ghost" style={{ padding: 0 }} onClick={() => act(() => portal.toggleSchedule(s.id, !s.is_active), s.is_active ? "Schedule paused" : "Schedule resumed")}>
                <Badge v={s.is_active ? "Active" : "Paused"} tone={s.is_active ? "green" : "amber"} /></button></td>
              <td><button className="btn ghost" onClick={() => act(() => portal.deleteSchedule(s.id), "Schedule removed")}>×</button></td></tr>))}
            {sch && !sch.schedules.length && <tr><td colSpan={7} className="empty">No scheduled reports.</td></tr>}
          </tbody>
        </table></div>
      </Card>
      <Card title="Recent Reports" sub="Reports generated from this portal">
        <div className="tablewrap"><table>
          <thead><tr><th>Report</th><th>Scope</th><th>Generated</th><th>Owner</th><th>Rows</th></tr></thead>
          <tbody>{data.recent.map((r) => (
            <tr key={r.id}><td><strong>{r.kind}</strong></td><td>{r.scope}</td>
              <td>{new Date(r.generated_at).toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })}</td>
              <td>{r.owner}</td><td>{r.rows}</td></tr>))}
            {!data.recent.length && <tr><td colSpan={5} className="empty">No reports generated yet.</td></tr>}
          </tbody>
        </table></div>
      </Card>
    </section>
  );
}
