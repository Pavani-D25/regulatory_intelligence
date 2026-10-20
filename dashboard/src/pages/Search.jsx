import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { AiPending, Card, DocLink, Empty, ErrorBox, Loading, classLabel, fmtDate } from "../components/ui";
import { usePortal } from "../portal/PortalLayout";
import useLoad from "../useLoad";

function highlight(text, q) {
  const words = q.split(/\s+/).filter((w) => w.length > 2).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!words.length) return text;
  const re = new RegExp(`(${words.join("|")})`, "gi");
  return text.split(re).map((part, i) => (i % 2 ? <mark key={i} className="rounded bg-amber-100 px-0.5">{part}</mark> : part));
}

export default function Search() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") || "";
  const category = params.get("category") || "";
  const [text, setText] = useState(q);
  const [cat, setCat] = useState(category);
  const { meta, version } = usePortal();
  const { data, error, loading } = useLoad(
    () => (q ? api.search({ q, category, in_scope: "", limit: 25 }) : null), [q, category, version]);
  const textMode = data?.mode?.startsWith("text");

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-xl font-semibold">Search</h1>
        <p className="text-sm text-zinc-500">Clause-level search over the English text of standards and notifications.</p>
      </div>
      <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); setParams(Object.fromEntries(Object.entries({ q: text, category: cat }).filter(([, v]) => v))); }}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. anti-lock braking for motorcycles" className="w-96 max-w-full" autoFocus />
        <select value={cat} onChange={(e) => setCat(e.target.value)} aria-label="Category">
          <option value="">Any category</option>
          {(meta?.categories || []).map((c) => <option key={c.code} value={c.code}>{c.code}</option>)}
        </select>
        <button className="rounded-md bg-brand px-3 py-1.5 text-sm text-white">Search</button>
      </form>
      {textMode && (
        <p className="text-xs text-zinc-500">
          Keyword matching for now <AiPending what="meaning-based search after embeddings" />
        </p>
      )}
      <ErrorBox error={error} />
      {!q ? <Empty>Type a question or a few words.</Empty> : loading ? <Loading /> : data && (
        <Card title={`${data.results.length} results`}>
          {data.results.length === 0 ? <Empty>No matching clauses.</Empty> : (
            <ul className="divide-y divide-zinc-100">
              {data.results.map((r) => (
                <li key={r.id} className="py-3">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <DocLink id={r.canonical_id} />
                    <span className="text-xs text-zinc-500">{classLabel(r.doc_class)} · {fmtDate(r.doc_date)}</span>
                    {r.clause_no && <span className="text-xs text-zinc-500">clause {r.clause_no}{r.heading && r.heading !== r.clause_no ? ` — ${r.heading}` : ""}</span>}
                    <span className="text-xs text-zinc-400">p. {r.page_from}{r.page_to !== r.page_from ? `–${r.page_to}` : ""}</span>
                  </div>
                  {(r.official_title || r.subject) && <div className="text-xs text-zinc-500">{r.official_title || r.subject}</div>}
                  <p className="mt-1 line-clamp-4 whitespace-pre-line text-sm text-zinc-700">{highlight(r.content, q)}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
    </div>
  );
}
