"""Rendu HTML (autonome) et PDF (ReportLab) d'un ``ReportContent``."""

from __future__ import annotations

import base64
import hashlib
import html
import io
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from lunatic_imsi_lab import APP_NAME
from lunatic_imsi_lab.reports.builder import ReportContent

BLUE = "#1f6feb"
RED = "#d62246"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_CSS = """
body{font-family:Segoe UI,Helvetica,Arial,sans-serif;background:#f4f6f9;color:#1b2430;margin:0}
.wrap{max-width:980px;margin:0 auto;padding:24px;background:#fff}
header{border-bottom:3px solid %(blue)s;margin-bottom:16px}
h1{margin:0 0 4px 0;font-size:24px} h2{color:%(blue)s;font-size:18px;margin-top:28px}
.banner{padding:8px 12px;font-weight:700;letter-spacing:.5px;color:#fff;background:#3b4656}
.banner.sim{background:%(red)s}
.assess{border-left:4px solid %(blue)s;background:#eef4ff;padding:10px 14px}
.disc{border:1px solid #d0d7de;background:#fafbfc;padding:10px 14px;font-size:13px}
table{border-collapse:collapse;width:100%%;font-size:12px;margin:8px 0}
th{background:#26303d;color:#fff;text-align:left;padding:5px}
td{border-bottom:1px solid #e1e4e8;padding:4px 5px;vertical-align:top}
img{max-width:100%%;border:1px solid #d0d7de;margin:6px 0}
.cap{font-size:12px;color:#57606a} li{margin:2px 0}
""" % {"blue": BLUE, "red": RED}


def render_html(content: ReportContent) -> str:
    e = html.escape
    parts = [f"<!doctype html><html lang='fr'><head><meta charset='utf-8'>"
             f"<title>{e(content.title)}</title><style>{_CSS}</style></head><body><div class='wrap'>",
             f"<div class='banner{' sim' if content.is_simulation else ''}'>{e(content.banner)}</div>",
             f"<header><h1>{e(content.title)}</h1><p class='cap'>{APP_NAME} — généré le "
             f"{content.generated_at:%Y-%m-%d %H:%M:%S} UTC</p></header>",
             f"<p class='assess'><b>Évaluation :</b> {e(content.assessment_text)}</p>",
             f"<p class='disc'>{e(content.disclaimer)}</p>"]
    for s in content.sections:
        parts.append(f"<h2>{e(s.title)}</h2>")
        parts += [f"<p>{e(p)}</p>" for p in s.paragraphs]
        if s.table:
            parts.append("<table><tr>" + "".join(f"<th>{e(c)}</th>" for c in s.table[0])
                         + "</tr>")
            parts += ["<tr>" + "".join(f"<td>{e(c)}</td>" for c in row) + "</tr>"
                      for row in s.table[1:]]
            parts.append("</table>")
        if s.bullets:
            parts.append("<ul>" + "".join(f"<li>{e(b)}</li>" for b in s.bullets) + "</ul>")
        for cap, png in s.images:
            b64 = base64.b64encode(png).decode()
            parts.append(f"<figure><img alt='{e(cap)}' src='data:image/png;base64,{b64}'>"
                         f"<figcaption class='cap'>{e(cap)}</figcaption></figure>")
    parts.append(f"<div class='banner{' sim' if content.is_simulation else ''}'>"
                 f"{e(content.banner)}</div></div></body></html>")
    return "\n".join(parts)


def write_html(content: ReportContent, path: str | Path) -> tuple[Path, str]:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_html(content), encoding="utf-8")
    return p, _sha256(p)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def _fonts() -> tuple[str, str]:
    """Police Unicode embarquée (DejaVu Sans, fournie avec Matplotlib) ; repli
    sur Helvetica si elle est introuvable."""
    try:
        import matplotlib
        base = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        if "LabSans" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("LabSans", str(base / "DejaVuSans.ttf")))
            pdfmetrics.registerFont(TTFont("LabSans-Bold", str(base / "DejaVuSans-Bold.ttf")))
            pdfmetrics.registerFontFamily("LabSans", normal="LabSans", bold="LabSans-Bold",
                                          italic="LabSans", boldItalic="LabSans-Bold")
        return "LabSans", "LabSans-Bold"
    except Exception:  # pragma: no cover - dépend de l'installation
        return "Helvetica", "Helvetica-Bold"


