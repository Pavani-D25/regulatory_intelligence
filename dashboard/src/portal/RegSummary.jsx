import { Badge } from "./ui";

// A regulation's detailed summary from its own text (regtrack/pipeline/digest.py): sections of sentences and facts
export function Digest({ digest, compact = false }) {
  const size = compact ? 12 : 13;
  return (
    <div className="digest" style={{ fontSize: size }}>
      {digest.sections.map((sec) => (
        <div key={sec.title} style={{ marginBottom: compact ? 10 : 14 }}>
          <div style={{ fontWeight: 650, marginBottom: 4, color: "var(--ink, #0f172a)" }}>{sec.title}</div>
          {sec.text && <p className="note" style={{ fontSize: size, margin: 0 }}>{sec.text}</p>}
          {sec.items?.length > 0 && (
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {sec.items.map((it, i) => <li key={i} className="note" style={{ fontSize: size, marginBottom: 3 }}>{it}</li>)}
            </ul>)}
        </div>))}
      <p className="note" style={{ fontSize: 11, margin: 0, fontStyle: "italic" }}>{digest.source}.</p>
    </div>
  );
}

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

// One regulation's detailed summary (Reports › Report builder preview)
export function RegSummaryView({ s }) {
  return (
        <div className="regsum" style={{ marginTop: 18, display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "flex-start" }}>
            <div>
              <h2 style={{ margin: 0, fontSize: 22 }}>{s.canonical_id}</h2>
              <div className="sub" style={{ marginTop: 4 }}>{s.title}{s.subtitle ? ` · ${s.subtitle}` : ""}</div>
            </div>
          </div>

          <div className="tablewrap"><table><tbody>
            {s.facts.map(([k, v]) => <tr key={k}><th style={{ width: 220, textAlign: "left" }}>{k}</th><td>{v || "—"}</td></tr>)}
          </tbody></table></div>

          <div className="grid3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
            <div><h3 style={{ fontSize: 14, margin: "0 0 6px" }}>Summary</h3><p className="note" style={{ fontSize: 13 }}>{s.summary}
</p></div>
            <div><h3 style={{ fontSize: 14, margin: "0 0 6px" }}>Detected change</h3><p className="note" style={{ fontSize: 13 }}>{s.change || "—"}</p></div>
            <div><h3 style={{ fontSize: 14, margin: "0 0 6px" }}>Recommended follow-up</h3><p className="note" style={{ fontSize: 13 }}>{s.action || "—"}</p></div>
          </div>

          {s.digest?.sections?.length > 0 && (
            <div><h3 style={{ fontSize: 15, margin: "0 0 8px" }}>Detailed summary</h3><Digest digest={s.digest} /></div>)}

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
  );
}
