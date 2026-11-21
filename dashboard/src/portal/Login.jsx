import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { auth } from "../api";
import "./portal.css";

// The sign-in page: every other page needs a signed-in user (regtrack/auth.py)
export default function Login() {
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const next = sp.get("next") || "/";
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      await auth.login(email.trim(), password);
      nav(next.startsWith("/") && !next.startsWith("//") ? next : "/", { replace: true });
    } catch (x) {
      setErr(x.status === 429 ? x.message : x.status === 401 ? "Wrong e-mail or password." : `Sign-in failed: ${x.message}`);
    } finally { setBusy(false); }
  };
  return (
    <div className="portal login-page">
      <form className="login-card" onSubmit={submit}>
        <div className="brand login-brand"><div className="brandmark">RI</div>
          <div><strong>Regulatory Intelligence</strong><small>Automotive regulatory compliance</small></div></div>
        <h1>Sign in</h1>
        <p className="login-sub">Use the e-mail address and password your administrator gave you.</p>
        <label className="formlabel">E-mail
          <input className="input" type="email" autoComplete="username" required autoFocus value={email}
            onChange={(e) => setEmail(e.target.value)} /></label>
        <label className="formlabel">Password
          <input className="input" type="password" autoComplete="current-password" required value={password}
            onChange={(e) => setPassword(e.target.value)} /></label>
        {err && <p className="login-error" role="alert">{err}</p>}
        <button className="btn primary login-btn" type="submit" disabled={busy || !email || !password}>
          {busy ? "Signing in…" : "Sign in"}</button>
        <p className="login-foot">Forgot your password? Ask an administrator to reset it.</p>
      </form>
    </div>
  );
}
