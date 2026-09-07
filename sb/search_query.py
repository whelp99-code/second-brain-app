"""One literal all-terms query plan for mutable/sealed indexes and cited records."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LexicalQuery:
    text: str
    terms: tuple[str, ...]

    @classmethod
    def parse(cls, text: str) -> LexicalQuery:
        stripped = text.strip()
        return cls(stripped, tuple(dict.fromkeys(stripped.split())))

    @property
    def uses_fts(self) -> bool:
        return any(len(term) >= 3 for term in self.terms)

    def predicate(self) -> tuple[str, tuple[str, ...]]:
        long = [term for term in self.terms if len(term) >= 3]
        clauses: list[str] = []
        params: list[str] = []
        if long:
            clauses.append("docs MATCH ?")
            params.append(" AND ".join('"' + term.replace('"', '""') + '"' for term in long))
        for term in self.terms:
            if len(term) < 3:
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
        return bool(self.terms) and all(term.casefold() in folded for term in self.terms)
