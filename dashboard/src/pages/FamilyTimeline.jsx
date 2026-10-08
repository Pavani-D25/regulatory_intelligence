import { Link, useParams } from "react-router-dom";
import { api, docPath, fileUrl } from "../api";
import { AiPending, Badge, Card, ErrorBox, Loading, classLabel, fmtDate } from "../components/ui";
import useLoad from "../useLoad";

const isAmend = (v) => ["AIS_AMENDMENT", "AIS_CORRIGENDUM"].includes(v.doc_class);

// Group an AIS family: each base standard / revision with the amendments and corrigenda made to it.
function groupVersions(versions) {
  const bases = versions.filter((v) => !isAmend(v));
  const groups = bases.map((b) => ({ base: b, children: [] }));
  const orphans = [];
  versions.filter(isAmend).forEach((a) => {
    const g = groups.find((x) => (x.base.revision || 0) === (a.revision || 0) && (x.base.part || null) === (a.part || null))
      || groups.find((x) => (x.base.revision || 0) === (a.revision || 0));
    (g ? g.children : orphans).push(a);
  });
  return { groups, orphans };
}

function Node({ v, small = false }) {
  const best = v.files?.find((f) => f.is_best_copy) || v.files?.[0];
  return (
    <li className="relative pb-5 pl-6">
      <span className={`absolute top-1.5 rounded-full border-2 ${small ? "-left-[6px] h-2.5 w-2.5" : "-left-[8px] h-3.5 w-3.5"}
        ${v.is_current ? "border-emerald-600 bg-emerald-600" : v.status === "superseded" ? "border-zinc-300 bg-white" : "border-brand bg-white"}`} />
      <div className="flex flex-wrap items-center gap-2">
        <Link to={docPath(v.canonical_id)} className={`font-mono ${small ? "text-[13px]" : "text-sm font-semibold"}`}>{v.canonical_id}</Link>
        <span className="text-xs text-zinc-500">{classLabel(v.doc_class)} · {fmtDate(v.doc_date)}</span>
        {v.is_current && <Badge tone="green">current</Badge>}
        {v.status === "superseded" && <Badge>superseded</Badge>}
        {v.status === "draft" && <Badge tone="amber">draft</Badge>}
        {v.version_seq && <span className="text-xs text-zinc-400">v{v.version_seq}</span>}
        {best && <a href={fileUrl(best.sha256)} target="_blank" rel="noreferrer" className="text-xs">PDF ↗</a>}
      </div>
      {!small && (v.official_title || v.subject) && <div className="mt-0.5 text-sm text-zinc-600">{v.official_title || v.subject}</div>}
      {!small && v.ai_pending && !v.subject && <div className="mt-1"><AiPending /></div>}
    </li>
  );
}

export default function FamilyTimeline() {
  const key = decodeURIComponent(useParams()["*"] || "");
  const { data, error, loading } = useLoad(() => api.family(key), [key]);
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const ais = data.versions.some(isAmend) || data.versions.some((v) => v.doc_class === "AIS_STANDARD");
  const { groups, orphans } = groupVersions(data.versions);

  return (
    <div className="flex flex-col gap-5">
      <div>
        <Link to="/versions" className="text-sm">← All families</Link>
        <h1 className="mt-1 font-mono text-xl font-semibold">{data.family_key}</h1>
        <p className="text-sm text-zinc-500">
          {data.versions.length} versions · current <span className="font-mono">{data.current || "—"}</span>
        </p>
      </div>
      <Card title="Timeline (oldest first)">
        {ais ? (
          <ol className="ml-2 border-l-2 border-zinc-200">
            {groups.map(({ base, children }) => (
              <div key={base.id}>
                <Node v={base} />
                {children.length > 0 && (
                  <ol className="-mt-3 mb-3 ml-8 border-l border-dashed border-zinc-300">
                    {children.map((c) => <Node key={c.id} v={c} small />)}
                  </ol>
                )}
              </div>
            ))}
            {orphans.map((c) => <Node key={c.id} v={c} small />)}
          </ol>
        ) : (
          <ol className="ml-2 border-l-2 border-zinc-200">
            {data.versions.map((v) => <Node key={v.id} v={v} />)}
          </ol>
        )}
      </Card>
    </div>
  );
}
