from __future__ import annotations

from pathlib import Path

import pytest

from sb.config import Config
from sb.pipeline import run_ingest
from sb.store.ledger import Ledger


@pytest.mark.parametrize("selection", [("missing",), ("docs", "missing")])
def test_unresolved_selection_fails_before_any_source_is_collected(tmp_path: Path, selection: tuple[str, ...]):
    source = tmp_path / "source"
    source.mkdir()
    _ = (source / "note.md").write_text("Must not be partially collected.")
    config = Config(raw={"vault_root": str(tmp_path / "vault"), "state_root": str(tmp_path / "state"),
        "sources": [{"id": "docs", "adapter": "markdown-vault", "root": str(source)}]})
    outcome = run_ingest(config, selection)
    assert outcome.exit_code != 0
    assert outcome.failure == "SOURCE_NOT_FOUND: missing"
    with Ledger(tmp_path / "vault") as ledger:
        assert ledger.list_source_items() == ()
        assert ledger.get_cursor("docs") is None
