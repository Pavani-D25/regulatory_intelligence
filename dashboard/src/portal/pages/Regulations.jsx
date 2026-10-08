import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { portal } from "../../api";
import useLoad from "../../useLoad";
import { usePortal } from "../PortalLayout";
import { Badge, Card, ErrorBox, fmt, Kpi, Loading, MetricRows, OfficialId } from "../ui";

const PAGE = 50;
const IMPACT_RANK = { High: 0, Medium: 1, Low: 2 };
const STATUS_RANK = { "Action Required": 0, "Under Review": 1, "Impact Analysis": 2, Tracked: 3 };
const COLS = [
  ["canonical_id", "ID"], ["name", "Regulation"], ["region", "Category"], ["authority", "Authority"],
  ["domain", "Domain"], ["effective", "Effective"], ["impact", "Impact"], ["status", "Status"],
];

function csv(rows) {
  const head = ["ID", "Regulation", "Category", "Authority", "Domain", "Effective", "Impact", "Status", "Document status"];
  const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const body = rows.map((r) => [r.canonical_id, r.name, r.region, r.authority, r.domain, r.effective, r.impact, r.status, r.doc_status].map(esc).join(","));
  const blob = new Blob(["﻿" + [head.join(","), ...body].join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `regulations_india_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
}

function sortValue(r, key) {
  if (key === "impact") return IMPACT_RANK[r.impact] ?? 9;
  if (key === "status") return STATUS_RANK[r.status] ?? 9;
  return (r[key] ?? "").toString().toLowerCase();
}

export default function Regulations() {
  const [sp, setSp] = useSearchParams();
  const f = {
    q: sp.get("q") || "", category: sp.get("category") || "", impact: sp.get("impact") || "", status: sp.get("status") || "",
    month: sp.get("month") || "", history: sp.get("history") === "1",
  };
  const set = (k, v) => { const n = new URLSearchParams(sp); if (v) n.set(k, v); else n.delete(k); setSp(n, { replace: true }); };
  const { openReg, meta, version } = usePortal();
  const { data, error, loading } = useLoad(
    () => portal.regulations({ q: f.q, category: f.category, impact: f.impact, status: f.status, history: f.history }),
    [f.q, f.category, f.impact, f.status, f.history, version]);
  const [sort, setSort] = useState({ key: "effective", dir: -1 });
  const [page, setPage] = useState(0);
  const cats = [["", "All categories"], ...(meta?.categories || []).map((c) => [c.code, c.label])];
  const rows = useMemo(() => {
    const r = (data?.rows || []).filter((x) => !f.month || (x.doc_date || "").startsWith(f.month));
    return [...r].sort((a, b) => {
      const va = sortValue(a, sort.key), vb = sortValue(b, sort.key);
      return (va < vb ? -1 : va > vb ? 1 : 0) * sort.dir;
    });
  }, [data, f.month, sort]);
  useEffect(() => setPage(0), [data, f.month, sort]);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const shown = rows.slice(page * PAGE, page * PAGE + PAGE);
  const pending = (data?.rows || []).filter((r) => r.ai_pending).length;
  const byStatus = ["Action Required", "Under Review", "Impact Analysis", "Tracked"].map((s) => ({ name: s, n: rows.filter((r) => r.status === s).length }));
  const k = data?.kpis;
  const head = (key, label) => (
    <th key={key} className="sort" onClick={() => setSort((s) => ({ key, dir: s.key === key ? -s.dir : key === "effective" ? -1 : 1 }))}>
      {label}{sort.key === key ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
    </th>
  );
  if (loading && !data) return <Loading />;
  return (
    <section className="view">
      <div className="pagehead">
        <div><h1>Regulation Library</h1><p>Search, filter and review Indian vehicle regulations, standards and notifications for {(meta?.categories || []).map((c) => c.code).join(", ")}.</p></div>
        <div className="actions"><button className="btn secondary" disabled={!rows.length} onClick={() => csv(rows)}>Export CSV ({rows.length})</button></div>
      </div>
      <div className="kpis">
        <Kpi label="Library Records" value={k?.records} small={f.history ? "Including superseded documents" : `In force and drafts · ${k?.superseded ?? 0} superseded hidden`} corner="L" />
        <Kpi label="New This Quarter" value={k?.new_quarter} small="Published in the last 90 days" corner="+" tone="green" />
        <Kpi label="Drafts Open" value={k?.drafts} small="Draft rules and draft AIS" corner="D" tone="amber" />
        <Kpi label="High Impact" value={k?.high} small="Rule-based until AI review" corner="!" tone="red" />
      </div>
      <Card>
        <div className="filterbar">
          <input className="input" placeholder="Search by ID, title, authority or topic" defaultValue={f.q} key={f.q}
            onKeyDown={(e) => { if (e.key === "Enter") set("q", e.target.value.trim()); }} onBlur={(e) => set("q", e.target.value.trim())} />
          <select className="select" value={f.category} onChange={(e) => set("category", e.target.value)}>
            {cats.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
          <select className="select" value={f.impact} onChange={(e) => set("impact", e.target.value)}>
            <option value="">All impact</option><option>High</option><option>Medium</option><option>Low</option></select>
          <select className="select" value={f.status} onChange={(e) => set("status", e.target.value)}>
            <option value="">All status</option><option>Action Required</option><option>Under Review</option><option>Impact Analysis</option><option>Tracked</option></select>
          <button className="btn secondary" onClick={() => setSp({}, { replace: true })}>Clear</button>
        </div>
        <div style={{ display: "flex", gap: 16, alignItems: "center", marginTop: 10, flexWrap: "wrap" }}>
          <label className="sub" style={{ display: "flex", gap: 6, alignItems: "center", margin: 0 }}>
            <input type="checkbox" checked={f.history} onChange={(e) => set("history", e.target.checked ? "1" : "")} /> Show superseded documents ({k?.superseded ?? 0})</label>
          {f.month && <span className="sub" style={{ margin: 0 }}>Month {f.month} · <button className="btn ghost" style={{ padding: 0 }} onClick={() => set("month", "")}>remove</button></span>}
        </div>
      </Card>
      {pending > 0 && <div className="banner">✦ <span>AI summaries and impact review are pending for <b>{pending}</b> of {data.rows.length} regulations. They fill in automatically once LM Studio is connected; until then impact is rule-based.</span></div>}
      <Card title="Regulation Register" sub={`${rows.length} matching records · click a column to sort · click a row for detail`}>
        <ErrorBox error={error} />
        <div className="tablewrap"><table>
          <thead><tr>{COLS.map(([key, label]) => head(key, label))}</tr></thead>
          <tbody>{shown.map((r) => (
            <tr key={r.canonical_id} className="click" onClick={() => openReg(r.canonical_id)}>
              <td><OfficialId id={r.canonical_id} /></td>
              <td className="wrap"><span className="clamp2" title={r.name}>{r.name}</span>
                {r.doc_status === "superseded" && <Badge v="Superseded" tone="blue" />}</td>
              <td>{r.region || "—"}</td><td>{r.authority}</td><td className="wrap" style={{ minWidth: 120 }}>{r.domain}</td><td>{fmt(r.effective)}</td>
              <td><Badge v={r.impact} /></td><td><Badge v={r.status} /></td>
            </tr>))}
            {!rows.length && <tr><td colSpan={8} className="empty">No regulations match these filters.</td></tr>}
          </tbody>
        </table></div>
        {pages > 1 && (
          <div className="pager">
            <span>{page * PAGE + 1}–{Math.min(rows.length, page * PAGE + PAGE)} of {rows.length}</span>
            <button className="btn secondary" disabled={page === 0} onClick={() => setPage(page - 1)}>← Prev</button>
            <span>Page {page + 1} / {pages}</span>
            <button className="btn secondary" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>Next →</button>
          </div>
        )}
      </Card>
      <div className="grid2">
        <Card title="Library Composition" sub="Documents by issuing authority · click to filter">
          <MetricRows rows={data?.composition || []} onClick={(r) => set("q", r.name === "Unknown" ? "" : r.name)} />
        </Card>
        <Card title="Review Status" sub="Matching records by status · click to filter">
          <MetricRows rows={byStatus} onClick={(r) => set("status", r.name)} />
          <p className="note" style={{ marginTop: 14 }}>Status follows the rules shown in Admin until your team sets it in the detail drawer; a team decision always wins.</p>
        </Card>
      </div>
    </section>
  );
}
