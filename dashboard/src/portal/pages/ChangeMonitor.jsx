import { useState } from "react";
import { portal } from "../../api";
import useLoad from "../../useLoad";
import { usePortal } from "../PortalLayout";
import { AiNote, Badge, Card, ErrorBox, Kpi, Loading, MetricRows, Ring } from "../ui";

const TYPE_LABEL = {
  new_document: "New document", draft_published: "Draft published", draft_finalised: "Draft finalised",
  new_revision: "New revision", implementation_date_changed: "Date changed", amendment: "Amendment",
  superseded: "Superseded", withdrawn: "Withdrawn", corrigendum: "Corrigendum", new_amendment: "New amendment",
};

export default function ChangeMonitor() {
  const [days, setDays] = useState(365);
  const [onlyOpen, setOnlyOpen] = useState(false);
  const [tick, setTick] = useState(0);
  const { data, error, loading } = useLoad(() => portal.changes(days), [days, tick]);
  const { openReg, toast } = usePortal();
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const k = data.kpis;
  const visible = data.events.filter((e) => e.in_scope && (!onlyOpen || e.review_status !== "confirmed"));
  const markAll = async () => {
    const ids = visible.filter((e) => e.review_status !== "confirmed").map((e) => e.id);
    if (!ids.length) { toast("Nothing to mark"); return; }
    const r = await portal.markReviewed(ids);
    toast(`${r.reviewed} change(s) marked as reviewed`);
    setTick((t) => t + 1);
  };
  const sla = data.sla;
  const slaPct = sla.reviewed ? Math.round((100 * sla.within) / sla.reviewed) : 0;
  return (
    <section className="view">
      <div className="pagehead">
        <div><h1>Change Monitor</h1><p>Delta tracking across MoRTH, ARAI, e-Gazette and India Code: new documents, drafts, revisions and date changes.</p></div>
        <div className="actions">
          <select className="select" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={30}>Last 30 days</option><option value={90}>Last 90 days</option><option value={365}>Last 12 months</option><option value={3650}>All</option></select>
          <button className="btn primary" onClick={markAll}>Mark Visible as Reviewed</button>
        </div>
      </div>
      <div className="kpis">
        <Kpi label="Changes Detected" value={k.detected} small="In the selected period" corner="Δ" />
        <Kpi label="Unreviewed" value={k.unreviewed} small="Waiting for review" corner="?" tone="amber" />
        <Kpi label="High Impact Changes" value={k.high} small="On high-impact regulations" corner="!" tone="red" />
        <Kpi label="Reviewed" value={k.reviewed} small="Marked as reviewed" corner="✓" tone="green" />
      </div>
      <div className="grid2 wide">
        <Card title="Delta Events" sub="Click an event for regulation detail"
          right={<label className="sub" style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} /> Unreviewed only</label>}>
          <div className="timeline" style={{ maxHeight: 720, overflow: "auto" }}>
            {visible.slice(0, 80).map((e) => (
              <div key={e.id} className="event">
                <div className="date">{new Date(e.detected_at).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })}</div>
                <div className="axis" />
                <div className="eventbox" onClick={() => e.canonical_id && openReg(e.canonical_id)}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 5 }}>
                    <h3>{TYPE_LABEL[e.event_type] || e.event_type} · <span className="mono">{e.canonical_id}</span></h3>
                    <span style={{ display: "flex", gap: 5 }}><Badge v={e.impact} />{e.review_status === "confirmed" ? <Badge v="Reviewed" tone="green" /> : <Badge v="New" tone="blue" />}</span>
                  </div>
                  <p>{e.summary}</p>
                  {e.ai_summary_pending && <AiNote>✦ AI summary pending</AiNote>}
                </div>
              </div>
            ))}
            {!visible.length && <div className="empty">No changes in this period.</div>}
          </div>
        </Card>
        <div>
          <Card title="Changes by Type" sub="Selected period">
            <MetricRows rows={data.by_type.map(([t, n]) => ({ name: TYPE_LABEL[t] || t, n }))} />
          </Card>
          <Card title="Review SLA" sub={`Target: review within ${sla.days} days (set in Admin)`}>
            <div style={{ display: "flex", gap: 20, alignItems: "center" }}>
              <Ring pct={slaPct} label="within SLA" color="var(--blue)" />
              <div className="legend" style={{ flex: 1 }}>
                {sla.buckets.map(([l, n]) => <div key={l} className="legendrow"><span>{l}</span><b>{n}</b></div>)}
                <div className="legendrow"><span>Open, overdue</span><b style={{ color: "var(--red)" }}>{sla.overdue}</b></div>
              </div>
            </div>
            {!sla.reviewed && <p className="note" style={{ marginTop: 12 }}>No changes reviewed yet — the SLA fills in as changes are marked reviewed.</p>}
          </Card>
        </div>
      </div>
    </section>
  );
}
