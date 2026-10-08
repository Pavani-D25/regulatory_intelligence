import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { portal } from "../../api";
import { usePortal } from "../PortalLayout";
import useLoad from "../../useLoad";
import { ago, Card, Loading } from "../ui";

export default function AskAI() {
  const [sp] = useSearchParams();
  const { openReg, meta } = usePortal();
  const { data: ctx } = useLoad(() => portal.askContext(), []);
  const cats = (meta?.categories || []).map((c) => c.code).join(", ");
  const [msgs, setMsgs] = useState([{ role: "ai", text: "Ask about Indian vehicle regulations. Answers cite the regulation and clause they come from." }]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef(null);
  const asked = useRef(false);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [msgs]);

  const ask = async (question) => {
    const text = (question ?? q).trim();
    if (!text || busy) return;
    setQ(""); setBusy(true);
    setMsgs((m) => [...m, { role: "user", text }]);
    try {
      const r = await portal.ask(text);
      setMsgs((m) => [...m, { role: "ai", text: r.answer, sources: r.sources, note: r.note, mode: r.mode }]);
    } catch (e) {
      setMsgs((m) => [...m, { role: "ai", text: `Could not answer: ${e.message}` }]);
    } finally { setBusy(false); }
  };
  useEffect(() => {
    const pre = sp.get("q");
    if (pre && !asked.current) { asked.current = true; ask(pre); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <section className="view">
      <div className="pagehead">
        <div><h1>Ask Regulatory AI</h1><p>Questions answered from the clause-level text of the regulations, with citations.</p></div>
      </div>
      <div className="aiLayout">
        <Card className="chat" title="Regulatory Assistant" sub="Answers only from indexed Indian regulations">
          <div className="messages">
            {msgs.map((m, i) => (
              <div key={i} className={`msg ${m.role}`}>
                <div className="role">{m.role === "ai" ? (m.mode === "qwen" ? "REGULATORY AI" : "REGULATORY SEARCH") : "YOU"}</div>
                {m.text}
                {m.sources?.length > 0 && (
                  <div className="sourcechips">
                    {[...new Map(m.sources.map((s) => [s.canonical_id, s])).values()].slice(0, 6).map((s) => (
                      <button key={s.canonical_id} className="pill blue" style={{ border: 0, cursor: "pointer" }} onClick={() => openReg(s.canonical_id)}
                        title={s.title}>{s.canonical_id}{s.clause ? ` · cl. ${s.clause}` : ""}</button>
                    ))}
                  </div>
                )}
                {m.note && <div className="aitag" style={{ marginTop: 6 }}>✦ {m.note}</div>}
              </div>
            ))}
            {busy && <div className="msg ai"><div className="role">REGULATORY AI</div>Searching the regulations…</div>}
            <div ref={end} />
          </div>
          <div className="composer">
            <textarea value={q} placeholder="e.g. Which lighting rules changed for M1?" onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); } }} />
            <button className="btn primary" disabled={busy || !q.trim()} onClick={() => ask()}>Ask</button>
          </div>
        </Card>
        <div>
          <Card title="Suggested Questions" sub="Built from the most-regulated topics and latest high-impact items">
            {!ctx ? <Loading /> : <div className="suggest">{ctx.suggestions.map((s) => <button key={s} onClick={() => ask(s)}>{s}</button>)}</div>}
          </Card>
          <Card title="Knowledge Sources" sub={ctx ? `${ctx.chunks.toLocaleString()} indexed clauses · categories ${cats}` : "What the assistant searches"}>
            <div className="stack">
              {ctx?.sources.map((s) => (
                <div key={s.code} className="sourceitem"><div className="itemmain">
                  <span className="dot" style={{ background: s.last_status === "ok" ? "#22c55e" : s.last_status === "partial" ? "#f59e0b" : "#cbd5e1" }} />
                  <div><strong style={{ fontSize: 12 }}>{s.name}</strong><small>{s.documents} in-scope documents · last run {s.last_run_at ? ago(s.last_run_at) : "never"}</small></div>
                </div></div>
              ))}
            </div>
            <p className="note" style={{ marginTop: 12 }}>Written answers come from the local Qwen model once LM Studio is connected. Until then the assistant returns the best-matching clauses with links.</p>
          </Card>
        </div>
      </div>
    </section>
  );
}
