// Thin client for the RegTrack read API (regtrack/api/app.py).
export const API = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

function qs(params = {}) {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "" && v !== false) p.set(k, v);
  });
  const s = p.toString();
  return s ? `?${s}` : "";
}

async function get(path, params) {
  const r = await fetch(`${API}${path}${qs(params)}`);
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch { /* not json */ }
    throw new Error(`${r.status}: ${detail}`);
  }
  return r.json();
}

const enc = (s) => encodeURIComponent(s);

export const api = {
  meta: () => get("/meta"),
  applicable: (p) => get("/vehicles/applicable", p),
  documents: (p) => get("/documents", p),
  document: (id) => get(`/documents/${enc(id)}`),
  families: (q) => get("/families", { q }),
  family: (key) => get(`/families/${enc(key)}/versions`),
  changes: (since) => get("/changes", { since, limit: 500 }),
  search: (p) => get("/search", p),
};

export const fileUrl = (sha, download = false) => `${API}/files/${sha}${download ? "?download=true" : ""}`;
export const sharePackUrl = (p) => `${API}/share-pack${qs(p)}`;
export const docPath = (id) => `/doc/${enc(id)}`;
export const familyPath = (key) => `/versions/${enc(key)}`;

// ---- portal (approved design v2) -------------------------------------------------------------
async function send(method, path, body) {
  const r = await fetch(`${API}${path}`, {
    method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch { /* not json */ }
    throw new Error(`${r.status}: ${detail}`);
  }
  return r.json();
}

export const portal = {
  meta: () => get("/portal/meta"),
  summary: () => get("/portal/summary"),
  regulations: (p) => get("/portal/regulations", p),
  detail: (id) => get(`/portal/regulations/${enc(id)}/detail`),
  review: (id, body) => send("PUT", `/portal/regulations/${enc(id)}/review`, body),
  changes: (days) => get("/portal/changes", { days }),
  markReviewed: (ids) => send("POST", "/portal/changes/review", { ids }),
  compliance: (category) => get("/portal/compliance", { category }),
  saveCompliance: (key, body) => send("PUT", `/portal/compliance/${enc(key)}`, body),
  impact: () => get("/portal/impact"),
  impactCell: (category, domain) => get("/portal/impact/cell", { category, domain }),
  ask: (question) => send("POST", "/portal/ask", { question }),
  askContext: () => get("/portal/ask/context"),
  reports: () => get("/portal/reports"),
  alerts: () => get("/portal/alerts"),
  addAlert: (body) => send("POST", "/portal/alerts", body),
  toggleAlert: (id, enabled) => send("PATCH", `/portal/alerts/${id}`, { enabled }),
  deleteAlert: (id) => send("DELETE", `/portal/alerts/${id}`),
  admin: () => get("/portal/admin"),
  saveSettings: (body) => send("PUT", "/portal/settings", body),
  sync: (source) => send("POST", "/portal/admin/sync", { source }),
};
export const reportUrl = (kind, fmt = "html") => `${API}/portal/reports/${kind}?fmt=${fmt}`;
