import { useEffect, useMemo, useState } from "react";
import { fileUrl, portal, regSummaryPdfUrl } from "../api";
import { Badge, Card } from "./ui";

const BASIS = { data: "from data", estimate: "estimate", team: "team" };

export function Obligations({ rows, empty }) {
  if (!rows.length) return <p className="note">{empty}</p>;
  return (
    <div className="tablewrap"><table>
      <thead><tr><th>Applies from</th><th>Requirement</th><th>Applies to</th><th>Categories</th><th>Standards / basis</th></tr></thead>
      <tbody>{rows.map((o, i) => (
        <tr key={i}><td style={{ whiteSpace: "nowrap" }}>{o.date || "—"}</td>
          <td className="wrap" style={{ minWidth: 280 }}>{o.requirement}</td><td>{o.applies_to}</td>
          <td>{o.categories.join(", ")}</td>
          <td>{o.standards.join(", ")}{o.legal_basis ? ` (${o.legal_basis})` : ""}{o.draft && <> <Badge v="draft" tone="amber" /></>}</td></tr>))}
      </tbody>
    </table></div>
  );
}

// Reports › Regulation summary: pick one regulation, read its detailed summary, download it as a PDF
export default function RegSummary({ version }) {
  const [regs, setRegs] = useState([]);
  const [query, setQuery] = useState("");
  const [s, setS] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => { portal.regulations({ history: true }).then((r) => setRegs(r.rows)).catch(() => setRegs([])); }, [version]);
  const byId = useMemo(() => new Map(regs.map((r) => [r.canonical_id, r])), [regs]);
  // the typed text may be "ID — name" (picked from the list) or just the ID
  const chosen = byId.get(query.split(" — ")[0].trim()) ? query.split(" — ")[0].trim() : null;

  const view = async () => {
    if (!chosen) return;
    setBusy(true); setErr("");
    try { setS(await portal.regSummary(chosen)); } catch (e) { setErr(e.message); setS(null); } finally { setBusy(false); }
  };

  return (
    <Card title="Regulation Summary" sub="Choose one regulation to see its detailed summary and download it as a PDF">
      <div style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
        <label className="formlabel" style={{ flex: "1 1 360px", maxWidth: 640 }}>Regulation
          <input className="input" list="reg-summary-list" placeholder="Type an ID or a title, e.g. GSR-310(E)-2016"
            value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && view()} />
          <datalist id="reg-summary-list">
            {regs.map((r) => <option key={r.canonical_id} value={`${r.canonical_id} — ${r.name || ""}`.slice(0, 140)} />)}
          </datalist>
        </label>
        <button className="btn primary" disabled={!chosen || busy} onClick={view}>{busy ? "Loading…" : "View summary"}</button>
        {chosen && <a className="btn secondary" href={regSummaryPdfUrl(chosen)}>⤓ Download PDF</a>}
      </div>
      {query && !chosen && <p className="note" style={{ marginTop: 8 }}>Pick a regulation from the list.</p>}
      {err && <p className="note" style={{ color: "var(--red)" }}>{err}</p>}

      {s && (
        <div className="regsum" style={{ marginTop: 18, display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "flex-start" }}>
            <div>
              <h2 style={{ margin: 0, fontSize: 22 }}>{s.canonical_id}</h2>
              <div className="sub" style={{ marginTop: 4 }}>{s.title}{s.subtitle ? ` · ${s.subtitle}` : ""}</div>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              {s.file && <a className="btn secondary" href={fileUrl(s.file.sha256)} target="_blank" rel="noreferrer">Open original ↗</a>}
              <a className="btn primary" href={regSummaryPdfUrl(s.canonical_id)}>⤓ Download PDF</a>
            </div>
          </div>

          <div className="tablewrap"><table><tbody>
            {s.facts.map(([k, v]) => <tr key={k}><th style={{ width: 220, textAlign: "left" }}>{k}</th><td>{v || "—"}</td></tr>)}
          </tbody></table></div>

          <div className="grid3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
            <div><h3 style={{ fontSize: 14, margin: "0 0 6px" }}>Summary</h3><p className="note" style={{ fontSize: 13 }}>{s.summary}
              {s.ai_pending && <span className="aitag"> · ✦ AI summary pending</span>}</p></div>
            <div><h3 style={{ fontSize: 14, margin: "0 0 6px" }}>Detected change</h3><p className="note" style={{ fontSize: 13 }}>{s.change || "—"}</p></div>
            <div><h3 style={{ fontSize: 14, margin: "0 0 6px" }}>Recommended follow-up</h3><p className="note" style={{ fontSize: 13 }}>{s.action || "—"}</p></div>
          </div>

          <div>
            <h3 style={{ fontSize: 15, margin: "0 0 4px" }}>Impact assessment</h3>
            <p className="note" style={{ margin: "0 0 8px" }}>Rule-based impact <Badge v={s.impact.level} /> · status <Badge v={s.impact.workflow} /> ·
              impact KPI score <b>{s.impact.kpi_score} / 100</b> <Badge v={s.impact.kpi_band} /></p>
            <div className="tablewrap"><table>
              <thead><tr><th>Criterion</th><th>Weight</th><th>Score</th><th>Points</th><th>Basis and reason</th></tr></thead>
              <tbody>{s.impact.kpi.map((k) => (
                <tr key={k.key}><td><strong>{k.label}</strong></td><td>{k.weight}%</td><td>{k.score} / 5</td><td>{k.points}</td>
                  <td>{BASIS[k.basis] || k.basis} · {k.reason}</td></tr>))}
              </tbody>
            </table></div>
          </div>

          <div><h3 style={{ fontSize: 15, margin: "0 0 8px" }}>Obligations set by this regulation</h3>
            <Obligations rows={s.obligations} empty="None recorded." /></div>
          <div><h3 style={{ fontSize: 15, margin: "0 0 8px" }}>Obligations citing this regulation as a standard</h3>
            <Obligations rows={s.cited_by} empty="None recorded." /></div>

          <div className="grid3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))" }}>
            <div><h3 style={{ fontSize: 15, margin: "0 0 8px" }}>Related documents</h3>
              {s.related.length ? <div className="tablewrap"><table><thead><tr><th>Relation</th><th>Document</th></tr></thead>
                <tbody>{s.related.map((r, i) => <tr key={i}><td>{r.relation}</td><td className="mono">{r.document}</td></tr>)}</tbody></table></div>
                : <p className="note">None recorded.</p>}</div>
            <div><h3 style={{ fontSize: 15, margin: "0 0 8px" }}>Version history</h3>
              {s.versions.length ? <div className="tablewrap"><table><thead><tr><th>Version</th><th>Type</th><th>Date</th><th /></tr></thead>
                <tbody>{s.versions.map((v) => <tr key={v.id}><td className="mono">{v.id}</td><td>{v.type}</td><td>{v.date || "—"}</td>
                  <td>{v.current && <Badge v="Current" tone="green" />}</td></tr>)}</tbody></table></div>
                : <p className="note">Not part of a versioned family.</p>}</div>
          </div>

          <p className="note" style={{ fontSize: 12 }}><b>Disclaimer:</b> {s.disclaimer}</p>
        </div>
      )}
    </Card>
  );
}
