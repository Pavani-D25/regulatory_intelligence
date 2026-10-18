import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { api, docPath, familyPath, fileUrl, portal } from "../api";
import "./portal.css";
import { ago, Badge, fmt, fmtTime } from "./ui";

// views of the approved design, in its order; "Tools" are the earlier RegTrack pages kept reachable
const NAV = [
  ["/", "▦", "Dashboard"], ["/regulations", "≡", "Regulations"], ["/changes", "↻", "Change Monitor"],
  ["/compliance", "✓", "Compliance Matrix"], ["/impact", "⌁", "Impact View"], ["/ai", "✦", "Ask Regulatory AI"],
  ["/reports", "▤", "Reports"], ["/alerts", "◉", "Alerts"], ["/team", "◍", "Teams"], ["/admin", "⚙", "Admin"],
];
const TOOLS = [["/vehicle", "◎", "Vehicle Check"], ["/versions", "⇄", "Versions"]];
const TITLES = Object.fromEntries([...NAV, ...TOOLS, ["/search", "", "Search"], ["/doc", "", "Document"]].map(([p, , t]) => [p, t]));
const REL_LABEL = {
  amends: "Amends", supersedes: "Supersedes", finalises: "Finalises draft", extends_date: "Extends dates in",
  substitutes_row: "Substitutes rows in", inserts_row: "Inserts rows in", omits_row: "Omits rows in", corrects: "Corrects",
  references: "References", rescinds: "Rescinds", implements: "Implements",
};
const REL_IN = {
  amends: "Amended by", supersedes: "Superseded by", finalises: "Finalised by", extends_date: "Dates extended by",
  substitutes_row: "Changed by", inserts_row: "Changed by", omits_row: "Changed by", corrects: "Corrected by",
  references: "Referenced by", rescinds: "Rescinded by", implements: "Implemented by",
};

const Ctx = createContext(null);
export const usePortal = () => useContext(Ctx);

const store = {  // per-viewer convenience only (bell "seen" time); the page works without it
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private window */ } },
};

function DrawerSection({ title, children, empty }) {
  return (
    <>
      <h3 style={{ fontSize: 14 }}>{title}</h3>
      {children || <p className="note">{empty}</p>}
    </>
  );
}

