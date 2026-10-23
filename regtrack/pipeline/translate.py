"""English for the dashboard: machine translation (Qwen) of Thai TIS titles and scopes that have no official English.

The official English title comes from the full text's cover (thai.english_cover_title, title_en_source="cover");
only what is missing is translated here, labelled title_en_source="machine translation" and extraction
machine_translation=[...] so the portal can say so. Runs after the pipeline when the LLM answers; when it does not,
nothing happens and the next run tries again (CLAUDE.md rule 8).
"""

from __future__ import annotations

import logging

import psycopg
from pydantic import BaseModel, Field

from regtrack import country, llm
from regtrack.db import Jsonb
from regtrack.pipeline import repo as R
from regtrack.validators import validate_data

log = logging.getLogger(__name__)
PROMPT_VERSION = "th-en-1"
SYSTEM = ("You translate Thai Industrial Standards (TIS / มอก.) into English for automotive regulatory engineers. "
          "Translate faithfully; keep standard numbers, UN Regulation numbers, vehicle categories (M1, N1, L3...), "
          "units and values exactly. No commentary.")


class ThaiTranslation(BaseModel):
    title_en: str = Field(description="English translation of the Thai title")
    scope_en: str | None = Field(None, description="English translation of the Thai scope text, if one was given")


def translate_pending(conn: psycopg.Connection, limit: int = 40) -> int:
    if country.code() != "TH" or not llm.reachable()[0]:
        return 0
    rows = conn.execute(
        f"""SELECT g.id, g.external_code AS canonical_id, g.data, g.extraction FROM regulations g
            WHERE {country.region_sql('g')} AND g.local_class = 'TIS_STANDARD' AND g.data->>'title' IS NOT NULL
              AND (g.data->>'title_en' IS NULL OR (g.data->>'scope_text' IS NOT NULL AND g.data->>'scope_en' IS NULL))
            ORDER BY g.id LIMIT %s""", (limit,)).fetchall()
    n = 0
    for r in rows:
        data = dict(r["data"] or {})
        user = f"Title: {data['title']}\n\nScope:\n{(data.get('scope_text') or '')[:2500]}"
        try:
            t = llm.structured(ThaiTranslation, SYSTEM, user, timeout=300)
        except llm.LLMUnavailable:
            break
        except Exception as e:  # noqa: BLE001  a bad answer leaves this one for the next run
            log.info("translation of %s failed: %s", r["canonical_id"], e)
            continue
        done = []
        if not data.get("title_en") and t.title_en:
            data.update(title_en=t.title_en.strip(), title_en_source="machine translation")
            done.append("title_en")
        if data.get("scope_text") and not data.get("scope_en") and t.scope_en:
            data["scope_en"] = t.scope_en.strip()
            done.append("scope_en")
        if not done or validate_data("TIS_STANDARD", data):
            continue
        ext = dict(r["extraction"] or {})
        ext["machine_translation"] = sorted(set(ext.get("machine_translation", [])) | set(done))
        ext["translation"] = {"model": llm.get_settings().llm_model, "prompt": PROMPT_VERSION}
        R.update_document(conn, r["id"], {"data": Jsonb(data), "extraction": Jsonb(ext),
                                          **({"official_title": data["title_en"]} if data.get("title_en") else {})})
        conn.commit()
        n += 1
    return n
