"""Release rehearsal must reject unrelated SQL before opening any database."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/operational-authority-upgrade-rehearsal.py"


@pytest.mark.parametrize("difference", ["changed", "missing", "extra"])
def test_mismatched_migrations_rejected_before_database_open(tmp_path, monkeypatch, difference):
    spec = importlib.util.spec_from_file_location("upgrade_rehearsal", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    build = tmp_path / "build"
    (build / "src").mkdir(parents=True)
    (build / "src/db.js").write_text("")
    packaged = build / "migrations"
    packaged.mkdir()
    (packaged / "001.sql").write_text("SELECT 1;")
    supplied = tmp_path / "supplied"
    supplied.mkdir()
    if difference != "missing":
        (supplied / "001.sql").write_text("SELECT 2;" if difference == "changed" else "SELECT 1;")
    if difference == "extra":
        (supplied / "002.sql").write_text("SELECT 2;")
    source = tmp_path / "database"
    source.write_bytes(b"not a database; must never be opened")

    def forbidden(_path):
        pytest.fail("database opened before migration artifact check")

    monkeypatch.setattr(module, "readonly", forbidden)
    monkeypatch.setattr(
        "sys.argv",
        [
            str(SCRIPT),
            "--source-db",
            str(source),
            "--jarvis-build",
            str(build),
            "--migrations",
            str(supplied),
        ],
    )
    with pytest.raises(ValueError, match="REHEARSAL_MIGRATIONS_DIFFER_FROM_BUILD"):
        module.main()
