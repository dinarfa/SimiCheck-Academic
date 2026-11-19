"""Peninjau bukti dan ekspor laporan di Streamlit."""

from html import escape
from threading import BoundedSemaphore

import streamlit as st

from pdf_report import make_pdf
from report import METHODOLOGY, SCOPE, SEMANTIC_METHOD, Report, make_csv, make_html, make_json

EXPORT_SLOTS = BoundedSemaphore(2)


def _export(builder, report: Report) -> bytes:
    if not EXPORT_SLOTS.acquire(blocking=False):
        raise RuntimeError("Sedang membuat laporan lain. Coba unduh kembali.")
    try:
        return builder(report)
    except Exception:
        raise RuntimeError("Ekspor belum dapat dibuat. Coba kembali.") from None
    finally:
        EXPORT_SLOTS.release()


def _wrap(text: str) -> None:
    st.html("<div style='overflow-wrap:anywhere'>" + escape(text) + "</div>")


def render_result() -> None:
    analysis = st.session_state.analysis
    result = analysis.result
    report = Report(analysis)
    _wrap(analysis.filename)
    st.caption(f"{report.date} ? {analysis.settings.mode}")
    with st.container(border=True):
        st.subheader("Ringkasan")
        first, second, third = st.columns(3)
        first.metric("Kemiripan teks langsung", f"{result.percentage:.1f}%")
        second.metric("Kata cocok", f"{result.covered_words:,}")
        third.metric("Kata dianalisis", f"{result.eligible_words:,}")
        st.caption(f"{len(result.source_words)} sumber cocok ? {result.checked_sources} sumber diperiksa")
        st.write("Pengecualian ? " + (", ".join(report.exclusions) or "Tidak ada"))
        st.caption(f"Ambang pencocokan langsung ? {analysis.settings.minimum} kata")
        if analysis.candidates:
            st.caption(f"Kandidat berlisensi dari OpenAlex ? {analysis.candidates}")
        if report.semantic_caption:
            st.write(report.semantic_caption)
    for warning in analysis.warnings:
        st.warning(warning)

    st.subheader("Tinjau bukti")
    if report.evidence:
        selected = st.selectbox(
            "Pilih kecocokan untuk melihat dokumen dan sumber", range(len(report.evidence)),
            format_func=lambda index: (
                f"{report.by_id[report.evidence[index].source_id]['label']} ? "
                f"{report.evidence[index].kind} ? {report.evidence[index].words} kata ? {report.evidence[index].source_title}"
            ),
        )
        evidence = report.evidence[selected]
    else:
        st.info("Belum ada kecocokan di atas ambang yang dipilih pada sumber yang diperiksa.")
        evidence = None

    document_column, detail = st.columns([3, 2])
    with document_column:
        st.markdown("#### Dokumen")
        position = evidence.start if evidence else 0
        begin = max(0, position - 1400)
        end = min(len(analysis.document), position + 3600)
        if begin or end < len(analysis.document):
            st.caption("Tampilan cuplikan. Dokumen lengkap tersedia melalui ekspor.")
        with st.container(height=420, border=True):
            st.html("<div style='line-height:1.8;overflow-wrap:anywhere'>"
                    + report.format_text(begin, end, selected=evidence) + "</div>")
    with detail:
        st.markdown("#### Detail sumber")
        if evidence:
            source = report.by_id[evidence.source_id]
            _wrap(f"{source['label']} ? {source['title']}")
            st.caption(f"{evidence.kind} ? {evidence.words} kata pada bagian ini")
            if source["doi"]:
                st.text("DOI ? " + source["doi"])
            if source["authors"]:
                st.text(", ".join(source["authors"]))
            if source["url"]:
                st.link_button("Buka sumber", source["url"])
            if evidence.cosine_similarity is None:
                st.write(f"Kontribusi teks langsung ? {source['percentage']:.2f}%")
            else:
                st.write(f"Kemiripan kosinus ? {evidence.cosine_similarity:.3f}")
            st.caption("Cuplikan dokumen")
            _wrap(evidence.document_excerpt)
            st.caption("Cuplikan sumber")
            _wrap(evidence.source_excerpt)
        else:
            st.caption("Detail sumber tersedia saat ada bukti kecocokan.")

    if report.sources:
        with st.expander("Semua sumber yang cocok"):
            for source in report.sources:
                _wrap(f"{source['label']} ? {source['title']}")
                st.caption(f"Teks langsung {source['words']} kata ? {source['percentage']:.2f}% ? Indikasi parafrase {source['semantic_words']} kata")
                if source["url"]:
                    st.link_button(f"Buka {source['label']}", source["url"])
    with st.expander("Metodologi dan cakupan"):
        st.write(METHODOLOGY)
        if report.semantic_caption:
            st.write(SEMANTIC_METHOD)
        st.write(SCOPE)

    st.subheader("Unduh laporan")
    st.caption("PDF dan HTML berisi teks dokumen. CSV memuat daftar sumber, dan JSON memuat ringkasan serta bukti.")
    export_left, export_right = st.columns(2)
    for column, label, export, suffix, mime in (
        (export_left, "Unduh PDF", make_pdf, "pdf", "application/pdf"),
        (export_right, "Unduh HTML", make_html, "html", "text/html"),
        (export_left, "Unduh CSV sumber", make_csv, "csv", "text/csv"),
        (export_right, "Unduh JSON", make_json, "json", "application/json"),
    ):
        column.download_button(label, lambda build=export: _export(build, report), f"laporan-simicheck.{suffix}",
                               mime=mime, on_click="ignore")
