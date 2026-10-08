import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { docPath, fileUrl, portal } from "../api";
import "./portal.css";
import { Badge, fmt } from "./ui";

// views of the approved design, in its order; "Tools" are the earlier RegTrack pages kept reachable
const NAV = [
  ["/", "▦", "Dashboard"], ["/regulations", "≡", "Regulations"], ["/changes", "↻", "Change Monitor"],
  ["/compliance", "✓", "Compliance Matrix"], ["/impact", "⌁", "Impact View"], ["/ai", "✦", "Ask Regulatory AI"],
  ["/reports", "▤", "Reports"], ["/alerts", "◉", "Alerts"], ["/admin", "⚙", "Admin"],
];
const TOOLS = [["/vehicle", "◎", "Vehicle Check"], ["/versions", "⇄", "Versions"]];
const TITLES = Object.fromEntries([...NAV, ...TOOLS, ["/search", "", "Search"], ["/doc", "", "Document"]].map(([p, , t]) => [p, t]));

const Ctx = createContext(null);
export const usePortal = () => useContext(Ctx);

function Drawer({ id, onClose, toast }) {
  const nav = useNavigate();
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const [form, setForm] = useState({ status: "", owner: "" });
  useEffect(() => {
    if (!id) return;
    setD(null); setErr(null);
    portal.detail(id).then((x) => { setD(x); setForm({ status: x.status, owner: x.owner || "" }); }).catch(setErr);
  }, [id]);
  const save = async () => {
    await portal.review(id, { status: form.status, owner: form.owner });
    toast("Review status saved");
    setD({ ...d, status: form.status, owner: form.owner });
  };
  return (
    <>
      <div className={`drawer ${id ? "open" : ""}`}>
        <div className="drawerhead">
          <div><small style={{ color: "var(--muted)" }}>REGULATION DETAIL</small>
            <h2 style={{ margin: "4px 0 0", fontSize: 18 }}>{d ? d.name : id ? "Loading…" : "—"}</h2></div>
          <button className="close" onClick={onClose}>×</button>
        </div>
        <div className="drawerbody">
          {err && <div className="errorbox">{String(err.message || err)}</div>}
          {d && (
            <>
              <div className="detailgrid">
                <div className="detail"><small>ID</small><strong className="mono">{d.canonical_id}</strong></div>
                <div className="detail"><small>Authority</small><strong>{d.authority}</strong></div>
                <div className="detail"><small>Vehicle category</small><strong>{d.region || "—"}</strong></div>
                <div className="detail"><small>Effective</small><strong>{fmt(d.effective)}</strong></div>
                <div className="detail"><small>Impact{d.impact_basis === "rules" ? " (rule-based)" : ""}</small><Badge v={d.impact} /></div>
                <div className="detail"><small>Status</small><Badge v={d.status} /></div>
              </div>
              <h3 style={{ fontSize: 14, marginTop: 20 }}>Summary</h3>
              <p className="note" style={{ fontSize: 12 }}>{d.summary}{d.ai_pending && <span className="aitag"> · ✦ AI summary pending</span>}</p>
              <h3 style={{ fontSize: 14 }}>Detected Change</h3>
              <p className="note" style={{ fontSize: 12 }}>{d.change}</p>
              <h3 style={{ fontSize: 14 }}>Recommended Follow-up</h3>
              <p className="note" style={{ fontSize: 12 }}>{d.action}</p>
              <div className="formrow">
                <label className="formlabel">Review status
                  <select className="select" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                    {["Action Required", "Under Review", "Impact Analysis", "Tracked"].map((s) => <option key={s}>{s}</option>)}
                  </select></label>
                <label className="formlabel">Owner
                  <input className="input" value={form.owner} placeholder="Team / person" onChange={(e) => setForm({ ...form, owner: e.target.value })} /></label>
              </div>
              <div className="actions" style={{ marginTop: 10 }}>
                <button className="btn secondary" onClick={save}>Save review</button>
                <button className="btn primary" onClick={() => { onClose(); nav("/compliance"); }}>Open Compliance Mapping</button>
                <button className="btn secondary" onClick={() => { onClose(); nav(`/ai?q=${encodeURIComponent(`Summarize ${d.canonical_id} and its impact`)}`); }}>Ask Regulatory AI</button>
              </div>
              <div className="actions" style={{ marginTop: 10 }}>
                {d.file && <a className="btn ghost" href={fileUrl(d.file.sha256)} target="_blank" rel="noreferrer">Open original PDF ↗</a>}
                <button className="btn ghost" onClick={() => { onClose(); nav(docPath(d.canonical_id)); }}>Full record →</button>
              </div>
            </>
          )}
        </div>
      </div>
      <div className={`backdrop ${id ? "show" : ""}`} onClick={onClose} />
    </>
  );
}

export default function PortalLayout() {
  const nav = useNavigate();
  const loc = useLocation();
  const [meta, setMeta] = useState(null);
  const [drawer, setDrawer] = useState(null);
  const [toastMsg, setToastMsg] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => { portal.meta().then(setMeta).catch(() => setMeta(null)); }, []);
  useEffect(() => { window.scrollTo(0, 0); }, [loc.pathname]);
  const toast = useCallback((m) => { setToastMsg(m); setTimeout(() => setToastMsg(""), 1800); }, []);
  const base = "/" + (loc.pathname.split("/")[1] || "");
  const title = TITLES[base] || "Dashboard";

  return (
    <Ctx.Provider value={{ openReg: setDrawer, toast, meta }}>
      <div className="app portal">
        <aside className="sidebar">
          <div className="brand"><div className="brandmark">RI</div><div><strong>Regulatory Intelligence</strong><small>Automotive Compliance · India</small></div></div>
          <nav className="nav">
            {NAV.map(([p, icon, label]) => (
              <button key={p} className={base === p ? "active" : ""} onClick={() => nav(p)}>{icon} <span>{label}</span></button>
            ))}
            <div className="navgroup">Tools</div>
            {TOOLS.map(([p, icon, label]) => (
              <button key={p} className={base === p ? "active" : ""} onClick={() => nav(p)}>{icon} <span>{label}</span></button>
            ))}
          </nav>
          <div className="sidefoot">
            <div className="health"><span className="dot" style={meta && meta.sources < 4 ? { background: "#f59e0b" } : undefined} />
              <span>{meta ? `${meta.sources} sources connected` : "connecting…"}</span></div>
            <div style={{ marginTop: 8, color: "#9ca3af" }}>Last sync: {meta?.last_sync ? new Date(meta.last_sync).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) + " IST" : "—"}</div>
          </div>
        </aside>
        <main className="main">
          <header className="topbar">
            <div className="crumb">Regulatory Intelligence / <strong>{title}</strong></div>
            <div className="topactions">
              <div className="search">⌕ <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search regulation, category, topic..."
                onKeyDown={(e) => { if (e.key === "Enter" && q.trim()) nav(`/regulations?q=${encodeURIComponent(q.trim())}`); }} /></div>
              <select className="select" defaultValue="en" aria-label="Language"><option value="en">English</option></select>
              <div className="avatar" title="Regulatory Affairs">RA</div>
            </div>
          </header>
          <div className="content"><Outlet /></div>
        </main>
      </div>
      <div className="portal"><Drawer id={drawer} onClose={() => setDrawer(null)} toast={toast} /></div>
      <div className={`toast ${toastMsg ? "show" : ""}`}>{toastMsg}</div>
    </Ctx.Provider>
  );
}
