import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { portal } from "../../api";
import useLoad from "../../useLoad";
import { usePortal } from "../PortalLayout";
import { Badge, Card, ErrorBox, Kpi, Loading, MetricRows } from "../ui";

const CAT_LABEL = { L1: "L1 Moped", L2: "L2 Two-wheeler", M1: "M1 Car", N1: "N1 Light goods" };
const STEPS = [
  ["Detect", "Source monitoring finds a new or changed document (every 6 hours)."],
  ["Classify", "Identity, category and topic are read from the document content."],
  ["Assess", "Impact is scored and applicability per category is checked."],
  ["Map", "Obligations are mapped to owners and evidence in the Compliance Matrix."],
  ["Close", "Evidence attached and the change marked as reviewed."],
];

export default function Impact() {
  const { data, error, loading } = useLoad(() => portal.impact(), []);
  const { openReg } = usePortal();
  const nav = useNavigate();
  const [cell, setCell] = useState(null);
  const [detail, setDetail] = useState(null);
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const pick = async (code, cat) => {
    setCell({ code, cat }); setDetail(null);
    setDetail(await portal.impactCell(cat, code));
  };
  const k = data.kpis;
  return (
    <section className="view">
      <div className="pagehead">
        <div><h1>Impact View</h1><p>Where regulation hits hardest: vehicle category × topic, weighted by impact.</p></div>
        <div className="actions"><button className="btn primary" onClick={() => nav("/compliance")}>Open Compliance Matrix</button></div>
      </div>
      <div className="kpis">
        <Kpi label="Critical Areas" value={k.critical} small="Topics scoring 4–5 for some category" corner="!" tone="red" />
        <Kpi label={k.top1.name} value={k.top1.n} small="Most regulated topic" corner="1" tone="amber" />
        <Kpi label={k.top2.name} value={k.top2.n} small="Second most regulated topic" corner="2" />
        <Kpi label="Owners Assigned" value={k.owners} small="Distinct owners in the matrix" corner="◎" tone="green" />
      </div>
      <div className="grid2 wide">
        <Card title="Category × Domain Impact Heatmap" sub="Score 1–5 from regulation count (high impact counts double) · click a cell">
          <div className="heat">
            <div />{data.categories.map((c) => <div key={c} className="hhead">{CAT_LABEL[c]}</div>)}
            {data.cells.map((row) => (
              <FragmentRow key={row.code} row={row} cats={data.categories} onPick={pick} sel={cell} />
            ))}
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 14, fontSize: 11, color: "var(--muted)" }}>
            Low {[1, 2, 3, 4, 5].map((l) => <span key={l} className={`l${l}`} style={{ width: 22, height: 12, borderRadius: 3, display: "inline-block" }} />)} High
          </div>
        </Card>
        <Card title={cell ? `${detail?.domain || "…"} · ${CAT_LABEL[cell.cat]}` : "Cell Detail"}
          sub={cell ? (detail ? `${detail.count} regulation(s) · top 6 shown` : "Loading…") : "Select a heatmap cell"}>
          {!cell && <div className="empty">Click any cell to see the regulations behind the score.</div>}
          <div className="stack">
            {detail?.rows.map((r) => (
              <div key={r.canonical_id} className="taskitem" style={{ cursor: "pointer" }} onClick={() => openReg(r.canonical_id)}>
                <div className="itemmain"><div><strong style={{ fontSize: 12 }} className="truncate">{r.name}</strong><small className="mono">{r.canonical_id}</small></div></div>
                <Badge v={r.impact} />
              </div>
            ))}
            {detail && detail.count > 6 && (
              <button className="btn ghost" onClick={() => nav(`/regulations?category=${cell.cat}&q=${encodeURIComponent(detail.domain)}`)}>View all {detail.count} →</button>
            )}
          </div>
        </Card>
      </div>
      <div className="grid2">
        <Card title="Top Affected Systems" sub="Standards most referenced by obligations in force">
          <MetricRows rows={data.top_standards} />
        </Card>
        <Card title="Impact Workflow" sub="How a change moves from detection to closure">
          <div className="stack">
            {STEPS.map(([t, d], i) => (
              <div key={t} className="taskitem"><div className="itemmain"><span className="pill blue">{i + 1}</span><div><strong style={{ fontSize: 12 }}>{t}</strong><small>{d}</small></div></div></div>
            ))}
          </div>
        </Card>
      </div>
    </section>
  );
}

function FragmentRow({ row, cats, onPick, sel }) {
  return (
    <>
      <div className="hlabel">{row.domain}</div>
      {cats.map((c, i) => (
        <button key={c} className={`hcell l${row.scores[i]}`} title={`${row.counts[i]} weighted`}
          style={sel && sel.code === row.code && sel.cat === c ? { outline: "2px solid var(--text)" } : undefined}
          onClick={() => onPick(row.code, c)}>{row.scores[i]}</button>
      ))}
    </>
  );
}
