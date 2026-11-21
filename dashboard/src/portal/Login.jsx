import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { auth } from "../api";
import "./portal.css";

// what the product does, beside the form
const POINTS = [
  ["Always current", "Official sources collected automatically every 6 hours."],
  ["Applicability per vehicle", "The rules in force by category, engine size and powertrain."],
  ["Traceable answers", "Every insight links back to the clause in the official document."],
];

// The sign-in page: every other page needs a signed-in user (regtrack/auth.py)
export default function Login() {
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [caps, setCaps] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const next = sp.get("next") || "/";

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      await auth.login(email.trim(), password);
      nav(next.startsWith("/") && !next.startsWith("//") ? next : "/", { replace: true });
    } catch (x) {
      setErr(x.status === 429 ? "Too many failed attempts. Try again in 15 minutes."
        : x.status === 401 ? "The e-mail address or password is incorrect."
          : `Sign-in failed: ${x.message}`);
    } finally {
      setBusy(false);
    }
  };
  const capsCheck = (e) => setCaps(e.getModifierState && e.getModifierState("CapsLock"));

  return (
    <div className="portal lg-page">
      <aside className="lg-hero">
        <div className="lg-hero-inner">
          <div className="lg-logo"><span className="lg-mark">RI</span><span>Regulatory Intelligence</span></div>
          <h1 className="lg-title">Every vehicle regulation, tracked and understood.</h1>
          <p className="lg-lead">One live source of truth for automotive regulatory compliance.</p>
          <ul className="lg-points">
            {POINTS.map(([h, t]) => (
              <li key={h}><span className="lg-check" aria-hidden="true">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#0f172a" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
              </span><div><strong>{h}</strong><span>{t}</span></div></li>
            ))}
          </ul>
          <p className="lg-countries">India · Thailand · Malaysia</p>
        </div>
      </aside>

      <main className="lg-main">
        <form className="lg-card" onSubmit={submit} noValidate>
          <div className="lg-logo lg-logo-dark"><span className="lg-mark">RI</span><span>Regulatory Intelligence</span></div>
          <h2>Welcome back</h2>
          <p className="lg-sub">Sign in with the account your administrator created for you.</p>

          <label className="lg-label" htmlFor="lg-email">E-mail address</label>
          <input id="lg-email" className="lg-input" type="email" autoComplete="username" autoFocus required
            placeholder="name@company.com" value={email} onChange={(e) => setEmail(e.target.value)} />

          <label className="lg-label" htmlFor="lg-password">Password</label>
          <div className="lg-pw">
            <input id="lg-password" className="lg-input" type={show ? "text" : "password"} autoComplete="current-password"
              required placeholder="Your password" value={password} onChange={(e) => setPassword(e.target.value)}
              onKeyUp={capsCheck} onKeyDown={capsCheck} />
            <button type="button" className="lg-toggle" onClick={() => setShow(!show)}
              aria-label={show ? "Hide password" : "Show password"} aria-pressed={show}>{show ? "Hide" : "Show"}</button>
          </div>
          {caps && <p className="lg-hint" role="status">Caps Lock is on.</p>}

          {err && <p className="lg-error" role="alert">{err}</p>}

          <button className="lg-submit" type="submit" disabled={busy || !email.trim() || !password}>
            {busy ? <><span className="lg-spinner" aria-hidden="true" /> Signing in…</> : "Sign in"}
          </button>

          <p className="lg-foot">Forgot your password? Ask an administrator to reset it.</p>
        </form>
        <p className="lg-legal">For authorised users only. Decisions should be verified against the official source documents.</p>
      </main>
    </div>
  );
}
