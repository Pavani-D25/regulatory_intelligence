import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { API, api } from "../api";
import { fmtDate } from "./ui";

const NAV = [
  ["/", "Vehicle check"],
  ["/browse", "Browse"],
  ["/versions", "Versions"],
  ["/changes", "Changes"],
  ["/search", "Search"],
];

export default function Layout() {
  const [meta, setMeta] = useState(null);
  const [q, setQ] = useState("");
  const nav = useNavigate();
  useEffect(() => { api.meta().then(setMeta).catch(() => setMeta(null)); }, []);
  const s = meta?.stats;

  return (
    <div className="min-h-screen">
      <header className="border-b border-zinc-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <NavLink to="/" className="text-base font-bold text-zinc-900 no-underline hover:no-underline">
            Reg<span className="text-brand">Track</span> India
          </NavLink>
          <nav className="flex flex-wrap gap-1">
            {NAV.map(([to, label]) => (
              <NavLink key={to} to={to} end={to === "/"}
                className={({ isActive }) =>
                  `rounded-md px-2.5 py-1.5 text-sm no-underline hover:no-underline ${isActive ? "bg-brand-soft font-medium text-brand" : "text-zinc-600 hover:bg-zinc-100"}`}>
                {label}
              </NavLink>
            ))}
          </nav>
          <form className="ml-auto" onSubmit={(e) => { e.preventDefault(); if (q.trim()) nav(`/search?q=${encodeURIComponent(q.trim())}`); }}>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search regulations…" className="w-56" aria-label="Search" />
          </form>
        </div>
      </header>

      {s && (
        <div className="border-b border-zinc-200 bg-white/60">
          <div className="mx-auto flex max-w-6xl flex-wrap gap-x-6 gap-y-1 px-4 py-2 text-xs text-zinc-500">
            <span><b className="text-zinc-800">{s.documents.toLocaleString()}</b> documents</span>
            <span><b className="text-zinc-800">{s.in_scope.toLocaleString()}</b> in scope (L1/L2/M1/N1)</span>
            <span><b className="text-zinc-800">{s.open_mandates}</b> open mandates</span>
            <span><b className="text-zinc-800">{s.changes_30d}</b> changes in 30 days</span>
            <span>last crawl {fmtDate(s.last_crawl)}</span>
            {s.ai_pending > 0 && (
              <span className="text-violet-700">✦ AI fields pending for {s.ai_pending.toLocaleString()} documents (LM Studio not connected)</span>
            )}
          </div>
        </div>
      )}

      <main className="mx-auto max-w-6xl px-4 py-6">
        <Outlet />
      </main>
      <footer className="mx-auto max-w-6xl px-4 pb-8 text-xs text-zinc-400">
        Read-only view of the RegTrack database · API <a href={`${API}/docs`}>{API}</a>
      </footer>
    </div>
  );
}
