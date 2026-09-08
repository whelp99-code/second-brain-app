"""Conservative provenance requirements for one compiled page, not an access grant."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import cast

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class PageAccess:
    source_refs: tuple[str, ...]
    complete: bool

    def encode(self) -> str:
        return json.dumps(
            {"schema_version": 1, "source_refs": self.source_refs, "complete": self.complete},
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def decode(cls, encoded: str) -> PageAccess:
        try:
            value = cast(dict[str, object], json.loads(encoded))
            refs = value["source_refs"]
            if not isinstance(refs, list) or type(value["complete"]) is not bool:
                raise ValueError("PAGE_ACCESS_CORRUPT")
            rows = cast(list[object], refs)
            if any(not isinstance(item, str) or _DIGEST.fullmatch(item) is None for item in rows):
                raise ValueError("PAGE_ACCESS_CORRUPT")
            sources = tuple(cast(list[str], rows))
            if sources != tuple(sorted(set(sources))) or (not sources and value["complete"]):
                raise ValueError("PAGE_ACCESS_CORRUPT")
            result = cls(sources, value["complete"])
            if result.encode() != encoded:
                raise ValueError("PAGE_ACCESS_CORRUPT")
            return result
        except (TypeError, KeyError, ValueError) as exc:
            raise ValueError("PAGE_ACCESS_CORRUPT") from exc
