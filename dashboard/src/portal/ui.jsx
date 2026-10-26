// Small building blocks in the approved design's vocabulary (pill, kpi, card, metric row, donut, ring).

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
        <select key={i} className="select" aria-label={["Vehicle class", "Vehicle category", "Vehicle type", "Use"][i]}
          value={keys[i] || ""} onChange={(e) => pick(i, e.target.value)}>
          <option value="">{SEGMENT_LEVELS[i]}</option>
          {opts.map((n) => <option key={n.key} value={n.key}>{n.label}</option>)}
        </select>
      ))}
    </div>
  );
}
// "4W/PV/M1/transport" -> "4W-PV · M1 · transport" for headings
export const segmentLabel = (path) => {
  const k = (path || "").split("/").filter(Boolean);
  return k.length ? [k.slice(0, 2).join("-"), ...k.slice(2)].join(" · ") : "";
};
