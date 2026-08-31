from __future__ import annotations

import base64
from datetime import datetime, timedelta
from typing import Literal, cast

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.effect_values import JsonObject, JsonValue, canonical_bytes, digest, format_instant
from sb.generations import Generation
from sb.targets import (
    GenerationIdentityV1,
    MemoryTargetSelectorV1,
    resolve_memory_target,
)

type Operation = Literal["correct", "forget", "export"]


def effect_request(
    generation: Generation,
    operation: Operation,
    record: str,
    now: datetime,
    high_water: tuple[int, str],
    private_key: Ed25519PrivateKey,
    lane_char: str,
) -> JsonObject:
    lane = {"correct": "correction", "forget": "deletion", "export": "export"}[operation]
    prefix = {"correct": "memcorr:req:v1:", "forget": "memdel:req:v1:", "export": "memexp:req:v1:"}[operation]
    lane_id = prefix + lane_char * 64
    page = next(generation.root.joinpath("wiki").glob("memory-*.md"))
    page_id = page.relative_to(generation.root).with_suffix("").as_posix()
    resolved_target = resolve_memory_target(
        generation.root,
        GenerationIdentityV1(
            generation.manifest.provider_instance_id,
            generation.generation_id,
            generation.manifest.generation_digest,
            generation.head,
            generation.tree,
        ),
        MemoryTargetSelectorV1(page_id, record, "6" * 64),
        owner_digest_key=b"owner-key",
        subject_digest_key=b"subject-key",
        now=now,
    )
    target = cast(JsonObject, resolved_target.as_dict())
    targets: list[JsonValue] = [target]
    target_manifest_digest = digest("target_manifest", {"targets": targets})
    scope: JsonObject = {
        "format": "json" if operation == "export" else "none",
        "sensitivity_classes": ["personal"],
        "valid_from": target["valid_from"],
        "valid_until": target["valid_until"],
        "max_records": 1,
        "max_bytes": 4096,
        "source_owner_classes": ["provider_owned"],
    }
    scope_digest = digest(
        "target_scope", {"target_digests": [target["target_digest"]], "scope": scope}
    )
    if operation == "correct":
        content = "corrected runtime record"
        payload: JsonObject = {
            "content": content,
            "content_digest": digest("effect_content", {"content": content}),
            "content_bytes": len(content.encode()),
            "disposition": "superseded",
        }
    elif operation == "forget":
        payload = {
            "disposition": "owner_requested",
            "erasure_claim": "managed_erasure",
            "external_receipts": cast(list[JsonValue], []),
        }
    else:
        payload = {
            "format": "json",
            "target_record_ids": [target["target_id"]],
            "sensitivity_classes": ["personal"],
            "valid_from": scope["valid_from"],
            "valid_until": scope["valid_until"],
            "max_records": 1,
            "max_bytes": 4096,
        }
    payload_digest = digest("effect_payload", payload)
    sequence, previous_root = high_water
    delta: list[JsonValue] = []
    if operation != "export":
        sequence += 1
        chain_core: JsonObject = {
            "sequence": sequence,
            "operation": operation,
            "lane_id": lane_id,
            "target_manifest_digest": target_manifest_digest,
            "scope_digest": scope_digest,
            "authority_receipt_digest": "sha256:" + "c" * 64,
            "payload_digest": payload_digest,
            "keyed_subject_digest": "hmac-sha256:" + "d" * 64,
            "effective_at": format_instant(now),
            "previous_root": previous_root,
        }
        set_root = digest("tombstone_chain", chain_core)
        delta.append({
            **chain_core,
            "tombstone_id": "memtomb:v1:" + set_root[7:],
            "set_root": set_root,
        })
    else:
        set_root = previous_root
    prior: JsonObject = {
        "provider_instance_id": target["provider_instance_id"],
        "generation_id": target["generation_id"],
        "generation_manifest_digest": target["generation_manifest_digest"],
        "vault_head": target["vault_head"],
        "vault_tree": target["vault_tree"],
        "page_blob_oid": target["page_blob_oid"],
        "page_content_digest": target["page_content_digest"],
        "citation_identity_full": target["citation_identity_full"],
    }
    created = format_instant(now)
    expires = format_instant(now + timedelta(minutes=10))
    request: JsonObject = {
        "schema_version": 2,
        "kind": "memory_effect",
        "provider_instance_id": generation.manifest.provider_instance_id,
        "lane": lane,
        "lane_id": lane_id,
        "operation": operation,
        "target_manifest_digest": target_manifest_digest,
        "targets": targets,
        "scope": scope,
        "scope_digest": scope_digest,
        "expected_prior": prior,
        "tombstone_high_water": {"sequence": sequence, "set_root": set_root},
        "tombstone_chain_delta": delta,
        "created_at": created,
        "expires_at": expires,
        "payload": payload,
    }
    request_digest = digest("effect_spec", request)
    request_id = "memeff:req:v2:" + request_digest[7:]
    idem = {
        "lane": lane,
        "lane_id": lane_id,
        "operation": operation,
        "request_id": request_id,
        "request_digest": request_digest,
        "target_manifest_digest": target_manifest_digest,
        "scope_digest": scope_digest,
    }
    delegation: JsonObject = {
        "schema_version": 1,
        "provider_instance_id": generation.manifest.provider_instance_id,
        "purpose": {"correct": "memory_correction", "forget": "memory_delete", "export": "memory_export"}[operation],
        "operation": operation,
        "lane_id": lane_id,
        "request_id": request_id,
        "request_digest": request_digest,
        "payload_digest": payload_digest,
        "target_manifest_digest": target_manifest_digest,
        "scope_digest": scope_digest,
        "expected_prior": prior,
        "tombstone_sequence": sequence,
        "tombstone_set_root": set_root,
        "principal_id": "principal:owner",
        "issued_at": created,
        "not_before": created,
        "expires_at": expires,
        "nonce": "nonce:" + lane_char * 64,
        "max_uses": 1,
        "signing_key_id": "jarvis:fixture",
    }
    delegation_digest = digest("delegation", delegation)
    delegation["delegation_id"] = "memdeleg:v1:" + delegation_digest[7:]
    delegation["delegation_digest"] = delegation_digest
    signature = private_key.sign(
        b"orca-jarvis/memory-effect-delegation/v1\0" + canonical_bytes(delegation)
    )
    delegation["signature"] = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    request["request_id"] = request_id
    request["request_digest"] = request_digest
    request["idempotency_key"] = "memeff:idem:v2:" + digest("effect_idempotency", idem)[7:]
    request["delegation"] = delegation
    request["envelope_digest"] = digest("envelope", request)
    return request
