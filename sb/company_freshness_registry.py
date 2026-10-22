"""Compare protected operator policy pins with retained anchored registration."""

from __future__ import annotations

from sb.company_approver_binding import decode_key, public_key_fingerprint
from sb.company_db_freshness_integrity import JournalEntry
from sb.company_db_freshness_models import FreshnessRegistry, RegistryAutoPolicyPin
from sb.company_freshness_anchor import AnchorRejected
from sb.company_freshness_models import FreshnessScope


def current_auto_pin(registry: FreshnessRegistry, scope: FreshnessScope) -> RegistryAutoPolicyPin:
    pins = [pin for pin in registry.auto_policies if pin.scope == scope]
    if len(pins) != 1:
        raise AnchorRejected("COMPANY_POLICY_REGISTRATION_REQUIRED")
    pin = pins[0]
    if public_key_fingerprint(decode_key(pin.public_key)) != pin.public_key_fingerprint:
        raise AnchorRejected("COMPANY_POLICY_REGISTRATION_REQUIRED")
    return pin


def latest_auto_pins(entries: list[JournalEntry]) -> dict[tuple[str, str], RegistryAutoPolicyPin]:
    latest: dict[tuple[str, str], RegistryAutoPolicyPin] = {}
    for entry in entries:
        if (
            entry.phase != "registry"
            or entry.published_sequence is None
            or entry.record.get("kind") != "internal_auto_policy"
        ):
            continue
        pin = RegistryAutoPolicyPin.model_validate(entry.record.get("pin"), strict=True)
        if pin.scope != entry.scope:
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
        previous = latest.get((pin.scope.provider_instance_id, pin.scope.workspace_id))
        require_forward_pin(previous, pin)
        latest[(pin.scope.provider_instance_id, pin.scope.workspace_id)] = pin
    return latest


def require_forward_pin(previous: RegistryAutoPolicyPin | None, pin: RegistryAutoPolicyPin) -> None:
    if previous is None:
        return
    if (
        pin.revision <= previous.revision
        or not set(previous.revoked_policy_digests) <= set(pin.revoked_policy_digests)
        or not set(previous.revoked_key_fingerprints) <= set(pin.revoked_key_fingerprints)
        or (
            previous.policy_digest != pin.policy_digest
            and previous.policy_digest not in pin.revoked_policy_digests
        )
        or (
            previous.public_key_fingerprint != pin.public_key_fingerprint
            and previous.public_key_fingerprint not in pin.revoked_key_fingerprints
        )
    ):
        raise AnchorRejected("COMPANY_POLICY_REGISTRATION_REQUIRED")


def require_scope_pins(registry: FreshnessRegistry, entries: list[JournalEntry]) -> None:
    for entry in entries:
        if entry.phase != "bootstrap":
            continue
        pins = [
            pin
            for pin in registry.scopes
            if pin.provider_instance_id == entry.scope.provider_instance_id
            and pin.workspace_id == entry.scope.workspace_id
        ]
        if (
            len(pins) != 1
            or pins[0].epoch != entry.after.operational_epoch
            or pins[0].genesis_digest != entry.after.intent_root
            or pins[0].source_deletion_sequence != entry.record.get("source_deletion_sequence")
            or pins[0].source_deletion_root != entry.record.get("source_deletion_root")
            or pins[0].source_context_digest != entry.record.get("source_context_digest")
        ):
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")


def require_current_auto_pins(registry: FreshnessRegistry, entries: list[JournalEntry]) -> None:
    pins = latest_auto_pins(entries)
    if entries:
        pending = entries[-1]
        if (
            pending.phase == "registry"
            and pending.published_sequence is None
            and pending.record.get("kind") == "internal_auto_policy"
        ):
            pin = RegistryAutoPolicyPin.model_validate(pending.record.get("pin"), strict=True)
            if pin.scope != pending.scope:
                raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
            key = (pin.scope.provider_instance_id, pin.scope.workspace_id)
            require_forward_pin(pins.get(key), pin)
            pins[key] = pin
    for pin in pins.values():
        if pin != current_auto_pin(registry, pin.scope):
            raise AnchorRejected("COMPANY_POLICY_REGISTRATION_REQUIRED")
