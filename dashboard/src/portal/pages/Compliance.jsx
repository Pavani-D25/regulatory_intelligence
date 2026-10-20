import { useEffect, useState } from "react";
import { portal } from "../../api";
import useLoad from "../../useLoad";
import { usePortal } from "../PortalLayout";
import { Badge, Card, ErrorBox, fmt, Kpi, Loading, MetricRows, Ring } from "../ui";

const STATUSES = ["Open", "In Progress", "Compliant", "Not Applicable"];

export default function Compliance() {
  const [category, setCategory] = useState("");
  const [tick, setTick] = useState(0);
  const { openReg, toast, meta, version, country } = usePortal();
  const { data, error, loading } = useLoad(() => portal.compliance(category), [category, tick, version]);
  const [edits, setEdits] = useState({});
  const [saving, setSaving] = useState(false);
  useEffect(() => setEdits({}), [data]);
  // a category selected under the previous country may not exist in this one
  useEffect(() => setCategory(""), [country]);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const k = data.kpis;
  const val = (r, f) => (edits[r.mandate_key]?.[f] ?? r[f] ?? "");
  const edit = (r, f, v) => setEdits((e) => ({ ...e, [r.mandate_key]: { ...e[r.mandate_key], [f]: v } }));
  const dirty = Object.keys(edits);
  const save = async () => {
    setSaving(true);
    try {
      for (const key of dirty) {
        const r = data.rows.find((x) => x.mandate_key === key);
        await portal.saveCompliance(key, {
          owner: val(r, "owner") || data.default_owner, evidence: val(r, "evidence"), status: val(r, "status") || "Open",
          due_date: val(r, "due_date") || null, note: val(r, "note"),
        });
      }
      toast(`${dirty.length} requirement(s) saved`);
      setTick((t) => t + 1);
    } catch (e) { toast(`Save failed: ${e.message}`); } finally { setSaving(false); }
  };
  return (
    <section className="view">
      <div className="pagehead">
        <div><h1>Compliance Matrix</h1><p>Map each obligation in force (CMVR rule + standard + categories) to owner, evidence and status.</p></div>
        <div className="actions">
          <select className="select" value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">All categories</option>{(meta?.categories || []).map((c) => <option key={c.code} value={c.code}>{c.label}</option>)}</select>
          <button className="btn primary" disabled={!dirty.length || saving} onClick={save}>{saving ? "Saving…" : `Save Matrix${dirty.length ? ` (${dirty.length})` : ""}`}</button>
        </div>
      </div>
      <div className="kpis">
        <Kpi label="Compliant" value={`${k.compliant_pct}%`} small={`of ${k.requirements} applicable requirements`} corner="✓" tone="green" />
        <Kpi label="In Progress" value={`${k.in_progress_pct}%`} small="Evidence being prepared" corner="…" tone="amber" />
        <Kpi label="Open Gaps" value={`${k.open_pct}%`} small="No owner / evidence yet" corner="!" tone="red" />
        <Kpi label="Due in 90 Days" value={k.due_90} small="Not yet compliant" corner="⏱" />
      </div>
      <div className="grid2 wide">
        <Card title="Requirement Mapping" sub={`${data.rows.length} obligations from notified rules · edit cells, then Save Matrix`}>
          <div className="tablewrap" style={{ maxHeight: 640 }}><table>
            <thead><tr><th>Requirement</th><th>Domain</th><th>Owner</th><th>Evidence</th><th>Status</th><th>Due</th></tr></thead>
            <tbody>{data.rows.map((r) => (
              <tr key={r.mandate_key} style={edits[r.mandate_key] ? { background: "#fffbea" } : undefined}>
                <td style={{ whiteSpace: "normal", minWidth: 260 }}>
                  <strong style={{ cursor: "pointer" }} onClick={() => openReg(r.canonical_id)}>{r.legal_basis}{r.standard_refs?.length ? ` · ${r.standard_refs.join(", ")}` : ""}</strong>
                  <div className="sub" title={r.subject}>{(r.subject || "").slice(0, 110)}{(r.subject || "").length > 110 ? "…" : ""}</div>
                  <div className="sub">{r.categories.join(", ")} · {r.canonical_id}</div>
                </td>
                <td>{r.domain}</td>
                <td><input className="input" style={{ width: 150 }} placeholder={data.default_owner} value={val(r, "owner")} onChange={(e) => edit(r, "owner", e.target.value)} /></td>
                <td><input className="input" style={{ width: 160 }} placeholder="Test report / CoP ref." value={val(r, "evidence")} onChange={(e) => edit(r, "evidence", e.target.value)} /></td>
                <td><select className="select" value={val(r, "status") || "Open"} onChange={(e) => edit(r, "status", e.target.value)}>
                  {STATUSES.map((s) => <option key={s}>{s}</option>)}</select></td>
                <td><input className="input" type="date" value={(val(r, "due_date") || "").slice(0, 10)} onChange={(e) => edit(r, "due_date", e.target.value)} />
                  <div className="sub">in force {fmt(r.implementation_date)}</div></td>
              </tr>))}
              {!data.rows.length && <tr><td colSpan={6} className="empty">No obligations for this category.</td></tr>}
            </tbody>
          </table></div>
        </Card>
        <div>
          <Card title="Compliance Readiness" sub="Share of applicable requirements marked compliant">
            <div style={{ display: "grid", placeItems: "center", padding: 8 }}><Ring pct={k.compliant_pct} label="ready" /></div>
            <div className="legend" style={{ marginTop: 12 }}>
              {STATUSES.map((s) => <div key={s} className="legendrow"><span><Badge v={s} /></span><b>{data.rows.filter((r) => r.status === s).length}</b></div>)}
            </div>
          </Card>
          <Card title="Readiness by Domain" sub="% compliant per topic">
            <MetricRows rows={data.readiness} />
          </Card>
        </div>
      </div>
    </section>
  );
}
