"""H6: historical failed brief rows close as superseded when a later brief succeeded."""
from __future__ import annotations

from datetime import datetime, tzinfo
from pathlib import Path
from typing import cast, override

import pytest

from sb.config import Config
from sb.ops import OperationError, retry_failed, status_snapshot
from sb.store import DerivStatus, deriv_key
from sb.store.ledger import DerivationOutput, Ledger

_PROMPT = "p"
_MODEL = "m"


def _mark_failed_at(ledger: Ledger, key: str, stamp: str) -> None:
    instant = datetime.fromisoformat(stamp)

    class Clock(datetime):
        @classmethod
        @override
        def now(cls, tz: tzinfo | None = None) -> datetime:
            del tz
            return instant

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("sb.store.ledger.datetime", Clock)
        ledger.mark_failed(key, "unresolved citations")


def test_failed_brief_stays_failed_without_later_success(tmp_path: Path) -> None:
    failed_key = deriv_key(("note-a",), "brief", _PROMPT, _MODEL)
    with Ledger(tmp_path) as ledger:
        ledger.ensure_derivation(failed_key, "brief", "run-old")
        ledger.mark_running(failed_key, "run-old")
        ledger.mark_failed(failed_key, "unresolved citations")
        closed = ledger.supersede_historical_brief_failures()
        row = ledger.get_derivation(failed_key)
    assert closed == 0
    assert row is not None
    assert row.status == DerivStatus.FAILED.value
    assert row.error == "unresolved citations"


def test_failed_brief_superseded_when_later_brief_is_done(tmp_path: Path) -> None:
    failed_key = deriv_key(("note-a",), "brief", _PROMPT, _MODEL)
    done_key = deriv_key(("note-b",), "brief", _PROMPT, _MODEL)
    with Ledger(tmp_path) as ledger:
        ledger.ensure_derivation(failed_key, "brief", "run-old")
        ledger.mark_running(failed_key, "run-old")
        _mark_failed_at(ledger, failed_key, "2026-09-05T00:00:00.000Z")
        ledger.ensure_derivation(done_key, "brief", "run-new")
        ledger.mark_running(done_key, "run-new")
        ledger.mark_done(done_key, DerivationOutput(output_hash="out", output_path="daily/2026-09-15.md"))
        closed = ledger.supersede_historical_brief_failures()
        failed = ledger.get_derivation(failed_key)
        done = ledger.get_derivation(done_key)
    assert closed == 1
    assert failed is not None
    assert failed.status == DerivStatus.SUPERSEDED.value
    assert failed.error == "unresolved citations"
    assert done is not None
    assert done.status == DerivStatus.DONE.value


def test_prior_done_does_not_supersede_later_failure(tmp_path: Path) -> None:
    done_key = deriv_key(("note-b",), "brief", _PROMPT, _MODEL)
    failed_key = deriv_key(("note-a",), "brief", _PROMPT, _MODEL)
    with Ledger(tmp_path) as ledger:
        ledger.ensure_derivation(done_key, "brief", "run-old")
        ledger.mark_running(done_key, "run-old")
        ledger.mark_done(done_key, DerivationOutput(output_hash="out", output_path="daily/2026-09-15.md"))
        ledger.ensure_derivation(failed_key, "brief", "run-new")
        ledger.mark_running(failed_key, "run-new")
        ledger.mark_failed(failed_key, "unresolved citations")
        closed = ledger.supersede_historical_brief_failures()
        failed = ledger.get_derivation(failed_key)
    assert closed == 0
    assert failed is not None
    assert failed.status == DerivStatus.FAILED.value


def test_llm_unavailable_failure_is_not_superseded(tmp_path: Path) -> None:
    failed_key = deriv_key(("note-a",), "brief", _PROMPT, _MODEL)
    done_key = deriv_key(("note-b",), "brief", _PROMPT, _MODEL)
    with Ledger(tmp_path) as ledger:
        ledger.ensure_derivation(failed_key, "brief", "run-old")
        ledger.mark_running(failed_key, "run-old")
        ledger.mark_failed(failed_key, "LLM unavailable after 1 attempts: Codex")
        ledger.ensure_derivation(done_key, "brief", "run-new")
        ledger.mark_running(done_key, "run-new")
        ledger.mark_done(done_key, DerivationOutput(output_hash="out", output_path="daily/2026-09-15.md"))
        closed = ledger.supersede_historical_brief_failures()
        failed = ledger.get_derivation(failed_key)
    assert closed == 0
    assert failed is not None
    assert failed.status == DerivStatus.FAILED.value


def test_superseded_brief_reopens_to_pending(tmp_path: Path) -> None:
    failed_key = deriv_key(("note-a",), "brief", _PROMPT, _MODEL)
    done_key = deriv_key(("note-b",), "brief", _PROMPT, _MODEL)
    with Ledger(tmp_path) as ledger:
        ledger.ensure_derivation(failed_key, "brief", "run-old")
        ledger.mark_running(failed_key, "run-old")
        _mark_failed_at(ledger, failed_key, "2026-09-05T00:00:00.000Z")
        ledger.ensure_derivation(done_key, "brief", "run-new")
        ledger.mark_running(done_key, "run-new")
        ledger.mark_done(done_key, DerivationOutput(output_hash="out", output_path="daily/2026-09-15.md"))
        _ = ledger.supersede_historical_brief_failures()
        assert ledger.requeue_failed(failed_key) is True
        ledger.mark_running(failed_key, "run-retry")
        row = ledger.get_derivation(failed_key)
    assert row is not None
    assert row.status == DerivStatus.RUNNING.value


def test_retry_failed_still_refuses_remaining_brief_failures(tmp_path: Path) -> None:
    failed_key = deriv_key(("note-a",), "brief", _PROMPT, _MODEL)
    with Ledger(tmp_path) as ledger:
        ledger.ensure_derivation(failed_key, "brief", "run-old")
        ledger.mark_running(failed_key, "run-old")
        ledger.mark_failed(failed_key, "unresolved citations")
    with pytest.raises(OperationError, match="BRIEF_REPLAY_INPUTS_UNAVAILABLE"):
        _ = retry_failed(tmp_path)


def test_status_snapshot_omits_superseded_from_failed_list(tmp_path: Path) -> None:
    failed_key = deriv_key(("note-a",), "brief", _PROMPT, _MODEL)
    done_key = deriv_key(("note-b",), "brief", _PROMPT, _MODEL)
    with Ledger(tmp_path) as ledger:
        ledger.ensure_derivation(failed_key, "brief", "run-old")
        ledger.mark_running(failed_key, "run-old")
        _mark_failed_at(ledger, failed_key, "2026-09-05T00:00:00.000Z")
        ledger.ensure_derivation(done_key, "brief", "run-new")
        ledger.mark_running(done_key, "run-new")
        ledger.mark_done(done_key, DerivationOutput(output_hash="out", output_path="daily/2026-09-15.md"))
        _ = ledger.supersede_historical_brief_failures()
    snapshot = status_snapshot(Config(raw={"vault_root": str(tmp_path)}))
    failed_items = cast(list[object], snapshot["failed_derivations"])
    counts = cast(dict[str, int], snapshot["derivation_counts"])
    assert failed_items == []
    assert counts[DerivStatus.SUPERSEDED.value] == 1
    assert counts[DerivStatus.FAILED.value] == 0
