"""Headless browser for the pages that need one (ARAI list, e-Gazette paging).

Uses a browser that is already installed, so no download is needed on most machines: Chrome, then Microsoft
Edge (present on every Windows PC), then Playwright's own Chromium (`python -m playwright install chromium`).
"""

from __future__ import annotations


def launch(p):
    errors = []
    for channel in ("chrome", "msedge", None):
        try:
            return p.chromium.launch(channel=channel, headless=True) if channel else p.chromium.launch(headless=True)
        except Exception as e:  # noqa: BLE001  try the next browser
            errors.append(f"{channel or 'chromium'}: {str(e).splitlines()[0][:120]}")
    raise RuntimeError("no browser for Playwright - install Chrome or run `python -m playwright install chromium` "
                       f"({'; '.join(errors)})")
