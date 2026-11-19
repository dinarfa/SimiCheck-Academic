"""Data laporan bersama, penanda teks, serta ekspor HTML, CSV, dan JSON."""

import csv
import html
import io
import json
from collections import Counter
from dataclasses import asdict, dataclass

from links import source_link
from workflow import Analysis

PALETTE = ("#FDF0B5", "#C8EFE0", "#DCEAFE", "#FDE0EC", "#EDE4FF", "#FDE7C8", "#DBF1F4")
METHODOLOGY = (
    "Kemiripan teks langsung dihitung dari jumlah token dokumen yang tercakup oleh "
    "kecocokan valid dibagi jumlah token yang dianalisis, dikalikan 100. Satu token "
    "dihitung sekali. Rentang dengan kecocokan terpanjang mendapat prioritas atribusi."
)
SEMANTIC_METHOD = (
    "Indikasi parafrase berasal dari perbandingan semantik pada sampel segmen tanpa kecocokan langsung. "
    "Skor pasangan adalah kemiripan kosinus. Tinjau bagian yang mirip makna sebelum mengambil kesimpulan."
)
SCOPE = (
    "Skor menggambarkan kemiripan terhadap sumber yang diperiksa di sesi ini. "
    "Turnitin menggunakan metode penilaian tersendiri. Gunakan bukti dan konteks sitasi untuk menilai temuan."
)


@dataclass(frozen=True)
class Evidence:
    source_id: str
    source_title: str
    start: int
    end: int
    words: int
    document_excerpt: str
    source_excerpt: str
    kind: str = "Teks langsung"
    cosine_similarity: float | None = None


