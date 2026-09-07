"""Project stored page metadata onto the existing public MCP page contract."""

from collections.abc import Mapping
from typing import Final

from sb.page_ids import git_rel
from sb.vault import PathEscapeError

_PUBLIC_FIELDS: Final = frozenset({
    "id", "title", "updated", "compiled_by", "status", "sources", "sensitivity",
})


def public_frontmatter(metadata: Mapping[str, str], requested_id: str) -> dict[str, str]:
    """Keep internal derivation/resolution metadata in the committed blob only.

    Missing or invalid public values remain visible to strict consumers; this
    projection does not invent source, status, or sensitivity assertions.
    """
    result = {key: value for key, value in metadata.items() if key in _PUBLIC_FIELDS}
    # YAML serializes an empty source list inline after the last citation is
    # erased. The frozen public scalar is empty for either list spelling.
    if result.get("sources") == "[]":
        result["sources"] = ""
    try:
        if git_rel(result.get("id", "")) == git_rel(requested_id):
            result["id"] = requested_id
    except PathEscapeError:
        pass  # Preserve malformed IDs for consumer rejection; never assert a new identity.
    return result
