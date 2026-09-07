"""Exact bounded conflict candidates with shared document frequency statistics."""
from __future__ import annotations

import heapq
import re
import unicodedata
from collections import Counter, OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, final

from sb.contracts import PageSpec, Unit

LEXICAL_FLOOR: Final = 1
LEXICAL_TOP: Final = 10
_CACHE_SIZE: Final = 256
_WORDS: Final = re.compile(r"[^\W_]+")
type _Signature = tuple[tuple[str, int], ...]
type _Ranked = tuple[tuple[str, int], ...]
type _Order = tuple[int, float, str, str]


@dataclass(frozen=True, slots=True)
class LexicalMatch:
    left_id: str
    unit_id: str
    score: float


def _tokens(text: str) -> tuple[str, ...]:
    # Unicode word characters without underscore match the former isalnum loop.
    return tuple(_WORDS.findall(unicodedata.normalize("NFC", text).casefold()))


@final
class _Candidates:
    def __init__(self, units: Sequence[Unit], pages: Sequence[PageSpec]) -> None:
        self.queries: list[tuple[str, tuple[str, ...]]] = []
        self.ordinals: dict[str, int] = {}
        self.occurrences: Counter[str] = Counter()
        self.document_frequency: Counter[str] = Counter()
        self.excluded_frequency: dict[str, Counter[str]] = {}
        self.postings: dict[str, dict[str, int]] = {}
        self.cache: OrderedDict[_Signature, _Ranked] = OrderedDict()
        self.count = len(units) + len(pages)
        frequencies: dict[str, Counter[str]] = {}
        for ordinal in range(self.count):
            if ordinal < len(units):
                doc_id, text = units[ordinal].unit_id, units[ordinal].text
            else:
                page = pages[ordinal - len(units)]
                doc_id, text = page.page_id, page.body_md
            frequency = Counter(_tokens(text))
            if ordinal < len(units):
                self.queries.append((doc_id, tuple(frequency)))
            self.occurrences[doc_id] += 1
            self.document_frequency.update(frequency.keys())
            if doc_id not in self.excluded_frequency:
                self.excluded_frequency[doc_id] = Counter()
            self.excluded_frequency[doc_id].update(frequency.keys())
            # The prior algorithm counts every occurrence in DF, but a repeated
            # document ID uses its last occurrence for ranking and ordinal ties.
            frequencies[doc_id] = frequency
            self.ordinals[doc_id] = ordinal
        for doc_id, frequency in frequencies.items():
            for token, tf in frequency.items():
                self.postings.setdefault(token, {})[doc_id] = tf

    def _score(self, signature: _Signature) -> _Ranked:
        scores: dict[str, int] = {}
        for token, weight in signature:
            for doc_id, tf in self.postings[token].items():
                scores[doc_id] = scores.get(doc_id, 0) + tf * weight
        ranked = heapq.nsmallest(
            LEXICAL_TOP + 1,
            ((doc_id, score) for doc_id, score in scores.items() if score >= LEXICAL_FLOOR),
            key=lambda item: (-item[1], self.ordinals[item[0]], item[0]),
        )
        return tuple(ranked)

    def rank(self, exclude: str, query: tuple[str, ...]) -> tuple[LexicalMatch, ...]:
        count = self.count - self.occurrences[exclude]
        own_frequency = self.excluded_frequency[exclude]
        signature = tuple(sorted(
            (token, max(count - self.document_frequency[token] + own_frequency[token] + 1, 1))
            for token in query
            if token in self.postings
            and (len(self.postings[token]) > 1 or exclude not in self.postings[token])
        ))
        if not signature:
            return ()
        ranked = self.cache.get(signature)
        if ranked is None:
            ranked = self._score(signature)
            self.cache[signature] = ranked
            if len(self.cache) > _CACHE_SIZE:
                _ = self.cache.popitem(last=False)
        else:
            self.cache.move_to_end(signature)
        # Cache one extra candidate because one distinct document ID is excluded
        # here. Occurrence multiplicity was already included in the weights.
        return tuple(LexicalMatch(exclude, doc_id, float(score))
                     for doc_id, score in ranked if doc_id != exclude)[:LEXICAL_TOP]


def lexical_top(units: Sequence[Unit], pages: Sequence[PageSpec]) -> tuple[LexicalMatch, ...]:
    if not units:
        return ()
    index = _Candidates(units, pages)
    unit_ids = {unit.unit_id for unit in units}
    selected: dict[tuple[str, str], tuple[_Order, LexicalMatch]] = {}
    worst_pair: tuple[str, str] | None = None
    for exclude, query in index.queries:
        for hit in index.rank(exclude, query):
            order = (0 if hit.left_id in unit_ids and hit.unit_id in unit_ids else 1,
                     -hit.score, hit.left_id, hit.unit_id)
            pair = (min(hit.left_id, hit.unit_id), max(hit.left_id, hit.unit_id))
            previous = selected.get(pair)
            if previous is not None and order >= previous[0]:
                continue
            if previous is None and len(selected) == LEXICAL_TOP:
                assert worst_pair is not None
                if order >= selected[worst_pair][0]:
                    continue
                del selected[worst_pair]
            selected[pair] = (order, hit)
            worst_pair = max(selected, key=lambda candidate: selected[candidate][0])
    return tuple(hit for _order, hit in sorted(selected.values(), key=lambda item: item[0]))
