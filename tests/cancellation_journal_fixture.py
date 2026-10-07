"""Concrete generation fixtures for cancellation journal serialization tests."""

from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path

from sb.correction_cancellation_models import CorrectionCancellationIntentV1
from sb.effect_values import JsonObject, parse_instant
from sb.generations import Generation, GenerationManifestV1
from tests.test_correction_cancellation import cancellation_fixture, resign

NOW = parse_instant("2026-08-31T00:00:01.000Z")


def intent() -> JsonObject:
    return resign({**cancellation_fixture(), "issued_at": "2026-08-31T00:00:01.000Z",
        "not_before": "2026-08-31T00:00:01.000Z", "expires_at": "2026-08-31T00:05:00.000Z"})


@dataclass(frozen=True, slots=True)
class JournalRoot:
    root: Path


@dataclass(frozen=True, slots=True)
class JournalGenerations:
    requests: JournalRoot
    generation: Generation
    provider_instance_id: str = "provider:fixture"

    def exclusive(self) -> nullcontext[None]:
        return nullcontext()

    def active(self) -> Generation:
        return self.generation


def journal_only_generations(root: Path) -> JournalGenerations:
    """Isolate journal serialization; integration tests check the real target and locks."""
    value = CorrectionCancellationIntentV1.model_validate(intent())
    target = value.target
    manifest = GenerationManifestV1(
        schema_version=1, generation_id=target.generation_id,
        generation_digest=target.generation_manifest_digest,
        provider_instance_id=value.provider_instance_id, provider_release_sha="a" * 40,
        parent_generation_id=None, head=target.vault_head, tree=target.vault_tree,
        tombstone_sequence=0, tombstone_set_root=value.tombstone.previous_root,
        content_manifest_digest="", ledger_manifest_digest="", lexical_manifest_digest="",
        vector_manifest_digest="", briefing_manifest_digest="", file_count=0, byte_count=0,
        created_at=value.issued_at,
    )
    return JournalGenerations(JournalRoot(root), Generation(manifest, root))
