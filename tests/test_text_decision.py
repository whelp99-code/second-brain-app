from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from sb.text_decision import (
    TextDecisionError,
    link_text_decision,
    load_quote_history,
    propose_confirmed,
    save_quote_history,
)

SOURCE = "합의: 김이 10월 9일까지 회사 견적을 보낸다. 담당 없는 메모는 보류."


def test_quote_must_be_exact_source_text_and_missing_fields_stay_unknown() -> None:
    recorded = link_text_decision(
        SOURCE,
        identity="meet-1",
        quote="담당 없는 메모는 보류.",
        owner=None,
        due="",
        scope=None,
        basis="quoted",
        action="record",
    )
    assert recorded.owner == "unknown"
    assert recorded.due == "unknown"
    assert recorded.scope == "unknown"
    assert recorded.quote == "담당 없는 메모는 보류."
    assert propose_confirmed(recorded) is None
    with pytest.raises(TextDecisionError, match="QUOTE_NOT_IN_SOURCE"):
        _ = link_text_decision(
            SOURCE,
            identity="meet-1",
            quote="김이 곧 견적을 보낸다",
            owner="김",
            due="2026-10-09",
            scope="company",
            basis="quoted",
            action="record",
        )


def test_personal_scope_is_not_rewritten_as_company() -> None:
    recorded = link_text_decision(
        SOURCE,
        identity="meet-personal",
        quote="담당 없는 메모는 보류.",
        owner="김",
        due="2026-10-09",
        scope="personal",
        basis="quoted",
        action="record",
    )
    assert recorded.scope == "personal"
    proposal = propose_confirmed(recorded)
    assert proposal is not None
    assert proposal.executed is False


def test_same_correction_is_replay_and_cancel_does_not_execute() -> None:
    recorded = link_text_decision(
        SOURCE,
        identity="meet-1",
        quote="김이 10월 9일까지 회사 견적을 보낸다.",
        owner="김",
        due="2026-10-09",
        scope="company",
        basis="quoted",
        action="record",
    )
    replay = link_text_decision(
        SOURCE,
        identity="meet-1",
        quote=recorded.quote,
        owner="김",
        due="2026-10-09",
        scope="company",
        basis="quoted",
        action="correct",
        prior=recorded,
    )
    assert replay is recorded
    corrected = link_text_decision(
        SOURCE,
        identity="meet-1",
        quote="담당 없는 메모는 보류.",
        owner="김",
        due="2026-10-09",
        scope="company",
        basis="quoted",
        action="correct",
        prior=recorded,
    )
    assert corrected.revision == 2
    assert corrected.prior_quote == recorded.quote
    proposal = propose_confirmed(corrected)
    assert proposal is not None
    assert proposal.executed is False
    cancelled = link_text_decision(
        SOURCE,
        identity="meet-1",
        quote=corrected.quote,
        owner="김",
        due="2026-10-09",
        scope="company",
        basis="quoted",
        action="cancel",
        prior=corrected,
    )
    again = link_text_decision(
        SOURCE,
        identity="meet-1",
        quote=corrected.quote,
        owner="김",
        due="2026-10-09",
        scope="company",
        basis="quoted",
        action="cancel",
        prior=cancelled,
    )
    assert again is cancelled
    assert propose_confirmed(cancelled) is None
    inferred = link_text_decision(
        SOURCE,
        identity="meet-2",
        quote="합의: 김이 10월 9일까지 회사 견적을 보낸다.",
        owner="김",
        due="2026-10-09",
        scope="company",
        basis="inferred",
        action="record",
    )
    assert propose_confirmed(inferred) is None


def test_malformed_history_json_is_text_decision_error(tmp_path: Path) -> None:
    path = tmp_path / "meet-bad.jsonl"
    _ = path.write_text("{not-json\n", encoding="utf-8")
    with pytest.raises(TextDecisionError, match="QUOTE_HISTORY_MALFORMED") as malformed:
        _ = load_quote_history(tmp_path, "meet-bad")
    assert not isinstance(malformed.value, json.JSONDecodeError)


@pytest.mark.parametrize(
    "missing_field",
    ("identity", "revision", "state", "quote", "owner", "due", "scope", "basis", "prior_quote"),
)
def test_missing_history_field_is_text_decision_error(
    tmp_path: Path,
    missing_field: str,
) -> None:
    row: dict[str, str | int | None] = {
        "identity": "meet-bad",
        "revision": 1,
        "state": "recorded",
        "quote": "exact source quote",
        "owner": "unknown",
        "due": "unknown",
        "scope": "unknown",
        "basis": "quoted",
        "prior_quote": None,
    }
    del row[missing_field]
    _ = (tmp_path / "meet-bad.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(TextDecisionError, match="QUOTE_HISTORY_MALFORMED") as error:
        _ = load_quote_history(tmp_path, "meet-bad")
    assert not isinstance(error.value.__cause__, KeyError)


def test_whitespace_metadata_stays_unknown(tmp_path: Path) -> None:
    recorded = link_text_decision(
        SOURCE,
        identity="meet-space",
        quote="담당 없는 메모는 보류.",
        owner="김",
        due="2026-10-09",
        scope="personal",
        basis="quoted",
        action="record",
    )
    save_quote_history(tmp_path, recorded)
    path = tmp_path / "meet-space.jsonl"
    row = TypeAdapter(dict[str, str | int | None]).validate_json(
        path.read_text(encoding="utf-8"),
        strict=True,
    )
    row["owner"] = "   "
    row["due"] = "\n"
    row["scope"] = " \t "
    _ = path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    loaded = load_quote_history(tmp_path, "meet-space")
    assert loaded.quote == recorded.quote
    assert loaded.scope == "unknown"
    assert loaded.owner == "unknown"
    assert loaded.due == "unknown"
    assert loaded.basis == "quoted"


def test_quote_history_reloads_same_fields_after_writer_dropped(tmp_path: Path) -> None:
    recorded = link_text_decision(
        SOURCE,
        identity="meet-1",
        quote="김이 10월 9일까지 회사 견적을 보낸다.",
        owner="김",
        due="2026-10-09",
        scope="company",
        basis="quoted",
        action="record",
    )
    corrected = link_text_decision(
        SOURCE,
        identity="meet-1",
        quote="담당 없는 메모는 보류.",
        owner="김",
        due="2026-10-09",
        scope="company",
        basis="quoted",
        action="correct",
        prior=recorded,
    )
    journal = tmp_path / "quote-history"
    save_quote_history(journal, recorded)
    save_quote_history(journal, corrected)
    del recorded, corrected
    loaded = load_quote_history(journal, "meet-1")
    assert loaded.identity == "meet-1"
    assert loaded.revision == 2
    assert loaded.quote == "담당 없는 메모는 보류."
    assert loaded.prior_quote == "김이 10월 9일까지 회사 견적을 보낸다."
    replay = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json, sys; from sb.text_decision import load_quote_history; "
                "row = load_quote_history(sys.argv[1], sys.argv[2]); "
                "json.dump({'identity': row.identity, 'revision': row.revision, "
                "'quote': row.quote, 'prior_quote': row.prior_quote}, sys.stdout)"
            ),
            str(journal),
            "meet-1",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    reloaded = TypeAdapter(dict[str, str | int]).validate_json(replay.stdout, strict=True)
    assert reloaded == {
        "identity": loaded.identity,
        "revision": loaded.revision,
        "quote": loaded.quote,
        "prior_quote": loaded.prior_quote,
    }
