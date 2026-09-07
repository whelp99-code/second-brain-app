"""A proved correction must expose every approved replacement statement."""

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.effect_write_models import MemoryEffectWriteRequestV2
from sb.effect_write_requests import accept_effect_request
from sb.erasure import ErasureEngine, ErasureError, ReingressGate
from sb.mcp_contract import write_fixture_request
from sb.memory_records import records_for_page
from sb.pipeline import audit_citations
from sb.request_executor import RequestExecutor
from sb.stable_requests import accept_stable_v1_request
from sb.targets import GenerationIdentityV1
from tests.task30_effect_factory import effect_request
from tests.task30_process_harness import NOW, executor_config


@pytest.mark.parametrize("content", [
    "정정 첫째\n반복 기억\n반복 기억\n사용자 [^deadbeef] 기록",
    "정정 첫째\n  반복 기억  \r\n반복 기억\n사용자 [^deadbeef] 기록",
    "정정 첫째\n\n  반복 기억  \r\n \r\n반복 기억\n사용자 [^deadbeef] 기록",
])
def test_proved_correction_preserves_all_cited_records(tmp_path: Path, content: str) -> None:
    config = executor_config(tmp_path)
    _ = accept_stable_v1_request(config.request_root, write_fixture_request(), NOW)
    executor = RequestExecutor(config)
    try:
        assert executor.apply_once(now=NOW).state == "proved"
        request = effect_request(executor.generations.active(), "correct", "ExampleAlpha 예시기록",
                                 NOW, executor.store.tombstone_high_water(),
                                 Ed25519PrivateKey.from_private_bytes(bytes(range(32))), "8",
                                 correction_content=content)
        _ = accept_effect_request(config.request_root, request, NOW,
                                  public_keys=config.jarvis_public_keys,
                                  provider_instance_id=config.provider_instance_id)
        result = executor.apply_once(now=NOW)
        generation = executor.generations.active()
        page = next((generation.root / "wiki").glob("*.md"))
        assert result.state == "proved", (result, page.read_bytes())
        identity = GenerationIdentityV1(config.provider_instance_id, generation.generation_id,
                                        generation.manifest.generation_digest,
                                        generation.head, generation.tree)
        records = records_for_page(generation.root, page.relative_to(generation.root).with_suffix("").as_posix(), identity)
        assert [row.record_text for row in records] == [
            line.strip() for line in content.replace("[^", "\\[\\^").splitlines() if line.strip()
        ]
        assert len({row.record_id for row in records}) == 4
        assert audit_citations(generation.root) == ()
        assert b"ExampleAlpha" not in page.read_bytes()
    finally:
        executor.close()


@pytest.mark.parametrize("content", ["\n".join(["new statement"] * 65), "[^" * 1025])
def test_oversize_correction_does_not_replace_target_bytes(tmp_path: Path, content: str) -> None:
    config = executor_config(tmp_path)
    _ = accept_stable_v1_request(config.request_root, write_fixture_request(), NOW)
    executor = RequestExecutor(config)
    try:
        assert executor.apply_once(now=NOW).state == "proved"
        generation = executor.generations.active()
        page = next((generation.root / "wiki").glob("*.md"))
        original = page.read_bytes()
        request = effect_request(generation, "correct", "ExampleAlpha 예시기록", NOW,
                                 executor.store.tombstone_high_water(),
                                 Ed25519PrivateKey.from_private_bytes(bytes(range(32))), "8",
                                 correction_content=content)
        # The parser checks prospective bytes before any write, even on a sealed page.
        gate = ReingressGate(tmp_path / "preflight.db")
        try:
            with pytest.raises(ErasureError, match="CORRECTION_RECORDS_INVALID"):
                _ = ErasureEngine(gate).apply(generation.root,
                                             MemoryEffectWriteRequestV2.model_validate(request), NOW)
        finally:
            gate.close()
        assert page.read_bytes() == original
    finally:
        executor.close()
