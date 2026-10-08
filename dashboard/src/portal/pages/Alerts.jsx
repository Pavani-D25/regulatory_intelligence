import { useState } from "react";
import { portal } from "../../api";
import useLoad from "../../useLoad";
import { usePortal } from "../PortalLayout";
import { Card, ErrorBox, Kpi, Loading } from "../ui";

const COND = {
  high_impact: "Change on a high-impact regulation", new_document: "New document published", draft_published: "Draft published",
  draft_finalised: "Draft finalised", date_changed: "Implementation date changed", due_within: "Implementation date within N days",
  domain: "Change in a topic",
};

export default function Alerts() {
  const [tick, setTick] = useState(0);
  const { data, error, loading } = useLoad(() => portal.alerts(), [tick]);
  const { openReg, toast } = usePortal();
  const [form, setForm] = useState(null);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const k = data.kpis;
  const toggle = async (r) => { await portal.toggleAlert(r.id, !r.enabled); toast(`${r.name}: ${r.enabled ? "off" : "on"}`); setTick((t) => t + 1); };
  const remove = async (r) => { await portal.deleteAlert(r.id); toast("Alert rule removed"); setTick((t) => t + 1); };
  const create = async () => {
    await portal.addAlert(form);
    toast("Alert rule created"); setForm(null); setTick((t) => t + 1);
  };
  const describe = (r) => `${r.scope} · ${COND[r.condition] || r.condition}` +
    (r.condition === "due_within" ? ` (${r.param || 60} days)` : r.condition === "domain" ? ` (${data.domains.find((d) => d.code === r.param)?.label || r.param})` : "");
  return (
    <section className="view">
      <div className="pagehead">
        <div><h1>Alerts</h1><p>Rules that watch the regulation stream and raise notifications in the portal.</p></div>
        <div className="actions"><button className="btn primary" onClick={() => setForm({ name: "", scope: "All categories", condition: "new_document", param: "" })}>New Alert</button></div>
      </div>
      <div className="kpis">
        <Kpi label="Active Alerts" value={k.active} small="Rules switched on" corner="◉" />
        <Kpi label="Needs Action" value={k.action} small="Notifications in the last 30 days" corner="!" tone="red" />
        <Kpi label="Due Soon" value={k.due_soon} small="Implementation dates within 60 days" corner="⏱" tone="amber" />
        <Kpi label="Resolved" value={k.resolved} small="Changes reviewed this month" corner="✓" tone="green" />
      </div>
      {form && (
        <Card title="New Alert Rule">
          <div className="formrow">
            <label className="formlabel">Name<input className="input" value={form.name} placeholder="e.g. M1 lighting changes" onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
            <label className="formlabel">Vehicle category<select className="select" value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value })}>
              {["All categories", "L1", "L2", "M1", "N1"].map((c) => <option key={c}>{c}</option>)}</select></label>
            <label className="formlabel">Condition<select className="select" value={form.condition} onChange={(e) => setForm({ ...form, condition: e.target.value, param: e.target.value === "due_within" ? "60" : "" })}>
              {data.conditions.map((c) => <option key={c} value={c}>{COND[c]}</option>)}</select></label>
            {form.condition === "due_within" && <label className="formlabel">Days<input className="input" type="number" min="1" value={form.param} onChange={(e) => setForm({ ...form, param: e.target.value })} /></label>}
            {form.condition === "domain" && <label className="formlabel">Topic<select className="select" value={form.param} onChange={(e) => setForm({ ...form, param: e.target.value })}>
              <option value="">Choose…</option>{data.domains.map((d) => <option key={d.code} value={d.code}>{d.label}</option>)}</select></label>}
          </div>
          <div className="actions"><button className="btn primary" disabled={form.condition === "domain" && !form.param} onClick={create}>Create</button>
            <button className="btn secondary" onClick={() => setForm(null)}>Cancel</button></div>
        </Card>
      )}
      <div className="grid2">
        <Card title="Alert Rules" sub="Toggle to switch a rule on or off">
          <div className="stack">
            {data.rules.map((r) => (
              <div key={r.id} className="alertitem">
                <div className="itemmain"><div><strong style={{ fontSize: 12 }}>{r.name}</strong><small>{describe(r)} · {r.matches} match(es)</small></div></div>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <button className="btn ghost" style={{ padding: 4, color: "var(--muted)" }} title="Delete rule" onClick={() => remove(r)}>✕</button>
                  <label className="switch"><input type="checkbox" checked={r.enabled} onChange={() => toggle(r)} /><span className="slider" /></label>
                </div>
              </div>
            ))}
          </div>
        </Card>
        <Card title="Recent Notifications" sub="Raised by active rules · last 30 days">
          <div className="stack" style={{ maxHeight: 560, overflow: "auto" }}>
            {data.notifications.map((n, i) => (
              <div key={i} className="alertitem" style={{ cursor: n.canonical_id ? "pointer" : "default" }} onClick={() => n.canonical_id && openReg(n.canonical_id)}>
                <div className="itemmain"><span className="dot" style={{ background: "var(--amber)" }} /><div><strong style={{ fontSize: 12 }}>{n.title}</strong><small>{n.text}</small></div></div>
                <small style={{ color: "var(--muted)", whiteSpace: "nowrap" }}>{n.when.slice(0, 10)}</small>
              </div>
            ))}
            {!data.notifications.length && <div className="empty">No notifications.</div>}
          </div>
          <p className="note" style={{ marginTop: 10 }}>Notifications appear here; email delivery is not set up yet.</p>
        </Card>
      </div>
    </section>
  );
}
