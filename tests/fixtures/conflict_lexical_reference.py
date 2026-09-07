"""Slow pre-optimization ranking oracle, retained independently for compatibility."""
from __future__ import annotations

import unicodedata
from collections import Counter
from collections.abc import Sequence

from sb.conflict_lexical import LexicalMatch
from sb.contracts import PageSpec, Unit


def tokens(text: str) -> tuple[str, ...]:
    values: list[str] = []
    buffer: list[str] = []
    for char in unicodedata.normalize("NFC", text).casefold():
        if char.isalnum():
            buffer.append(char)
        elif buffer:
            values.append("".join(buffer))
            buffer = []
    if buffer:
        values.append("".join(buffer))
    return tuple(values)


def rank(query: tuple[str, ...], docs: Sequence[tuple[str, tuple[str, ...]]], exclude: str) -> list[LexicalMatch]:
    keys = list(dict.fromkeys(query))
    if not keys:
        return []
    grouped: dict[str, Counter[str]] = {}
    ordinals: dict[str, int] = {}
    df: dict[str, int] = {}
    count = 0
    want = set(keys)
    for ordinal, (doc_id, words) in enumerate(docs):
        if doc_id == exclude:
            continue
        count += 1
        ordinals[doc_id] = ordinal
        freqs = Counter(words)
        grouped[doc_id] = freqs
        for token in freqs:
            if token in want:
                df[token] = df.get(token, 0) + 1
    ranked: list[tuple[int, int, str, int]] = []
    for doc_id, freqs in grouped.items():
        score = sum(freqs.get(key, 0) * max(count - df.get(key, 0) + 1, 1) for key in keys)
        if score >= 1:
            ranked.append((-score, ordinals[doc_id], doc_id, score))
    ranked.sort()
    return [LexicalMatch(exclude, doc_id, float(score)) for _n, _o, doc_id, score in ranked[:10]]


def reference(units: Sequence[Unit], pages: Sequence[PageSpec]) -> tuple[LexicalMatch, ...]:
    docs = [(unit.unit_id, tokens(unit.text)) for unit in units]
    docs.extend((page.page_id, tokens(page.body_md)) for page in pages)
    ids = {unit.unit_id for unit in units}
    hits = [hit for unit in units for hit in rank(tokens(unit.text), docs, unit.unit_id)]
    hits.sort(key=lambda hit: (0 if hit.left_id in ids and hit.unit_id in ids else 1,
                              -hit.score, hit.left_id, hit.unit_id))
    seen: set[tuple[str, str]] = set()
    unique: list[LexicalMatch] = []
    for hit in hits:
        pair = (min(hit.left_id, hit.unit_id), max(hit.left_id, hit.unit_id))
        if pair in seen:
            continue
        seen.add(pair)
        unique.append(hit)
        if len(unique) == 10:
            break
    return tuple(unique)
