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


def _compact_sql(column: str) -> str:
    return (
        "replace(replace(replace(replace(replace(lower("
        + column
        + "),' ',''), char(9), ''), char(10), ''), char(13), ''), char(12), '')"
    )


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
        return any(len(term) >= 3 and not _has_hangul(term) for term in self.terms)

    def predicate(self) -> tuple[str, tuple[str, ...]]:
        long = [term for term in self.terms if len(term) >= 3]
        clauses: list[str] = []
        params: list[str] = []
        if long:
            latin = [term for term in long if not _has_hangul(term)]
            hangul = [term for term in long if _has_hangul(term)]
            if latin:
                clauses.append("docs MATCH ?")
                params.append(" AND ".join('"' + term.replace('"', '""') + '"' for term in latin))
            for term in hangul:
                clauses.append(f"instr({_compact_sql('text')}, ?) > 0")
                params.append(_compact(term.casefold()))
        for term in self.terms:
            if len(term) < 3:
                if _has_hangul(term):
                    compact = _compact(term.casefold())
                    clauses.append(
                        f"(instr({_compact_sql('text')}, ?) > 0 OR instr({_compact_sql('page_id')}, ?) > 0 "
                        + f"OR instr({_compact_sql('section')}, ?) > 0)"
                    )
                    params.extend((compact, compact, compact))
                else:
                    clauses.append("(instr(lower(text),lower(?))>0 OR instr(lower(page_id),lower(?))>0 "
                                   + "OR instr(lower(section),lower(?))>0)")
                    params.extend((term, term, term))
        return " AND ".join(clauses) if clauses else "0", tuple(params)

    def ordering(self) -> tuple[str, tuple[str, ...]]:
        score = "bm25(docs)" if self.uses_fts else "0.0"
        if len(self.terms) < 2:
            return f"{score},page_id,section,rowid", ()
        return ("CASE WHEN instr(lower(text),lower(?))>0 OR instr(lower(page_id),lower(?))>0 "
                + f"OR instr(lower(section),lower(?))>0 THEN 0 ELSE 1 END,{score},page_id,section,rowid",
                (self.text, self.text, self.text))

    def record_priority(self, text: str) -> int:
        return 0 if self.text.casefold() in text.casefold() else 1

    def matches_record(self, text: str) -> bool:
        folded = text.casefold()
        compact = _compact(folded)
        return bool(self.terms) and all(
            term.casefold() in folded
            or (_has_hangul(term) and _compact(term.casefold()) in compact)
            for term in self.terms
        )
