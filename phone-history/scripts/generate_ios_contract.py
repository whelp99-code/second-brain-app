#!/usr/bin/env python3
"""Generate Swift contract constants from canonical Phone History contracts."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "contracts" / "fixtures" / "event-batch.json"
SCHEMA = ROOT / "contracts" / "phone-event-v1.schema.json"
OUTPUT = ROOT / "ios" / "Core" / "GeneratedContract.swift"

EVENT_ALIASES: dict[str, tuple[str, ...]] = {
    "id": ("id", "event_id"),
    "device_id": ("device_id", "device"),
    "occurred_at": ("occurred_at", "captured_at", "created_at"),
    "source": ("source", "source_app"),
    "event_type": ("event_type", "type", "kind"),
    "capture_mode": ("capture_mode",),
    "sensitivity": ("sensitivity", "privacy_class"),
    "title": ("title", "name"),
    "body": ("body", "text", "content", "note"),
    "url": ("url", "link"),
    "project_hint": ("project_hint", "project", "project_id"),
    "attachment": ("attachment", "attachments", "file", "files"),
    "metadata": ("metadata", "attributes"),
    "knowledge_status": ("knowledge_status",),
    "approval_status": ("approval_status",),
    "canonical": ("canonical",),
}
ATTACHMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "filename": ("filename", "name"),
    "mime_type": ("mime_type", "content_type", "media_type", "uti"),
    "content_base64": ("content_base64", "content_b64", "data_base64", "content"),
    "sha256": ("sha256", "content_sha256", "hash_sha256", "digest"),
    "bytes": ("bytes", "size", "size_bytes", "byte_count"),
}

BATCH_ALIASES: dict[str, tuple[str, ...]] = {
    "id": ("batch_id", "id"),
    "device_id": ("device_id", "device"),
    "sent_at": ("sent_at", "uploaded_at", "created_at"),
    "event_count": ("event_count", "count"),
}


def compact(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def swift_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def resolve_ref(root: dict[str, Any], node: Any) -> Any:
    while isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/"):
            break
        current: Any = root
        for part in ref[2:].split("/"):
            current = current[part.replace("~1", "/").replace("~0", "~")]
        node = current
    return node


def non_null_schema(root: dict[str, Any], node: Any) -> dict[str, Any] | None:
    node = resolve_ref(root, node)
    if not isinstance(node, dict):
        return None
    for union_key in ("anyOf", "oneOf"):
        options = node.get(union_key)
        if isinstance(options, list):
            for option in options:
                resolved = resolve_ref(root, option)
                if isinstance(resolved, dict) and resolved.get("type") != "null":
                    return resolved
    return node


def find_event_schema(root: dict[str, Any], node: Any) -> dict[str, Any] | None:
    node = resolve_ref(root, node)
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            names = set(properties)
            id_like = {"id", "event_id"} & names
            source_like = {"source", "source_app"} & names
            event_like = {"event_type", "type", "kind"} & names
            device_like = {"device_id", "device"} & names
            if id_like and source_like and event_like and device_like:
                return node
        for value in node.values():
            found = find_event_schema(root, value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = find_event_schema(root, value)
            if found is not None:
                return found
    return None


def field_map(properties: dict[str, Any], aliases: dict[str, tuple[str, ...]]) -> dict[str, str]:
    return {
        semantic: match
        for semantic, candidates in aliases.items()
        if (match := next((name for name in candidates if name in properties), None)) is not None
    }


def swift_dictionary(values: dict[str, str]) -> str:
    return "\n".join(
        f"        {swift_string(key)}: {swift_string(value)},"
        for key, value in sorted(values.items())
    )


def batch_template() -> tuple[dict[str, Any], dict[str, Any], str]:
    batch = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if isinstance(batch, list):
        event_key = "events"
        root: dict[str, Any] = {event_key: batch}
    elif isinstance(batch, dict):
        root = dict(batch)
        arrays = [(key, value) for key, value in root.items() if isinstance(value, list)]
        event_key = next(
            (key for key, value in arrays if value and isinstance(value[0], dict)),
            "events",
        )
    else:
        raise SystemExit("event-batch fixture must be an object or array")
    events = root.get(event_key)
    if not isinstance(events, list) or not events or not isinstance(events[0], dict):
        raise SystemExit("event-batch fixture must contain at least one event object")
    return root, dict(events[0]), event_key


def main() -> int:
    root_template, event_template, event_key = batch_template()
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    event_schema = find_event_schema(schema, schema)
    if event_schema is None:
        raise SystemExit("could not locate PhoneEvent object in JSON Schema")
    event_properties = event_schema.get("properties")
    if not isinstance(event_properties, dict):
        raise SystemExit("PhoneEvent schema has no properties")

    combined_properties = dict(event_properties)
    combined_properties.update(event_template)
    event_fields = field_map(combined_properties, EVENT_ALIASES)
    required = {"id", "device_id", "occurred_at", "source", "event_type", "capture_mode"}
    missing = sorted(required - event_fields.keys())
    if missing:
        raise SystemExit(f"contract is missing semantic fields: {', '.join(missing)}")

    required_contract_fields = set(event_schema.get("required", []))
    clean_event_template: dict[str, Any] = {}
    for key, property_schema in event_properties.items():
        resolved = resolve_ref(schema, property_schema)
        default_present = isinstance(resolved, dict) and "default" in resolved
        if key in required_contract_fields:
            if default_present:
                clean_event_template[key] = resolved["default"]
            elif key in event_template:
                clean_event_template[key] = event_template[key]
            else:
                raise SystemExit(f"required event field has no fixture value/default: {key}")
        elif default_present:
            clean_event_template[key] = resolved["default"]
    event_template = clean_event_template

    attachment_key = event_fields.get("attachment")
    if not attachment_key:
        raise SystemExit("PhoneEvent contract does not define an attachment field")
    attachment_schema = non_null_schema(schema, event_properties.get(attachment_key))
    attachment_is_array = False
    if isinstance(attachment_schema, dict) and attachment_schema.get("type") == "array":
        attachment_is_array = True
        attachment_schema = non_null_schema(schema, attachment_schema.get("items"))
    if not isinstance(attachment_schema, dict):
        raise SystemExit("attachment schema could not be resolved")
    attachment_properties = attachment_schema.get("properties")
    if not isinstance(attachment_properties, dict):
        raise SystemExit("attachment schema has no properties")
    attachment_fields = field_map(attachment_properties, ATTACHMENT_ALIASES)
    required_attachment = {"filename", "mime_type", "content_base64", "sha256"}
    missing_attachment = sorted(required_attachment - attachment_fields.keys())
    if missing_attachment:
        raise SystemExit("attachment contract is missing fields: " + ", ".join(missing_attachment))

    attachment_template: dict[str, Any] = {}
    for key, value_schema in attachment_properties.items():
        resolved = non_null_schema(schema, value_schema) or {}
        default = resolved.get("default") if isinstance(resolved, dict) else None
        value_type = resolved.get("type") if isinstance(resolved, dict) else None
        if default is not None:
            attachment_template[key] = default
        elif value_type == "integer":
            attachment_template[key] = 0
        elif value_type == "boolean":
            attachment_template[key] = False
        elif value_type == "array":
            attachment_template[key] = []
        elif value_type == "object":
            attachment_template[key] = {}
        else:
            attachment_template[key] = ""

    root_template[event_key] = []
    batch_fields = field_map(root_template, BATCH_ALIASES)
    schema_digest = hashlib.sha256(SCHEMA.read_bytes()).hexdigest()
    fixture_digest = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    root_b64 = base64.b64encode(compact(root_template)).decode()
    event_b64 = base64.b64encode(compact(event_template)).decode()
    attachment_b64 = base64.b64encode(compact(attachment_template)).decode()
    source = f"""// Generated by scripts/generate_ios_contract.py. Do not hand-edit.
import Foundation

enum GeneratedPhoneHistoryContract {{
    static let schemaSHA256 = {swift_string(schema_digest)}
    static let fixtureSHA256 = {swift_string(fixture_digest)}
    static let eventArrayKey = {swift_string(event_key)}
    static let batchTemplateBase64 = {swift_string(root_b64)}
    static let eventTemplateBase64 = {swift_string(event_b64)}
    static let attachmentTemplateBase64 = {swift_string(attachment_b64)}
    static let attachmentIsArray = {str(attachment_is_array).lower()}
    static let fields: [String: String] = [
{swift_dictionary(event_fields)}
    ]
    static let batchFields: [String: String] = [
{swift_dictionary(batch_fields)}
    ]
    static let attachmentFields: [String: String] = [
{swift_dictionary(attachment_fields)}
    ]
}}
"""
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(source, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
