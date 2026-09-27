"""Release rehearsal must reject unrelated SQL before opening any database."""

import importlib.util
from pathlib import Path
from typing import Protocol, runtime_checkable

import pytest

from sb.effect_values import JsonObject


@runtime_checkable
class RehearsalModule(Protocol):
    def main(self) -> None: ...
    def database_health(self, path: Path) -> JsonObject: ...


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/operational-authority-upgrade-rehearsal.py"


@pytest.mark.parametrize("difference", ["changed", "missing", "extra"])
def test_mismatched_migrations_rejected_before_database_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, difference: str):
    spec = importlib.util.spec_from_file_location("upgrade_rehearsal", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    build = tmp_path / "build"
    (build / "src").mkdir(parents=True)
    _ = (build / "src/db.js").write_text("")
    packaged = build / "migrations"
    packaged.mkdir()
    _ = (packaged / "001.sql").write_text("SELECT 1;")
    supplied = tmp_path / "supplied"
    supplied.mkdir()
    if difference != "missing":
        _ = (supplied / "001.sql").write_text("SELECT 2;" if difference == "changed" else "SELECT 1;")
    if difference == "extra":
        _ = (supplied / "002.sql").write_text("SELECT 2;")
    source = tmp_path / "database"
    _ = source.write_bytes(b"not a database; must never be opened")

    def forbidden(_path: Path):
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
        assert isinstance(module, RehearsalModule)
        module.main()


@pytest.mark.parametrize('orphan', [False, True])
def test_restored_health_checks_foreign_keys_even_when_database_opens(tmp_path: Path, orphan: bool):
    import sqlite3

    spec = importlib.util.spec_from_file_location("upgrade_rehearsal", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert isinstance(module, RehearsalModule)
    path = tmp_path / 'restored.sqlite'
    with sqlite3.connect(path) as connection:
        _ = connection.execute('CREATE TABLE parent(id INTEGER PRIMARY KEY)')
        _ = connection.execute('CREATE TABLE child(parent_id INTEGER REFERENCES parent(id))')
        if not orphan:
            _ = connection.execute('INSERT INTO parent VALUES(1)')
        _ = connection.execute('INSERT INTO child VALUES(1)')
    result = module.database_health(path)
    assert result == {'integrity_ok': True, 'foreign_key_errors': int(orphan)}
