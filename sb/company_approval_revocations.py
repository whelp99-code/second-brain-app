"""Protected human revocations append evidence and close, never reenroll a scope."""

from __future__ import annotations

from sb.company_db_freshness_integrity import JournalEntry
from sb.company_db_freshness_models import FreshnessRegistry, RegistryApprovalRevocation
from sb.company_freshness_anchor import AnchorRejected
from sb.company_freshness_models import FreshnessScope
from sb.effect_values import format_instant, parse_instant


def approval_revocation_inventory(
    registry: FreshnessRegistry,
    entries: list[JournalEntry],
    *,
    allow_pending: bool = False,
) -> dict[tuple[str, str, str], RegistryApprovalRevocation]:
    declared: dict[tuple[str, str, str], RegistryApprovalRevocation] = {}
    for fact in registry.approval_revocations:
        identity = (fact.scope.provider_instance_id, fact.scope.workspace_id, fact.source_record_id)
        if (
            identity in declared
            or format_instant(parse_instant(fact.original_at)) != fact.original_at
            or (fact.reason == "key_revoked" and not fact.revoked_key_fingerprints)
        ):
            raise AnchorRejected("COMPANY_APPROVAL_REVOKED")
        declared[identity] = fact
    published: dict[tuple[str, str, str], RegistryApprovalRevocation] = {}
    for entry in entries:
        if (
            entry.phase != "registry"
            or entry.published_sequence is None
            or entry.record.get("kind") != "approval_revocation"
        ):
            continue
        fact = RegistryApprovalRevocation.model_validate(
            entry.record.get("revocation"), strict=True
        )
        identity = (
            entry.scope.provider_instance_id,
            entry.scope.workspace_id,
            fact.source_record_id,
        )
        if (
            fact.scope != entry.scope
            or identity in published
            or entry.record.get("closed") is not True
            or declared.get(identity) != fact
        ):
            raise AnchorRejected("COMPANY_APPROVAL_REVOKED")
        published[identity] = fact
    if not allow_pending and declared != published:
        raise AnchorRejected("COMPANY_APPROVAL_REVOKED")
    return {identity: fact for identity, fact in declared.items() if identity not in published}


def pending_approval_revocations(
    registry: FreshnessRegistry,
    entries: list[JournalEntry],
    scope: FreshnessScope,
) -> list[RegistryApprovalRevocation]:
    return [
        fact
        for fact in approval_revocation_inventory(registry, entries, allow_pending=True).values()
        if fact.scope == scope
    ]
