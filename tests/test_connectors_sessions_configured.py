"""Configured [[sources]] rows collect Claude, Codex, and OMO session fixtures.

discovery.py is unchanged: its SourceName allowlist is a metadata-only
filesystem inventory, not the ingest adapter registry. Session adapters are
selected from [[sources]] adapter values via discover_adapters().
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from sb.config import load_config
from sb.connectors import discover_adapters
from sb.connectors.base import ItemMeta
from sb.connectors.sessions_claude import ADAPTER_ID as CLAUDE_ID
from sb.connectors.sessions_codex import ADAPTER_ID as CODEX_ID
from sb.connectors.sessions_omo import ADAPTER_ID as OMO_ID
from sb.contracts import SourceRef
from sb.pipeline import _select_adapters

EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.toml"
FIXTURES = Path(__file__).parent / "fixtures" / "second-brain"
FAMILIES: tuple[tuple[str, str, str, str], ...] = (
    ("claude", CLAUDE_ID, "claude", "golden.jsonl"),
    ("codex", CODEX_ID, "codex", "golden.jsonl"),
    ("omo", OMO_ID, "omo", "current.jsonl"),
)


def _delivered(items: Sequence[tuple[SourceRef, bytes, ItemMeta]]) -> list[bytes]:
    return [body for _ref, body, meta in items if "skip_reason" not in meta]


def test_example_config_documents_session_source_adapters() -> None:
    # Given: the checked-in example configuration operators copy.
    text = EXAMPLE.read_text(encoding="utf-8")

    # Then: each session family is named as a [[sources]] adapter.
    for _source_id, adapter_id, _family, _fixture in FAMILIES:
        assert f'adapter = "{adapter_id}"' in text


@pytest.mark.parametrize(("source_id", "adapter_id", "family", "fixture"), FAMILIES)
def test_configured_session_source_collects_fixture_and_resumes(
    tmp_path: Path, source_id: str, adapter_id: str, family: str, fixture: str
) -> None:
    # Given: a config.toml [[sources]] row using the example adapter id and a fixture root.
    root = tmp_path / family
    dest = root / fixture
    dest.parent.mkdir(parents=True, exist_ok=True)
    _ = dest.write_bytes((FIXTURES / family / fixture).read_bytes())
    settings = tmp_path / "config.toml"
    _ = settings.write_text(
        "\n".join(
            [
                f'vault_root = "{tmp_path / "vault"}"',
                "[[sources]]",
                f'id = "{source_id}"',
                f'adapter = "{adapter_id}"',
                f'root = "{root}"',
                'llm_policy = "deny"',
                'sensitive = "mask"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    config = load_config(settings)

    # When: the pipeline selects that configured source and scans from the start.
    selected = _select_adapters(discover_adapters(config), None, config)
    assert len(selected) == 1
    adapter = selected[0]
    items = list(adapter.scan(None))
    cursor = adapter.next_cursor()

    # Then: the family fixture is collected, and an unchanged resume yields nothing.
    assert adapter.source_id == source_id
    blob = b"\n".join(_delivered(items))
    assert b"VISIBLE_USER_1" in blob
    assert b"VISIBLE_ASSISTANT_1" in blob
    assert all(ref.source_id == source_id for ref, _body, _meta in items)
    resume = list(adapter.scan(cursor))
    assert resume == []
    assert adapter.next_cursor() == cursor
