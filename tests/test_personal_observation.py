"""K1 synthetic fixtures; no source I/O, clock, credentials, or network."""

import hashlib
import json
import subprocess
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from sb.effect_values import canonical_bytes
from sb.personal_observation import (
    ObservationError,
    TrustedSourceManifest,
    check_revision,
    decode_observation,
    parse_observation,
)

FIXTURES = Path(__file__).parent / "fixtures" / "personal-observation"
CONTRACTS = Path(__file__).parents[1] / "contracts"
FAMILIES = ("mail", "kakao", "audio", "session")


def fixture(family="mail"):
    return json.loads((FIXTURES / f"{family}.json").read_text())


def parse(value, **options):
    manifest = TrustedSourceManifest(**value["manifest"])
    return parse_observation(
        value["observation"], manifest, emitter=manifest.emitter,
        account_id=manifest.account_id, root=manifest.root,
        content=value["content_utf8"].encode(), **options,
    )


def test_observation_id_is_domain_separated_digest_of_identity():
    observation = parse(fixture())
    identity = {
        "namespace": "personal", "account_id": "synthetic-account", "source_id": "mail",
        "event_id": "event-한글-1", "revision": 1,
    }
    expected = "sha256:" + hashlib.sha256(
        b"second-brain/personal-source-observation/v1\0" + canonical_bytes(identity)
    ).hexdigest()
    assert observation.identity == identity
    assert observation.observation_id == expected
    assert observation.observation_id != "sha256:" + hashlib.sha256(canonical_bytes(identity)).hexdigest()
    assert replace(observation, ingested_at="2026-09-25T00:00:00.000Z").observation_id == expected
    for field, value in (("event_id", "other"), ("revision", 2), ("account_id", "other"),
                         ("source_id", "other"),
                         ("namespace", "company:12345678-1234-1234-1234-123456789abc")):
        assert replace(observation, **{field: value}).observation_id != expected


def test_same_identity_revision_different_bytes_is_source_revision_conflict():
    original = fixture()
    first = parse(original)
    assert parse(original, previous=first) == first
    changed = fixture()
    changed["content_utf8"] = "Synthetic corrected original\n"
    changed["observation"]["content_sha256"] = hashlib.sha256(changed["content_utf8"].encode()).hexdigest()
    with pytest.raises(ObservationError, match="^SOURCE_REVISION_CONFLICT$"):
        parse(changed, previous=first)
    changed["observation"].update(revision=2, supersedes_observation_id=first.observation_id)
    corrected = parse(changed, previous=first)
    assert corrected.observation_id != first.observation_id
    assert corrected.supersedes_observation_id == first.observation_id
    assert first.canonical_bytes() == canonical_bytes(original["observation"])


def test_same_content_different_source_is_preserved_separately():
    first = parse(fixture())
    for field in ("source_id", "account_id"):
        other = fixture()
        other["manifest"][field] = other["observation"][field] = "other"
        second = parse(other, previous=first)
        assert first.content_sha256 == second.content_sha256
        assert first.observation_id != second.observation_id
        check_revision(first, second)


def test_manifest_decides_namespace_and_policy_body_cannot_escalate():
    value = fixture()
    manifest = TrustedSourceManifest(**value["manifest"])
    assert manifest.external_processing == "local_only"
    for field, injected in (("project_hint", "company"), ("allow", True), ("owner", "attacker"),
                            ("root", "file:///etc"), ("external_processing", "explicitly_allowed")):
        altered = fixture()
        altered["observation"][field] = injected
        with pytest.raises(ObservationError, match="^FIELDS_INVALID$"):
            parse(altered)
    for field in ("emitter", "account_id", "root"):
        context = {key: getattr(manifest, key) for key in ("emitter", "account_id", "root")}
        context[field] = "attacker"
        with pytest.raises(ObservationError, match="^SOURCE_MANIFEST_MISMATCH$"):
            parse_observation(value["observation"], manifest, **context)
    # Only a trusted configuration change can move this source into company scope.
    value["manifest"]["namespace"] = value["observation"]["namespace"] = (
        "company:12345678-1234-1234-1234-123456789abc"
    )
    assert parse(value).namespace.startswith("company:")


@pytest.mark.parametrize("tamper", json.loads((FIXTURES / "tampered.json").read_text()),
                         ids=lambda row: row["name"])
def test_tampered_namespace_account_revision_hash_time_rejected(tamper):
    value = fixture()
    value["observation"].update(tamper.get("set", {}))
    if "remove" in tamper:
        del value["observation"][tamper["remove"]]
    with pytest.raises(ValueError, match=f"^{tamper['error']}$"):
        parse(value)


