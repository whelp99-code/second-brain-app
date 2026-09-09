"""Deterministic markdown chunking and credential redaction."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Final, Protocol, override

from llama_index.core.node_parser import SentenceSplitter

from sb.contracts import Blob, Unit
from sb.redaction import redact_credentials as _redact

NORMALIZER_VERSION: Final = "v2"
CHUNK_SIZE: Final = 700
CHUNK_OVERLAP: Final = 100

_TOKEN: Final = re.compile(r"\w+|[^\w\s]", flags=re.UNICODE)
_SENTENCE: Final = re.compile(
    r".+?(?:[.!?。？！]+(?:\s+|$)|\n{2,}|$)",
    flags=re.DOTALL,
)


class _TextSplitter(Protocol):
    def split_text(self, text: str) -> list[str]: ...


@dataclass(frozen=True, slots=True)
class UnlocatableChunk(Exception):
    """SentenceSplitter returned text that is not a substring of the source."""

    prefix: str

    @override
    def __str__(self) -> str:
        return f"splitter chunk not found in source text: {self.prefix!r}"


def _splitter() -> _TextSplitter:
    return SentenceSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        tokenizer=_tokenize,
        chunking_tokenizer_fn=_sentence_chunks,
    )


def _tokenize(text: str) -> list[str]:
    """Portable Unicode token counter with no model or downloaded data dependency."""
    return _TOKEN.findall(text)


def _sentence_chunks(text: str) -> list[str]:
    """Preserve deterministic sentence/paragraph pieces without NLTK resources."""
    if not text:
        return []
    chunks = [match.group(0) for match in _SENTENCE.finditer(text)]
    return chunks if "".join(chunks) == text else [text]


def _split(text: str) -> list[str]:
    return [chunk for chunk in _splitter().split_text(text) if chunk != ""]


def _locate(text: str, chunk: str, search_from: int) -> tuple[int, int]:
    start = text.find(chunk, search_from)
    if start < 0:
        start = text.find(chunk)
    if start < 0:
        raise UnlocatableChunk(prefix=chunk[:40])
    return start, start + len(chunk)


def _unit_id(content_hash: str, span: str, version: str) -> str:
    return hashlib.sha256(f"{content_hash}{span}{version}".encode()).hexdigest()


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def normalize(blob: Blob, text: str, origin: str) -> list[Unit]:
    """Chunk redacted text into stable Units for compile/conflict."""
    redacted = _redact(text)
    units: list[Unit] = []
    seen: set[str] = set()
    cursor = 0
    for chunk in _split(redacted):
        start, end = _locate(redacted, chunk, cursor)
        cursor = start + 1
        digest = _text_hash(chunk)
        if digest in seen:
            continue
        seen.add(digest)
        span = f"{start}-{end}"
        units.append(
            Unit(
                unit_id=_unit_id(blob.hash, span, NORMALIZER_VERSION),
                content_hash=blob.hash,
                span=span,
                text=chunk,
                origin=origin,
            )
        )
    return units
