import { useState } from "react";
import { Obligations } from "./RegSummary";
import { Badge } from "./ui";

const SHOWN = 25;  // register rows before "Show all"

// A vehicle category's or a topic's summary (Reports › Report builder preview)
export default function GroupSummaryView({ s, openReg }) {
  const [all, setAll] = useState(false);
  const Id = ({ id }) => <button className="btn ghost mono" style={{ padding: 0 }} onClick={() => openReg(id)}>{id}</button>;
  return (
        <div style={{ marginTop: 18, display: "flex", flexDirection: "column", gap: 18 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "flex-start" }}>
            <div>
              <h2 style={{ margin: 0, fontSize: 22 }}>{s.label}</h2>
              <div className="sub" style={{ marginTop: 4 }}>{s.kind_label} · {s.country_name} · filters: {s.filters} · {s.note}</div>
            </div>
          </div>

          {!s.register.length && <p className="rb-stale">No regulations match these filters. Choose another year or "All powertrains" and preview again.</p>}
          <div className="kpis" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
            {s.figures.map(([k, v]) => (
              <div key={k} className="card" style={{ padding: "14px 16px" }}>
                <div className="sub" style={{ fontSize: 12 }}>{k}</div>
                <div style={{ fontSize: 22, fontWeight: 750, marginTop: 4 }}>{v}</div>
              </div>))}
          </div>

          <div className="grid3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", alignItems: "start" }}>
            <div><h3 style={{ fontSize: 15, margin: "0 0 8px" }}>{s.breakdown.title}</h3>
              <div className="tablewrap"><table><thead><tr><th>{s.breakdown.label}</th><th>Regulations</th><th>High impact</th></tr></thead>
                <tbody>{s.breakdown.rows.map((g) => <tr key={g.name}><td>{g.name}</td><td>{g.regulations}</td><td>{g.high}</td></tr>)}</tbody>
              </table></div></div>
            <div><h3 style={{ fontSize: 15, margin: "0 0 8px" }}>Highest impact regulations (KPI score)</h3>
              <div className="tablewrap"><table><thead><tr><th>Regulation</th><th>Title</th><th>KPI</th></tr></thead>
                <tbody>{s.top_impact.map((r) => (
                  <tr key={r.id}><td><Id id={r.id} /></td><td className="wrap">{r.title}</td>
                    <td style={{ whiteSpace: "nowrap" }}><b>{r.kpi_score}</b> <Badge v={r.kpi_band} /></td></tr>))}
                </tbody></table></div></div>
          </div>

          <div><h3 style={{ fontSize: 15, margin: "0 0 8px" }}>Upcoming implementation dates</h3>
            <Obligations rows={s.upcoming} empty="None scheduled." /></div>

          <div><h3 style={{ fontSize: 15, margin: "0 0 8px" }}>Changes detected in the last 90 days
            {s.changes_total > s.changes.length && <span className="sub"> (latest {s.changes.length} of {s.changes_total})</span>}</h3>
            {s.changes.length ? <div className="tablewrap"><table><thead><tr><th>Detected</th><th>Type</th><th>Regulation</th><th>Summary</th></tr></thead>
              <tbody>{s.changes.map((c, i) => (
                <tr key={i}><td style={{ whiteSpace: "nowrap" }}>{c.date}</td><td>{c.type}</td><td><Id id={c.id} /></td><td className="wrap">{c.summary}</td></tr>))}
              </tbody></table></div> : <p className="note">No changes detected.</p>}</div>

          <div><h3 style={{ fontSize: 15, margin: "0 0 8px" }}>Regulation register ({s.register.length})</h3>
            <div className="tablewrap"><table><thead><tr><th>Regulation</th><th>Title</th><th>Published</th><th>Impact</th><th>KPI</th><th>Status</th></tr></thead>
              <tbody>{(all ? s.register : s.register.slice(0, SHOWN)).map((r) => (
                <tr key={r.id}><td><Id id={r.id} /></td><td className="wrap">{r.title}</td><td style={{ whiteSpace: "nowrap" }}>{r.date || "—"}</td>
                  <td><Badge v={r.impact} /></td><td>{r.kpi_score}</td><td><Badge v={r.status} /></td></tr>))}
              </tbody></table></div>
            {s.register.length > SHOWN && (
              <button className="btn ghost" onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show all ${s.register.length}`}</button>)}
          </div>

          <p className="note" style={{ fontSize: 12 }}><b>Disclaimer:</b> {s.disclaimer}</p>
        </div>
  );
}