class Report:
    """Turunkan ringkasan dan bukti dari satu hasil pemeriksaan."""

    def __init__(self, analysis: Analysis):
        self.analysis = analysis
        result = analysis.result
        self.evidence = [Evidence(
            match.source_id, match.source_title, result.tokens[match.doc_start].start,
            result.tokens[match.doc_end - 1].end, match.length, match.doc_excerpt, match.source_excerpt,
        ) for match in result.matches]
        semantic_words = Counter()
        if analysis.semantic:
            for match in analysis.semantic.matches:
                first, second = match.document, match.source
                semantic_words[second.source_id] += first.words
                self.evidence.append(Evidence(
                    second.source_id, second.source_title, first.start, first.end, first.words,
                    first.text, second.text, "Indikasi parafrase", match.similarity,
                ))
        sorted_sources = sorted(
            result.source_words.keys() | semantic_words.keys(),
            key=lambda sid: (-result.source_words.get(sid, 0), -semantic_words[sid], sid),
        )
        metadata = {str(source["id"]): source for source in analysis.sources}
        self.sources = []
        for index, sid in enumerate(sorted_sources, 1):
            source = metadata[sid]
            words = result.source_words.get(sid, 0)
            self.sources.append({
                "id": sid, "label": f"S{index}", "title": source["title"], "doi": source.get("doi") or "",
                "url": source_link(source), "license": source.get("license") or "",
                "authors": source.get("authors") or [], "version": source.get("version") or "",
                "words": words, "semantic_words": semantic_words[sid], "percentage": 100 * words / result.eligible_words,
            })
        self.by_id = {source["id"]: source for source in self.sources}
        self.colors = {source["id"]: PALETTE[index % len(PALETTE)] for index, source in enumerate(self.sources)}
        self.date = analysis.analyzed_at.strftime("%d-%m-%Y %H:%M WITA")
        self.exclusions = [
            name for enabled, name in ((analysis.settings.bibliography, "Daftar pustaka"),
                                       (analysis.settings.quotes, "Teks dalam tanda kutip")) if enabled
        ]
        self.highlight_order = sorted(self.evidence, key=lambda item: item.start)

    def format_text(self, begin: int = 0, end: int | None = None, *,
                    pdf: bool = False, selected: Evidence | None = None) -> str:
        """Render cuplikan dokumen, dengan markup terpisah untuk PDF dan HTML."""
        document = self.analysis.document
        stop = len(document) if end is None else end
        out = []
        cursor = begin
        for item in self.highlight_order:
            if item.end <= cursor:
                continue
            if item.start >= stop:
                break
            first, last = max(cursor, item.start), min(stop, item.end)
            out.append(html.escape(document[cursor:first]))
            text = html.escape(document[first:last])
            label, color = self.by_id[item.source_id]["label"], self.colors[item.source_id]
            if item.cosine_similarity is not None:
                label += " ? Parafrase"
                color = "#EDE4FF"
            badge = f" [{label}]" if item.start >= begin else ""
            if pdf:
                out.append(f'<font backColor="{color}">{text}{badge}</font>')
            else:
                emphasis = ";outline:2px solid #0F766E" if item == selected else ""
                out.append(f'<mark style="background:{color};color:#172033{emphasis}">{text}'
                           f'<span class="source-id">{badge}</span></mark>')
            cursor = last
        out.append(html.escape(document[cursor:stop]))
        return "".join(out).replace("\n", "<br/>")

    @property
    def summary(self) -> dict:
        result = self.analysis.result
        return {
            "text_similarity_percent": result.percentage, "matched_words": result.covered_words,
            "analyzed_words": result.eligible_words, "matched_sources": len(result.source_words),
            "checked_sources": result.checked_sources, "openalex_candidates": self.analysis.candidates,
            "exclusions": self.exclusions,
        }

    @property
    def semantic_summary(self) -> dict | None:
        semantic = self.analysis.semantic
        if semantic is None:
            return None
        return {
            "matched_words": semantic.covered_words, "matched_segments": len(semantic.matches),
            "document_segments": semantic.document_segments, "eligible_segments": semantic.eligible_segments,
            "source_segments": semantic.source_segments,
        }

    @property
    def semantic_caption(self) -> str:
        data = self.semantic_summary
        if data is None:
            return ""
        return (
            f"{data['matched_words']:,} kata dalam {data['matched_segments']} indikasi parafrase. "
            f"Sampel mencakup {data['document_segments']} dari {data['eligible_segments']} segmen dokumen "
            f"dan {data['source_segments']} segmen sumber."
        )

    def as_dict(self) -> dict:
        return {
            "filename": self.analysis.filename, "analyzed_at": self.analysis.analyzed_at.isoformat(),
            "settings": asdict(self.analysis.settings),
            "summary": self.summary, "semantic": self.semantic_summary,
            "warnings": self.analysis.warnings, "sources": self.sources,
            "evidence": [asdict(item) for item in self.evidence],
            "methodology": METHODOLOGY, "semantic_methodology": SEMANTIC_METHOD, "scope": SCOPE,
        }


def make_json(report: Report) -> bytes:
    return json.dumps(report.as_dict(), ensure_ascii=False, indent=2).encode("utf-8")


