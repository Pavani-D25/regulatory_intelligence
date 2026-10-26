import { useEffect, useState } from "react";
import { portal } from "../../api";
import useLoad from "../../useLoad";
import { usePortal } from "../PortalLayout";
import { Badge, Card, ErrorBox, Kpi, Loading, SegmentPicker, segmentLabel } from "../ui";

const COVERAGE_TONE = { Covered: "green", Partial: "amber", Gap: "red" };
const ROLE_TONE = { primary: "green", supporting: "blue", candidate: "amber" };

export default function Requirements() {
  const { openReg, version, countryName, country, meta } = usePortal();
  // vehicle segment path, e.g. "4W/CV" (regtrack/segments.py): rows and coverage follow the linked regulations
  const [segment, setSegment] = useState("");
  useEffect(() => setSegment(""), [country]);
  const { data, error, loading } = useLoad(() => portal.requirements(segment), [version, segment]);
  const [filter, setFilter] = useState("");
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const k = data.kpis;
  const rows = data.rows.filter((r) => !filter || r.coverage === filter);
  return (
    <section className="view">
      <div className="pagehead">
        <div><h1>Requirements Register</h1>
          <p>The client's regulatory register for {countryName}, each requirement linked to the official documents collected for it.</p></div>
        <div className="actions">
          <select className="select" value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">All requirements</option>
            {["Covered", "Partial", "Gap"].map((s) => <option key={s}>{s}</option>)}
          </select>
        </div>
      </div>
      {(data.rows.length > 0 || segment) && <Card>
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <strong style={{ fontSize: 13 }}>Vehicle segment</strong>
          <SegmentPicker tree={meta?.segments} value={segment} onChange={setSegment} />
          {segment && <button className="btn ghost" onClick={() => setSegment("")}>Clear</button>}
          {loading && <span className="sub">updating…</span>}
        </div>
        {segment && <p className="note" style={{ marginTop: 8 }}>
          Requirements name their vehicles in free text, so the segment applies to their linked documents: coverage counts
          only documents for {segmentLabel(segment)} (or all vehicles).
          {data.kpis.other_vehicles > 0 && ` ${data.kpis.other_vehicles} requirement(s) whose documents are all for other vehicles are hidden;`} requirements
          with no document yet stay listed as gaps.</p>}
      </Card>}
      {!data.rows.length && !segment ? (
        <Card title="No register loaded"><p className="empty">No client requirement register is loaded for {countryName}.</p></Card>
      ) : (
        <>
          <div className="kpis">
            <Kpi label="Requirements" value={k.requirements} small="rows in the register" corner="▤" />
            <Kpi label="Covered" value={`${k.covered_pct}%`} small={`${k.covered} backed by a source document`} corner="✓" tone="green" />
            <Kpi label="Partial" value={k.partial} small="related document, not conclusive" corner="…" tone="amber" />
            <Kpi label="Gaps" value={k.gap} small="no source collected yet" corner="!" tone="red" />
          </div>
          <Card title="Register" sub={`${rows.length} requirement(s) · click a document to open it`}>
            <div className="tablewrap" style={{ maxHeight: 720 }}><table>
              <thead><tr><th>Requirement</th><th>Applies to</th><th>Authority / source</th><th>Coverage</th><th>Documents</th></tr></thead>
              <tbody>{rows.map((r) => (
                <tr key={r.code}>
                  <td style={{ whiteSpace: "normal", minWidth: 260 }}>
                    <strong>{r.code} · {r.topic}</strong>
                    <div className="sub">{r.requirement_text}</div>
                    {r.caution && <div className="sub" style={{ color: "var(--amber, #b7791f)" }}>⚠ {r.caution}</div>}
                  </td>
                  <td style={{ whiteSpace: "normal", minWidth: 160 }}><div className="sub">{r.applies_to}</div>
                    {r.client_status && <div className="sub"><em>{r.client_status}</em></div>}</td>
                  <td style={{ whiteSpace: "normal", minWidth: 160 }}>{r.authority}
                    {r.source_url && <div className="sub"><a href={r.source_url} target="_blank" rel="noreferrer">{r.source_name || r.source_url}</a></div>}</td>
                  <td><Badge v={r.coverage} tone={COVERAGE_TONE[r.coverage]} />
                    {r.mandates > 0 && <div className="sub">{r.mandates} obligation(s)</div>}</td>
                  <td style={{ whiteSpace: "normal", minWidth: 240 }}>
                    {r.regulations.length ? r.regulations.slice(0, 8).map((g) => (
                      <div key={g.canonical_id} style={{ marginBottom: 4 }}>
                        <Badge v={g.role} tone={ROLE_TONE[g.role]} />{" "}
                        <strong style={{ cursor: "pointer" }} onClick={() => openReg(g.canonical_id)}>{g.canonical_id}</strong>
                        {g.categories?.length > 0 && <span className="sub"> · {g.categories.join(", ")}</span>}
                        <div className="sub" title={g.subject}>{(g.subject || "").slice(0, 70)}</div>
                      </div>
                    )) : <span className="sub">No source document collected for this area yet</span>}
                    {r.regulations.length > 8 && <div className="sub">+{r.regulations.length - 8} more</div>}
                  </td>
                </tr>))}
              </tbody>
            </table></div>
          </Card>
        </>
      )}
    </section>
  );
}
