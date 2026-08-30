"""Deterministic provider contract, idempotency, tombstone, and saga tests."""

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from sb.compile import compile_terminal_work_summary
from sb.contracts import TerminalWorkSummaryV1
from sb.search import SearchIndex
from sb.vault import init_vault
from sb.write_requests import RequestInbox, WriteOperation, WriteRequestError, WriteRequestV1


def _digest(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode()).hexdigest()}"


def _summary(candidate: str = "mem_1") -> TerminalWorkSummaryV1:
    return TerminalWorkSummaryV1(
        memory_candidate_id=candidate,
        jarvis_closeout_id="close_1",
        jarvis_receipt_digest=_digest("receipt"),
        project_id="second-brain-app",
        host_scope=("jm-cloud",),
        terminal_count=1,
        started_at="2026-08-29T10:00:00Z",
        finished_at="2026-08-29T10:01:00Z",
        outcome="success",
        verified=True,
        purpose="verify provider",
        work_performed=("implemented provider",),
        verified_results=("tests pass",),
        source_refs=("evidence-1",),
    )


def _request(
    summary: TerminalWorkSummaryV1,
    *,
    operation: str = "remember",
    key: str = "key-1",
    prior: str | None = None,
) -> WriteRequestV1:
    return WriteRequestV1(
        operation=cast(WriteOperation, operation),
        candidate_id=summary.memory_candidate_id,
        closeout_id=summary.jarvis_closeout_id,
        receipt_digest=summary.jarvis_receipt_digest,
        purpose=summary.purpose,
        sensitivity="normal",
        retention="durable",
        expected_prior_digest=prior,
        idempotency_key=key,
        summary=summary if operation != "forget" else None,
    )


def test_summary_roundtrip_and_cited_compile() -> None:
    summary = _summary()
    restored = TerminalWorkSummaryV1.from_mapping(summary.as_dict())
    page = compile_terminal_work_summary(restored)
    assert restored == summary
    assert page.page_id == "terminal-work/mem_1"
    assert "verify provider" in page.body_md


def test_inbox_idempotency_and_collision_are_fail_closed(tmp_path: Path) -> None:
    inbox = RequestInbox(tmp_path)
    first = inbox.submit(_request(_summary()))
    replay = inbox.submit(_request(_summary()))
    assert replay.request_id == first.request_id
    assert replay.idempotent_replay is True
    with pytest.raises(WriteRequestError, match="key-1"):
        _ = inbox.submit(_request(_summary("mem_2")))


def test_approved_summary_forget_hides_search_and_restore_is_safe(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    _ = init_vault(root)
    inbox = RequestInbox(root)
    applied = inbox.submit(_request(_summary()))
    result = inbox.process(applied.request_id)
    assert result.status == "applied"
    assert result.artifact_digest is not None
    settled = inbox.observe_artifact(applied.request_id, digest=result.artifact_digest)
    assert settled.status == "settled"
    assert [item["status"] for item in inbox.history(applied.request_id)] == [
        "accepted",
        "applied",
        "settled",
    ]
    assert SearchIndex(root).search("verify provider", 10)

    forgotten = inbox.submit(
        _request(_summary(), operation="forget", key="forget-1", prior=result.artifact_digest)
    )
    forgotten_result = inbox.process(forgotten.request_id)
    assert forgotten_result.status == "forgotten"
    assert not SearchIndex(root).search("verify provider", 10)
    assert inbox.restore(forgotten.request_id).status == "restored"
    assert SearchIndex(root).search("verify provider", 10)


def test_expected_prior_digest_prevents_uncertain_correction(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    _ = init_vault(root)
    inbox = RequestInbox(root)
    accepted = inbox.submit(_request(_summary()))
    applied = inbox.process(accepted.request_id)
    correction = inbox.submit(
        _request(_summary(), operation="correct", key="correct-1", prior=_digest("wrong"))
    )
    with pytest.raises(WriteRequestError) as error:
        _ = inbox.process(correction.request_id)
    assert error.value.code == "prior_digest_mismatch"
    record = inbox.get(correction.request_id)
    assert record is not None and record.status == "error"
    assert applied.artifact_digest is not None


def test_export_is_bounded_and_excludes_forgotten_by_default(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    _ = init_vault(root)
    inbox = RequestInbox(root)
    accepted = inbox.submit(_request(_summary()))
    _ = inbox.process(accepted.request_id)
    exported = inbox.export()
    assert exported["schema"] == "second-brain-write-history-export-v1"
    records = exported["records"]
    assert isinstance(records, list) and len(cast(list[object], records)) == 1
    assert str(exported["digest"]).startswith("sha256:")

def test_summary_redaction_and_mismatched_observation_never_settle(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    _ = init_vault(root)
    inbox = RequestInbox(root)
    secret = "Bearer abcdefghijklmnop"
    summary = replace(_summary(), work_performed=(secret,))
    accepted = inbox.submit(_request(summary, key="redaction-1"))
    applied = inbox.process(accepted.request_id)
    page = root / "wiki" / "terminal-work" / "mem_1.md"
    assert secret not in page.read_text(encoding="utf-8")
    assert applied.artifact_digest is not None
    wrong = _digest("not-the-artifact")
    assert inbox.observe_artifact(accepted.request_id, digest=wrong).status == "reconciling"
