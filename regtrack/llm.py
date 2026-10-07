"""Qwen (LM Studio via ngrok) helpers.

Only ChatOpenAI(...).with_structured_output(Model, method="json_schema") is used; no agents.
If the endpoint is unreachable, callers get LLMUnavailable and must leave work at its current stage.
"""

from __future__ import annotations

import base64
import time
from typing import TypeVar

import httpx
from pydantic import BaseModel

from regtrack.config import get_settings

M = TypeVar("M", bound=BaseModel)
HEADERS = {"ngrok-skip-browser-warning": "1"}
_reach_cache: dict[str, tuple[float, bool, str]] = {}


class LLMUnavailable(RuntimeError):
    """LM Studio is off, ngrok URL changed, or LLM_BASE_URL is not configured."""


def reachable(force: bool = False, ttl: float = 120.0) -> tuple[bool, str]:
    """GET /models with a short timeout. Cached for `ttl` seconds."""
    s = get_settings()
    if not s.llm_configured:
        return False, f"LLM_BASE_URL not configured ({s.llm_base_url!r})"
    hit = _reach_cache.get(s.llm_base_url)
    if hit and not force and time.time() - hit[0] < ttl:
        return hit[1], hit[2]
    try:
        r = httpx.get(f"{s.llm_base_url}/models", headers={**HEADERS, "Authorization": f"Bearer {s.llm_api_key}"},
                      timeout=8.0)
        ok = r.status_code == 200 and "data" in r.json()
        msg = ", ".join(m.get("id", "?") for m in r.json().get("data", [])) if ok else f"HTTP {r.status_code}"
    except Exception as e:  # noqa: BLE001
        ok, msg = False, f"{type(e).__name__}: {str(e)[:150]}"
    _reach_cache[s.llm_base_url] = (time.time(), ok, msg)
    return ok, msg


def chat_model(timeout: float = 600.0):
    from langchain_openai import ChatOpenAI

    s = get_settings()
    return ChatOpenAI(base_url=s.llm_base_url, model=s.llm_model, api_key=s.llm_api_key, temperature=0,
                      timeout=timeout, max_retries=1, default_headers=HEADERS)


def structured(model: type[M], system: str, user: str, timeout: float = 600.0) -> M:
    """One structured-output call. Raises LLMUnavailable when the endpoint is down."""
    ok, msg = reachable()
    if not ok:
        raise LLMUnavailable(msg)
    llm = chat_model(timeout).with_structured_output(model, method="json_schema")
    try:
        return llm.invoke([("system", system), ("user", user)])
    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        _reach_cache.pop(get_settings().llm_base_url, None)
        raise LLMUnavailable(str(e)) from e
    except Exception as e:
        if type(e).__name__ in {"APIConnectionError", "APITimeoutError"}:
            _reach_cache.pop(get_settings().llm_base_url, None)
            raise LLMUnavailable(str(e)) from e
        raise


def structured_with_image(model: type[M], system: str, prompt: str, png: bytes, timeout: float = 600.0) -> M:
    """Vision call (one page image) with structured output; used for OCR of scanned pages."""
    ok, msg = reachable()
    if not ok:
        raise LLMUnavailable(msg)
    from langchain_core.messages import HumanMessage, SystemMessage

    b64 = base64.b64encode(png).decode()
    msg_h = HumanMessage(content=[{"type": "text", "text": prompt},
                                  {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}])
    llm = chat_model(timeout).with_structured_output(model, method="json_schema")
    try:
        return llm.invoke([SystemMessage(content=system), msg_h])
    except Exception as e:
        if type(e).__name__ in {"APIConnectionError", "APITimeoutError", "ConnectError"}:
            raise LLMUnavailable(str(e)) from e
        raise


def embedder():
    from langchain_openai import OpenAIEmbeddings

    s = get_settings()
    return OpenAIEmbeddings(base_url=s.llm_base_url, model=s.embed_model, api_key=s.llm_api_key,
                            check_embedding_ctx_length=False, default_headers=HEADERS, timeout=120)


def embed(texts: list[str]) -> list[list[float]]:
    s = get_settings()
    if not s.embed_configured:
        raise LLMUnavailable(f"EMBED_MODEL not configured ({s.embed_model!r})")
    ok, msg = reachable()
    if not ok:
        raise LLMUnavailable(msg)
    try:
        return embedder().embed_documents(texts)
    except Exception as e:
        if type(e).__name__ in {"APIConnectionError", "APITimeoutError", "ConnectError"}:
            raise LLMUnavailable(str(e)) from e
        raise
