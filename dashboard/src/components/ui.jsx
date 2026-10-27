import { Link } from "react-router-dom";
import { docPath } from "../api";

const CLASS_LABEL = {
  NOTIFICATION_FINAL: "Notification", NOTIFICATION_DRAFT: "Draft notification", NOTIFICATION_ORDER: "Order (S.O.)",
  NOTIFICATION_EXTENSION: "Date extension", NOTIFICATION_EXEMPTION: "Exemption", NOTIFICATION_CORRIGENDUM: "Corrigendum",
  AIS_STANDARD: "AIS standard", AIS_AMENDMENT: "AIS amendment", AIS_CORRIGENDUM: "AIS corrigendum", AIS_DRAFT: "AIS draft",
  AIS_FORM_TABLE: "AIS form table", AIS_INTERPRETATION: "AIS interpretation", TAP_DOCUMENT: "CMVR-TAP",
  CIRCULAR_OM: "Circular / OM", GUIDELINE_POLICY: "Guideline", FORM_TEMPLATE: "Form", OFF_TOPIC: "Off-topic",
};
export const classLabel = (c) => CLASS_LABEL[c] || (c || "").replaceAll("_", " ").toLowerCase().replace(/^\w/, (x) => x.toUpperCase());

export function fmtDate(d) {
  if (!d) return "—";
  const dt = new Date(d);
  if (Number.isNaN(dt.getTime())) return d;
  return dt.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

const TONES = {
  gray: "bg-zinc-100 text-zinc-700",
  blue: "bg-brand-soft text-brand",
  green: "bg-emerald-50 text-emerald-700",
  amber: "bg-amber-50 text-amber-700",
  red: "bg-red-50 text-red-700",
  violet: "bg-violet-50 text-violet-700",
};
export function Badge({ tone = "gray", children, title }) {
  return (
    <span title={title} className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${TONES[tone]}`}>
      {children}
    </span>
  );
}

export function AiPending({ what = "AI fields pending" }) {
  return (
    <Badge tone="violet" title="Filled by rules only; the Qwen pass runs when LM Studio is connected">
      ✦ {what}
    </Badge>
  );
}

export function Chips({ items, scope = false }) {
  if (!items || !items.length) return <span className="text-zinc-400">—</span>;
  const inScope = new Set(["L1", "L2", "M1", "N1", "ALL"]);
  return (
    <span className="inline-flex flex-wrap gap-1">
      {items.map((c) => (
        <Badge key={c} tone={scope && inScope.has(c) ? "blue" : "gray"}>{c}</Badge>
      ))}
    </span>
  );
}

export function DocLink({ id, children }) {
  if (!id) return <span className="text-zinc-400">—</span>;
  return <Link to={docPath(id)} className="font-mono text-[13px]">{children || id}</Link>;
}

export function StatusBadges({ d }) {
  return (
    <span className="inline-flex flex-wrap gap-1">
      {d.status === "draft" && <Badge tone="amber">draft</Badge>}
      {d.status === "superseded" && <Badge>superseded</Badge>}
      {d.is_current && <Badge tone="green">current</Badge>}
      {d.in_scope && <Badge tone="blue">in scope</Badge>}
    </span>
  );
}

export function Card({ title, actions, children, className = "" }) {
  return (
    <section className={`rounded-xl border border-zinc-200 bg-white ${className}`}>
      {(title || actions) && (
        <div className="flex items-center justify-between gap-3 border-b border-zinc-100 px-4 py-3">
          <h2 className="text-sm font-semibold">{title}</h2>
          {actions}
        </div>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Loading() {
  return <div className="py-10 text-center text-sm text-zinc-400">Loading…</div>;
}

export function ErrorBox({ error }) {
  if (!error) return null;
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
      {String(error.message || error)}. Is the API running? <code className="font-mono">python -m regtrack.cli api</code>
    </div>
  );
}

export function Empty({ children }) {
  return <div className="py-8 text-center text-sm text-zinc-400">{children}</div>;
}

export function Table({ head, children }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-zinc-200 text-xs text-zinc-500">
            {head.map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100">{children}</tbody>
      </table>
    </div>
  );
}

export const Td = ({ children, className = "" }) => <td className={`px-3 py-2 align-top ${className}`}>{children}</td>;

export function Button({ as = "button", className = "", variant = "primary", ...props }) {
  const base = "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition no-underline hover:no-underline disabled:cursor-not-allowed disabled:opacity-50";
  const v = variant === "primary"
    ? "bg-brand text-white hover:bg-brand/90"
    : "border border-zinc-300 bg-white text-zinc-700 hover:bg-zinc-50";
  const Tag = as;
  return <Tag className={`${base} ${v} ${className}`} {...props} />;
}
