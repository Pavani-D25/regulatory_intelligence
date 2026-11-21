import { useState } from "react";
import { catSummaryPdfUrl, portal } from "../api";
import { Obligations } from "./RegSummary";
import { Badge, Card } from "./ui";

const SHOWN = 25;  // register rows before "Show all"

// Reports › Category summary: pick a vehicle category, read its summary, download it as a PDF
export default function CatSummary({ meta, openReg }) {
  const cats = meta?.categories || [];
  const [cat, setCat] = useState("");
  const [s, setS] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [all, setAll] = useState(false);

  const view = async () => {
    if (!cat) return;
    setBusy(true); setErr(""); setAll(false);
    try { setS(await portal.catSummary(cat)); } catch (e) { setErr(e.message); setS(null); } finally { setBusy(false); }
  };
  const Id = ({ id }) => <button className="btn ghost mono" style={{ padding: 0 }} onClick={() => openReg(id)}>{id}</button>;

  return (
    <Card title="Category Summary" sub="Choose a vehicle category to see its regulatory summary and download it as a PDF; follows the year and powertrain filters">
      <div style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
        <label className="formlabel" style={{ flex: "0 1 360px" }}>Vehicle category
          <select className="select" value={cat} onChange={(e) => { setCat(e.target.value); setS(null); }}>
            <option value="">Choose a category…</option>
            {cats.map((c) => <option key={c.code} value={c.code}>{c.label}</option>)}
          </select>
        </label>
        <button className="btn primary" disabled={!cat || busy} onClick={view}>{busy ? "Loading…" : "View summary"}</button>
        {cat && <a className="btn secondary" href={catSummaryPdfUrl(cat)}>⤓ Download PDF</a>}
      </div>
      {err && <p className="note" style={{ color: "var(--red)" }}>{err}</p>}

      {s && (
        <div style={{ marginTop: 18, display: "flex", flexDirection: "column", gap: 18 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "flex-start" }}>
            <div>
              <h2 style={{ margin: 0, fontSize: 22 }}>{s.label}</h2>
              <div className="sub" style={{ marginTop: 4 }}>{s.country_name} · filters: {s.filters} · {s.note}</div>
            </div>
            <a className="btn primary" href={catSummaryPdfUrl(s.category)}>⤓ Download PDF</a>
          </div>

          <div className="kpis" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
            {s.figures.map(([k, v]) => (
              <div key={k} className="card" style={{ padding: "14px 16px" }}>
                <div className="sub" style={{ fontSize: 12 }}>{k}</div>
                <div style={{ fontSize: 22, fontWeight: 750, marginTop: 4 }}>{v}</div>
              </div>))}
          </div>

          <div className="grid3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", alignItems: "start" }}>
            <div><h3 style={{ fontSize: 15, margin: "0 0 8px" }}>Regulations by topic</h3>
              <div className="tablewrap"><table><thead><tr><th>Topic</th><th>Regulations</th><th>High impact</th></tr></thead>
                <tbody>{s.topics.map((t) => <tr key={t.topic}><td>{t.topic}</td><td>{t.regulations}</td><td>{t.high}</td></tr>)}</tbody>
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
      )}
    </Card>
  );
}
