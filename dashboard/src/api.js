// Thin client for the RegTrack read API (regtrack/api/app.py).
export const API = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

// The selected country, injected into every request below so a page author never has to pass it explicitly.
// PortalLayout is the only writer (setApiCountry), and persists it under the same key it reads on load.
let currentCountry = (() => {
  try { return localStorage.getItem("ri.country") || "IN"; } catch { return "IN"; }
})();

export function setApiCountry(cc) {
  currentCountry = cc;
}

function qs(params = {}) {
  const p = new URLSearchParams();
  Object.entries({ country: currentCountry, ...params }).forEach(([k, v]) => {
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
  const payload = { country: currentCountry, ...(body || {}) };
  const r = await fetch(`${API}${path}${qs()}`, {
    method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
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
  summary: (p) => get("/portal/summary", p),
  regulations: (p) => get("/portal/regulations", p),
  detail: (id) => get(`/portal/regulations/${enc(id)}/detail`),
  review: (id, body) => send("PUT", `/portal/regulations/${enc(id)}/review`, body),
  changes: (days, segment) => get("/portal/changes", { days, segment }),
  markReviewed: (ids) => send("POST", "/portal/changes/review", { ids }),
  compliance: (category, segment) => get("/portal/compliance", { category, segment }),
  saveCompliance: (key, body) => send("PUT", `/portal/compliance/${enc(key)}`, body),
  impact: (segment) => get("/portal/impact", { segment }),
  impactCell: (category, domain, segment) => get("/portal/impact/cell", { category, domain, segment }),
  ask: (question, conversation_id) => send("POST", "/portal/ask", { question, conversation_id }),
  conversations: () => get("/portal/ask/conversations"),
  conversation: (id) => get(`/portal/ask/conversations/${id}`),
  team: () => get("/portal/team"),
  addTeam: (name) => send("POST", "/portal/teams", { name }),
  addUser: (body) => send("POST", "/portal/users", body),
  updateUser: (id, body) => send("PATCH", `/portal/users/${id}`, body),
  watches: (canonical_id) => get("/portal/watches", { canonical_id }),
  addWatch: (body) => send("POST", "/portal/watches", body),
  deleteWatch: (id) => send("DELETE", `/portal/watches/${id}`),
  schedules: () => get("/portal/report-schedules"),
  addSchedule: (body) => send("POST", "/portal/report-schedules", body),
  toggleSchedule: (id, is_active) => send("PATCH", `/portal/report-schedules/${id}`, { is_active }),
  deleteSchedule: (id) => send("DELETE", `/portal/report-schedules/${id}`),
  askContext: () => get("/portal/ask/context"),
  reports: (segment) => get("/portal/reports", { segment }),
  alerts: () => get("/portal/alerts"),
  addAlert: (body) => send("POST", "/portal/alerts", body),
  toggleAlert: (id, enabled) => send("PATCH", `/portal/alerts/${id}`, { enabled }),
  deleteAlert: (id) => send("DELETE", `/portal/alerts/${id}`),
  admin: () => get("/portal/admin"),
  saveSettings: (body) => send("PUT", "/portal/settings", body),
  sync: (source) => send("POST", "/portal/admin/sync", { source }),
  requirements: () => get("/portal/requirements"),
};
export const reportUrl = (kind, fmt = "html", segment = "") => `${API}/portal/reports/${kind}${qs({ fmt, segment })}`;
