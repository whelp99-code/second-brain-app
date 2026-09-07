"""Project stored page metadata onto the existing public MCP page contract."""

from collections.abc import Mapping
from typing import Final

_PUBLIC_FIELDS: Final = frozenset({
    "id", "title", "updated", "compiled_by", "status", "sources", "sensitivity",
})


def public_frontmatter(metadata: Mapping[str, str]) -> dict[str, str]:
    """Keep internal derivation/resolution metadata in the committed blob only.

    Missing or invalid public values remain visible to strict consumers; this
    projection does not invent source, status, or sensitivity assertions.
    """
    return {key: value for key, value in metadata.items() if key in _PUBLIC_FIELDS}
