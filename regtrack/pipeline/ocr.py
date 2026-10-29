"""OCR for scanned pages (< 100 chars of text layer).

Engines, in order of preference:
  1. qwen_vision   - the LM Studio Qwen model, one page image per call, plain text out (if it accepts images)
  2. windows_ocr   - Windows.Media.Ocr (built into Windows 10/11; Python access via the winrt packages)
  3. tesseract     - only if the user has installed it (on PATH); never installed by this project
If no engine is available the file stays at stage 'text' with scanned_pages set.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)
DPI = 200
WORD = re.compile(r"[A-Za-z]{2,}")
COMMON = set(
    """the of and to in a is that for be by with as on or this shall any under such which from
notification rule rules vehicle vehicles motor government central india section sub said date new delhi
ministry road transport highways no namely amendment hereby following published gazette part ii extraordinary
order made act year with effect provided be may an at are has have it its not other all""".split()
)


class OcrPage(BaseModel):
    text: str = Field(description="All text visible on the page, in reading order, plain text")
    english: bool = Field(description="True if the page is mainly English")


def render_png(pdf_path: Path, page_no: int, dpi: int = DPI) -> bytes:
    import pymupdf

    with pymupdf.open(pdf_path) as d:
        pg = d[page_no - 1]
        return pg.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY).tobytes("png")


THAI = re.compile("[ก-๛]")
THAI_GAP = re.compile("(?<=[ก-๛]) +(?=[ก-๛])")  # Tesseract's spaces between Thai letters
THAI_WORDS = ("มาตรฐาน", "ผลิตภัณฑ์", "อุตสาหกรรม", "ที่", "และ", "ของ", "ให้", "ใน", "การ", "ตาม", "ต้อง", "รถ")


def join_thai(text: str) -> str:
    """'ท ่ อ ไอ เส ี ย' -> 'ท่อไอเสีย': Thai has no spaces between letters; Tesseract's Thai output adds them."""
    return THAI_GAP.sub("", text)


def thai_confidence(text: str) -> float:
    """Share of Thai letters / digits / usual punctuation among the characters, scaled by common Thai words."""
    chars = [c for c in text if not c.isspace()]
    if len(chars) < 20:
        return 0.0
    ok = sum(1 for c in chars if THAI.match(c) or c.isdigit() or c in ".,()-/:%")
    words = sum(text.count(w) for w in THAI_WORDS)
    return round(min(1.0, ok / len(chars) * min(1.0, 0.5 + words / 10)), 3)


def heuristic_confidence(text: str) -> float:
    """No engine here reports a calibrated score; estimate from the share of recognisable words (Thai or English)."""
    if len(THAI.findall(text)) > len(re.findall(r"[A-Za-z]", text)):
        return thai_confidence(text)
    tokens = text.split()
    if len(tokens) < 5:
        return 0.0
    good = sum(1 for t in tokens if GOOD_TOKEN.match(t))
    common = sum(1 for t in tokens if t.strip(".,;:()").lower() in COMMON)
    return round(min(1.0, good / len(tokens) * min(1.0, 0.5 + 2 * common / len(tokens))), 3)


GOOD_TOKEN = re.compile(
    r"^[(\[\"']?(?:[A-Z]?[a-z]+|[A-Z]+|\d+(?:[.,/\-]\d+)*(?:st|nd|rd|th)?|[A-Z]\.(?:[A-Z]\.)*)"
    r"(?:\([A-Za-z0-9]+\))?[)\]\"']?[.,;:\-—]*$"
)


# ------------------------------------------------------------------ engines
# OCR language per country: Thai script needs Thai; Malay (Latin script) reads well with English
OCR_LANG = {"TH": ("th", "tha+eng"), "MY": ("en-US", "eng+msa"), "IN": ("en-US", "eng")}


def ocr_lang(cc: str | None) -> tuple[str, str]:
    """(Windows OCR language tag, tesseract -l) for a country; English for any other."""
    return OCR_LANG.get((cc or "").upper(), ("en-US", "eng"))


@lru_cache(maxsize=8)
def windows_language_installed(tag: str) -> bool:
    """Windows OCR has only the languages installed in Settings (Thai: Language & region > Thai, with OCR)."""
    try:
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine

        return bool(OcrEngine.is_language_supported(Language(tag)))
    except Exception:  # noqa: BLE001
        return False


@lru_cache(maxsize=1)
def windows_ocr_available() -> bool:
    try:
        from winrt.windows.globalization import Language  # noqa: F401
        from winrt.windows.media.ocr import OcrEngine

        return OcrEngine.try_create_from_language(Language("en-US")) is not None
    except Exception:  # noqa: BLE001
        return False


async def _win_ocr_async(png: bytes, lang: str = "en-US") -> str:
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    stream = InMemoryRandomAccessStream()
    w = DataWriter(stream)
    w.write_bytes(png)
    await w.store_async()
    await w.flush_async()
    w.detach_stream()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bmp = await decoder.get_software_bitmap_async()
    engine = OcrEngine.try_create_from_language(Language(lang))
    res = await engine.recognize_async(bmp)
    return "\n".join(line.text for line in res.lines)


