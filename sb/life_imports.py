"""Bounded import preparation for the existing single-writer pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from sb.config import Config
from sb.life_config import policy_for, settings
from sb.life_contracts import SENSITIVITIES, LifeInputError
from sb.life_exports import parse_export
from sb.life_json import LifePayload, decode_json
from sb.life_sensors import HEALTH_TYPES, health_batch, parse_overland, point_payload, segments
from sb.life_values import canonical_bytes, text


@dataclass(frozen=True, slots=True)
class PreparedImport:
    payloads: tuple[LifePayload, ...]
    deleted_source_items: tuple[str, ...]
    input_digest: str
    anchor: str | None
    kind: str
    attachment_states: tuple[str, ...] = ()


def prepare(
    config: Config, source_id: str, kind: str, raw: bytes, *, filename: str, now: datetime
) -> PreparedImport:
    opts = settings(config)
    policy = policy_for(config, source_id, admission=False)
    if type(raw) is not bytes or len(raw) > 16 * 1024 * 1024:
        raise LifeInputError("LIFE_IMPORT_TOO_LARGE")
    if kind == "health":
        try:
            value = decode_json(raw)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise LifeInputError("LIFE_HEALTH_BATCH_INVALID") from exc
        sensor_config = config.raw.get("life_sensor_sources", {})
        entry = sensor_config.get(source_id, {}) if isinstance(sensor_config, Mapping) else None
        if not isinstance(entry, Mapping) or set(entry) - {"health_types"}:
            raise LifeInputError("LIFE_SENSOR_CONFIG_INVALID")
        allowed = entry.get("health_types", [])
        if (
            not isinstance(allowed, list)
            or not allowed
            or any(not isinstance(t, str) or t not in HEALTH_TYPES for t in allowed)
        ):
            raise LifeInputError("LIFE_HEALTH_TYPE_DISABLED")
        # Deletion-only batches may be processed after disabling collection.
        if isinstance(value, dict) and not value.get("samples") and value.get("deleted"):
            if policy.sensitivity != "restricted" or policy.external_processing != "local_only":
                raise LifeInputError("LIFE_SENSOR_POLICY_REQUIRED")
        else:
            opts.require("health_capture")
            _ = policy_for(config, source_id)
        rows, removed, anchor = health_batch(
            value,
            allowed_types=[t for t in allowed if isinstance(t, str)],
            timezone=opts.timezone,
            now=now,
        )
        return PreparedImport(rows, removed, sha256(raw).hexdigest(), anchor, kind)
    _ = policy_for(config, source_id)
    if kind == "overland":
        opts.require("location_capture")
        if policy.sensitivity != "restricted" or policy.external_processing != "local_only":
            raise LifeInputError("LIFE_SENSOR_POLICY_REQUIRED")
        try:
            value = decode_json(raw)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise LifeInputError("LIFE_LOCATION_BATCH_INVALID") from exc
        points = parse_overland(value, now=now)
        rows = tuple(point_payload(p, timezone=opts.timezone) for p in points)
        derived = tuple(
            p
            for p in segments(points, timezone=opts.timezone)
            if p["event_type"] in policy.allowed_types
        )
        return PreparedImport(rows + derived, (), sha256(raw).hexdigest(), None, kind)
    if kind == "phone-event":
        try:
            original = decode_json(raw)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise LifeInputError("LIFE_PHONE_EVENT_INVALID") from exc
        if (
            not isinstance(original, dict)
            or original.get("sensitivity", "personal") not in SENSITIVITIES
        ):
            raise LifeInputError("LIFE_PHONE_EVENT_INVALID")
        declared = original.get("sensitivity", "personal")
        if SENSITIVITIES.index(declared) > SENSITIVITIES.index(policy.sensitivity):
            # Client labels never grant privileges, but a stricter privacy label
            # must not silently become a less sensitive source classification.
            raise LifeInputError("LIFE_SOURCE_SENSITIVITY_TOO_LOW")
        if original.get("event_type") == "call_recording_imported" and (
            policy.sensitivity != "restricted" or policy.external_processing != "local_only"
        ):
            raise LifeInputError("LIFE_SENSOR_POLICY_REQUIRED")
    filename = text(filename, maximum=512)
    rows = parse_export(kind, raw, filename, timezone=opts.timezone)
    if len(rows) > 1000 or len(canonical_bytes(rows)) > 24 * 1024 * 1024:
        raise LifeInputError("LIFE_IMPORT_TOO_LARGE")
    states = tuple(
        line.split("=", 1)[1]
        for row in rows
        for line in str(row.get("body", "")).splitlines()
        if line.startswith("attachment_state=")
    )
    return PreparedImport(rows, (), sha256(raw).hexdigest(), None, kind, states)
