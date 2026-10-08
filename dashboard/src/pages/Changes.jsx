import { useState } from "react";
import { api } from "../api";
import { AiPending, Badge, Card, DocLink, Empty, ErrorBox, Loading, classLabel, fmtDate } from "../components/ui";
import useLoad from "../useLoad";

const TYPE = {
  new_document: ["New document", "gray"],
  new_amendment: ["New amendment", "blue"],
  new_revision: ["New revision", "blue"],
  corrigendum: ["Corrigendum", "gray"],
  draft_published: ["Draft published", "amber"],
  draft_finalised: ["Draft finalised", "green"],
  implementation_date_changed: ["Date changed", "red"],
  mandate_superseded: ["Mandate superseded", "violet"],
  file_reissued: ["File re-issued", "gray"],
  listing_removed: ["Listing removed", "gray"],
};

export default function Changes() {
  const [days, setDays] = useState(30);
  const [type, setType] = useState("");
  const since = new Date(Date.now() - days * 86400000).toISOString();
  const { data, error, loading } = useLoad(() => api.changes(since), [days]);
  const rows = (data?.changes || []).filter((c) => !type || c.event_type === type);
  const byDay = rows.reduce((acc, c) => {
    const d = c.detected_at.slice(0, 10);
    (acc[d] = acc[d] || []).push(c);
    return acc;
  }, {});

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-xl font-semibold">Changes</h1>
        <p className="text-sm text-zinc-500">What the 6-hourly crawls found: new documents, drafts, finalised drafts and changed dates.</p>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label>Period</label>
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[7, 30, 90, 365].map((d) => <option key={d} value={d}>last {d} days</option>)}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label>Type</label>
          <select value={type} onChange={(e) => setType(e.target.value)} className="w-52">
            <option value="">All</option>
            {Object.entries(TYPE).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </div>
      </div>
      <ErrorBox error={error} />
      {loading ? <Loading /> : rows.length === 0 ? <Empty>No changes in this period.</Empty> : (
        Object.entries(byDay).map(([day, items]) => (
          <Card key={day} title={`${fmtDate(day)} · ${items.length}`}>
            <ul className="divide-y divide-zinc-100">
              {items.map((c) => {
                const [label, tone] = TYPE[c.event_type] || [c.event_type, "gray"];
                const template = c.details?.summary_by === "template";
                return (
                  <li key={c.id} className="flex flex-wrap items-start gap-3 py-2.5">
                    <span className="w-40 shrink-0"><Badge tone={tone}>{label}</Badge></span>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm">
                        {(c.summary || "").replace(/:\s*$/, "") || c.canonical_id}
                        {/:\s*$/.test(c.summary || "") && (
                          <span className="text-zinc-500"> · {c.details?.doc_class ? classLabel(c.details.doc_class) : "no title yet"}</span>
                        )}
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-zinc-500">
                        <DocLink id={c.canonical_id} />
                        {c.details?.old && <span>{c.details.old} → {c.details.new}</span>}
                        {template && <AiPending what="AI summary pending" />}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          </Card>
        ))
      )}
    </div>
  );
}