def _styles():
    regular, bold = _fonts()
    ss = getSampleStyleSheet()
    for name in ("Title", "Heading2", "BodyText"):
        ss[name].fontName = bold if name != "BodyText" else regular
    return {
        "title": ParagraphStyle("t", parent=ss["Title"], fontSize=18, textColor=colors.HexColor(
            "#1b2430"), alignment=0),
        "h2": ParagraphStyle("h2", parent=ss["Heading2"], textColor=colors.HexColor(BLUE),
                             fontSize=13, spaceBefore=10),
        "body": ParagraphStyle("b", parent=ss["BodyText"], fontSize=9, leading=12),
        "small": ParagraphStyle("s", parent=ss["BodyText"], fontSize=7.5, leading=9.5),
        "cell": ParagraphStyle("c", parent=ss["BodyText"], fontSize=7, leading=8.5),
        "banner": ParagraphStyle("ban", parent=ss["BodyText"], fontSize=10,
                                 textColor=colors.white, fontName=bold),
    }


def _p(text: str, style) -> Paragraph:
    return Paragraph(html.escape(text), style)


def render_pdf(content: ReportContent) -> bytes:
    st = _styles()
    regular, bold = _fonts()
    buf = io.BytesIO()
    banner_color = colors.HexColor(RED if content.is_simulation else "#3b4656")

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(banner_color)
        canvas.rect(0, A4[1] - 0.9 * cm, A4[0], 0.9 * cm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont(bold, 9)
        canvas.drawString(1.5 * cm, A4[1] - 0.6 * cm, content.banner)
        canvas.setFillColor(colors.HexColor("#57606a"))
        canvas.setFont(regular, 7)
        canvas.drawString(1.5 * cm, 0.8 * cm, f"{APP_NAME} — {content.title}")
        canvas.drawRightString(A4[0] - 1.5 * cm, 0.8 * cm, f"Page {doc.page}")
        if content.is_simulation:
            canvas.setFillColor(colors.Color(0.84, 0.13, 0.27, alpha=0.08))
            canvas.setFont(bold, 70)
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(35)
            canvas.drawCentredString(0, 0, "SIMULATION")
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.6 * cm, bottomMargin=1.4 * cm, title=content.title,
                            author=APP_NAME)
    width = A4[0] - 3 * cm
    flow = [_p(content.title, st["title"]),
            _p(f"Généré le {content.generated_at:%Y-%m-%d %H:%M:%S} UTC", st["small"]),
            Spacer(1, 6)]
    box = Table([[_p("Évaluation : " + content.assessment_text, st["body"])],
                 [_p(content.disclaimer, st["small"])]], colWidths=[width])
    box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef4ff")),
                             ("LINEBEFORE", (0, 0), (0, 0), 3, colors.HexColor(BLUE)),
                             ("BOX", (0, 1), (-1, 1), 0.5, colors.HexColor("#d0d7de"))]))
    flow += [box, Spacer(1, 6)]
    for s in content.sections:
        block = [_p(s.title, st["h2"])]
        block += [_p(p, st["body"]) for p in s.paragraphs]
        flow += block
        if s.table:
            ncol = len(s.table[0])
            data = [[Paragraph(f"<font color='white'><b>{html.escape(str(c))}</b></font>",
                               st["cell"]) for c in s.table[0]]]
            data += [[_p(str(c), st["cell"]) for c in row] for row in s.table[1:]]
            t = Table(data, colWidths=[width / ncol] * ncol, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#26303d")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#d0d7de")),
                ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            flow.append(t)
        for b in s.bullets:
            flow.append(_p("• " + b, st["body"]))
        for cap, png in s.images:
            img = Image(io.BytesIO(png))
            ratio = img.imageHeight / img.imageWidth
            img.drawWidth = width
            img.drawHeight = width * ratio
            flow.append(KeepTogether([img, _p(cap, st["small"])]))
    doc.build(flow, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


def write_pdf(content: ReportContent, path: str | Path) -> tuple[Path, str]:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(render_pdf(content))
    return p, _sha256(p)