// who follows this regulation; a team starts or stops watching it here (portal: Teams page lists all watches)
function Watchers({ id, teams, toast }) {
  const [list, setList] = useState(null);
  const [team, setTeam] = useState("");
  const load = useCallback(() => portal.watches(id).then((x) => setList(x.watches)).catch(() => setList([])), [id]);
  useEffect(() => { setList(null); load(); }, [load]);
  const free = (teams || []).filter((t) => !(list || []).some((w) => w.team_id === t.id));
  const add = async () => {
    try { await portal.addWatch({ canonical_id: id, team_id: Number(team) }); toast("Watching"); setTeam(""); load(); }
    catch (e) { toast(e.message); }
  };
  const remove = async (w) => { await portal.deleteWatch(w.id); toast("Watch removed"); load(); };
  return (
    <DrawerSection title="Watched By" empty={list ? null : "Loading…"}>
      {list && (
        <>
          <div className="chips">
            {list.map((w) => <span key={w.id} className="chip">{w.team || w.user}<b onClick={() => remove(w)} title="Stop watching" style={{ cursor: "pointer" }}>×</b></span>)}
            {!list.length && <span className="note">Nobody watches this regulation yet.</span>}
          </div>
          {free.length > 0 && (
            <div className="actions" style={{ marginTop: 8 }}>
              <select className="select" value={team} onChange={(e) => setTeam(e.target.value)}>
                <option value="">Choose a team…</option>{free.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select>
              <button className="btn secondary" disabled={!team} onClick={add}>Watch</button>
            </div>
          )}
        </>
      )}
    </DrawerSection>
  );
}

function Drawer({ id, onClose, toast, openReg, teams }) {
  const nav = useNavigate();
  const [d, setD] = useState(null);
  const [full, setFull] = useState(null);
  const [fam, setFam] = useState(null);
  const [err, setErr] = useState(null);
  const [form, setForm] = useState({ status: "", owner: "" });
  useEffect(() => {
    if (!id) return;
    setD(null); setFull(null); setFam(null); setErr(null);
    portal.detail(id).then((x) => {
      setD(x); setForm({ status: x.status, owner: x.owner || "" });
      if (x.family_key) api.family(x.family_key).then(setFam).catch(() => setFam(null));
    }).catch(setErr);
    api.document(id).then(setFull).catch(() => setFull(null));
  }, [id]);
  useEffect(() => {
    const esc = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  const save = async () => {
    await portal.review(id, { status: form.status, owner: form.owner });
    toast("Review status saved");
    setD({ ...d, status: form.status, owner: form.owner });
  };
  const go = (cid) => { if (cid && cid !== id) openReg(cid); };
  const rels = [...(full?.relations_out || []).filter((r) => r.type !== "references").map((r) => ({ ...r, dir: "out" })),
    ...(full?.relations_in || []).map((r) => ({ ...r, dir: "in", target: r.source, resolved: true }))];
  const versions = fam?.versions || [];
  return (
    <>
      <div className={`drawer ${id ? "open" : ""}`}>
        <div className="drawerhead">
          <div><small style={{ color: "var(--muted)" }}>REGULATION DETAIL</small>
            <h2 style={{ margin: "4px 0 0", fontSize: 18 }}>{d ? d.name : id ? "Loading…" : "—"}</h2>
            {d?.subtitle && <div className="sub">{d.subtitle}</div>}</div>
          <button className="close" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="drawerbody">
          {err && <div className="errorbox">{String(err.message || err)}</div>}
          {!d && id && !err && <div className="skeleton" style={{ height: 220 }} />}
          {d && (
            <>
              <div className="detailgrid">
                <div className="detail"><small>ID</small><strong className="mono">{d.canonical_id}</strong></div>
                <div className="detail"><small>Authority</small><strong>{d.authority}</strong></div>
                <div className="detail"><small>Vehicle category</small><strong>{d.region || "—"}</strong></div>
                <div className="detail"><small>Effective</small><strong>{fmt(d.effective)}</strong></div>
                <div className="detail"><small>Impact{d.impact_basis === "rules" ? " (rule-based)" : ""}</small><Badge v={d.impact} /></div>
                <div className="detail"><small>Status</small><Badge v={d.status} />{d.doc_status === "superseded" && <> <Badge v="Superseded" tone="blue" /></>}</div>
              </div>
              <DrawerSection title="Summary">
                <p className="note" style={{ fontSize: 12 }}>{d.summary}{d.ai_pending && <span className="aitag"> · ✦ AI summary pending</span>}</p>
              </DrawerSection>
              <DrawerSection title="Detected Change"><p className="note" style={{ fontSize: 12 }}>{d.change}</p></DrawerSection>
              <DrawerSection title="Recommended Follow-up"><p className="note" style={{ fontSize: 12 }}>{d.action}</p></DrawerSection>

              <DrawerSection title={`Obligations${full?.mandates?.length ? ` (${full.mandates.length})` : ""}`}
                empty={full ? "No dated obligations read from this document." : "Loading…"}>
                {full?.mandates?.length > 0 && (
                  <div className="stack">
                    {full.mandates.slice(0, 6).map((m) => (
                      <div key={m.id} className="taskitem">
                        <div className="itemmain"><div><strong style={{ fontSize: 12 }}>{m.mandate_key}</strong>
                          <small>{(m.vehicle_categories || []).join(", ")}{m.is_draft ? " · proposed" : ""}{m.valid_to ? " · replaced" : ""}</small></div></div>
                        <Badge v={fmt(m.implementation_date)} tone={m.is_draft ? "purple" : "amber"} />
                      </div>
                    ))}
                  </div>
                )}
              </DrawerSection>

              <DrawerSection title="Related Documents" empty={full ? "No links to other documents found." : "Loading…"}>
                {rels.length > 0 && (
                  <div className="stack">
                    {rels.slice(0, 8).map((r, i) => (
                      <div key={i} className="taskitem" style={{ cursor: r.resolved ? "pointer" : "default" }} onClick={() => r.resolved && go(r.target)}>
                        <div className="itemmain"><div>
                          <small>{r.dir === "in" ? REL_IN[r.type] || r.type : REL_LABEL[r.type] || r.type}</small>
                          <strong className="mono" style={{ fontSize: 12 }}>{r.target}</strong></div></div>
                        {!r.resolved && <Badge v="not collected" tone="blue" />}
                      </div>
                    ))}
                  </div>
                )}
              </DrawerSection>

              {versions.length > 1 && (
                <DrawerSection title={`Version History (${versions.length})`}>
                  <div className="timeline">
                    {versions.slice(-6).reverse().map((v) => (
                      <div key={v.canonical_id} className="event" style={{ gridTemplateColumns: "90px 18px 1fr", padding: "6px 0" }}>
                        <div className="date">{fmt(v.doc_date)}</div><div className="axis" />
                        <div className="eventbox" style={{ padding: 8 }} onClick={() => go(v.canonical_id)}>
                          <h3 className="mono" style={{ fontSize: 12 }}>{v.canonical_id} {v.is_current && <Badge v="current" tone="green" />}</h3>
                        </div>
                      </div>
                    ))}
                  </div>
                  <button className="btn ghost" style={{ padding: 0 }} onClick={() => { onClose(); nav(familyPath(d.family_key)); }}>Full timeline →</button>
                </DrawerSection>
              )}

              <Watchers id={d.canonical_id} teams={teams} toast={toast} />

              <div className="formrow" style={{ marginTop: 8 }}>
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
                <button className="btn secondary" onClick={() => { onClose(); nav(`/ai?q=${encodeURIComponent(`Summarize ${d.canonical_id}`)}`); }}>Ask Regulatory AI</button>
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

function Bell({ version, openReg }) {
  const nav = useNavigate();
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [seen, setSeen] = useState(() => store.get("ri.bellSeen") || "");
  const box = useRef(null);
  useEffect(() => { portal.alerts().then((a) => setItems(a.notifications)).catch(() => setItems([])); }, [version]);
  useEffect(() => {
    const out = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", out);
    return () => document.removeEventListener("mousedown", out);
  }, []);
  const unread = items.filter((n) => n.when > seen).length;
  const toggle = () => {
    setOpen(!open);
    if (!open && items[0]) { store.set("ri.bellSeen", items[0].when); setSeen(items[0].when); }
  };
  return (
    <div className="bellwrap" ref={box}>
      <button className="bell" onClick={toggle} aria-label={`${unread} new notifications`}>🔔{unread > 0 && <span className="bellcount">{unread > 99 ? "99+" : unread}</span>}</button>
      {open && (
        <div className="bellmenu">
          <div className="cardhead" style={{ margin: 0, padding: "12px 14px", borderBottom: "1px solid var(--line)" }}>
            <strong style={{ fontSize: 13 }}>Notifications</strong><span className="sub" style={{ margin: 0 }}>from active alert rules</span></div>
          <div style={{ maxHeight: 360, overflow: "auto" }}>
            {items.slice(0, 10).map((n, i) => (
              <button key={i} className="bellitem" onClick={() => { setOpen(false); if (n.canonical_id) openReg(n.canonical_id); }}>
                <strong>{n.title}</strong><span>{n.text}</span><small>{n.when.slice(0, 10)}</small>
              </button>
            ))}
            {!items.length && <div className="empty">No notifications.</div>}
          </div>
          <button className="btn ghost" style={{ width: "100%", borderTop: "1px solid var(--line)", borderRadius: 0 }} onClick={() => { setOpen(false); nav("/alerts"); }}>View all alerts →</button>
        </div>
      )}
    </div>
  );
}

export default function PortalLayout() {
  const nav = useNavigate();
  const loc = useLocation();
  const [meta, setMeta] = useState(null);
  const [version, setVersion] = useState(0);
  const lastSync = useRef(null);
  const [drawer, setDrawer] = useState(null);
  const [toastMsg, setToastMsg] = useState("");
  const [q, setQ] = useState("");
  const searchRef = useRef(null);
  const toast = useCallback((m) => { setToastMsg(m); setTimeout(() => setToastMsg(""), 2200); }, []);
  // poll source / scheduler status every minute; when a sync has landed new data, every page reloads ("version")
  useEffect(() => {
    const load = () => portal.meta().then((m) => {
      setMeta(m);
      if (lastSync.current && m.last_sync && m.last_sync !== lastSync.current) {
        setVersion((v) => v + 1);
        toast("New sync finished — data refreshed");
      }
      lastSync.current = m.last_sync;
    }).catch(() => setMeta(null));
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [toast]);
  useEffect(() => { window.scrollTo(0, 0); }, [loc.pathname]);
  useEffect(() => {  // "/" jumps to the search box
    const key = (e) => {
      if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) { e.preventDefault(); searchRef.current?.focus(); }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  const closeDrawer = useCallback(() => setDrawer(null), []);
  const base = "/" + (loc.pathname.split("/")[1] || "");
  const title = TITLES[base] || "Dashboard";
  const sch = meta?.scheduler;

  return (
    <Ctx.Provider value={{ openReg: setDrawer, toast, meta, version }}>
      <div className="app portal">
        <aside className="sidebar">
          <div className="brand"><div className="brandmark">RI</div><div><strong>Regulatory Intelligence</strong><small>India · Automotive</small></div></div>
          <nav className="nav">
            {NAV.map(([p, icon, label]) => (
              <button key={p} className={base === p ? "active" : ""} onClick={() => nav(p)} title={label}>{icon} <span>{label}</span></button>
            ))}
            <div className="navgroup">Tools</div>
            {TOOLS.map(([p, icon, label]) => (
              <button key={p} className={base === p ? "active" : ""} onClick={() => nav(p)} title={label}>{icon} <span>{label}</span></button>
            ))}
          </nav>
          <div className="sidefoot">
            <div className="health"><span className="dot" style={meta && meta.sources < meta.sources_total ? { background: "#f59e0b" } : undefined} />
              <span>{meta ? `${meta.sources}/${meta.sources_total} sources connected` : "connecting…"}</span></div>
            <div className="health" style={{ marginTop: 8 }}>
              <span className="dot" style={{ background: !sch ? "#6b7280" : sch.alive && sch.auto_sync ? "#22c55e" : "#ef4444" }} />
              <span>{!sch ? "—" : !sch.auto_sync ? "Auto-sync paused" : sch.alive ? "Auto-sync running" : "Auto-sync not running"}</span></div>
            <div style={{ marginTop: 8, color: "#9ca3af" }} title={meta?.last_sync ? fmtTime(meta.last_sync) : ""}>Last sync: {meta?.last_sync ? ago(meta.last_sync) : "—"}</div>
          </div>
        </aside>
        <main className="main">
          <header className="topbar">
            <div className="crumb">Regulatory Intelligence / <strong>{title}</strong></div>
            <div className="topactions">
              <div className="search">⌕ <input ref={searchRef} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search regulation, category, topic…  ( / )"
                onKeyDown={(e) => { if (e.key === "Enter" && q.trim()) { nav(`/regulations?q=${encodeURIComponent(q.trim())}`); e.target.blur(); } }} /></div>
              <Bell version={version} openReg={setDrawer} />
              <select className="select" defaultValue="en" aria-label="Language"><option value="en">English</option></select>
              <div className="avatar" title="Regulatory Affairs">RA</div>
            </div>
          </header>
          <div className="content"><Outlet /></div>
        </main>
      </div>
      <div className="portal"><Drawer id={drawer} onClose={closeDrawer} toast={toast} openReg={setDrawer} teams={meta?.teams} /></div>
      <div className={`toast ${toastMsg ? "show" : ""}`}>{toastMsg}</div>
    </Ctx.Provider>
  );
}
