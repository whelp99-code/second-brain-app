"""Bounded access metadata for an already authorized, pinned page read."""

from sb.effect_values import JsonObject, JsonValue
from sb.memory_access import ClassifiedPage, MemoryAccessError
from sb.source_access import source_access_digest


def page_access_projection(page: ClassifiedPage) -> JsonObject:
    """Caller must finish scope checks before projecting any source metadata.

    The outer scoped response binds this projection to its request, committed page
    digest and generation. These checksums alone do not authenticate a response.
    """
    if not 1 <= len(page.source_refs) <= 64 or len(page.source_refs) != len(page.requirements):
        raise MemoryAccessError("MEMORY_ACCESS_UNAVAILABLE")
    sources: list[JsonValue] = []
    for ref, requirement in zip(page.source_refs, page.requirements, strict=True):
        sources.append({"source_ref_digest": ref, "classification": {
            "schema_version": 1, "owner": requirement.owner, "projects": list(requirement.projects),
            "policy_revision": requirement.policy_revision},
            "classification_digest": source_access_digest(ref, requirement)})
    return {"schema_version": 1, "complete": True, "sources": sources}
