"""Independent, self-contained HTML similarity report."""
import html
from datetime import datetime
from collections import defaultdict

PALETTE = ['#fce7a3', '#bce8d3', '#d9d1fc', '#c8e4ff', '#ffccda', '#edd9ba']


def highlighted(document, result, source_by_id):
    tokens = result.tokens
    attr = result.attribution
    parts = []
    last = 0
    for i, tok in enumerate(tokens):
        source_id = attr[i]
        if not source_id:
            continue
        if i > 0 and attr[i - 1] == source_id:
            continue
        end_i = i + 1
        while end_i < len(tokens) and attr[end_i] == source_id:
            end_i += 1
        begin = tok.start
        end = tokens[end_i - 1].end
        parts.append(html.escape(document[last:begin]))
        source = source_by_id.get(source_id, {'title': 'Sumber tidak diketahui'})
        title = html.escape(source['title'], quote=True)
        color = PALETTE[list(source_by_id).index(source_id) % len(PALETTE)] if source_id in source_by_id else PALETTE[0]
        parts.append(f'<mark title="{title}" style="background:{color};border-radius:3px;padding:1px 0">{html.escape(document[begin:end])}</mark>')
        last = end
    parts.append(html.escape(document[last:]))
    return ''.join(parts).replace('\n', '<br>')


def make_html(document, result, sources, filename='Dokumen'):
    smap = {str(s['id']): s for s in sources}
    items = sorted(result.source_words.items(), key=lambda x: -x[1])
    rows = []
    for sid, words in items:
        s = smap.get(sid, {})
        url = s.get('source_url') or ''
        title = html.escape(s.get('title', sid))
        source_html = f'<a href="{html.escape(url, quote=True)}" rel="noopener" target="_blank">{title}</a>' if url.startswith('https://') else title
        percent = 100 * words / result.eligible_words if result.eligible_words else 0
        rows.append(f'<tr><td>{source_html}</td><td>{words}</td><td>{percent:.2f}%</td></tr>')
    matches = []
    for match in result.matches[:100]:
        matches.append(f'<div class="match"><b>{html.escape(match.source_title)}</b> — {match.length} kata<br>'
                       f'<small>Dokumen:</small> {html.escape(match.doc_excerpt)}<br>'
                       f'<small>Sumber:</small> {html.escape(match.source_excerpt)}</div>')
    safe_name = html.escape(filename)
    return f'''<!DOCTYPE html><html lang="id"><head><meta charset="utf-8"><title>Laporan SimiCheck — {safe_name}</title>
<style>body{{font:15px/1.6 system-ui,sans-serif;margin:2rem auto;max-width:1000px;padding:0 1rem;color:#18232d}}h1{{margin-bottom:0}}.score{{font-size:3.3rem;font-weight:700}}.note{{color:#5f6d78}}table{{border-collapse:collapse;width:100%;margin-bottom:2rem}}th,td{{padding:.65rem;text-align:left;border-bottom:1px solid #ddd}}.paper{{white-space:normal;line-height:1.95;border:1px solid #eee;border-radius:9px;padding:1rem}}.match{{border-bottom:1px solid #ddd;padding:1rem 0;overflow-wrap:anywhere}}small{{color:#666}}@media print{{body{{margin:0}}}}</style></head>
<body><h1>SimiCheck Academic</h1><p class="note">Laporan kemiripan, bukan keputusan plagiarisme dan bukan hasil Turnitin. Dibuat {datetime.now().strftime('%Y-%m-%d %H:%M')}.</p>
<h2>{safe_name}</h2><div class="score">{result.percentage:.1f}%</div>
<p>{result.covered_words} dari {result.eligible_words} kata yang dihitung cocok dengan korpus yang tersedia. Skor dapat berubah bila database atau aturan pengecualian berubah.</p>
<h2>Sumber yang cocok</h2><table><tr><th>Sumber</th><th>Kata teratribusikan</th><th>Kontribusi</th></tr>{''.join(rows)}</table>
<h2>Dokumen dengan penanda kemiripan</h2><div class="paper">{highlighted(document, result, smap)}</div>
<h2>Cuplikan pasangan kecocokan</h2>{''.join(matches)}<p class="note">Periksa sitasi dan konteks secara manual. Karya yang diunggah tidak dikirim ke Turnitin.</p></body></html>'''
