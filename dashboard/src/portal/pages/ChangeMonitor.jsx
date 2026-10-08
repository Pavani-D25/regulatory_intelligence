import { useState } from "react";
import { portal } from "../../api";
import useLoad from "../../useLoad";
import { usePortal } from "../PortalLayout";
import { AiNote, Badge, Card, ErrorBox, fmt, Kpi, Loading, MetricRows, Ring } from "../ui";

const TYPE_LABEL = {
  new_document: "New document", draft_published: "Draft published", draft_finalised: "Draft finalised",
  new_revision: "New revision", implementation_date_changed: "Date changed", amendment: "Amendment",
  superseded: "Superseded", withdrawn: "Withdrawn", corrigendum: "Corrigendum", new_amendment: "New amendment",
};

export default function ChangeMonitor() {
  const [days, setDays] = useState(365);
  const [onlyOpen, setOnlyOpen] = useState(false);
  const [tick, setTick] = useState(0);
  const [type, setType] = useState("");
  const [limit, setLimit] = useState(60);
  const { openReg, toast, version } = usePortal();
  const { data, error, loading } = useLoad(() => portal.changes(days), [days, tick, version]);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const k = data.kpis;
  const scoped = data.events.filter((e) => e.in_scope);
  const visible = scoped.filter((e) => (!onlyOpen || e.review_status !== "confirmed") && (!type || e.event_type === type));
  const openIds = visible.filter((e) => e.review_status !== "confirmed").map((e) => e.id);
  const types = [...new Set(scoped.map((e) => e.event_type))].map((t) => [t, scoped.filter((e) => e.event_type === t).length]).sort((a, b) => b[1] - a[1]);
  const mark = async (ids) => {
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
          <button className="btn primary" disabled={!openIds.length} onClick={() => mark(openIds)}>Mark Visible as Reviewed{openIds.length ? ` (${openIds.length})` : ""}</button>
        </div>
      </div>
      <div className="kpis">
        <Kpi label="Changes Detected" value={k.detected} small="In the selected period" corner="Δ" />
        <Kpi label="Unreviewed" value={k.unreviewed} small="Waiting for review" corner="?" tone="amber" />
        <Kpi label="High Impact Changes" value={k.high} small="On high-impact regulations" corner="!" tone="red" />
        <Kpi label="Reviewed" value={k.reviewed} small="Marked as reviewed" corner="✓" tone="green" />
      </div>
      <div className="grid2 wide">
        <Card title="Delta Events" sub={`${visible.length} event(s) · "found" = when our crawl saw it, "dated" = the document's own date`}
          right={<label className="sub" style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} /> Unreviewed only</label>}>
          <div className="chips" style={{ marginBottom: 12 }}>
            <button className={`chip ${!type ? "on" : ""}`} onClick={() => setType("")}>All<b>{scoped.length}</b></button>
            {types.map(([t, n]) => <button key={t} className={`chip ${type === t ? "on" : ""}`} onClick={() => setType(type === t ? "" : t)}>{TYPE_LABEL[t] || t}<b>{n}</b></button>)}
          </div>
          <div className="timeline" style={{ maxHeight: 720, overflow: "auto" }}>
            {visible.slice(0, limit).map((e) => (
              <div key={e.id} className="event">
                <div className="date">found {fmt(e.detected_at)}{e.doc_date && <><br />dated {fmt(e.doc_date)}</>}</div>
                <div className="axis" />
                <div className="eventbox" onClick={() => e.canonical_id && openReg(e.canonical_id)}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 5 }}>
                    <h3>{TYPE_LABEL[e.event_type] || e.event_type} · <span className="mono">{e.canonical_id}</span></h3>
                    <span style={{ display: "flex", gap: 5, alignItems: "center" }}><Badge v={e.impact} />
                      {e.review_status === "confirmed" ? <Badge v="Reviewed" tone="green" />
                        : <button className="chip" title="Mark this change as reviewed" onClick={(ev) => { ev.stopPropagation(); mark([e.id]); }}>✓ Review</button>}</span>
                  </div>
                  <p>{e.summary}</p>
                  {e.ai_summary_pending && <AiNote>✦ AI summary pending</AiNote>}
                </div>
              </div>
            ))}
            {!visible.length && <div className="empty">No changes match.</div>}
          </div>
          {visible.length > limit && <button className="btn ghost" onClick={() => setLimit(limit + 60)}>Show more ({visible.length - limit} left)</button>}
        </Card>
        <div>
          <Card title="Changes by Type" sub="Selected period · click to filter">
            <MetricRows rows={data.by_type.map(([t, n]) => ({ name: TYPE_LABEL[t] || t, n, t }))} onClick={(r) => setType(r.t)} />
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
