"""Transparent word-coverage similarity engine; NOT Turnitin's proprietary score."""
from __future__ import annotations
from dataclasses import dataclass
from collections import defaultdict
import re

WORD = re.compile(r"[^\W_]+", re.UNICODE)
REFERENCES = re.compile(r"(?im)^\s*(?:DAFTAR\s+PUSTAKA|REFERENCES|BIBLIOGRAPHY|DAFTAR\s+REFERENSI)\s*$")
QUOTATIONS = re.compile(r'“[^”]*”|«[^»]*»|"[^"\n]*"', re.S)

@dataclass
class Token:
    value: str
    start: int
    end: int

@dataclass
class Match:
    source_id: str
    source_title: str
    doc_start: int
    doc_end: int
    source_start: int
    source_end: int
    length: int
    doc_excerpt: str
    source_excerpt: str

@dataclass
class Result:
    percentage: float
    covered_words: int
    eligible_words: int
    tokens: list[Token]
    attribution: list[str | None]
    matches: list[Match]
    source_words: dict[str, int]


def tokenize(text: str) -> list[Token]:
    return [Token(m.group().casefold(), m.start(), m.end()) for m in WORD.finditer(text)]


def allowed_words(text: str, tokens: list[Token], exclude_bibliography=True, exclude_quotes=False) -> list[bool]:
    cutoff = len(text)
    if exclude_bibliography:
        match = REFERENCES.search(text)
        if match:
            cutoff = match.start()
    quote_spans = []
    if exclude_quotes:
        quote_spans = [(q.start(), q.end()) for q in QUOTATIONS.finditer(text)]
    result = []
    q = 0
    for t in tokens:
        while q < len(quote_spans) and quote_spans[q][1] <= t.start:
            q += 1
        in_quote = q < len(quote_spans) and t.start < quote_spans[q][1] and t.end > quote_spans[q][0]
        result.append(t.start < cutoff and not in_quote)
    return result


def analyze(document: str, sources: list[dict], min_match_words=10,
            exclude_bibliography=True, exclude_quotes=False, max_index_words=1_500_000) -> Result:
    """Exact token-run matching, 10+ words by default, union coverage by source.

    sources: [{'id': ..., 'title': ..., 'text_content': ...}].
    The algorithm detects near-verbatim text, not semantic paraphrases.
    """
    min_match_words = max(5, int(min_match_words))
    doc = tokenize(document)
    allowed = allowed_words(document, doc, exclude_bibliography, exclude_quotes)
    n = len(doc)
    attr: list[str | None] = [None] * n
    if n == 0:
        return Result(0, 0, 0, doc, attr, [], {})

    src_list = []
    inverted = defaultdict(list)
    total = 0
    for s in sources:
        text = s.get('text_content') or ''
        toks = tokenize(text)
        if len(toks) < min_match_words:
            continue
        if total + len(toks) > max_index_words:
            raise ValueError('Koleksi sumber terlalu besar untuk sesi gratis. Pilih lebih sedikit jurnal.')
        total += len(toks)
        idx = len(src_list)
        src_list.append((s, toks, text))
        vals = [t.value for t in toks]
        for j in range(len(vals) - min_match_words + 1):
            key = tuple(vals[j:j + min_match_words])
            # Limit common repeated phrases so one boilerplate cannot overwhelm memory.
            if len(inverted[key]) < 15:
                inverted[key].append((idx, j))

    v = [t.value for t in doc]
    seen = set()
    candidates = []
    for i in range(n - min_match_words + 1):
        if not all(allowed[i:i + min_match_words]):
            continue
        key = tuple(v[i:i + min_match_words])
        for si, j in inverted.get(key, ()):
            _, toks, _ = src_list[si]
            left, right = i, i + min_match_words
            srcleft, srcright = j, j + min_match_words
            while left > 0 and srcleft > 0 and allowed[left - 1] and v[left - 1] == toks[srcleft - 1].value:
                left -= 1
                srcleft -= 1
            while right < n and srcright < len(toks) and allowed[right] and v[right] == toks[srcright].value:
                right += 1
                srcright += 1
            dedup = (si, left, right)
            if dedup not in seen:
                seen.add(dedup)
                candidates.append((right - left, si, left, right, srcleft, srcright))

    # Longest non-overlapping runs take priority; token coverage is never double counted.
    candidates.sort(key=lambda z: (-z[0], z[2], z[1]))
    matches = []
    source_words = defaultdict(int)
    for length, si, left, right, sl, sr in candidates:
        free_positions = [p for p in range(left, right) if attr[p] is None]
        if len(free_positions) < min_match_words:
            continue
        source, stoks, stext = src_list[si]
        sid = str(source['id'])
        for p in free_positions:
            attr[p] = sid
        source_words[sid] += len(free_positions)
        matches.append(Match(
            source_id=sid, source_title=source['title'], doc_start=left, doc_end=right,
            source_start=sl, source_end=sr, length=length,
            doc_excerpt=document[doc[left].start:doc[right - 1].end][:500],
            source_excerpt=stext[stoks[sl].start:stoks[sr - 1].end][:500],
        ))

    eligible = sum(allowed)
    covered = sum(1 for a, ok in zip(attr, allowed) if ok and a is not None)
    return Result(100 * covered / eligible if eligible else 0, covered, eligible,
                  doc, attr, matches, dict(source_words))
