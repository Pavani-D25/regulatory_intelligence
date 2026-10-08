import { useState } from "react";
import { portal, reportUrl } from "../../api";
import useLoad from "../../useLoad";
import { usePortal } from "../PortalLayout";
import { ago, Card, ErrorBox, fmtTime, Kpi, Loading } from "../ui";

const CARDS = {
  executive: ["▤", "Management summary: tracked regulations, changes, high-impact items, category and topic breakdown, upcoming dates."],
  compliance_gap: ["✓", "Every open or in-progress obligation with owner, evidence, status and due date, from the Compliance Matrix."],
  change_impact: ["Δ", "All detected changes in the last 12 months with type, impact and review status."],
};

export default function Reports() {
  const [tick, setTick] = useState(0);
  const { data, error, loading } = useLoad(() => portal.reports(), [tick]);
  const { toast } = usePortal();
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const gen = (kind, fmt) => {
    window.open(reportUrl(kind, fmt), "_blank");
    toast("Report generated");
    setTimeout(() => setTick((t) => t + 1), 1200);
  };
  const k = data.kpis;
  return (
    <section className="view">
      <div className="pagehead">
        <div><h1>Reports</h1><p>Generate regulatory reports from live data · India · {data.scope}.</p></div>
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
