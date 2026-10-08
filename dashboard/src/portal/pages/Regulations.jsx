import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { portal } from "../../api";
import useLoad from "../../useLoad";
import { usePortal } from "../PortalLayout";
import { AiNote, Badge, Card, ErrorBox, fmt, Kpi, Loading, MetricRows } from "../ui";

const CATS = [["", "All categories"], ["L1", "L1 Moped"], ["L2", "L2 Two-wheeler"], ["M1", "M1 Car"], ["N1", "N1 Light goods"]];

function csv(rows) {
  const head = ["ID", "Regulation", "Category", "Authority", "Domain", "Effective", "Impact", "Status"];
  const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const body = rows.map((r) => [r.canonical_id, r.name, r.region, r.authority, r.domain, r.effective, r.impact, r.status].map(esc).join(","));
  const blob = new Blob(["﻿" + [head.join(","), ...body].join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `regulations_india_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
}

export default function Regulations() {
  const [sp, setSp] = useSearchParams();
  const f = { q: sp.get("q") || "", category: sp.get("category") || "", impact: sp.get("impact") || "", status: sp.get("status") || "", month: sp.get("month") || "" };
  const set = (k, v) => { const n = new URLSearchParams(sp); if (v) n.set(k, v); else n.delete(k); setSp(n, { replace: true }); };
  const { data, error, loading } = useLoad(() => portal.regulations({ q: f.q, category: f.category, impact: f.impact, status: f.status }),
    [f.q, f.category, f.impact, f.status]);
  const { openReg } = usePortal();
  const rows = useMemo(() => (data?.rows || []).filter((r) => !f.month || (r.doc_date || "").startsWith(f.month)), [data, f.month]);
  const k = data?.kpis;
  return (
    <section className="view">
      <div className="pagehead">
        <div><h1>Regulation Library</h1><p>Search, filter and review Indian vehicle regulations, standards and notifications for L1, L2, M1 and N1.</p></div>
        <div className="actions"><button className="btn secondary" disabled={!rows.length} onClick={() => csv(rows)}>Export CSV</button></div>
      </div>
      <div className="kpis">
        <Kpi label="Library Records" value={k?.records} small="Notifications, AIS standards, rules, acts" corner="L" />
        <Kpi label="New This Quarter" value={k?.new_quarter} small="Published in the last 90 days" corner="+" tone="green" />
        <Kpi label="Drafts Open" value={k?.drafts} small="Draft rules and draft AIS" corner="D" tone="amber" />
        <Kpi label="High Impact" value={k?.high} small="Rule-based until AI review" corner="!" tone="red" />
      </div>
      <Card>
        <div className="filterbar">
          <input className="input" placeholder="Search by ID, title, authority or topic" defaultValue={f.q}
            onKeyDown={(e) => { if (e.key === "Enter") set("q", e.target.value.trim()); }} onBlur={(e) => set("q", e.target.value.trim())} />
          <select className="select" value={f.category} onChange={(e) => set("category", e.target.value)}>
            {CATS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
          <select className="select" value={f.impact} onChange={(e) => set("impact", e.target.value)}>
            <option value="">All impact</option><option>High</option><option>Medium</option><option>Low</option></select>
          <select className="select" value={f.status} onChange={(e) => set("status", e.target.value)}>
            <option value="">All status</option><option>Action Required</option><option>Under Review</option><option>Impact Analysis</option><option>Tracked</option></select>
          <button className="btn secondary" onClick={() => setSp({}, { replace: true })}>Clear</button>
        </div>
        {f.month && <div className="sub" style={{ marginTop: 9 }}>Showing month {f.month} · <button className="btn ghost" style={{ padding: 0 }} onClick={() => set("month", "")}>remove</button></div>}
      </Card>
      <div className="grid2 wide">
        <Card title="Regulation Register" sub={loading ? "Loading…" : `${rows.length} matching records · click a row for detail`}>
          <ErrorBox error={error} />
          {loading ? <Loading /> : (
            <div className="tablewrap" style={{ maxHeight: 640 }}><table>
              <thead><tr><th>ID</th><th>Regulation</th><th>Category</th><th>Authority</th><th>Domain</th><th>Effective</th><th>Impact</th><th>Status</th></tr></thead>
              <tbody>{rows.slice(0, 300).map((r) => (
                <tr key={r.canonical_id} className="click" onClick={() => openReg(r.canonical_id)}>
                  <td className="mono">{r.canonical_id}</td>
                  <td><span className="truncate" style={{ display: "block" }} title={r.name}>{r.name}</span>{r.ai_pending && <AiNote />}</td>
                  <td>{r.region || "—"}</td><td>{r.authority}</td><td>{r.domain}</td><td>{fmt(r.effective)}</td>
                  <td><Badge v={r.impact} /></td><td><Badge v={r.status} /></td>
                </tr>))}
                {!rows.length && <tr><td colSpan={8} className="empty">No regulations match these filters.</td></tr>}
              </tbody>
            </table>{rows.length > 300 && <div className="sub" style={{ padding: 10 }}>Showing the first 300 of {rows.length} — narrow the filters or export CSV for all.</div>}</div>
          )}
        </Card>
        <Card title="Library Composition" sub="Documents by issuing authority">
          <MetricRows rows={data?.composition || []} onClick={(r) => set("q", r.name)} />
          <p className="note" style={{ marginTop: 16 }}>Impact is computed by rules (technical documents with dates still to come, new revisions requiring re-approval, or recently published) until the AI pass reviews each document. Status can be changed in the detail drawer and is saved.</p>
        </Card>
      </div>
    </section>
  );
}
