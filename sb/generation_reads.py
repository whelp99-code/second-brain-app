"""Closed schema-4 generation bindings shared by every provider read."""

from __future__ import annotations

from dataclasses import dataclass

from sb.effect_values import JsonObject
from sb.targets import GenerationIdentityV1


@dataclass(frozen=True, slots=True)
class GenerationReadBindingV1:
    provider_instance_id: str
    generation_id: str
    generation_manifest_digest: str
    vault_head: str
    vault_tree: str
    tombstone_sequence: int
    tombstone_set_root: str

    def as_dict(self) -> JsonObject:
        return {
            "provider_instance_id": self.provider_instance_id,
            "generation_id": self.generation_id,
            "generation_manifest_digest": self.generation_manifest_digest,
            "vault_head": self.vault_head,
            "vault_tree": self.vault_tree,
            "tombstone_sequence": self.tombstone_sequence,
            "tombstone_set_root": self.tombstone_set_root,
        }


def generation_read_binding(
    generation: GenerationIdentityV1,
    current: tuple[int, str],
) -> GenerationReadBindingV1:
    """Bind one read to one generation and one tombstone high-water tuple."""
    sequence, set_root = current
    return GenerationReadBindingV1(
        provider_instance_id=generation.provider_instance_id,
        generation_id=generation.generation_id,
        generation_manifest_digest=generation.generation_manifest_digest,
        vault_head=generation.vault_head,
        vault_tree=generation.vault_tree,
        tombstone_sequence=sequence,
        tombstone_set_root=set_root,
    )
