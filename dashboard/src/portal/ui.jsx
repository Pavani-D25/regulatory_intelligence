// Small building blocks in the approved design's vocabulary (pill, kpi, card, metric row, donut, ring).
import { useEffect, useRef, useState } from "react";
import Select from "./Select";

const TONE = {
  High: "red", "Action Required": "red", Medium: "amber", "Under Review": "amber", "Impact Analysis": "purple",
  Low: "green", Tracked: "green", Open: "red", "In Progress": "amber", Compliant: "green", "Not Applicable": "blue",
  ok: "green", partial: "amber", failed: "red", running: "blue",
};
export function Badge({ v, tone }) {
  if (!v) return <span className="pill blue">—</span>;
  return <span className={`pill ${tone || TONE[v] || "blue"}`}>{v}</span>;
}

export function fmt(d) {
  if (!d) return "—";
  const x = new Date(d);
  return Number.isNaN(x.getTime()) ? String(d) : x.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

// "5 min ago" / "3 h ago" / "2 d ago" from a timestamp
export function ago(t) {
  if (!t) return "—";
  const m = Math.max(0, Math.round((Date.now() - new Date(t).getTime()) / 60000));
  return m < 60 ? `${m} min ago` : m < 2880 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`;
}

// local date-time with the browser's own time-zone name (e.g. "08 Oct, 04:16 GMT+5:30")
export function fmtTime(t) {
  if (!t) return "—";
  return new Date(t).toLocaleString(undefined, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", timeZoneName: "short" });
}

export function Kpi({ label, value, small, corner, tone = "" }) {
  return (
    <div className={`kpi ${tone}`}><div className="corner">{corner}</div><span className="label">{label}</span>
      <strong>{value ?? "—"}</strong><small>{small}</small></div>
  );
}

export function Card({ title, sub, right, children, className = "", style }) {
  return (
    <div className={`card ${className}`} style={style}>
      {(title || right) && (
        <div className="cardhead"><div>{title && <h2>{title}</h2>}{sub && <div className="sub">{sub}</div>}</div>{right}</div>
      )}
      {children}
    </div>
  );
}

export function MetricRows({ rows, onClick, suffix = "" }) {
  const peak = Math.max(1, ...rows.map((r) => r.n));
  if (!rows.length) return <div className="empty">No data yet.</div>;
  return (
    <div className="stack">
      {rows.map((r) => (
        <div key={r.name} className="metricrow" style={onClick ? { cursor: "pointer" } : undefined} onClick={onClick ? () => onClick(r) : undefined}>
          <span title={r.name} style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.name}</span>
          <div className="bartrack"><div className="barfill" style={{ width: `${(r.pct ?? (r.n / peak) * 100)}%` }} /></div>
          <b>{r.pct !== undefined ? `${r.pct}%` : r.n}{suffix}</b>
        </div>
      ))}
    </div>
  );
}

export function Donut({ parts, total, label }) {
  const sum = parts.reduce((a, p) => a + p.n, 0) || 1;
  let acc = 0;
  const stops = parts.map((p) => { const a = (acc / sum) * 100; acc += p.n; return `${p.color} ${a}% ${(acc / sum) * 100}%`; });
  return (
    <div className="donutwrap">
      <div className="donut" style={{ background: `conic-gradient(${stops.join(",")})` }}>
        <div className="donutcenter"><div><strong>{total ?? sum}</strong>{label}</div></div>
      </div>
      <div className="legend">
        {parts.map((p) => (
          <div key={p.name} className="legendrow"><span><i className="sw" style={{ background: p.color }} />{p.name}</span><b>{p.n}</b></div>
        ))}
      </div>
    </div>
  );
}

export function Ring({ pct, label, color = "var(--green)" }) {
  return (
    <div className="progressRing" style={{ background: `conic-gradient(${color} 0 ${pct}%,#e8edf4 ${pct}% 100%)` }}>
      <div className="ringtext"><div><strong>{pct}%</strong><span>{label}</span></div></div>
    </div>
  );
}

// page-shaped placeholder while live data loads (inline=true for a small block inside a card)
export function Loading({ inline = false }) {
  if (inline) return <div className="skeleton" style={{ height: 120 }} aria-label="Loading" />;
  return (
    <div aria-label="Loading live data">
      <div className="skeleton" style={{ height: 54, width: "45%", marginBottom: 18 }} />
      <div className="skelkpis">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton" style={{ height: 116 }} />)}</div>
      <div className="skeleton" style={{ height: 320 }} />
    </div>
  );
}

// documents without an official number get a generated id (DOC-…, NOTIF-…): show that plainly
export function OfficialId({ id }) {
  if (/^(DOC|NOTIF)-[0-9a-f]{8,}$/.test(id || "")) return <span className="idmuted" title={id}>no official no.</span>;
  return <span className="mono">{id}</span>;
}
export function ErrorBox({ error }) {
  if (!error) return null;
  return <div className="errorbox">{String(error.message || error)} — is the API running? (python -m regtrack.cli api)</div>;
}
export function AiNote({ children = "✦ AI fields pending" }) { return <span className="aitag">{children}</span>; }

// Vehicle-segment picker: class (2W/4W) → category (PV/CV) → type (L1, M1, N1...) → subtype (private, transport...).
// `tree` is meta.segments (regtrack/segments.py); value / onChange use the path "4W/PV/M1/transport" ("" = all).
const SEGMENT_LEVELS = ["All vehicles", "PV and CV", "All types", "All uses"];
export function SegmentPicker({ tree, value, onChange }) {
  const keys = (value || "").split("/").filter(Boolean);
  const levels = [];
  let nodes = tree || [];
  for (let i = 0; i < 4 && nodes.length; i++) {
    levels.push(nodes);
    const node = nodes.find((n) => n.key === keys[i]);
    if (!node) break;
    nodes = node.children || [];
  }
  const pick = (i, k) => onChange([...keys.slice(0, i), k].filter(Boolean).join("/"));
  return (
    <div className="segpick">
      {levels.map((opts, i) => (
        <Select key={i} className="select" aria-label={["Vehicle class", "Vehicle category", "Vehicle type", "Use"][i]}
          value={keys[i] || ""} onChange={(e) => pick(i, e.target.value)}>
          <option value="">{SEGMENT_LEVELS[i]}</option>
          {opts.map((n) => <option key={n.key} value={n.key}>{n.label}</option>)}
        </Select>
      ))}
    </div>
  );
}
// "4W/PV/M1/transport" -> "4W-PV · M1 · transport" for headings
export const segmentLabel = (path) => {
  const k = (path || "").split("/").filter(Boolean);
  return k.length ? [k.slice(0, 2).join("-"), ...k.slice(2)].join(" · ") : "";
};

// The year filter: "" (all years), "2024" (one year) or "2020-2024" (a range), as the API's ?year= takes it
export const yearRange = (v) => {
  if (!v) return null;
  const [a, b = a] = String(v).split("-").map(Number);
  return [Math.min(a, b), Math.max(a, b)];
};
export const yearLabel = (v) => {
  const r = yearRange(v);
  return !r ? "All years" : r[0] === r[1] ? String(r[0]) : `${r[0]}–${r[1]}`;
};

export function YearFilter({ value, years = [], onChange, label = "Year", disabled = false }) {
  const [open, setOpen] = useState(false);
  const r = yearRange(value);
  const modeOf = (x) => (!x ? "all" : x[0] === x[1] ? "single" : "range");
  const [mode, setMode] = useState(modeOf(r));
  const box = useRef(null);
  const sorted = [...years].sort((x, y) => y - x);
  const newest = sorted[0] || new Date().getFullYear();
  const oldest = sorted[sorted.length - 1] || newest;
  useEffect(() => { setMode(modeOf(yearRange(value))); }, [value]);
  useEffect(() => {
    if (!open) return undefined;
    // a click in a dropdown list (portal/Select.jsx, rendered at the page body) counts as inside
    const close = (e) => { if (box.current && !box.current.contains(e.target) && !e.target.closest?.(".sel-pop")) setOpen(false); };
    const esc = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  const range = (a, b) => onChange(`${Math.min(a, b)}-${Math.max(a, b)}`);
  const pick = (m) => {
    setMode(m);
    if (m === "all") onChange("");
    else if (m === "single") onChange(String(r ? r[1] : newest));
    else {
      const to = r ? r[1] : newest;
      range(Math.max(r && r[0] !== r[1] ? r[0] : to - 4, oldest), to);
    }
  };
  const opts = sorted.map((y) => <option key={y} value={y}>{y}</option>);
  return (
    <div className="yearfilter" ref={box}>
      <button type="button" className="select yf-btn" aria-label={label} aria-expanded={open} disabled={disabled}
        onClick={() => setOpen(!open)} title="Show regulations published in one year or a range of years">
        <span>{yearLabel(value)}</span><span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="yf-pop" role="dialog" aria-label={`${label} filter`}>
          <div className="yf-tabs">
            {[["all", "All years"], ["single", "Single year"], ["range", "Range"]].map(([m, l]) => (
              <button key={m} type="button" className={mode === m ? "on" : ""} onClick={() => pick(m)}>{l}</button>))}
          </div>
          {mode === "single" && r && (
            <label className="yf-row yf-col">Year
              <Select className="select" value={r[0]} onChange={(e) => onChange(e.target.value)}>{opts}</Select>
            </label>)}
          {mode === "range" && r && (
            <div className="yf-row">
              <label className="yf-col">From
                <Select className="select" value={r[0]} onChange={(e) => range(Number(e.target.value), r[1])}>{opts}</Select>
              </label>
              <label className="yf-col">To
                <Select className="select" value={r[1]} onChange={(e) => range(r[0], Number(e.target.value))}>{opts}</Select>
              </label>
            </div>)}
          <div className="yf-foot">
            <span className="sub">{mode === "all" ? "Every publication year" : `Published ${yearLabel(value)}`}</span>
            <button type="button" className="btn primary" onClick={() => setOpen(false)}>Done</button>
          </div>
        </div>)}
    </div>
  );
}

// A compact multi-select: a button ("All codes" / "3 selected") opening a panel with a search, grouped tick boxes and
// "all" per group, in a short scrolling list. options: [{ value, label, group, n }]; value: the chosen values.
export function MultiSelect({ options, value, onChange, allLabel = "All", noun = "selected", label = "Filter", searchHint = "Search…" }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const box = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    // a click in a dropdown list (portal/Select.jsx, rendered at the page body) counts as inside
    const close = (e) => { if (box.current && !box.current.contains(e.target) && !e.target.closest?.(".sel-pop")) setOpen(false); };
    const esc = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  const sel = new Set(value);
  const ql = q.trim().toLowerCase();
  const shown = ql ? options.filter((o) => `${o.value} ${o.label}`.toLowerCase().includes(ql)) : options;
  const groups = [];
  shown.forEach((o) => {
    let g = groups.find((x) => x.name === o.group);
    if (!g) groups.push((g = { name: o.group, items: [] }));
    g.items.push(o);
  });
  const toggle = (v) => onChange(sel.has(v) ? value.filter((x) => x !== v) : [...value, v]);
  const setGroup = (items, on) => {
    const vs = items.map((o) => o.value);
    onChange(on ? [...value, ...vs.filter((v) => !sel.has(v))] : value.filter((v) => !vs.includes(v)));
  };
  const text = !value.length ? allLabel : value.length === 1 ? (options.find((o) => o.value === value[0])?.label || value[0]) : `${value.length} ${noun}`;
  return (
    <div className="multiselect" ref={box}>
      <button type="button" className="select yf-btn" aria-label={label} aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="ms-text">{text}</span><span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="ms-pop" role="dialog" aria-label={label}>
          <input className="input" autoFocus placeholder={searchHint} value={q} onChange={(e) => setQ(e.target.value)} />
          <div className="ms-list">
            {groups.map((g) => {
              const on = g.items.every((o) => sel.has(o.value));
              return (
                <div key={g.name}>
                  <label className="ms-group"><input type="checkbox" checked={on} onChange={() => setGroup(g.items, !on)} />
                    {g.name} <span className="sub">({g.items.length})</span></label>
                  {g.items.map((o) => (
                    <label key={o.value} className="ms-item"><input type="checkbox" checked={sel.has(o.value)} onChange={() => toggle(o.value)} />
                      <span>{o.label}</span>{o.n != null && <span className="sub">{o.n}</span>}</label>))}
                </div>);
            })}
            {!groups.length && <div className="sub" style={{ padding: 10 }}>Nothing matches.</div>}
          </div>
          <div className="yf-foot">
            <button type="button" className="btn ghost" disabled={!value.length} onClick={() => onChange([])}>Clear</button>
            <span className="sub">{value.length ? `${value.length} ${noun}` : allLabel}</span>
            <button type="button" className="btn primary" onClick={() => setOpen(false)}>Done</button>
          </div>
        </div>)}
    </div>
  );
}
