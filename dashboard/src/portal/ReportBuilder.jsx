import { useEffect, useMemo, useState } from "react";
import { fileUrl, groupSummaryPdfUrl, portal, regSummariesPdfUrl, regSummaryPdfUrl } from "../api";
import GroupSummaryView from "./CatSummary";
import { RegSummaryView } from "./RegSummary";
import { usePortal } from "./PortalLayout";
import { Card, fmt, yearLabel, YearFilter } from "./ui";

const TYPES = [
  ["regulation", "Regulations", "One or several regulations in detail: facts, impact and KPI, obligations, related documents, versions"],
  ["category", "Vehicle category", "Everything for one category (L1, L2, M1, N1…): figures, topics, upcoming dates, changes, register"],
  ["topic", "Topic", "Everything on one topic (emission, braking, lighting…): figures, categories, upcoming dates, changes, register"],
];
const POWERTRAINS = [["", "All powertrains"], ["ev", "EV"], ["hybrid", "Hybrid"], ["ice", "ICE"]];
const MAX = 25; // regulations per report (the API's MAX_SUMMARIES)
const LIST = 200; // rows the picker shows before asking to narrow the search

// Choose regulations from a list narrowed by the year / powertrain filters and a search: tick one or several
function RegPicker({ regs, loading, selected, setSelected }) {
  const [q, setQ] = useState("");
  const shown = useMemo(() => {
    const ql = q.trim().toLowerCase();
    return ql ? regs.filter((r) => `${r.canonical_id} ${r.name || ""} ${r.subtitle || ""} ${r.domain || ""}`.toLowerCase().includes(ql)) : regs;
  }, [regs, q]);
  const sel = new Set(selected);
  const toggle = (id) => setSelected(sel.has(id) ? selected.filter((x) => x !== id) : selected.length < MAX ? [...selected, id] : selected);
  const addShown = () => setSelected([...selected, ...shown.map((r) => r.canonical_id).filter((id) => !sel.has(id))].slice(0, MAX));
  return (
    <div className="rp">
      <div className="rp-top">
        <input className="input" placeholder="Search by ID, title or topic, e.g. ABS, GSR-310, emission" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="sub">{loading ? "Loading…" : `${shown.length} of ${regs.length} regulations`}</span>
        <button type="button" className="btn ghost" disabled={!shown.length || selected.length >= MAX} onClick={addShown}
          title={`Select the regulations listed (up to ${MAX})`}>Select listed</button>
        <button type="button" className="btn ghost" disabled={!selected.length} onClick={() => setSelected([])}>Clear</button>
      </div>
      {selected.length > 0 && (
        <div className="rp-chips">
          <span className="sub">{selected.length} selected{selected.length >= MAX ? ` (maximum ${MAX})` : ""}:</span>
          {selected.map((id) => (
            <span key={id} className="rp-chip mono">{id}<button type="button" aria-label={`Remove ${id}`} onClick={() => toggle(id)}>×</button></span>))}
        </div>)}
      <div className="rp-list" role="listbox" aria-multiselectable="true">
        {shown.slice(0, LIST).map((r) => (
          <label key={r.canonical_id} className={`rp-row ${sel.has(r.canonical_id) ? "on" : ""}`}>
            <input type="checkbox" checked={sel.has(r.canonical_id)} disabled={!sel.has(r.canonical_id) && selected.length >= MAX}
              onChange={() => toggle(r.canonical_id)} />
            <span className="mono rp-id">{r.canonical_id}</span>
            <span className="rp-name">{r.name}{r.subtitle && <small> · {r.subtitle}</small>}</span>
            <span className="rp-meta">{r.categories?.join(", ")}</span>
            <span className="rp-meta">{fmt(r.doc_date)}</span>
          </label>))}
        {!loading && !shown.length && <div className="empty">No regulation matches. Widen the year or powertrain, or change the search.</div>}
        {shown.length > LIST && <div className="empty">Showing the first {LIST}; type in the search to narrow the list.</div>}
      </div>
    </div>
  );
}

