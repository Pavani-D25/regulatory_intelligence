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
