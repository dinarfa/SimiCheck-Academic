"""Discover and import only clearly licensed open-access full text."""
import re
import requests
from defusedxml import ElementTree as SafeET

API = 'https://api.openalex.org/works'
CONTENT = 'https://content.openalex.org/works/{}.grobid-xml'
# Conservative initial scope; do not assume all free-to-read material is reusable.
REUSABLE = {'cc-by', 'cc-by-sa', 'cc0', 'cc0-1.0', 'public-domain'}


def licensed(record):
    loc = record.get('best_oa_location') or {}
    raw = str(loc.get('license') or '').lower()
    return raw in REUSABLE or bool(re.fullmatch(r'cc-by(?:-[0-9.]+)?|cc-by-sa(?:-[0-9.]+)?', raw))


def search_works(query, api_key, limit=10):
    if not api_key:
        raise ValueError('Masukkan OPENALEX_API_KEY di Secrets untuk mencari jurnal.')
    params = {'search': query, 'per_page': min(int(limit), 20),
              'filter': 'is_oa:true', 'api_key': api_key}
    r = requests.get(API, params=params, timeout=25)
    if not r.ok:
        raise RuntimeError(f'OpenAlex HTTP {r.status_code}: {r.text[:280]}')
    out = []
    for item in r.json().get('results', []):
        if licensed(item):
            work_id = str(item.get('id', '')).split('/')[-1]
            if re.fullmatch(r'W\d+', work_id):
                out.append({
                    'id': work_id,
                    'title': item.get('display_name') or 'Tanpa judul',
                    'year': item.get('publication_year') or '',
                    'doi': item.get('doi') or '',
                    'license': (item.get('best_oa_location') or {}).get('license') or '',
                    'source_url': item.get('doi') or item.get('id') or '',
                    'has_full_text': bool((item.get('content_urls') or {}).get('grobid_xml')),
                })
    return out


def download_full_text(work_id, api_key):
    if not re.fullmatch(r'W\d+', work_id):
        raise ValueError('ID OpenAlex tidak valid.')
    if not api_key:
        raise ValueError('OPENALEX_API_KEY wajib diisi.')
    r = requests.get(CONTENT.format(work_id), params={'api_key': api_key}, timeout=40, stream=True)
    if not r.ok:
        raise RuntimeError(f'Full-text tidak tersedia (OpenAlex HTTP {r.status_code}).')
    chunks, total = [], 0
    for chunk in r.iter_content(chunk_size=65536):
        total += len(chunk)
        if total > 10 * 1024 * 1024:
            r.close()
            raise ValueError('XML lebih besar dari 10 MB.')
        chunks.append(chunk)
    root = SafeET.fromstring(b''.join(chunks))
    body = root.find('.//{*}text/{*}body')
    if body is None:
        raise ValueError('Tidak ada isi artikel yang bisa diekstrak.')
    paragraphs = []
    for node in body.iter():
        if node.tag.rsplit('}', 1)[-1] in ('p', 'head'):
            value = ' '.join(' '.join(node.itertext()).split())
            if value:
                paragraphs.append(value)
    text = '\n'.join(paragraphs)
    if len(text.split()) < 100:
        raise ValueError('Full-text terlalu pendek untuk diindeks.')
    return text[:2_000_000]
