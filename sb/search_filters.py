"""Shared knowledge-state/date metadata filters; these are not access grants."""
from __future__ import annotations

from dataclasses import dataclass

from sb.knowledge_registry import ACTIVE, APPROVED, CANDIDATE


@dataclass(frozen=True, slots=True)
class SearchFilters:
    kinds: tuple[str, ...] = ()
    status: str | None = None
    updated_from: str | None = None
    updated_to: str | None = None
    scope: str | None = None

    def predicate(self, prefix: str = "") -> tuple[str, tuple[str, ...]]:
        if prefix not in {"", "d."}:
            raise ValueError("invalid search metadata alias")
        where: list[str] = []
        params: list[str] = []
        kinds = tuple(dict.fromkeys(kind for kind in self.kinds if kind))
        if kinds:
            where.append(prefix + "kind IN (" + ",".join("?" for _ in kinds) + ")")
            params.extend(kinds)
        for column, operator, value in [("status", "=", self.status), ("updated", ">=", self.updated_from),
                                        ("updated", "<=", self.updated_to)]:
            if value:
                where.append(prefix + column + operator + "?")
                params.append(value)
        scope = (self.scope or "active").strip().lower()
        if scope == "candidate":
            where.append(prefix + "knowledge_status=?")
            params.append(CANDIDATE)
        elif scope not in {"reference", "all"}:
            where.extend((prefix + "knowledge_status=?", prefix + "approval_status=?"))
            params.extend((ACTIVE, APPROVED))
        return " AND ".join(where) or "1", tuple(params)
