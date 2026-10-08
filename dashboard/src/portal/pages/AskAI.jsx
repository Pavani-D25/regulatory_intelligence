import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { portal } from "../../api";
import { usePortal } from "../PortalLayout";
import { Card } from "../ui";

const SUGGEST = [
  "Which ABS / CBS rules apply to L2 motorcycles?",
  "Seat belt reminder requirements for M1",
  "Traction battery safety for electric vehicles",
  "Speed limiting device requirements for N1",
  "High security registration plate rules",
];
const SOURCES = [
  ["MoRTH notifications", "G.S.R. / S.O. final and draft rules, orders"], ["ARAI AIS standards", "Standards, amendments, corrigenda, drafts"],
  ["e-Gazette of India", "Gazette copies of MoRTH notifications"], ["India Code", "Motor Vehicles Act, CMVR 1989 and amendments"],
];

export default function AskAI() {
  const [sp] = useSearchParams();
  const { openReg } = usePortal();
  const [msgs, setMsgs] = useState([{ role: "ai", text: "Ask about Indian vehicle regulations for L1, L2, M1 and N1. Answers cite the regulation and clause they come from." }]);
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
          <Card title="Suggested Questions">
            <div className="suggest">{SUGGEST.map((s) => <button key={s} onClick={() => ask(s)}>{s}</button>)}</div>
          </Card>
          <Card title="Knowledge Sources" sub="What the assistant searches">
            <div className="stack">
              {SOURCES.map(([t, d]) => (
                <div key={t} className="sourceitem"><div className="itemmain"><span className="dot" /><div><strong style={{ fontSize: 12 }}>{t}</strong><small>{d}</small></div></div></div>
              ))}
            </div>
            <p className="note" style={{ marginTop: 12 }}>Written answers come from the local Qwen model once LM Studio is connected. Until then the assistant returns the best-matching clauses with links.</p>
          </Card>
        </div>
      </div>
    </section>
  );
}