// Reports › Report builder: 1 choose the report, 2 set its filters, 3 preview it (on screen and as the PDF), 4 download
export default function ReportBuilder() {
  const { meta, version, openReg, year: headerYear, variant: headerVariant } = usePortal();
  const [type, setType] = useState("regulation");
  const [item, setItem] = useState("");
  const [selected, setSelected] = useState([]);
  const [year, setYear] = useState(headerYear || "");
  const [variant, setVariant] = useState(headerVariant || "");
  const [regs, setRegs] = useState([]);
  const [listing, setListing] = useState(false);
  const [preview, setPreview] = useState(null); // { type, codes, filters, s }
  const [tab, setTab] = useState("screen");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => { setYear(headerYear || ""); }, [headerYear]);
  useEffect(() => { setVariant(headerVariant || ""); }, [headerVariant]);
  // the regulations to choose from, narrowed by the builder's year and powertrain
  useEffect(() => {
    if (type !== "regulation") return;
    let live = true;
    setListing(true);
    portal.regulations({ history: true, year, variant })
      .then((r) => live && setRegs(r.rows)).catch(() => live && setRegs([])).finally(() => live && setListing(false));
    return () => { live = false; };
  }, [type, year, variant, version]);

  const options = type === "category" ? (meta?.categories || []).map((c) => [c.code, c.label])
    : type === "topic" ? [...(meta?.domains || [])].sort((a, b) => a.label.localeCompare(b.label)).map((d) => [d.code, d.label])
      : [];
  const codes = type === "regulation" ? selected : item ? [item] : [];
  const filters = { year, variant };
  const filterText = (f) => [yearLabel(f.year), POWERTRAINS.find(([v]) => v === f.variant)?.[1] || "All powertrains"].join(" · ");

  const choose = (t) => { setType(t); setItem(""); setErr(""); };
  const show = async () => {
    if (!codes.length) return;
    setBusy(true); setErr("");
    try {
      const s = type !== "regulation" ? await portal.groupSummary(type, codes[0], filters)
        : codes.length === 1 ? await portal.regSummary(codes[0]) : await portal.regSummaries(codes);
      setPreview({ type, codes, filters, s }); setTab("screen");
      setTimeout(() => document.getElementById("report-preview")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    } catch (e) { setErr(e.message); setPreview(null); } finally { setBusy(false); }
  };
  const many = preview?.type === "regulation" && preview.codes.length > 1;
  const pdf = (inline) => (preview.type !== "regulation" ? groupSummaryPdfUrl(preview.type, preview.codes[0], preview.filters, inline)
    : many ? regSummariesPdfUrl(preview.codes, inline) : regSummaryPdfUrl(preview.codes[0], inline));
  const title = preview && (preview.type !== "regulation" ? preview.s.label : many ? `${preview.codes.length} regulations` : preview.s.canonical_id);
  const kind = preview && (preview.type !== "regulation" ? preview.s.kind_label : many ? "Regulation summaries" : "Regulation summary");
  const stale = preview && (preview.type !== type || preview.codes.join("|") !== codes.join("|")
    || (type !== "regulation" && (preview.filters.year !== year || preview.filters.variant !== variant)));

  return (
    <>
      <Card title="Report Builder" sub="Choose a report, set its filters, preview it, then download the PDF">
        <div className="rb-step"><span className="rb-num">1</span><strong>Report type</strong></div>
        <div className="rb-types">
          {TYPES.map(([t, label, desc]) => (
            <button key={t} className={`rb-type ${type === t ? "on" : ""}`} onClick={() => choose(t)}>
              <b>{label}</b><span>{desc}</span>
            </button>))}
        </div>

        <div className="rb-step"><span className="rb-num">2</span><strong>Filters</strong></div>
        <div className="rb-filters">
          {type !== "regulation" && (
            <label className="formlabel" style={{ flex: "2 1 320px" }}>{type === "topic" ? "Topic" : "Vehicle category"}
              <select className="select" value={item} onChange={(e) => setItem(e.target.value)}>
                <option value="">{type === "topic" ? "Choose a topic…" : "Choose a category…"}</option>
                {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>)}
          <div className="formlabel" style={{ flex: "1 1 170px" }}>Year (single or range)
            <YearFilter value={year} years={meta?.years || []} onChange={setYear} />
          </div>
          <label className="formlabel" style={{ flex: "1 1 170px" }}>Powertrain
            <select className="select" value={variant} onChange={(e) => setVariant(e.target.value)}>
              {POWERTRAINS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
        </div>
        <p className="note" style={{ margin: "6px 0 10px" }}>
          {type === "regulation"
            ? "Don't know the regulation ID? Set the year and powertrain, then search or scroll the list below and tick one or several."
            : "Year = publication year(s) of the regulations; powertrain = regulations specific to EV, hybrid or ICE. Defaults to the header's selection."}
        </p>
        {type === "regulation" && <RegPicker regs={regs} loading={listing} selected={selected} setSelected={setSelected} />}

        <div className="rb-step"><span className="rb-num">3</span><strong>Preview</strong></div>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <button className="btn primary" disabled={!codes.length || busy} onClick={show}>
            {busy ? "Preparing preview…" : type === "regulation" && codes.length > 1 ? `Preview ${codes.length} regulations` : "Preview report"}
          </button>
          <span className="sub">{type === "regulation" && !codes.length ? "Tick at least one regulation above." : "The PDF can be downloaded from the preview."}</span>
        </div>
        {err && <p className="note" style={{ color: "var(--red)" }}>{err}</p>}
      </Card>

      {preview && (
        <div id="report-preview" className="card rb-preview">
          <div className="rb-bar">
            <div>
              <div className="sub">Preview · {kind}{preview.type !== "regulation" && <> · {filterText(preview.filters)}</>}</div>
              <h2 style={{ margin: "2px 0 0", fontSize: 20 }}>{title}</h2>
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <div className="rb-tabs">
                <button className={tab === "screen" ? "on" : ""} onClick={() => setTab("screen")}>Summary</button>
                <button className={tab === "pdf" ? "on" : ""} onClick={() => setTab("pdf")}>PDF preview</button>
              </div>
              {preview.type === "regulation" && !many && preview.s.file && (
                <a className="btn secondary" href={fileUrl(preview.s.file.sha256)} target="_blank" rel="noreferrer">Open original ↗</a>)}
              <a className="btn primary" href={pdf(false)}>⤓ Download PDF</a>
              <button className="btn ghost" title="Close preview" onClick={() => setPreview(null)}>✕</button>
            </div>
          </div>
          {stale && <p className="rb-stale">The choices above have changed since this preview. Click <b>Preview</b> to update it before downloading.</p>}
          {tab === "pdf" ? (
            <div className="rb-pdf">
              <iframe key={pdf(true)} src={pdf(true)} title={`${title} PDF preview`} />
              <p className="note">The PDF does not show here? <a href={pdf(true)} target="_blank" rel="noreferrer">Open it in a new tab</a>.</p>
            </div>
          ) : preview.type !== "regulation" ? <GroupSummaryView s={preview.s} openReg={openReg} />
            : !many ? <RegSummaryView s={preview.s} />
              : (
                <div className="rb-many">
                  {preview.s.items.map((s, i) => (
                    <details key={s.canonical_id} open={i === 0}>
                      <summary><span className="mono">{s.canonical_id}</span><span>{s.title}</span></summary>
                      <RegSummaryView s={s} />
                    </details>))}
                </div>)}
        </div>
      )}
    </>
  );
}
