import { useEffect, useMemo, useState } from "react";
import { fileUrl, groupSummaryPdfUrl, portal, regSummaryPdfUrl } from "../api";
import GroupSummaryView from "./CatSummary";
import { RegSummaryView } from "./RegSummary";
import { usePortal } from "./PortalLayout";
import { Card } from "./ui";

const TYPES = [
  ["regulation", "Single regulation", "One regulation in detail: facts, impact and KPI, obligations, related documents, versions"],
  ["category", "Vehicle category", "Everything for one category (L1, L2, M1, N1…): figures, topics, upcoming dates, changes, register"],
  ["topic", "Topic", "Everything on one topic (emission, braking, lighting…): figures, categories, upcoming dates, changes, register"],
];
const POWERTRAINS = [["", "All powertrains"], ["ev", "EV"], ["hybrid", "Hybrid"], ["ice", "ICE"]];

// Reports › Report builder: 1 choose the report, 2 set its filters, 3 preview it (on screen and as the PDF), 4 download
export default function ReportBuilder() {
  const { meta, version, openReg, year: headerYear, variant: headerVariant } = usePortal();
  const [type, setType] = useState("regulation");
  const [item, setItem] = useState("");
  const [year, setYear] = useState(headerYear || "");
  const [variant, setVariant] = useState(headerVariant || "");
  const [regs, setRegs] = useState([]);
  const [preview, setPreview] = useState(null); // { type, code, filters, s }
  const [tab, setTab] = useState("screen");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => { setYear(headerYear || ""); }, [headerYear]);
  useEffect(() => { setVariant(headerVariant || ""); }, [headerVariant]);
  useEffect(() => {
    portal.regulations({ history: true, year: "", variant: "" }).then((r) => setRegs(r.rows)).catch(() => setRegs([]));
  }, [version]);

  const ids = useMemo(() => new Set(regs.map((r) => r.canonical_id)), [regs]);
  const options = type === "category" ? (meta?.categories || []).map((c) => [c.code, c.label])
    : type === "topic" ? [...(meta?.domains || [])].sort((a, b) => a.label.localeCompare(b.label)).map((d) => [d.code, d.label])
      : [];
  // a regulation is typed or picked as "ID — title"
  const code = type === "regulation" ? (ids.has(item.split(" — ")[0].trim()) ? item.split(" — ")[0].trim() : "") : item;
  const filters = { year, variant };

  const choose = (t) => { setType(t); setItem(""); setErr(""); };
  const show = async () => {
    if (!code) return;
    setBusy(true); setErr("");
    try {
      const s = type === "regulation" ? await portal.regSummary(code) : await portal.groupSummary(type, code, filters);
      setPreview({ type, code, filters, s }); setTab("screen");
      setTimeout(() => document.getElementById("report-preview")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    } catch (e) { setErr(e.message); setPreview(null); } finally { setBusy(false); }
  };
  const pdf = (inline) => (preview.type === "regulation" ? regSummaryPdfUrl(preview.code, inline)
    : groupSummaryPdfUrl(preview.type, preview.code, preview.filters, inline));
  const filterText = (f) => [f.year || "all years", POWERTRAINS.find(([v]) => v === f.variant)?.[1] || "all powertrains"].join(" · ");
  const title = preview && (preview.type === "regulation" ? preview.s.canonical_id : preview.s.label);
  const stale = preview && (preview.type !== type || preview.code !== code
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
          <label className="formlabel" style={{ flex: "2 1 320px" }}>
            {type === "regulation" ? "Regulation" : type === "topic" ? "Topic" : "Vehicle category"}
            {type === "regulation" ? (
              <>
                <input className="input" list="rb-regs" placeholder="Type an ID or a title, e.g. GSR-310(E)-2016" value={item}
                  onChange={(e) => setItem(e.target.value)} onKeyDown={(e) => e.key === "Enter" && show()} />
                <datalist id="rb-regs">
                  {regs.map((r) => <option key={r.canonical_id} value={`${r.canonical_id} — ${r.name || ""}`.slice(0, 140)} />)}
                </datalist>
              </>
            ) : (
              <select className="select" value={item} onChange={(e) => setItem(e.target.value)}>
                <option value="">{type === "topic" ? "Choose a topic…" : "Choose a category…"}</option>
                {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            )}
          </label>
          <label className="formlabel" style={{ flex: "1 1 150px" }}>Year
            <select className="select" value={year} disabled={type === "regulation"} onChange={(e) => setYear(e.target.value)}>
              <option value="">All years</option>
              {(meta?.years || []).map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
          </label>
          <label className="formlabel" style={{ flex: "1 1 150px" }}>Powertrain
            <select className="select" value={variant} disabled={type === "regulation"} onChange={(e) => setVariant(e.target.value)}>
              {POWERTRAINS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
        </div>
        <p className="note" style={{ margin: "6px 0 0" }}>
          {type === "regulation" ? "A single regulation's report is not filtered by year or powertrain."
            : "Year = publication year of the regulations; powertrain = regulations specific to EV, hybrid or ICE. Defaults to the header's selection."}
          {type === "regulation" && item && !code && <b> Pick a regulation from the list.</b>}
        </p>

        <div className="rb-step"><span className="rb-num">3</span><strong>Preview</strong></div>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <button className="btn primary" disabled={!code || busy} onClick={show}>{busy ? "Preparing preview…" : "Preview report"}</button>
          <span className="sub">The PDF can be downloaded from the preview.</span>
        </div>
        {err && <p className="note" style={{ color: "var(--red)" }}>{err}</p>}
      </Card>

      {preview && (
        <div id="report-preview" className="card rb-preview">
          <div className="rb-bar">
            <div>
              <div className="sub">Preview · {preview.type === "regulation" ? "Regulation summary" : preview.s.kind_label}
                {preview.type !== "regulation" && <> · {filterText(preview.filters)}</>}</div>
              <h2 style={{ margin: "2px 0 0", fontSize: 20 }}>{title}</h2>
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <div className="rb-tabs">
                <button className={tab === "screen" ? "on" : ""} onClick={() => setTab("screen")}>Summary</button>
                <button className={tab === "pdf" ? "on" : ""} onClick={() => setTab("pdf")}>PDF preview</button>
              </div>
              {preview.type === "regulation" && preview.s.file && (
                <a className="btn secondary" href={fileUrl(preview.s.file.sha256)} target="_blank" rel="noreferrer">Open original ↗</a>)}
              <a className="btn primary" href={pdf(false)}>⤓ Download PDF</a>
              <button className="btn ghost" title="Close preview" onClick={() => setPreview(null)}>✕</button>
            </div>
          </div>
          {stale && <p className="rb-stale">The choices above have changed since this preview. Click <b>Preview report</b> to update it before downloading.</p>}
          {tab === "screen" ? (
            preview.type === "regulation" ? <RegSummaryView s={preview.s} /> : <GroupSummaryView s={preview.s} openReg={openReg} />
          ) : (
            <div className="rb-pdf">
              <iframe key={pdf(true)} src={pdf(true)} title={`${title} PDF preview`} />
              <p className="note">The PDF does not show here? <a href={pdf(true)} target="_blank" rel="noreferrer">Open it in a new tab</a>.</p>
            </div>
          )}
        </div>
      )}
    </>
  );
}
