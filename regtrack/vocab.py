"""Vocabulary (vehicle_category synonyms, domain keywords) read from db/seeds/0001_vocab.sql.

The seed file is the single definition; this module parses it so deterministic code can run without a DB
and stays in step with what the DB holds.
"""

from __future__ import annotations

import re
from functools import lru_cache

from regtrack.config import ROOT

SEED = ROOT / "db" / "seeds" / "0001_vocab.sql"
# topic codes renamed by a later migration (the seed file is never edited after it was applied)
RENAMED = {"hsrp": "number_plates"}  # 0006
_ROW = re.compile(r"\(\s*'([^']+)'\s*,\s*'([^']*)'\s*,\s*ARRAY\[(.*?)\]\s*(?:,\s*(TRUE|FALSE))?\s*\)", re.S)


def _arr(s: str) -> list[str]:
    return re.findall(r"'([^']*)'", s)


@lru_cache(maxsize=1)
def _parse() -> tuple[dict, dict]:
    sql = SEED.read_text(encoding="utf-8")
    cat_sql = sql[sql.index("INSERT INTO vehicle_category"):sql.index("INSERT INTO domain")]
    dom_sql = sql[sql.index("INSERT INTO domain"):sql.index("INSERT INTO source")]
    cats = {m.group(1): {"label": m.group(2), "synonyms": _arr(m.group(3)), "in_scope": m.group(4) == "TRUE"}
            for m in _ROW.finditer(cat_sql)}
    doms = {RENAMED.get(m.group(1), m.group(1)): {"label": m.group(2), "keywords": _arr(m.group(3))}
            for m in _ROW.finditer(dom_sql)}
    return cats, doms


def categories() -> dict:
    return _parse()[0]


def domains() -> dict:
    return _parse()[1]


@lru_cache(maxsize=1)
def _domain_res() -> dict[str, re.Pattern]:
    out = {}
    for code, d in domains().items():
        words = sorted(d["keywords"], key=len, reverse=True)
        parts = []
        for w in words:
            e = re.escape(w)
            # short upper-case acronyms (ABS, CBS, PUC, AHO) must match case-sensitively as whole words
            parts.append(f"(?-i:\\b{e}\\b)" if w.isupper() and len(w) <= 5 else f"\\b{e}")
        out[code] = re.compile("|".join(parts), re.I)
    return out


def find_domains(text: str, min_hits: int = 2) -> list[str]:
    """Domains whose keywords appear at least `min_hits` times (one strong hit for short texts)."""
    t = text[:60000]
    hits = {code: len(rx.findall(t)) for code, rx in _domain_res().items()}
    need = 1 if len(t) < 4000 else min_hits
    return [c for c, n in sorted(hits.items(), key=lambda kv: -kv[1]) if n >= need]


def in_scope_codes() -> set[str]:
    return {c for c, d in categories().items() if d["in_scope"]}
