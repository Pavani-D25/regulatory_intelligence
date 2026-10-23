import { Link, useParams } from "react-router-dom";
import { api, docPath, familyPath, fileUrl } from "../api";
import { AiPending, Badge, Button, Card, Chips, DocLink, Empty, ErrorBox, Loading, StatusBadges, Table, Td, classLabel, fmtDate } from "../components/ui";
import { usePortal } from "../portal/PortalLayout";
import useLoad from "../useLoad";

const RELATION = {
  finalises: "finalises draft", amends: "amends", corrects: "corrects", revises: "revises", supersedes: "supersedes",
  extends_date: "extends date in", exempts: "exempts", inserts_row: "inserts rows in", substitutes_row: "substitutes rows in",
  omits_row: "omits rows in", annex_of: "annex of", part_of: "part of", interprets: "interprets", references: "references",
  same_as: "same as",
};

// data fields worth showing as text (shape differs per doc_class)
const DATA_FIELDS = [
  ["file_no", "File no."], ["gazette", "Gazette"], ["official_title", "Short title"], ["signatory", "Signed by"],
  ["commencement", "Commencement"], ["comment_period_days", "Comment period (days)"], ["draft_ref", "Draft"],
  ["amends_targets", "Amends"], ["powers", "Powers"], ["title", "Title"], ["scope_text", "Scope"],
  ["transitional_text", "Transitional provisions"], ["based_on", "Based on"], ["deemed_compliance", "Deemed to comply with"],
  ["amends", "Amends"], ["amendment_no", "Amendment no."], ["issued", "Issued"], ["header_format", "Header format"],
  ["draft_of", "Draft of"], ["comments_until", "Comments until"], ["ref_no", "Reference no."], ["subject", "Subject"],
  ["addressees", "Addressees"], ["form_no", "Form no."], ["rule_ref", "Rule"], ["purpose", "Purpose"],
  ["doc_no", "Doc no."], ["issue", "Issue"], ["table_ref", "Table"], ["annex_of", "Annex of"],
];

function fmtValue(v) {
  if (v === null || v === undefined || v === "") return null;
  if (Array.isArray(v)) return v.length ? v.join(", ") : null;
  if (typeof v === "object") {
    if (v.canonical_id) return `${v.canonical_id}${v.date ? ` (${v.date})` : ""}`;
    return Object.entries(v).filter(([, x]) => x).map(([k, x]) => `${k} ${x}`).join(" · ");
  }
  return String(v);
}

