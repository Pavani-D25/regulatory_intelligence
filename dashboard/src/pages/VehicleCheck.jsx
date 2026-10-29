import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, familyPath, sharePackUrl } from "../api";
import { AiPending, Badge, Button, Card, Chips, DocLink, Empty, ErrorBox, Loading, Table, Td, fmtDate } from "../components/ui";
import { usePortal } from "../portal/PortalLayout";
import { SegmentPicker, segmentLabel } from "../portal/ui";
import useLoad from "../useLoad";

const POWERTRAINS = ["petrol", "diesel", "cng", "lpg", "ethanol_flex", "hybrid", "bev", "hydrogen"];
const today = () => new Date().toISOString().slice(0, 10);
// a past year chosen in the header: what applied at the end of that year
const defaultOn = (year) => (year && Number(year) < new Date().getFullYear() ? `${year}-12-31` : today());

function Standards({ m }) {
  if (!m.standards?.length) return <span className="text-zinc-400">not named in the notification</span>;
  return (
    <div className="flex flex-col gap-1">
      {m.standards.map((s) => (
        <div key={s.ref}>
          <span className="font-mono text-[13px]">{s.ref}</span>
          {s.current_version && (
            <span className="ml-1 text-xs text-zinc-500">
              current: <DocLink id={s.current_version.canonical_id} />
              {s.amendments?.length > 0 && <> · <Link to={familyPath(s.current_version.family_key)}>{s.amendments.length} amd.</Link></>}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

function MandateTable({ rows, upcoming = false }) {
  if (!rows.length) return <Empty>{upcoming ? "Nothing scheduled after this date." : "No mandates found for this selection."}</Empty>;
  return (
    <Table head={["Requirement", "Standard", upcoming ? "Applies from" : "Implemented", "Legal basis", "Source"]}>
      {rows.map((m) => (
        <tr key={m.id} className="hover:bg-zinc-50">
          <Td className="max-w-sm">
            <div className="line-clamp-3">{m.subject || <span className="text-zinc-400">—</span>}</div>
            <div className="mt-1 flex flex-wrap gap-1">
              {m.model_scope && m.model_scope !== "all" && <Badge>{m.model_scope.replace("_", " ")}</Badge>}
              {m.is_draft && <Badge tone="amber">draft</Badge>}
              {Object.keys(m.conditions || {}).length > 0 && <Badge title={JSON.stringify(m.conditions)}>conditions</Badge>}
              <Chips items={m.vehicle_categories} scope />
            </div>
          </Td>
          <Td><Standards m={m} /></Td>
          <Td className="w-44">
            <span className="whitespace-nowrap">{fmtDate(m.implementation_date)}</span>
            {m.implementation_rule && <div className="max-w-[12rem] text-xs text-zinc-500">{m.implementation_rule}</div>}
          </Td>
          <Td className="max-w-[11rem] break-words font-mono text-xs">{m.legal_basis}</Td>
          <Td><DocLink id={m.source_canonical_id} /><div className="text-xs text-zinc-500">{fmtDate(m.date_of_notification)}</div></Td>
        </tr>
      ))}
    </Table>
  );
}

export default function VehicleCheck() {
  const [params, setParams] = useSearchParams();
  const { meta, version, year, variant } = usePortal();
  const variantPowertrain = { ev: "bev", hybrid: "hybrid" }[variant] || "";  // the header's EV / Hybrid preselects it
  // the vehicle: a segment path ("4W/PV/M1/transport", regtrack/segments.py); ?category= / ?usage= links still work
  const sel = {
    segment: params.get("segment") || "",
    category: params.get("category") || "",
    engine_cc: params.get("engine_cc") || "",
    powertrain: params.get("powertrain") ?? variantPowertrain,
    usage: params.get("usage") || "",
    on: params.get("on") || defaultOn(year),
  };
  const [form, setForm] = useState(sel);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  useEffect(() => { if (!params.get("on")) setForm((f) => ({ ...f, on: defaultOn(year) })); }, [year]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!params.has("powertrain")) setForm((f) => ({ ...f, powertrain: variantPowertrain })); }, [variant]);  // eslint-disable-line react-hooks/exhaustive-deps

  // ?all=1: "All vehicles" (every in-scope category); the share pack still needs one segment
  const chosen = sel.segment || sel.category;
  const asked = chosen || params.get("all") === "1";
  const q = { segment: sel.segment, category: sel.segment ? "" : sel.category, engine_cc: sel.engine_cc,
              powertrain: sel.powertrain, usage: sel.segment ? "" : sel.usage, on: sel.on,
              all_vehicles: chosen ? "" : "true" };
  const { data, error, loading } = useLoad(async () => {
    if (!asked) return null;
    const [now, all] = await Promise.all([api.applicable(q), api.applicable({ ...q, include_future: true })]);
    const nowIds = new Set(now.mandates.map((m) => m.id));
    return { now: now.mandates, upcoming: all.mandates.filter((m) => !nowIds.has(m.id)) };
  }, [params.toString(), version]);

  const submit = (e) => {
    e.preventDefault();
    const { category, usage, ...rest } = form;  // the segment replaces the old category / usage choices
    const vehicle = form.segment ? rest : form.category ? { ...rest, category, usage } : { ...rest, all: "1" };
    setParams(Object.fromEntries(Object.entries(vehicle).filter(([k, v]) => v || k === "powertrain")));  // "Any" is a choice over the header's variant
  };

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-xl font-semibold">Vehicle check</h1>
        <p className="text-sm text-zinc-500">Which regulations apply to a vehicle on a given date — standard, implementation date, legal basis and source.</p>
      </div>

      <Card>
        <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <label>Vehicle segment</label>
            <SegmentPicker tree={meta?.segments} value={form.segment}
              onChange={(v) => setForm({ ...form, segment: v, category: "", usage: "" })} />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="cc">Engine cc</label>
            <input id="cc" type="number" min="0" value={form.engine_cc} onChange={set("engine_cc")} placeholder="e.g. 110" className="w-28" />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="pt">Powertrain</label>
            <select id="pt" value={form.powertrain} onChange={set("powertrain")} className="w-36">
              <option value="">Any</option>
              {POWERTRAINS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="on">On date</label>
            <input id="on" type="date" value={form.on} onChange={set("on")} />
          </div>
          <Button type="submit">Check</Button>
          {chosen && (
            <Button as="a" variant="secondary" className="ml-auto" href={sharePackUrl(q)}>
              ⤓ Download share pack
            </Button>
          )}
        </form>
        <p className="mt-3 text-xs text-zinc-500">
          Mandates come from S.O. 1365(E) table notifications and CMVR rule amendments read by rules; provisions that need Qwen are
          not listed yet <AiPending what="more mandates after the AI pass" />
        </p>
      </Card>

      <ErrorBox error={error} />
      {loading && asked && <Loading />}
      {!asked && <Empty>Choose a vehicle segment (2W / 4W, then PV / CV, type and use as needed), or keep All vehicles, and press Check.</Empty>}
      {data && (
        <>
          <Card title={`${sel.segment ? segmentLabel(sel.segment) : sel.category || "All vehicles"}${sel.usage && !sel.segment ? ` · ${sel.usage}` : ""} · in force on ${fmtDate(sel.on)} · ${data.now.length}`}>
            <MandateTable rows={data.now} />
          </Card>
          <Card title={`Coming later · ${data.upcoming.length}`}>
            <MandateTable rows={data.upcoming} upcoming />
          </Card>
        </>
      )}
    </div>
  );
}
