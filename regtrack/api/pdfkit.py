"""Shared PDF building blocks for the portal's downloadable reports (regulation and category summaries).

Kit holds the fonts (a Unicode face for ≤ and the like when the machine has one, else Helvetica with ASCII
replacements), the styles and the table look, so every report PDF looks the same.
"""

from __future__ import annotations

import io
from pathlib import Path
from xml.sax.saxutils import escape

FACES = (
    (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\segoeuib.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
)
ASCII = str.maketrans({"≤": "<=", "≥": ">=", "–": "-", "·": "-", "’": "'", "…": "..."})


class Kit:
    def __init__(self) -> None:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        self.reg, self.bold, self.tr = "Helvetica", "Helvetica-Bold", ASCII
        for regular, bold in FACES:
            if Path(regular).exists() and Path(bold).exists():
                if "RT" not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont("RT", regular))
                    pdfmetrics.registerFont(TTFont("RTB", bold))
                self.reg, self.bold, self.tr = "RT", "RTB", None
                break
        self.colors, self.A4, self.mm = colors, A4, mm
        self.navy, self.accent, self.body, self.muted, self.rule, self.band = (
            colors.HexColor(c) for c in ("#13233F", "#A84E14", "#2D3748", "#5A6578", "#D9D4C7", "#F3F1EB")
        )
        r, b = self.reg, self.bold
        self.st = {
            "title": ParagraphStyle("t", fontName=b, fontSize=17, leading=22, textColor=self.navy),
            "sub": ParagraphStyle("s", fontName=r, fontSize=10, leading=14, textColor=self.muted),
            "h": ParagraphStyle(
                "h", fontName=b, fontSize=12, leading=16, textColor=self.accent, spaceBefore=12, spaceAfter=5
            ),
            "p": ParagraphStyle("p", fontName=r, fontSize=9.5, leading=14, textColor=self.body, spaceAfter=4),
            "cell": ParagraphStyle("c", fontName=r, fontSize=8.5, leading=11.5, textColor=self.body),
            "cellb": ParagraphStyle("cb", fontName=b, fontSize=8.5, leading=11.5, textColor=self.navy),
            "head": ParagraphStyle("hd", fontName=b, fontSize=8.5, leading=11.5, textColor=colors.white),
            "note": ParagraphStyle("n", fontName=r, fontSize=8, leading=11, textColor=self.muted),
        }
        self.width = A4[0] - 36 * mm

    def text(self, v) -> str:
        s = "—" if v in (None, "", []) else str(v)
        return escape(s.translate(self.tr) if self.tr else s)

    def P(self, v, style: str = "p"):
        from reportlab.platypus import Paragraph

        return Paragraph(self.text(v), self.st[style])

    def table(self, head: list, rows: list, widths: list, bold_first: bool = True):
        from reportlab.platypus import Paragraph, Table, TableStyle

        data = [[Paragraph(self.text(h), self.st["head"]) for h in head]]
        data += [
            [Paragraph(self.text(c), self.st["cellb" if i == 0 and bold_first else "cell"]) for i, c in enumerate(r)]
            for r in rows
        ]
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), self.navy),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [self.colors.white, self.band]),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.4, self.rule),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        return t

    def build(self, story: list, title: str, footer: str) -> bytes:
        from reportlab.platypus import SimpleDocTemplate

        mm, A4 = self.mm, self.A4
        label = footer.translate(self.tr) if self.tr else footer

        def on_page(c, d):
            c.saveState()
            c.setFont(self.reg, 7.5)
            c.setFillColor(self.muted)
            c.drawString(18 * mm, 10 * mm, label)
            c.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {d.page}")
            c.restoreState()

        # a section heading never ends a page: move it to the next one when less than 35 mm are left under it
        from reportlab.platypus import CondPageBreak, Paragraph

        story = [
            x
            for f in story
            for x in ((CondPageBreak(35 * mm), f) if isinstance(f, Paragraph) and f.style.name == "h" else (f,))
        ]
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=16 * mm,
            bottomMargin=18 * mm,
            title=title,
            author="RegTrack",
        )
        doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
        return buf.getvalue()


def safe_name(*parts: str) -> str:
    keep = "_".join("".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in p) for p in parts if p)
    return f"RegTrack_{keep}.pdf"
