"""Ekspor laporan A4 dengan ReportLab Platypus."""

import html
import io
import os
from functools import lru_cache
from pathlib import Path

import reportlab
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import LongTable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, TableStyle

from report import METHODOLOGY, SCOPE, SEMANTIC_METHOD, Report

TEAL = colors.HexColor("#0F766E")
SLATE = colors.HexColor("#334155")


@lru_cache(maxsize=1)
def _fonts() -> None:
    system = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    linux = Path("/usr/share/fonts/truetype/dejavu")
    packaged = Path(reportlab.__file__).parent / "fonts"
    for regular, bold in ((linux / "DejaVuSans.ttf", linux / "DejaVuSans-Bold.ttf"),
                          (system / "arial.ttf", system / "arialbd.ttf"),
                          (packaged / "Vera.ttf", packaged / "VeraBd.ttf")):
        if regular.is_file() and bold.is_file():
            pdfmetrics.registerFont(TTFont("SimiSans", str(regular)))
            pdfmetrics.registerFont(TTFont("SimiSansBold", str(bold)))
            return


def _text(value) -> str:
    return html.escape(str(value)).replace("\n", "<br/>")


def _folio(canvas, document) -> None:
    width, height = A4
    canvas.setStrokeColor(colors.HexColor("#CBD5E1"))
    canvas.line(42, 40, width - 42, 40)
    canvas.setFont("SimiSans", 8)
    canvas.setFillColor(SLATE)
    canvas.drawString(42, 26, "SimiCheck Academic")
    canvas.drawRightString(width - 42, 26, f"Halaman {document.page}")


def make_pdf(report: Report) -> bytes:
    """Bangun PDF A4 langsung dari model laporan, dengan teks yang bisa disalin."""
    _fonts()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=42, rightMargin=42,
                            topMargin=46, bottomMargin=52, title="Laporan SimiCheck Academic",
                            author="SimiCheck Academic")
    base = ParagraphStyle("Isi", fontName="SimiSans", fontSize=9.5, leading=14,
                          textColor=SLATE, spaceAfter=6, splitLongWords=1)
    title = ParagraphStyle("Judul", parent=base, fontName="SimiSansBold", fontSize=24,
                           leading=31, textColor=TEAL, spaceAfter=14)
    heading = ParagraphStyle("Bagian", parent=base, fontName="SimiSansBold", fontSize=14,
                             leading=20, textColor=TEAL, spaceAfter=8, spaceBefore=10,
                             keepWithNext=True)
    small = ParagraphStyle("Tabel", parent=base, fontSize=8.5, leading=12, spaceAfter=0)
    summary = report.summary
    story = [
        Spacer(1, 80), Paragraph("SimiCheck Academic", title),
        Paragraph("Laporan pemeriksaan kemiripan", heading),
        Paragraph(_text(report.analysis.filename), base), Paragraph(_text(report.date), base),
        Spacer(1, 26),
        Paragraph(f"{summary['text_similarity_percent']:.1f}% kemiripan teks langsung", heading),
        Paragraph(f"{summary['matched_words']:,} dari {summary['analyzed_words']:,} kata cocok", base),
        Paragraph(f"{summary['matched_sources']} sumber cocok ? {summary['checked_sources']} sumber diperiksa", base),
        Paragraph("Pengecualian ? " + _text(", ".join(report.exclusions) or "Tidak ada"), base),
        Paragraph(_text(SCOPE), base),
    ]
    if report.semantic_caption:
        story.append(Paragraph(_text(report.semantic_caption), base))
    story.append(PageBreak())
    if report.analysis.warnings:
        story.append(Paragraph("Cakupan pemeriksaan", heading))
        story.extend(Paragraph(_text(message), base) for message in report.analysis.warnings)
    story.append(Paragraph("Sumber yang cocok", heading))
    if report.sources:
        table_rows = [[Paragraph(value, small) for value in ("Kode", "Sumber dan identitas", "Kata", "Kontribusi")]]
        for source in report.sources:
            name = _text(source["title"])
            if source["url"]:
                name = f'<link href="{html.escape(source["url"], quote=True)}" color="#0F766E">{name}</link>'
            details = [_text(part) for part in (", ".join(source["authors"]), source["doi"],
                       source["license"], source["url"]) if part]
            if source["semantic_words"]:
                details.append(f"{source['semantic_words']} kata indikasi parafrase")
            table_rows.append([
                Paragraph(source["label"], small), Paragraph("<br/>".join([name, *details]), small),
                Paragraph(str(source["words"]), small), Paragraph(f"{source['percentage']:.2f}%", small),
            ])
        table = LongTable(table_rows, colWidths=[40, doc.width - 145, 45, 60], repeatRows=1, splitInRow=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E5F4F1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, TEAL),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(table)
    else:
        story.append(Paragraph("Belum ada kecocokan di atas ambang yang dipilih.", base))
    story.append(Paragraph("Dokumen dengan sorotan", heading))
    document = report.analysis.document
    begin = 0
    while begin < len(document):
        end = min(begin + 2000, len(document))
        if end < len(document):
            cut = document.rfind(" ", begin + 1200, end)
            if cut >= 0:
                end = cut + 1
        story.append(Paragraph(report.format_text(begin, end, pdf=True), base))
        begin = end
    if report.evidence:
        story.append(Paragraph("Detail kecocokan", heading))
        if len(report.evidence) > 150:
            story.append(Paragraph("PDF menampilkan 150 pasangan bukti. HTML dan JSON memuat pasangan lengkap.", base))
        for evidence in report.evidence[:150]:
            code = report.by_id[evidence.source_id]["label"]
            label = f"{code} ? {evidence.kind} ? {evidence.words} kata"
            if evidence.cosine_similarity is not None:
                label += f" ? kemiripan kosinus {evidence.cosine_similarity:.3f}"
            story.extend((
                Paragraph(_text(label), heading),
                Paragraph("Dokumen ? " + _text(evidence.document_excerpt), base),
                Paragraph("Sumber ? " + _text(evidence.source_excerpt), base),
            ))
    story.append(Paragraph("Metodologi dan cakupan", heading))
    if report.semantic_caption:
        story.append(Paragraph(_text(SEMANTIC_METHOD), base))
    story.extend(Paragraph(_text(item), base) for item in (METHODOLOGY, SCOPE))
    doc.build(story, onFirstPage=_folio, onLaterPages=_folio)
    return buffer.getvalue()