@pytest.mark.parametrize("family", FAMILIES)
def test_canonical_roundtrip_matches_cross_language_digest_fixture(family):
    value = fixture(family)
    observation = parse(value)
    vectors = json.loads((FIXTURES / "digest-vectors.json").read_text())
    expected = vectors[family]
    assert observation.canonical_bytes() == expected["canonical_utf8"].encode()
    assert hashlib.sha256(observation.canonical_bytes()).hexdigest() == expected["canonical_sha256"]
    assert canonical_bytes(observation.identity).decode() == expected["identity_utf8"]
    assert observation.observation_id == expected["observation_id"]
    node = subprocess.run(
        ["node", str(FIXTURES / "canonical.cjs")], input=observation.canonical_bytes(),
        capture_output=True, check=True, timeout=10,
    )
    assert json.loads(node.stdout) == expected
    manifest = TrustedSourceManifest(**value["manifest"])
    decoded = decode_observation(
        observation.canonical_bytes(), manifest, emitter=manifest.emitter,
        account_id=manifest.account_id, root=manifest.root, content=value["content_utf8"].encode(),
    )
    assert decoded == observation
    schema = json.loads((CONTRACTS / "personal-source-observation-v1.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(observation.as_dict())
    with pytest.raises(FrozenInstanceError):
        decoded.__setattr__("revision", 99)
    exported = decoded.as_dict()
    spans = exported["evidence_spans"]
    assert isinstance(spans, list)
    spans.clear()
    assert decoded.evidence_spans


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{ "x":1}',
                                  b'{"x":"e\\u0301"}', b'[]'])
def test_noncanonical_wire_is_rejected(raw):
    value = fixture()
    manifest = TrustedSourceManifest(**value["manifest"])
    with pytest.raises(ValueError):
        decode_observation(raw, manifest, emitter=manifest.emitter,
                           account_id=manifest.account_id, root=manifest.root)


@pytest.mark.parametrize("precision,occurred,original,zone", [
    ("unknown", None, None, None),
    ("day", "2026-09-23", "2026-09-23", None),
    ("minute", "2026-09-23T00:00:00.000Z", "2026-09-23T09:00:00+09:00", "Asia/Seoul"),
    ("millisecond", "2026-09-23T00:00:00.123Z", "2026-09-23T09:00:00.123+09:00", "Asia/Seoul"),
    ("second", "2026-11-01T05:30:00.000Z", "2026-11-01T01:30:00-04:00", "America/New_York"),
    ("second", "2026-11-01T06:30:00.000Z", "2026-11-01T01:30:00-05:00", "America/New_York"),
])
def test_unknown_date_only_and_dst_offsets_preserved(precision, occurred, original, zone):
    value = fixture()
    value["observation"].update(timestamp_precision=precision, occurred_at=occurred,
                                 original_timestamp=original, source_timezone=zone)
    result = parse(value)
    assert result.occurred_at == occurred
    assert result.original_timestamp == original
    assert result.ingested_at == value["observation"]["ingested_at"]


@pytest.mark.parametrize("changes", [
    {"occurred_at": None}, {"timestamp_precision": "unknown"},
    {"source_timezone": "Mars/Olympus"}, {"source_updated_at": "2026-09-23"},
    {"timestamp_precision": "millisecond",
     "original_timestamp": "2026-09-23T09:00:00+09:00",
     "occurred_at": "2026-09-23T00:00:00.000Z"},
    {"original_timestamp": "2026-09-23T09:00:00"},
    {"original_timestamp": "2026-02-30T09:00:00+09:00"},
    {"original_timestamp": "2026-09-23T09:00:00+08:60"},
    {"original_timestamp": "0001-01-01T00:00:00+09:00"},
    {"original_timestamp": "2026-03-08T02:30:00-05:00",
     "occurred_at": "2026-03-08T07:30:00.000Z", "source_timezone": "America/New_York"},
    {"capture_mode": "execute"}, {"schema_version": 2}, {"source_deleted": 1},
    {"evidence_spans": [{"kind": "byte", "start": True, "end": 4}]},
    {"evidence_spans": [{"kind": "byte", "start": 0, "end": 0}]},
    {"evidence_spans": [{"kind": "command", "start": 0, "end": 1}]},
    {"evidence_spans": [{"kind": [], "start": 0, "end": 1}]},
    {"evidence_spans": [{"kind": "byte", "start": "0", "end": 1}]},
    {"evidence_spans": [{"kind": "byte", "start": 0, "end": 1}] * 1025},
    {"evidence_spans": [None]}, {"event_id": "e\u0301"},
])
def test_invalid_time_span_and_wire_values_rejected(changes):
    value = fixture()
    value["observation"].update(changes)
    with pytest.raises(ValueError):
        parse(value)


def test_source_deleted_is_observation_metadata_not_original_destruction():
    value = fixture()
    value["observation"]["source_deleted"] = True
    assert parse(value).source_deleted is True
    assert value["content_utf8"] == fixture()["content_utf8"]
