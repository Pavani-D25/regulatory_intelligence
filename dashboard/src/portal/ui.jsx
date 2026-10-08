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

export function Loading() { return <div className="loading">Loading live data…</div>; }
export function ErrorBox({ error }) {
  if (!error) return null;
  return <div className="errorbox">{String(error.message || error)} — is the API running? (python -m regtrack.cli api)</div>;
}
export function AiNote({ children = "✦ AI fields pending" }) { return <span className="aitag">{children}</span>; }
