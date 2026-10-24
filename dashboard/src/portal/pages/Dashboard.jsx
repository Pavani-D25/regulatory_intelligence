import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { portal } from "../../api";
import useLoad from "../../useLoad";
import { usePortal } from "../PortalLayout";
import { ago, Badge, Card, Donut, ErrorBox, fmt, Kpi, Loading, MetricRows, OfficialId } from "../ui";

export default function Dashboard() {
  const { version, countryName, country } = usePortal();
  // trend chart range: view (auto / month / year) and years; the year choices come from the data (trend_years)
  const [range, setRange] = useState({ view: "auto", from: "", to: "" });
  useEffect(() => setRange({ view: "auto", from: "", to: "" }), [country]);
  const { data: s, error, loading } = useLoad(
    () => portal.summary({ trend_view: range.view, trend_from: range.from || undefined, trend_to: range.to || undefined }),
    [version, range.view, range.from, range.to]);
  const { openReg, meta } = usePortal();
  const nav = useNavigate();
  if (loading && !s) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const k = s.kpis;
  const peak = Math.max(1, ...s.trend.map((m) => m.n));
  const deadlines = s.deadlines.length ? s.deadlines : s.recent_deadlines;
  return (
    <section className="view">
      <div className="pagehead">
        <div><h1>Regulatory Overview</h1>
          <p>Live view of {countryName} vehicle regulations from {meta ? `${meta.sources_total} monitored sources` : "the monitored sources"} for {(meta?.categories || []).map((c) => c.code).join(", ")}.</p></div>
        <div className="actions">
          <button className="btn secondary" onClick={() => nav("/reports")}>Generate Report</button>
          <button className="btn primary" onClick={() => nav("/changes")}>Review Changes</button>
        </div>
      </div>
      <div className="kpis">
        <Kpi label="Regulations Tracked" value={k.tracked} small={`${k.new_this_quarter} published in the last 90 days`} corner="R" />
        <Kpi label="Changes Detected" value={k.changes_30d} small={`${k.changes_open} not yet reviewed · last 30 days`} corner="Δ" tone="amber" />
        <Kpi label="High Impact Items" value={k.high} small="Technical, with obligations or new revisions" corner="!" tone="red" />
        <Kpi label="Action Required" value={k.action_required} small="High impact with a date still to come" corner="✓" tone="green" />
      </div>
      <div className="grid2 wide">
        <Card title="Regulatory Change Trend" sub={s.trend_sub || "New regulations published per month · last 12 months"} right={meta?.last_sync && <Badge v={`synced ${ago(meta.last_sync)}`} tone={meta.scheduler?.alive ? "green" : "amber"} />}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 8 }}>
            <select className="select" aria-label="Trend view" value={range.view}
              onChange={(e) => setRange({ view: e.target.value, from: "", to: "" })}>
              <option value="auto">Auto</option><option value="month">Monthly</option><option value="year">Yearly</option>
            </select>
            {range.view !== "auto" && s.trend_years && (() => {
              const years = [];
              for (let y = s.trend_years.max; y >= s.trend_years.min; y--) years.push(y);
              return (<>
                <select className="select" aria-label="From year" value={range.from} onChange={(e) => setRange({ ...range, from: e.target.value })}>
                  <option value="">{range.view === "month" ? "From (last 12 months)" : `From ${s.trend_years.min}`}</option>
                  {years.map((y) => <option key={y} value={y}>{y}</option>)}
                </select>
                <select className="select" aria-label="To year" value={range.to} onChange={(e) => setRange({ ...range, to: e.target.value })}>
                  <option value="">{`To ${s.trend_years.max}`}</option>
                  {years.map((y) => <option key={y} value={y}>{y}</option>)}
                </select>
              </>);
            })()}
            {loading && <span className="sub">updating…</span>}
          </div>
          <div className="chartbars">
            {s.trend.map((m, i) => {
              // many bars (a per-year history): label every step-th one so the labels do not overlap; hover shows all
              const step = Math.ceil(s.trend.length / 14);
              const labelled = i % step === 0 || i === s.trend.length - 1;
              return (
                <button key={m.ym} className="vbar" style={{ height: `${Math.max(3, (m.n / peak) * 100)}%` }}
                  title={`${m.label}: ${m.n}`} onClick={() => nav(`/regulations?month=${m.ym}`)}>
                  <b>{m.n || (step > 1 ? "" : m.n)}</b><label>{labelled ? m.label : ""}</label>
                </button>
              );
            })}
          </div>
        </Card>
        <Card title="Severity Distribution" sub="In-scope regulations by impact (rule-based until AI review)">
          <Donut total={s.kpis.tracked} label="regulations" parts={[
            { name: "High", n: s.severity.High, color: "#dc2626" },
            { name: "Medium", n: s.severity.Medium, color: "#f59e0b" },
            { name: "Low", n: s.severity.Low, color: "#22c55e" },
          ]} />
        </Card>
      </div>
      <div className="grid2">
        <Card title="Vehicle Categories" sub="Regulations applying to each category (incl. all-vehicle rules)">
          <MetricRows rows={s.by_category} onClick={(r) => nav(`/regulations?category=${r.code}`)} />
        </Card>
        <Card title="Top Impact Areas" sub="Most regulated topics">
          <MetricRows rows={s.top_domains} onClick={(r) => nav(`/regulations?q=${encodeURIComponent(r.name)}`)} />
        </Card>
      </div>
      <div className="grid2 wide">
        <Card title="Latest Regulatory Changes" sub="Click a row to open the regulation detail" right={<button className="btn ghost" onClick={() => nav("/regulations")}>View all</button>}>
          <div className="tablewrap"><table>
            <thead><tr><th>Regulation</th><th>Category</th><th>Domain</th><th>Effective</th><th>Impact</th><th>Status</th></tr></thead>
            <tbody>{s.latest.map((r) => (
              <tr key={r.canonical_id} className="click" onClick={() => openReg(r.canonical_id)}>
                <td><strong className="truncate" style={{ display: "block" }}>{r.name}</strong><span style={{ color: "var(--muted)" }}><OfficialId id={r.canonical_id} /></span></td>
                <td>{r.region || "—"}</td><td>{r.domain}</td><td>{fmt(r.effective)}</td>
                <td><Badge v={r.impact} /></td><td><Badge v={r.status} /></td>
              </tr>))}</tbody>
          </table></div>
        </Card>
        <Card title={s.deadlines.length ? "Upcoming Deadlines" : "Recent Implementation Dates"}
          sub={s.deadlines.length ? "Obligations still to come (P = proposed in a draft)" : "No future dates in the data yet; latest dates in force"}>
          <div className="stack">
            {deadlines.map((d) => (
              <div key={d.mandate_key} className="taskitem" style={{ cursor: "pointer" }} onClick={() => openReg(d.canonical_id)}>
                <div className="itemmain"><div>
                  <strong style={{ fontSize: 12 }}>{d.mandate_key}</strong>
                  <small>{d.canonical_id} · {(d.vehicle_categories || []).filter((c) => c === "ALL" || (meta?.categories || []).some((x) => x.code === c)).join(", ")}</small>
                </div></div>
                <Badge v={(d.is_draft ? "P · " : "") + fmt(d.implementation_date)} tone={s.deadlines.length ? "amber" : "blue"} />
              </div>
            ))}
            {!deadlines.length && <div className="empty">No implementation dates recorded.</div>}
          </div>
        </Card>
      </div>
    </section>
  );
}
