"""Briefing date isolation, classified omission, and metadata dates. No sleep."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from sb.briefing import OMISSION_DENIED, OMISSION_EMPTY, generate_briefing
from sb.config import Config
from sb.contracts import BriefingInputs
from sb.pipeline import collect_briefing_inputs
from sb.store import SourceItem
from sb.store.cas import ContentAddressedStore
from sb.store.ledger import Ledger
from sb.vault import init_vault

TODAY = date(2026, 9, 28)
SECRET = "DENIED_SECRET_MUST_NOT_EGRESS"
DENIED = f"origin=blocked:note.md hash={'ab' * 32} [^abcdefab] text={SECRET}"


class RecordingLLM:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, prompt: str, *, system: str | None = None, json_mode: bool = False, timeout: int = 120) -> str:
        del system, json_mode, timeout
        self.prompts.append(prompt)
        return "없음"


def test_feb30_leap_offset_dates_isolate_invalid_input_not_batch(tmp_path: Path) -> None:
    body = (
        "valid 2026-09-30\n"
        "impossible 2026-02-30\n"
        "non-leap 2025-02-29\n"
        "leap-ok-but-outside-window 2024-02-29\n"
        "broken-offset 2026-09-30T00:00:00+99:99\n"
        "offset-civil 2026-10-01T01:00:00+09:00\n"
    )
    root = tmp_path / "vault"
    init_vault(root)
    digest = ContentAddressedStore(root).put(body.encode())
    from sb.store import Run

    with Ledger(root) as ledger:
        ledger.record_run(Run("run-brief", "2026-09-28T12:00:00+00:00", None, None, "ok"))
        ledger.upsert_source_item(SourceItem("notes", "note.md", "v1", digest, "run-brief", "run-brief"))
        inputs = collect_briefing_inputs(ledger, root, today=TODAY)
    joined = "\n".join(inputs.upcoming_items)
    assert "2026-09-30" in joined
    assert "2026-10-01" in joined
    assert "2026-02-30" not in joined
    assert "2025-02-29" not in joined
    assert "2024-02-29" not in joined
    assert "+99:99" not in joined


def test_empty_and_denied_sources_yield_classified_omission_and_zero_egress() -> None:
    empty_llm = RecordingLLM()
    empty = generate_briefing(BriefingInputs((), (), (), (), None, "ok"), empty_llm, Config())
    assert OMISSION_EMPTY in empty.body_md
    assert empty.sources == []
    assert empty_llm.prompts
    assert SECRET not in "\n".join(empty_llm.prompts)
    assert all("origin=" not in prompt for prompt in empty_llm.prompts)

    denied_llm = RecordingLLM()
    config = Config(raw={"sources": [{"id": "blocked", "llm_policy": "deny"}]})
    denied = generate_briefing(
        BriefingInputs((DENIED,), (), (), (), None, "ok"),
        denied_llm,
        config,
    )
    assert OMISSION_DENIED in denied.body_md
    assert denied.sources == []
    sent = "\n".join(denied_llm.prompts)
    assert SECRET not in sent
    assert "blocked:note.md" not in sent


def test_page_metadata_date_vs_arbitrary_body_date(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    init_vault(root)
    digest = ContentAddressedStore(root).put(b"source line without a date\n")
    page = root / "wiki" / "old.md"
    page.write_text(
        "\n".join((
            "---",
            "id: wiki/old",
            "title: old",
            "updated: 2020-01-01",
            "compiled_by: sb/1.0.0|v1|fake",
            "status: active",
            "sources:",
            f"  - sid: {digest[:8]}",
            "    origin: notes:note.md",
            f"    hash: {digest}",
            "---",
            "",
            "updated: 2026-09-28",
            "body date 2026-09-30 is not metadata",
            "",
        )),
        encoding="utf-8",
    )
    from sb.store import Run

    with Ledger(root) as ledger:
        ledger.record_run(Run("run-brief", "2026-09-28T12:00:00+00:00", None, None, "ok"))
        ledger.upsert_source_item(SourceItem("notes", "note.md", "v2", "ff" * 32, "run-brief", "run-brief"))
        ledger.upsert_source_item(SourceItem("notes", "note.md", "v1", digest, "run-brief", "run-brief"))
        ContentAddressedStore(root).put(b"ff")
        inputs = collect_briefing_inputs(ledger, root, today=TODAY)
    stale = "\n".join(inputs.stale_pages)
    upcoming = "\n".join(inputs.upcoming_items)
    assert "wiki/old" in stale or "old" in stale
    assert "2026-09-30" not in upcoming
    assert "2026-09-28" not in upcoming
