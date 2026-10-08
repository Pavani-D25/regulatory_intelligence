"""llm-smoke plumbing without LM Studio: the unreachable path, and a dry run against a fake LLM."""

from __future__ import annotations

import pytest

from regtrack import llm, llm_smoke
from regtrack.db import is_reachable

pytestmark = pytest.mark.skipif(not is_reachable()[0], reason="PostgreSQL not reachable")


def test_unreachable_writes_nothing(monkeypatch, capsys):
    monkeypatch.setattr(llm, "reachable", lambda force=False, ttl=120.0: (False, "not configured"))
    assert llm_smoke.run(dry_run=False) == 2
    assert "nothing was written" in capsys.readouterr().out


def test_dry_run_with_fake_llm(monkeypatch, capsys):
    from regtrack.config import get_settings

    def fake_structured(model, system, user, timeout=600.0):
        if model is llm_smoke._Ping:
            return model(answer="pong", number=42)
        payload = {"data": {}} if "data" in model.model_fields else {}
        if "subject" in model.model_fields:
            payload["subject"] = "fake subject"
        return model.model_validate(payload)

    dim = get_settings().embed_dim
    monkeypatch.setattr(llm, "reachable", lambda force=False, ttl=120.0: (True, "fake-model"))
    monkeypatch.setattr(llm, "structured", fake_structured)
    monkeypatch.setattr(llm, "embed", lambda texts: [[0.01] * dim for _ in texts])
    code = llm_smoke.run(n=3, dry_run=True, max_chunks=5)
    out = capsys.readouterr().out
    assert code == 0, out
    assert "structured output" in out and "dimension" in out and "Smoke test PASSED" in out