function Row({ label, children }) {
  return (
    <div className="grid grid-cols-1 gap-1 py-1.5 sm:grid-cols-[180px_1fr]">
      <dt className="text-sm text-zinc-500">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

export default function DocumentDetail() {
  const id = decodeURIComponent(useParams()["*"] || "");
  const { version } = usePortal();
  const { data: d, error, loading } = useLoad(() => api.document(id), [id, version]);
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const ex = d.extraction || {};
  const best = d.files.find((f) => f.is_best_copy) || d.files[0];
  const dataRows = DATA_FIELDS.map(([k, l]) => [l, fmtValue(d.data?.[k])]).filter(([, v]) => v);
  const refs = d.data?.references || [];

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="text-xs text-zinc-500">{classLabel(d.doc_class)} · {d.issuer || "issuer unknown"}</div>
          <h1 className="mt-1 break-all font-mono text-xl font-semibold">{d.canonical_id}</h1>
          <div className="mt-1 text-zinc-700">{d.official_title || d.subject || <span className="text-zinc-400">No title yet</span>}</div>
          <div className="mt-2 flex flex-wrap gap-1.5"><StatusBadges d={d} />{d.ai_pending && <AiPending />}</div>
        </div>
        {best && (
          <div className="flex gap-2">
            <Button as="a" href={fileUrl(best.sha256)} target="_blank" rel="noreferrer">Open original ↗</Button>
            <Button as="a" variant="secondary" href={fileUrl(best.sha256, true)}>⤓ Download</Button>
          </div>
        )}
      </div>

      {d.ai_pending && (
        <div className="rounded-lg border border-violet-200 bg-violet-50 px-4 py-3 text-sm text-violet-800">
          Fields below were read by rules only. The Qwen pass (subject, provisions, implicit vehicle scope, per-field
          confidence) runs automatically once LM Studio is connected.
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
        <Card title="Metadata">
          <dl className="divide-y divide-zinc-100">
            <Row label="Date">{fmtDate(d.doc_date)}{d.doc_date_precision && d.doc_date_precision !== "day" && <span className="text-zinc-400"> ({d.doc_date_precision})</span>}</Row>
            <Row label="Status">{d.status}</Row>
            <Row label="Nature">{d.nature || <AiPending what="pending" />}</Row>
            <Row label="Vehicle categories"><Chips items={d.vehicle_categories} scope /></Row>
            <Row label="Powertrains"><Chips items={d.powertrains} /></Row>
            <Row label="Usage"><Chips items={d.usage} /></Row>
            <Row label="Topics"><Chips items={d.domains} /></Row>
            {d.family_key && (
              <Row label="Version family">
                <Link to={familyPath(d.family_key)} className="font-mono text-[13px]">{d.family_key}</Link>
                {d.version_seq && <span className="text-zinc-500"> · version {d.version_seq}</span>}
              </Row>
            )}
            {dataRows.map(([l, v]) => <Row key={l} label={l}><span className="whitespace-pre-line">{v.length > 600 ? `${v.slice(0, 600)}…` : v}</span></Row>)}
            {refs.length > 0 && <Row label={`References (${refs.length})`}><span className="text-zinc-600">{refs.slice(0, 40).join(", ")}{refs.length > 40 ? " …" : ""}</span></Row>}
          </dl>
        </Card>

        <div className="flex flex-col gap-5">
          <Card title={`Files · ${d.files.length}`}>
            <ul className="flex flex-col gap-3">
              {d.files.map((f) => (
                <li key={`${f.sha256}-${f.page_from}`} className="text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <a href={fileUrl(f.sha256)} target="_blank" rel="noreferrer" className="font-mono text-xs">{f.sha256.slice(0, 16)}.{f.ext}</a>
                    {f.is_best_copy && <Badge tone="green">best copy</Badge>}
                    <Badge>{f.role.replace("_", " ")}</Badge>
                    {f.ocr_engine && <Badge tone="amber">OCR</Badge>}
                    <a href={fileUrl(f.sha256, true)} className="text-xs">download</a>
                  </div>
                  <div className="text-xs text-zinc-500">
                    pages {f.page_from}–{f.page_to ?? f.page_count}{f.part_label ? ` · ${f.part_label}` : ""}
                    {f.english_page_from && ` · English p. ${f.english_page_from}–${f.english_page_to}`}
                  </div>
                  {(f.sightings || []).filter((s) => s.source !== "LOCAL_SEED").slice(0, 3).map((s, i) => (
                    <div key={i} className="truncate text-xs text-zinc-500">
                      {s.source}: {s.url ? <a href={s.url} target="_blank" rel="noreferrer">{s.title || s.url}</a> : s.title} {s.date && `(${s.date})`}
                    </div>
                  ))}
                </li>
              ))}
            </ul>
          </Card>

          {d.quality_flags.length > 0 && (
            <Card title={`Quality flags · ${d.quality_flags.length}`}>
              <ul className="flex flex-col gap-2 text-sm">
                {d.quality_flags.map((q, i) => (
                  <li key={i}><Badge tone="amber">{q.rule.replaceAll("_", " ")}</Badge>
                    <span className="ml-2 text-xs text-zinc-500">{fmtValue(q.details)}</span></li>
                ))}
              </ul>
            </Card>
          )}

          <Card title="Extraction">
            <dl className="text-sm">
              <Row label="Model">{ex.model || "—"}{ex.prompt && ` · ${ex.prompt}`}</Row>
              <Row label="Needs check">{ex.needs_check?.length ? ex.needs_check.join(", ") : "—"}</Row>
            </dl>
          </Card>
        </div>
      </div>

      <Card title={`Relations · ${d.relations_out.length + d.relations_in.length}`}>
        {d.relations_out.length + d.relations_in.length === 0 ? <Empty>No relations.</Empty> : (
          <Table head={["Direction", "Relation", "Document", "Details"]}>
            {d.relations_out.filter((r) => r.type !== "references")
              // every reference, the collected (clickable) ones first
              .concat(d.relations_out.filter((r) => r.type === "references").sort((a, b) => Number(b.resolved) - Number(a.resolved)))
              .map((r, i) => (
              <tr key={`o${i}`}>
                <Td className="text-zinc-500">this →</Td>
                <Td>{RELATION[r.type] || r.type}{r.requires_reapproval && <span className="ml-1"><Badge tone="red">re-approval</Badge></span>}</Td>
                <Td>{r.resolved ? <DocLink id={r.target} /> : <span className="font-mono text-[13px] text-zinc-500" title="not collected yet">{r.target}</span>}</Td>
                <Td className="text-xs text-zinc-500">{fmtValue(r.details)}</Td>
              </tr>
            ))}
            {d.relations_in.slice(0, 40).map((r, i) => (
              <tr key={`i${i}`}>
                <Td className="text-zinc-500">→ this</Td>
                <Td>{RELATION[r.type] || r.type}</Td>
                <Td><Link to={docPath(r.source)} className="font-mono text-[13px]">{r.source}</Link></Td>
                <Td className="text-xs text-zinc-500">{fmtValue(r.details)}</Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      {d.mandates.length > 0 && (
        <Card title={`Mandates created by this document · ${d.mandates.length}`}>
          <Table head={["Mandate key", "Requirement", "Standards", "Implementation", "Valid"]}>
            {d.mandates.map((m) => (
              <tr key={m.id}>
                <Td className="font-mono text-xs">{m.mandate_key}</Td>
                <Td className="max-w-xs"><div className="line-clamp-2">{m.subject}</div><Chips items={m.vehicle_categories} scope /></Td>
                <Td className="font-mono text-xs">{(m.standard_refs || []).join(", ") || "—"}</Td>
                <Td className="whitespace-nowrap">{fmtDate(m.implementation_date)}{m.is_draft && <span className="ml-1"><Badge tone="amber">draft</Badge></span>}</Td>
                <Td className="whitespace-nowrap text-xs text-zinc-500">{fmtDate(m.valid_from)} → {m.valid_to ? fmtDate(m.valid_to) : "open"}</Td>
              </tr>
            ))}
          </Table>
        </Card>
      )}
    </div>
  );
}
