"""One literal all-terms query plan for mutable/sealed indexes and cited records."""
from __future__ import annotations

from dataclasses import dataclass

from sb.search_errors import SearchQueryError

MAX_QUERY_BYTES = 4096
MAX_QUERY_GROUPS = 32
_HANGUL_START = 0xAC00
_HANGUL_END = 0xD7A3


def _has_hangul(text: str) -> bool:
    return any(_HANGUL_START <= ord(char) <= _HANGUL_END for char in text)


def _compact(text: str) -> str:
    return "".join(char for char in text if not char.isspace())


def normalize(text: str) -> str:
    return _compact(text.casefold())


def _groups(text: str) -> tuple[str, ...]:
    groups: list[str] = []
    index = 0
    while index < len(text):
        if text[index].isspace():
            index += 1
            continue
        if len(groups) >= MAX_QUERY_GROUPS:
            raise SearchQueryError("SEARCH_QUERY_TOO_MANY_GROUPS: maximum 32")
        if text[index] != '"':
            start = index
            while index < len(text) and not text[index].isspace():
                index += 1
            groups.append(text[start:index])
            continue
        index += 1
        characters: list[str] = []
        while index < len(text) and text[index] != '"':
            if text[index] == "\\" and index + 1 < len(text) and text[index + 1] in {'"', "\\"}:
                index += 1
            characters.append(text[index])
            index += 1
        if index == len(text):
            raise SearchQueryError("SEARCH_QUERY_SYNTAX: unclosed quoted phrase")
        index += 1
        if index < len(text) and not text[index].isspace():
            raise SearchQueryError("SEARCH_QUERY_SYNTAX: separate quoted groups with whitespace")
        phrase = "".join(characters)
        if not phrase.strip():
            raise SearchQueryError("SEARCH_QUERY_SYNTAX: empty quoted phrase")
        groups.append(phrase)
    return tuple(dict.fromkeys(groups))


@dataclass(frozen=True, slots=True)
class LexicalQuery:
    text: str
    terms: tuple[str, ...]

    @classmethod
    def parse(cls, text: str) -> LexicalQuery:
        try:
            size = len(text.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise SearchQueryError("SEARCH_QUERY_ENCODING_INVALID") from exc
        if size > MAX_QUERY_BYTES:
            raise SearchQueryError("SEARCH_QUERY_TOO_LARGE: maximum 4096 UTF-8 bytes")
        if any(ord(char) < 32 and char not in "\t\r\n" or ord(char) == 127 for char in text):
            raise SearchQueryError("SEARCH_QUERY_CONTROL_CHARACTER")
        stripped = text.strip()
        terms = _groups(stripped)
        return cls(" ".join(terms), terms)

    @property
    def uses_fts(self) -> bool:
        return False

    def predicate(self) -> tuple[str, tuple[str, ...]]:
        if not self.terms:
            return "0", ()
        clauses: list[str] = []
        params: list[str] = []
        for term in self.terms:
            compact = normalize(term)
            clauses.append(
                "(instr(compact, ?) > 0 OR instr(normalize_id, ?) > 0 OR instr(normalize_section, ?) > 0)"
            )
            params.extend((compact, compact, compact))
        return " AND ".join(clauses) if clauses else "0", tuple(params)

    def relevance_sql(self) -> tuple[str, tuple[str, ...]]:
        if not self.terms:
            return "0", ()
        scores: list[str] = []
        params: list[str] = []
        for term in self.terms:
            compact = normalize(term)
            scores.append("(1.0*(length(compact)-length(replace(compact,?,''))))/max(length(compact),1)")
            params.append(compact)
        return "+".join(scores), tuple(params)

    def ordering(self) -> tuple[str, tuple[str, ...]]:
        if not self.terms:
            return "page_id,section,rowid", ()
        relevance, params = self.relevance_sql()
        if len(self.terms) < 2:
            return f"({relevance}) DESC,page_id,section,rowid", params
        return ("CASE WHEN instr(lower(text),lower(?))>0 OR instr(lower(page_id),lower(?))>0 "
                + f"OR instr(lower(section),lower(?))>0 THEN 0 ELSE 1 END,({relevance}) DESC,page_id,section,rowid",
                (self.text, self.text, self.text, *params))

    def record_priority(self, text: str) -> int:
        return 0 if self.text.casefold() in text.casefold() else 1

    def matches_record(self, text: str) -> bool:
        compact = normalize(text)
        return bool(self.terms) and all(normalize(term) in compact for term in self.terms)
