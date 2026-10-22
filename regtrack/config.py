"""Configuration loaded from .env (never committed)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def _clean(v: str | None) -> str:
    """Strip inline comments and whitespace (values in .env.example carry '# ...' notes)."""
    if v is None:
        return ""
    v = v.strip()
    if v.startswith("#"):  # "KEY=   # note" means empty
        return ""
    if " #" in v:
        v = v.split(" #", 1)[0].rstrip()
    return v.strip().strip('"').strip("'")


@dataclass(frozen=True)
class Settings:
    database_url: str
    storage_dir: Path
    seed_corpus_dir: Path
    text_dir: Path
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    embed_model: str
    embed_dim: int
    storage_backend: str = "local"          # local | s3 (MinIO or any S3-compatible store)
    s3_endpoint: str = "localhost:9000"
    s3_bucket: str = "regtrack-raw"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_secure: bool = False
    cache_dir: Path = ROOT / "data" / "cache"  # local copies of s3 objects for parsing/serving
    user_agent: str = "RegTrackIndia/0.1 (research)"
    country: str = "IN"                     # whose rows this process sees (env REGTRACK_COUNTRY); see regtrack/country.py
    pg_bin: Path | None = None              # local PostgreSQL programs (pg_ctl, pg_dump…); empty = database in Docker
    pg_data: Path | None = None             # local PostgreSQL data folder (initdb -D)
    import_dir: Path = ROOT / "data" / "import"  # documents people saved by hand: <import_dir>/<TH|MY>/... (read-only)

    @property
    def psycopg_dsn(self) -> str:
        """psycopg wants plain postgresql://, SQLAlchemy wants postgresql+psycopg://."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url) and "<" not in self.llm_base_url

    @property
    def embed_configured(self) -> bool:
        return self.llm_configured and bool(self.embed_model) and "<" not in self.embed_model


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(ROOT / ".env", override=False)
    storage = Path(_clean(os.getenv("STORAGE_DIR")) or ROOT / "data" / "raw")
    return Settings(
        database_url=_clean(os.getenv("DATABASE_URL")) or "postgresql+psycopg://regtrack:regtrack@localhost:5432/regtrack",
        storage_dir=storage,
        seed_corpus_dir=Path(_clean(os.getenv("SEED_CORPUS_DIR")) or r"D:\Regulatory_Documents"),
        text_dir=Path(_clean(os.getenv("TEXT_DIR")) or storage.parent / "text"),
        llm_base_url=_clean(os.getenv("LLM_BASE_URL")).rstrip("/"),
        llm_model=_clean(os.getenv("LLM_MODEL")) or "qwen/qwen3.8-27b",
        llm_api_key=_clean(os.getenv("LLM_API_KEY")) or "lm-studio",
        embed_model=_clean(os.getenv("EMBED_MODEL")),
        embed_dim=int(_clean(os.getenv("EMBED_DIM")) or 768),
        storage_backend=(_clean(os.getenv("STORAGE_BACKEND")) or "local").lower(),
        s3_endpoint=_clean(os.getenv("S3_ENDPOINT")) or "localhost:9000",
        s3_bucket=_clean(os.getenv("S3_BUCKET")) or "regtrack-raw",
        s3_access_key=_clean(os.getenv("S3_ACCESS_KEY")),
        s3_secret_key=_clean(os.getenv("S3_SECRET_KEY")),
        s3_secure=(_clean(os.getenv("S3_SECURE")) or "false").lower() in ("1", "true", "yes"),
        cache_dir=Path(_clean(os.getenv("CACHE_DIR")) or storage.parent / "cache"),
        country=(_clean(os.getenv("REGTRACK_COUNTRY")) or "IN").upper(),
        pg_bin=Path(_clean(os.getenv("PG_BIN"))) if _clean(os.getenv("PG_BIN")) else None,
        pg_data=Path(_clean(os.getenv("PG_DATA"))) if _clean(os.getenv("PG_DATA")) else None,
        import_dir=Path(_clean(os.getenv("IMPORT_DIR")) or ROOT / "data" / "import"),
    )
