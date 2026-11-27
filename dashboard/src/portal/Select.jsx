import { Children, isValidElement, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

// A drop-in for <select>: same <option> children, same onChange(e) with e.target.value, but its list is a short
// scrolling panel (about 8 rows) instead of the browser's own list, which grows to the full height of the screen
// when there are many options (years, topics, categories, teams). More than SEARCH_FROM options: a search box.
const SEARCH_FROM = 10;
const ROW = 34;
const MAX_ROWS = 8;

function optionsOf(children) {
  const out = [];
  const walk = (nodes) => Children.forEach(nodes, (c) => {
    if (!isValidElement(c)) return;
    if (c.type === "option") {
      const label = Children.toArray(c.props.children).join("");
      out.push({ value: String(c.props.value ?? label), label, disabled: !!c.props.disabled });
    } else if (c.props?.children) walk(c.props.children); // fragments
  });
  walk(children);
  return out;
}

export default function Select({ value, onChange, children, className = "select", style, disabled, title, defaultValue, ...rest }) {
  const opts = useMemo(() => optionsOf(children), [children]);
  const [inner, setInner] = useState(defaultValue ?? opts[0]?.value ?? "");
  const current = value !== undefined ? String(value ?? "") : String(inner);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [hi, setHi] = useState(0);
  const [pos, setPos] = useState(null);
  const btn = useRef(null);
  const panel = useRef(null);
  const search = opts.length > SEARCH_FROM;
  const shown = useMemo(() => {
    const ql = q.trim().toLowerCase();
    return ql ? opts.filter((o) => o.label.toLowerCase().includes(ql) || o.value.toLowerCase().includes(ql)) : opts;
  }, [opts, q]);
  const selected = opts.find((o) => o.value === current) || opts[0];

  const place = () => {
    const r = btn.current?.getBoundingClientRect();
    if (!r) return;
    const listH = Math.min(shown.length || 1, MAX_ROWS) * ROW + (search ? 48 : 8);
    const below = window.innerHeight - r.bottom - 8;
    const up = below < listH && r.top > below;
    setPos({
      left: Math.min(r.left, window.innerWidth - Math.max(r.width, 200) - 8),
      width: Math.max(r.width, 200),
      top: up ? undefined : r.bottom + 4,
      bottom: up ? window.innerHeight - r.top + 4 : undefined,
    });
  };
  useLayoutEffect(() => { if (open) place(); }, [open, shown.length]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => {
      if (!btn.current?.contains(e.target) && !panel.current?.contains(e.target)) setOpen(false);
    };
    const away = (e) => { if (!panel.current?.contains(e.target)) setOpen(false); }; // the page scrolled
    document.addEventListener("mousedown", close);
    window.addEventListener("scroll", away, true);
    window.addEventListener("resize", place);
    return () => {
      document.removeEventListener("mousedown", close);
      window.removeEventListener("scroll", away, true);
      window.removeEventListener("resize", place);
    };
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { // keep the highlighted row in view
    panel.current?.querySelector(`[data-i="${hi}"]`)?.scrollIntoView({ block: "nearest" });
  }, [hi, open]);

  const openList = () => {
    if (disabled) return;
    setQ("");
    setHi(Math.max(0, opts.findIndex((o) => o.value === current)));
    setOpen(true);
  };
  const choose = (o) => {
    if (!o || o.disabled) return;
    setOpen(false);
    btn.current?.focus();
    if (o.value === current) return;
    if (value === undefined) setInner(o.value);
    onChange?.({ target: { value: o.value }, currentTarget: { value: o.value } });
  };
  const key = (e) => {
    if (!open) {
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) { e.preventDefault(); openList(); }
      return;
    }
    if (e.key === "Escape") { e.preventDefault(); setOpen(false); btn.current?.focus(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); setHi((h) => Math.min(h + 1, shown.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); choose(shown[hi]); }
    else if (e.key === "Tab") setOpen(false);
  };

  return (
    <>
      <button type="button" ref={btn} className={`${/select/.test(className) ? className : `select ${className}`} sel-btn`} style={style} disabled={disabled} title={title}
        aria-haspopup="listbox" aria-expanded={open} onClick={() => (open ? setOpen(false) : openList())} onKeyDown={key} {...rest}>
        <span className="sel-text">{selected?.label ?? ""}</span><span className="sel-caret" aria-hidden="true">▾</span>
      </button>
      {open && pos && createPortal(
        <div ref={panel} className="sel-pop" role="listbox" onKeyDown={key}
          style={{ left: pos.left, width: pos.width, top: pos.top, bottom: pos.bottom }}>
          {search && (
            <input className="input sel-search" autoFocus placeholder="Type to filter…" value={q}
              onChange={(e) => { setQ(e.target.value); setHi(0); }} />
          )}
          <div className="sel-list" style={{ maxHeight: MAX_ROWS * ROW }}>
            {shown.map((o, i) => (
              <div key={o.value + i} data-i={i} role="option" aria-selected={o.value === current}
                className={`sel-opt${o.value === current ? " on" : ""}${i === hi ? " hi" : ""}${o.disabled ? " off" : ""}`}
                onMouseEnter={() => setHi(i)} onMouseDown={(e) => e.preventDefault()} onClick={() => choose(o)}>
                {o.label}
              </div>
            ))}
            {!shown.length && <div className="sel-opt off">Nothing matches.</div>}
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}