def _csv_value(value):
    if isinstance(value, str) and (value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n"))):
        return "'" + value
    return value


def make_csv(report: Report) -> bytes:
    text = io.StringIO(newline="")
    writer = csv.writer(text)
    writer.writerow(["Kode", "Judul sumber", "DOI", "URL", "Lisensi", "Kata cocok", "Kontribusi langsung (%)", "Kata indikasi parafrase"])
    for source in report.sources:
        writer.writerow([_csv_value(source[key]) for key in ("label", "title", "doi", "url", "license", "words")]
                        + [f"{source['percentage']:.2f}", source["semantic_words"]])
    return text.getvalue().encode("utf-8-sig")


def make_html(report: Report) -> bytes:
    source_rows = []
    for source in report.sources:
        title = html.escape(source["title"])
        url = html.escape(source["url"], quote=True)
        link = f'<a href="{url}" rel="noopener noreferrer">{title}</a>' if url else title
        authors = html.escape(", ".join(source["authors"]))
        source_rows.append(
            f'<tr><td>{source["label"]}</td><td>{link}<br/>{authors}</td>'
            f'<td>{html.escape(source["doi"])}</td><td>{html.escape(source["license"])}</td>'
            f'<td>{source["words"]}</td><td>{source["percentage"]:.2f}%</td><td>{source["semantic_words"]}</td></tr>'
        )
    summary = report.summary
    semantic = html.escape(report.semantic_caption)
    warnings = "".join(f"<li>{html.escape(message)}</li>" for message in report.analysis.warnings)
    details = "".join(
        f'<details><summary>{report.by_id[item.source_id]["label"]} ? '
        f'{html.escape(item.source_title)} ? {item.words} kata ? {item.kind}</summary>'
        f'<p>Dokumen ? {html.escape(item.document_excerpt)}</p>'
        f'<p>Sumber ? {html.escape(item.source_excerpt)}</p>'
        + (f'<p>Kemiripan kosinus ? {item.cosine_similarity:.3f}</p>' if item.cosine_similarity is not None else "")
        + "</details>"
        for item in report.evidence
    )
    filename = html.escape(report.analysis.filename)
    exclusions = html.escape(", ".join(report.exclusions) or "Tidak ada")
    rendered = f"""<!doctype html><html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Laporan SimiCheck Academic ? {filename}</title>
<style>
*{{box-sizing:border-box}}body{{margin:2rem auto;padding:0 1rem;max-width:70rem;background:#f8fafc;color:#334155;font:1rem/1.65 system-ui,sans-serif;overflow-wrap:anywhere}}
h1,h2{{color:#172033;line-height:1.25}}a{{color:#0f766e}}a:focus-visible,summary:focus-visible{{outline:3px solid #0f766e;outline-offset:3px}}
section{{background:#fff;border:1px solid #cbd5e1;border-radius:10px;padding:1rem;margin-bottom:1rem}}
table{{width:100%;border-collapse:collapse}}th,td{{text-align:start;padding:.55rem;border-bottom:1px solid #cbd5e1}}
.table{{overflow:auto}}summary{{cursor:pointer;padding:.4rem}}mark{{border-radius:3px}}.source-id{{font-size:.85em;font-weight:650}}
</style></head><body><header><h1>Laporan SimiCheck Academic</h1><p>{filename} ? {report.date}</p></header>
<main><section><h2>Ringkasan</h2><p><strong>{summary['text_similarity_percent']:.1f}% kemiripan teks langsung</strong></p>
<p>{summary['matched_words']:,} dari {summary['analyzed_words']:,} kata ? {summary['matched_sources']} sumber cocok ? {summary['checked_sources']} sumber diperiksa</p>
<p>Pengecualian ? {exclusions}</p>{("<p>" + semantic + "</p>") if semantic else ""}{('<ul>' + warnings + '</ul>') if warnings else ''}</section>
<section><h2>Sumber yang cocok</h2>
{('<div class="table"><table><thead><tr><th>Kode</th><th>Sumber</th><th>DOI</th><th>Lisensi</th><th>Kata</th><th>Kontribusi langsung</th><th>Kata indikasi parafrase</th></tr></thead><tbody>' + ''.join(source_rows) + '</tbody></table></div>') if source_rows else '<p>Belum ada kecocokan di atas ambang yang dipilih.</p>'}</section>
<section><h2>Dokumen dengan sorotan</h2><p>{report.format_text()}</p></section>
{('<section><h2>Detail kecocokan</h2>' + details + '</section>') if details else ''}
<section><h2>Metodologi dan cakupan</h2><p>{METHODOLOGY}</p>{("<p>" + SEMANTIC_METHOD + "</p>") if semantic else ""}<p>{SCOPE}</p></section></main></body></html>"""
    return rendered.encode("utf-8")