def windows_ocr(png: bytes, lang: str = "en-US") -> str:
    return asyncio.run(_win_ocr_async(png, lang))


def tesseract_cmd() -> str | None:
    """TESSERACT_CMD (e.g. D:/tesseract/Library/bin/tesseract.exe, a conda-forge env), else tesseract on PATH."""
    from regtrack.config import get_settings

    cmd = get_settings().tesseract_cmd
    return str(cmd) if cmd and Path(cmd).exists() else shutil.which("tesseract")


def _tess_env() -> dict:
    import os

    from regtrack.config import get_settings

    env = dict(os.environ)
    if get_settings().tessdata_prefix:
        env["TESSDATA_PREFIX"] = str(get_settings().tessdata_prefix)
    return env


def tesseract_available() -> bool:
    return tesseract_cmd() is not None


def tesseract_ocr(png: bytes, lang: str = "eng") -> str:
    r = subprocess.run(
        [tesseract_cmd(), "stdin", "stdout", "-l", lang], input=png, capture_output=True, timeout=300, env=_tess_env()
    )
    return r.stdout.decode("utf-8", "ignore")


_vision_ok: bool | None = None


def qwen_vision_available() -> bool:
    """Probe once per process: does the LM Studio model accept an image?"""
    global _vision_ok
    if _vision_ok is not None:
        return _vision_ok
    from regtrack import llm

    ok, _ = llm.reachable()
    if not ok:
        return False  # do not cache: the laptop may come back
    try:
        import pymupdf

        doc = pymupdf.open()
        page = doc.new_page(width=300, height=100)
        page.insert_text((20, 60), "MOTOR VEHICLES 42", fontsize=20)
        png = page.get_pixmap(dpi=100).tobytes("png")
        r = llm.structured_with_image(
            OcrPage, "You transcribe page images.", "Transcribe this image.", png, timeout=120
        )
        _vision_ok = "42" in r.text
    except Exception as e:  # noqa: BLE001
        log.info("Qwen vision probe failed: %s", e)
        _vision_ok = False
    return _vision_ok


QWEN_OCR_PROMPT = {  # per country: the page's language and the numbers that must stay exact
    "IN": ("scanned Indian Gazette pages", "Keep numbers, dates and G.S.R./S.O. numbers exact."),
    "TH": (
        "scanned Thai regulatory documents (Thai script, sometimes English)",
        "Write Thai in Thai script exactly as printed; keep มอก. numbers, Thai or Arabic numerals and dates exact.",
    ),
    "MY": (
        "scanned Malaysian regulatory documents (Malay or English)",
        "Keep P.U. (A) numbers, Act numbers and dates exact.",
    ),
}


def qwen_ocr(png: bytes, cc: str | None = None) -> str:
    from regtrack import llm

    what, keep = QWEN_OCR_PROMPT.get((cc or "IN").upper(), QWEN_OCR_PROMPT["IN"])
    r = llm.structured_with_image(
        OcrPage,
        f"You transcribe {what} exactly. Output plain text only, no commentary, no translation.",
        f"Transcribe all text on this page in reading order. {keep}",
        png,
    )
    return r.text


@lru_cache(maxsize=4)
def tesseract_has(lang: str) -> bool:
    """tesseract --list-langs includes this traineddata (Thai: 'tha', from the installer's language options)."""
    if not tesseract_available():
        return False
    r = subprocess.run([tesseract_cmd(), "--list-langs"], capture_output=True, timeout=30, env=_tess_env())
    return lang in r.stdout.decode("utf-8", "ignore").split()


def pick_engine(cc: str | None = None) -> str | None:
    """Thai: Tesseract with Thai data first (exact on printed Thai; Qwen vision reads Thai but misreads digits and
    invents words, tested on TIS 341), Qwen vision as the fallback. Elsewhere: Qwen vision, Windows OCR, Tesseract."""
    if (cc or "").upper() == "TH" and tesseract_has("tha"):
        return "tesseract"
    if qwen_vision_available():
        return "qwen_vision"
    if windows_ocr_available():
        return "windows_ocr"
    if tesseract_available():
        return "tesseract"
    return None


def can_ocr(engine: str | None, cc: str | None) -> bool:
    """False when the engine cannot read this country's script (Thai without the Windows Thai OCR language)."""
    if engine == "windows_ocr":
        return windows_language_installed(ocr_lang(cc)[0])
    return engine is not None


def ocr_page(pdf_path: Path, page_no: int, engine: str, cc: str | None = None) -> tuple[str, float]:
    png = render_png(pdf_path, page_no)
    win_lang, tess_lang = ocr_lang(cc)
    if engine == "qwen_vision":
        text = qwen_ocr(png, cc)
    elif engine == "windows_ocr":
        text = windows_ocr(png, win_lang)
    elif engine == "tesseract":
        text = tesseract_ocr(png, tess_lang)
        if "tha" in tess_lang:
            text = join_thai(text)
    else:
        raise ValueError(engine)
    return text, heuristic_confidence(text)
