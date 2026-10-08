import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { AiPending, Button, Card, Chips, DocLink, Empty, ErrorBox, Loading, StatusBadges, Table, Td, classLabel, fmtDate } from "../components/ui";
import useLoad from "../useLoad";

const PAGE = 50;

export default function Browse() {
  const [params, setParams] = useSearchParams();
  const [meta, setMeta] = useState(null);
  useEffect(() => { api.meta().then(setMeta).catch(() => {}); }, []);

  const f = {
    year: params.get("year") || "", category: params.get("category") || "", domain: params.get("domain") || "",
    doc_class: params.get("doc_class") || "", in_scope: params.get("in_scope") === "1", q: params.get("q") || "",
  };
  const offset = Number(params.get("offset") || 0);
  const update = (patch) => {
    const next = { ...f, ...patch, offset: patch.offset ?? 0 };
    setParams(Object.fromEntries(Object.entries(next).filter(([, v]) => v !== "" && v !== false && v !== 0)
      .map(([k, v]) => [k, v === true ? "1" : String(v)])));
  };

  const { data, error, loading } = useLoad(
    () => api.documents({ ...f, in_scope: f.in_scope ? "true" : "", limit: PAGE, offset }),
    [params.toString()],
  );
  // only plausible years in the chart (a few documents carry mis-read future dates; they are flagged for checking)
  const maxYear = new Date().getFullYear() + 1;
  const years = (meta?.years || []).filter((y) => y.year >= 1950 && y.year <= maxYear);
  const peak = Math.max(1, ...years.map((y) => y.n));

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-xl font-semibold">Browse</h1>
        <p className="text-sm text-zinc-500">All collected documents by year, vehicle category, topic and type.</p>
      </div>

      {years.length > 0 && (
        <Card title="Documents per year" actions={f.year && <button className="text-xs text-brand" onClick={() => update({ year: "" })}>all years</button>}>
          <div className="flex h-24 items-end gap-[3px] overflow-x-auto pb-1">
            {[...years].reverse().map((y) => (
              <button key={y.year} onClick={() => update({ year: String(y.year) })} title={`${y.year}: ${y.n}`}
                className="group flex min-w-[14px] flex-1 flex-col items-center justify-end">
                <span className={`w-full rounded-t-sm ${String(y.year) === f.year ? "bg-brand" : "bg-brand/40 group-hover:bg-brand/70"}`}
                  style={{ height: `${Math.max(4, (y.n / peak) * 80)}px` }} />
              </button>
            ))}
          </div>
          <div className="mt-1 flex justify-between text-[11px] text-zinc-400">
            <span>{years[years.length - 1]?.year}</span><span>{years[0]?.year}</span>
          </div>
        </Card>
      )}

      <Card>
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <label>Year</label>
            <select value={f.year} onChange={(e) => update({ year: e.target.value })} className="w-28">
              <option value="">All</option>
              {years.map((y) => <option key={y.year} value={y.year}>{y.year} ({y.n})</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label>Category</label>
            <select value={f.category} onChange={(e) => update({ category: e.target.value })} className="w-40">
              <option value="">All</option>
              {(meta?.categories || []).map((c) => <option key={c.code} value={c.code}>{c.code}{c.in_scope ? " ★" : ""}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label>Topic</label>
            <select value={f.domain} onChange={(e) => update({ domain: e.target.value })} className="w-48">
              <option value="">All</option>
              {(meta?.domains || []).map((d) => <option key={d.code} value={d.code}>{d.label} ({d.n})</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label>Type</label>
            <select value={f.doc_class} onChange={(e) => update({ doc_class: e.target.value })} className="w-52">
              <option value="">All</option>
              {(meta?.doc_classes || []).map((c) => <option key={c.doc_class} value={c.doc_class}>{classLabel(c.doc_class)} ({c.n})</option>)}
            </select>
          </div>
          <form className="flex flex-col gap-1" onSubmit={(e) => { e.preventDefault(); update({ q: e.target.q.value }); }}>
            <label>ID or title</label>
            <input name="q" defaultValue={f.q} placeholder="GSR-659, helmet…" className="w-48" />
          </form>
          <label className="flex items-center gap-2 pb-1.5 text-sm text-zinc-700">
            <input type="checkbox" checked={f.in_scope} onChange={(e) => update({ in_scope: e.target.checked })} />
            In scope only (L1/L2/M1/N1)
          </label>
        </div>
      </Card>

      <ErrorBox error={error} />
      {loading ? <Loading /> : data && (
        <Card title={`${data.total.toLocaleString()} documents`}>
          {data.documents.length === 0 ? <Empty>No documents match these filters.</Empty> : (
            <Table head={["Document", "Type", "Title / subject", "Date", "Categories"]}>
              {data.documents.map((d) => (
                <tr key={d.id} className="hover:bg-zinc-50">
                  <Td><DocLink id={d.canonical_id} /><div className="mt-1"><StatusBadges d={d} /></div></Td>
                  <Td className="whitespace-nowrap text-zinc-600">{classLabel(d.doc_class)}</Td>
                  <Td className="max-w-md">
                    <div className="line-clamp-2">{d.official_title || d.subject || <span className="text-zinc-400">no title</span>}</div>
                    {d.ai_pending && !d.subject && <div className="mt-1"><AiPending what="subject pending" /></div>}
                  </Td>
                  <Td className="whitespace-nowrap">{fmtDate(d.doc_date)}</Td>
                  <Td><Chips items={d.vehicle_categories} scope /></Td>
                </tr>
              ))}
            </Table>
          )}
          <div className="mt-4 flex items-center gap-3 text-sm">
            <Button variant="secondary" disabled={offset === 0} onClick={() => update({ offset: Math.max(0, offset - PAGE) })}>← Previous</Button>
            <span className="text-zinc-500">{offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total.toLocaleString()}</span>
            <Button variant="secondary" disabled={offset + PAGE >= data.total} onClick={() => update({ offset: offset + PAGE })}>Next →</Button>
          </div>
        </Card>
      )}
    </div>
  );
}
