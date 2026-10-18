import { useState } from "react";
import { portal } from "../../api";
import useLoad from "../../useLoad";
import { usePortal } from "../PortalLayout";
import { ago, Badge, Card, ErrorBox, fmt, Kpi, Loading } from "../ui";

const CHANGE = {
  new_document: "New document", new_amendment: "New amendment", new_revision: "New revision", corrigendum: "Corrigendum",
  draft_published: "Draft published", draft_finalised: "Draft finalised", implementation_date_changed: "Date changed",
  mandate_superseded: "Obligation replaced",
};

export default function Team() {
  const [tick, setTick] = useState(0);
  const { version, toast, openReg } = usePortal();
  const { data, error, loading } = useLoad(() => Promise.all([portal.team(), portal.watches()]), [tick, version]);
  const [teamName, setTeamName] = useState("");
  const [user, setUser] = useState(null);
  const [busy, setBusy] = useState(false);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const [dir, w] = data;
  const reload = () => setTick((t) => t + 1);
  const run = async (fn, msg) => {
    setBusy(true);
    try { await fn(); toast(msg); reload(); return true; } catch (e) { toast(e.message); return false; } finally { setBusy(false); }
  };
  const active = dir.users.filter((u) => u.is_active);
  return (
    <section className="view">
      <div className="pagehead">
        <div><h1>Teams &amp; Users</h1><p>Who owns regulations and requirements, and which regulations each team watches.</p></div>
        <div className="actions"><button className="btn primary" onClick={() => setUser({ name: "", email: "", team_id: dir.teams[0]?.id || "", role: "viewer" })}>Add User</button></div>
      </div>
      <div className="kpis">
        <Kpi label="Teams" value={dir.teams.length} small="Owners of reviews and requirements" corner="◍" />
        <Kpi label="Active Users" value={active.length} small={`${dir.users.length - active.length} inactive`} corner="☺" tone="green" />
        <Kpi label="Watched Regulations" value={w.count} small="Followed by a team or user" corner="◉" tone="amber" />
        <Kpi label="Owned Requirements" value={dir.teams.reduce((n, t) => n + t.requirements, 0)} small="In the Compliance Matrix" corner="✓" />
      </div>
      {user && (
        <Card title="New User">
          <div className="formrow">
            <label className="formlabel">Name<input className="input" value={user.name} onChange={(e) => setUser({ ...user, name: e.target.value })} /></label>
            <label className="formlabel">E-mail<input className="input" type="email" value={user.email} onChange={(e) => setUser({ ...user, email: e.target.value })} /></label>
            <label className="formlabel">Team<select className="select" value={user.team_id} onChange={(e) => setUser({ ...user, team_id: Number(e.target.value) || "" })}>
              <option value="">No team</option>{dir.teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label>
            <label className="formlabel">Role<select className="select" value={user.role} onChange={(e) => setUser({ ...user, role: e.target.value })}>
              {dir.roles.map((r) => <option key={r}>{r}</option>)}</select></label>
          </div>
          <div className="actions">
            <button className="btn primary" disabled={busy || !user.name.trim() || !user.email.trim()}
              onClick={() => run(() => portal.addUser(user), "User added").then((ok) => ok && setUser(null))}>Add</button>
            <button className="btn secondary" onClick={() => setUser(null)}>Cancel</button>
          </div>
        </Card>
      )}
      <div className="grid2">
        <Card title="Teams" sub="Owners are teams; a new owner name typed in a review or the Compliance Matrix becomes a team">
          <div className="stack">
            {dir.teams.map((t) => (
              <div key={t.id} className="taskitem">
                <div className="itemmain"><div><strong style={{ fontSize: 12 }}>{t.name}</strong>
                  <small>{t.users} users · {t.regulations} regulations · {t.requirements} requirements · {t.watches} watches</small></div></div>
                <span className="mono" style={{ fontSize: 10, color: "var(--muted)" }}>{t.code}</span>
              </div>
            ))}
          </div>
          <div className="actions" style={{ marginTop: 12 }}>
            <input className="input" style={{ flex: 1 }} value={teamName} placeholder="New team name" onChange={(e) => setTeamName(e.target.value)} />
            <button className="btn secondary" disabled={busy || !teamName.trim()}
              onClick={() => run(() => portal.addTeam(teamName.trim()), "Team added").then((ok) => ok && setTeamName(""))}>Add Team</button>
          </div>
        </Card>
        <Card title="Watched Regulations" sub="Newest change first · watch a regulation from its detail panel">
          <div className="stack">
            {w.watches.map((x) => (
              <div key={x.id} className="taskitem" style={{ cursor: "pointer" }} onClick={() => openReg(x.canonical_id)}>
                <div className="itemmain"><div><strong className="mono" style={{ fontSize: 12 }}>{x.canonical_id}</strong>
                  <small>{x.team || x.user} · {x.last_change ? `${CHANGE[x.last_change] || x.last_change} ${ago(x.last_change_at)}` : "no change detected yet"}</small></div></div>
                <button className="btn ghost" onClick={(e) => { e.stopPropagation(); run(() => portal.deleteWatch(x.id), "Watch removed"); }}>×</button>
              </div>
            ))}
            {!w.watches.length && <p className="empty">No regulation is watched yet.</p>}
          </div>
        </Card>
      </div>
      <Card title="Users" sub="A directory of the people on each team (sign-in comes later)">
        <div className="tablewrap"><table>
          <thead><tr><th>Name</th><th>E-mail</th><th>Team</th><th>Role</th><th>Added</th><th>Status</th></tr></thead>
          <tbody>{dir.users.map((u) => (
            <tr key={u.id}><td><strong>{u.name}</strong></td><td>{u.email}</td>
              <td><select className="select" value={u.team_id || ""} onChange={(e) => run(() => portal.updateUser(u.id, { team_id: Number(e.target.value) || null }), "Team changed")}>
                <option value="">No team</option>{dir.teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></td>
              <td><select className="select" value={u.role} onChange={(e) => run(() => portal.updateUser(u.id, { role: e.target.value }), "Role changed")}>
                {dir.roles.map((r) => <option key={r}>{r}</option>)}</select></td>
              <td>{fmt(u.created_at)}</td>
              <td><button className="btn ghost" style={{ padding: 0 }} onClick={() => run(() => portal.updateUser(u.id, { is_active: !u.is_active }), u.is_active ? "User deactivated" : "User activated")}>
                <Badge v={u.is_active ? "Active" : "Inactive"} tone={u.is_active ? "green" : "blue"} /></button></td></tr>))}
            {!dir.users.length && <tr><td colSpan={6} className="empty">No users yet — add the people on each team.</td></tr>}
          </tbody>
        </table></div>
      </Card>
    </section>
  );
}
