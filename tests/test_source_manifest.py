"""Opt-in root inventory and connector hardening acceptance."""

from __future__ import annotations

import json
import os
import tomllib
from hashlib import sha256
from pathlib import Path

import pytest

from sb.config import Config
from sb.connectors import discover_adapters
from sb.connectors.discovery import (
    SOURCE_DISCOVERY_REQUEST_V1,
    SourceDiscoveryRequestV1,
    discover_source,
)
from sb.connectors.markdown_vault import create as markdown
from sb.connectors.records_orca import OrcaRecordsAdapter
from sb.connectors.records_project import ProjectRecordsAdapter
from sb.connectors.sessions_claude import ClaudeSessionsAdapter
from sb.connectors.sessions_codex import CodexSessionsAdapter
from sb.connectors.sessions_gjc import GjcSessionsAdapter
from sb.connectors.sessions_omo import OmoSessionsAdapter
from sb.connectors.sessions_opencode import OpenCodeSessionsAdapter
from sb.connectors.source_manifest import installer_source_config, inventory, source_id
from sb.pipeline import _select_adapters
from tests.test_session_file_replacement import record

FACTORIES = {
    "claude": ClaudeSessionsAdapter,
    "codex": CodexSessionsAdapter,
    "omo": OmoSessionsAdapter,
    "gjc": GjcSessionsAdapter,
    "opencode": OpenCodeSessionsAdapter,
}


def _visible(adapter, cursor=None):
    return [(ref, body, meta) for ref, body, meta in adapter.scan(cursor) if not meta.get("skip_reason")]


def _row(kind: str, text: str) -> bytes:
    if kind == "opencode":
        return json.dumps({"parts": [{"id": "one", "data": {"type": "text", "text": text}}]}).encode()
    return record(kind, text)


def _place(root: Path, kind: str, text: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / ("snapshot.json" if kind == "opencode" else "session.jsonl")
    path.write_bytes(_row(kind, text))
    return path


def test_absent_root_yields_unavailable_skip_not_absent_root_success(tmp_path: Path) -> None:
    candidates = (("gjc", "gjc-sessions", str(tmp_path / "missing"), "ai-session"),)
    (entry,) = inventory(candidates)
    assert entry.state == "unavailable"
    assert installer_source_config((entry,)) == ""
    with pytest.raises(ValueError, match="unavailable"):
        entry.config_row()
    adapter = GjcSessionsAdapter((), "gjc")
    # Selection of an absent configured path is a typed skip, not a successful scan.
    assert [meta["skip_reason"] for _, _, meta in adapter.scan(None)] == ["absent-root"]


def test_two_roots_two_source_rows_two_identities_no_legacy_cursor_merge(tmp_path: Path) -> None:
    roots = (tmp_path / "a", tmp_path / "b")
    for root in roots:
        _place(root, "omo", "same")
    candidates = tuple(("omo", "omo-sessions", str(root), "ai-session") for root in roots)
    rows = inventory(candidates)
    assert len({row.source_id for row in rows}) == 2
    config_rows = [row.config_row() for row in rows]
    cfg = Config(raw={"sources": config_rows}, base_dir=tmp_path)
    adapters = _select_adapters(discover_adapters(cfg), None, cfg)
    assert len(adapters) == 2
    assert {ref.source_id for adapter in adapters for ref, _, _ in _visible(adapter)} == {
        row.source_id for row in rows
    }
    assert all(_visible(adapter, "0") for adapter in adapters)
    assert all(_visible(adapter, adapter.next_cursor()) == [] for adapter in adapters)


def _example_source_templates(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for block in text.split("# [[sources]]\n")[1:]:
        lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("# ") and " = " in line:
                lines.append(line[2:])
            elif lines:
                break
        parsed = tomllib.loads("\n".join(lines))
        rows.append({key: value for key, value in parsed.items() if isinstance(value, str)})
    return rows


def test_installer_generator_output_differs_from_example_config_only_by_roots(tmp_path: Path) -> None:
    example = (Path(__file__).parents[1] / "config.example.toml").read_text()
    selected = [
        row for row in _example_source_templates(example)
        if row["id"] in {
            "claude", "codex", "omo", "gjc", "opencode", "hermes", "dev-wiki", "project", "orca",
        }
    ]
    assert len(selected) == 9
    roots = {row["id"]: tmp_path / row["id"] for row in selected}
    for root in roots.values():
        root.mkdir()
    candidates = tuple(
        (row["id"], row["adapter"], str(roots[row["id"]]), row["scope"]) for row in selected
    )
    installed = tomllib.loads(installer_source_config(inventory(candidates)))["sources"]
    assert len(installed) == len(selected)
    for row in installed:
        family = next(name for name, path in roots.items() if str(path) == row["root"])
        template = next(item for item in selected if item["id"] == family)
        assert set(row) == set(template)
        for key, value in row.items():
            if key in {"id", "root"}:
                assert value != template[key]
            else:
                assert value == template[key]
        assert row["id"] == source_id(family, roots[family])
        assert row["root"] == str(roots[family])


@pytest.mark.parametrize("kind", tuple(FACTORIES))
def test_credential_and_probe_noise_lines_filtered_per_family(tmp_path: Path, kind: str) -> None:
    root = tmp_path / kind
    _place(root, kind, "api_key=do-not-ingest")
    adapter = FACTORIES[kind]((root,), kind, filter_noise=True)
    assert _visible(adapter) == []
    _place(root, kind, "$ curl -I https://probe.example")
    assert _visible(adapter, adapter.next_cursor()) == []
    _place(root, kind, "Decision: retain evidence")
    assert [body for _, body, _ in _visible(adapter, adapter.next_cursor())] == [
        b"Decision: retain evidence"
    ]
    _place(root, kind, "Decision: keep the secret plan")
    assert [body for _, body, _ in _visible(adapter, adapter.next_cursor())] == [
        b"Decision: keep the secret plan"
    ]


@pytest.mark.parametrize("kind", tuple(FACTORIES))
@pytest.mark.parametrize("tag", ("decision", "attempt", "test", "commit", "deploy"))
def test_fact_kind_tag_decision_attempt_test_commit_deploy(tmp_path: Path, kind: str, tag: str) -> None:
    root = tmp_path / kind
    _place(root, kind, f"{tag.title()}: evidence")
    assert [meta['fact_kind'] for _, _, meta in _visible(FACTORIES[kind]((root,), kind, filter_noise=True))] == [tag]


@pytest.mark.parametrize("kind", tuple(FACTORIES))
def test_incremental_rerun_rotation_preserves_observation_set(tmp_path: Path, kind: str) -> None:
    root = tmp_path / kind
    path = _place(root, kind, "old")
    adapter = FACTORIES[kind]((root,), kind, filter_noise=True)
    first = _visible(adapter)
    assert [body for _, body, _ in first] == [b"old"]
    cursor = adapter.next_cursor()
    assert _visible(adapter, cursor) == []
    if kind == "opencode":
        path.write_text(json.dumps({"parts": [
            {"id": "one", "data": {"type": "text", "text": "old"}},
            {"id": "two", "data": {"type": "text", "text": "next"}},
        ]}))
    else:
        with path.open("ab") as output:
            addition = _row(kind, "next")
            output.write(addition.split(b"\n", 1)[1] if kind == "gjc" else addition)
    appended = _visible(adapter, cursor)
    expected = [b"old", b"next"] if kind == "opencode" else [b"next"]
    assert [body for _, body, _ in appended] == expected
    cursor = adapter.next_cursor()
    assert _visible(adapter, cursor) == []
    # A same-path rotation changes the prefix even when its length is unchanged.
    replacement = path.with_suffix(".replacement")
    replacement.write_bytes(_row(kind, "new"))
    replacement.replace(path)
    rotated = _visible(adapter, cursor)
    assert [body for _, body, _ in rotated] == [b"new"]
    fresh = FACTORIES[kind]((root,), kind, filter_noise=True)
    assert [body for _, body, _ in _visible(fresh)] == [body for _, body, _ in rotated]
    assert _visible(adapter, adapter.next_cursor()) == []


def test_markdown_allowlist_excludes_config_plugins_skills(tmp_path: Path) -> None:
    root = tmp_path / "hermes"
    for name in ("memory.md", "memory/day.md", "config/settings.md", "plugins/a.md", "skills/a.md"):
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("# same bytes\n")
    cfg = Config(raw={"sources": [{"id": "hermes", "adapter": "markdown-vault",
                                    "root": str(root), "include": "memory/**/*.md,memory.md"}]}, base_dir=tmp_path)
    adapter = markdown(cfg)
    assert [ref.source_uri for ref, _, meta in adapter.scan(None) if not meta.get("skip_reason")] == [
        "memory.md", "memory/day.md"
    ]
    (root / "notes.md").write_text("# same bytes\n")
    denied = Config(raw={"sources": [{
        "id": "hermes", "adapter": "markdown-vault", "root": str(root),
        "include": "**/*.md,*.md", "exclude": "config/**,plugins/**,skills/**",
    }]}, base_dir=tmp_path)
    visible = [
        ref.source_uri for ref, _, meta in markdown(denied).scan(None) if not meta.get("skip_reason")
    ]
    assert set(visible) == {"memory.md", "memory/day.md", "notes.md"}


def test_same_bytes_under_two_roots_keep_distinct_source_identity(tmp_path: Path) -> None:
    roots = (tmp_path / "wiki", tmp_path / "dev-wiki")
    for root in roots:
        root.mkdir()
        (root / "note.md").write_bytes(b"same")
    rows = inventory(tuple(("dev-wiki", "markdown-vault", str(root), "development-memory") for root in roots))
    observed = [next(markdown(Config(raw={"sources": [row.config_row()]}, base_dir=tmp_path)).scan(None))
                for row in rows]
    assert observed[0][1] == observed[1][1] == b"same"
    assert observed[0][0].source_id != observed[1][0].source_id


@pytest.mark.parametrize(
    ("factory", "version", "kind"),
    (
        (ProjectRecordsAdapter, "project-jarvis-records-v1", "record"),
        (OrcaRecordsAdapter, "orca-exported-records-v1", "artifact"),
    ),
)
def test_records_export_schema_mismatch_is_classified_exclusion_without_source_write(
    tmp_path: Path, factory, version: str, kind: str,
) -> None:
    root = tmp_path / "records"
    root.mkdir()
    source = root / "record.jsonl"
    source.write_text(
        json.dumps({"type": "export_meta", "export_version": version}) + "\n"
        + json.dumps({
            "type": kind, "id": "x", "schema": "unknown", "text": "no",
            "namespace": "life", "llm_policy": "allow",
        }) + "\n"
    )
    before = source.read_bytes()
    adapter = factory((root,), "record-test", record_identity=True)
    rows = list(adapter.scan(None))
    assert not [body for _, body, meta in rows if not meta.get("skip_reason")]
    assert source.read_bytes() == before
    assert any(meta.get("skip_reason") == "unknown-schema" for _, _, meta in rows)


@pytest.mark.parametrize("factory,version,kind", ((ProjectRecordsAdapter, "project-jarvis-records-v1", "record"),
                                                  (OrcaRecordsAdapter, "orca-exported-records-v1", "artifact")))
def test_truncated_jsonl_and_same_mtime_change_lose_no_cursor(tmp_path: Path, factory, version: str, kind: str) -> None:
    root = tmp_path / "records"
    root.mkdir()
    source = root / "data.jsonl"
    header = json.dumps({"type": "export_meta", "export_version": version}).encode() + b"\n"
    def line(value: str) -> bytes:
        return json.dumps({"type": kind, "id": "one", "schema": "operational_json_v1", "text": value}).encode() + b"\n"
    source.write_bytes(header + line("old") + line("later")[:-5])
    adapter = factory((root,), "source", record_identity=True)
    assert [body for _, body, _ in _visible(adapter)] == [b"old"]
    first = adapter.next_cursor()
    assert json.loads(first)["data.jsonl"] == len(header + line("old"))
    source.write_bytes(header + line("old") + line("later"))
    assert [body for _, body, _ in _visible(adapter, first)] == [b"later"]
    before = source.stat()
    source.write_bytes(header + line("new") + line("later"))
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert [body for _, body, _ in _visible(adapter, adapter.next_cursor())] == [b"new", b"later"]
    assert _visible(adapter, adapter.next_cursor()) == []


@pytest.mark.parametrize(
    ("factory", "version", "kind"),
    (
        (ProjectRecordsAdapter, "project-jarvis-records-v1", "record"),
        (OrcaRecordsAdapter, "orca-exported-records-v1", "artifact"),
    ),
)
def test_record_identity_fields_are_manifest_bound_not_body_scope(
    tmp_path: Path, factory, version: str, kind: str,
) -> None:
    root = tmp_path / "records"
    root.mkdir()
    source = root / "data.jsonl"
    source.write_text(
        json.dumps({"type": "export_meta", "export_version": version}) + "\n"
        + json.dumps({
            "type": kind, "id": "one", "schema": "operational_json_v1", "text": "keep",
            "namespace": "life", "llm_policy": "allow", "scope": "personal-life",
        }) + "\n"
    )
    before = source.read_bytes()
    adapter = factory((root,), "source", record_identity=True)
    ref, body, meta = _visible(adapter)[0]
    digest = sha256(b"keep").hexdigest()
    assert body == b"keep"
    assert source.read_bytes() == before
    assert ref.source_id == "source"
    assert ref.source_version == "sha256:" + digest
    assert meta["source_namespace"] == "source"
    assert meta["record_scope"] == "project-record"
    assert meta["content_sha256"] == digest
    assert meta["byte_cursor"] == meta["cursor"]
    assert meta["export_version"] == version
    assert meta["record_id"] == "one"
    assert meta["schema"] == "operational_json_v1"
    assert "life" not in meta.values()
    assert "allow" not in meta.values()


def test_code_instructions_are_data_not_executed(tmp_path: Path) -> None:
    sentinel = tmp_path / "ran"
    command = f"python3 -c \"open({str(sentinel)!r}, 'w').close()\""
    root = tmp_path / "notes"
    root.mkdir()
    (root / "note.md").write_text(f"# note\n\n```sh\n{command}\n```\n")
    (root / "run.py").write_text(f"open({str(sentinel)!r}, 'w').close()\n")
    cfg = Config(
        raw={"sources": [{"id": "wiki", "adapter": "markdown-vault", "root": str(root)}]},
        base_dir=tmp_path,
    )
    rows = [row for row in markdown(cfg).scan(None) if not row[2].get("skip_reason")]
    assert [ref.source_uri for ref, _, _ in rows] == ["note.md"]
    assert command.encode() in rows[0][1]
    records = tmp_path / "records"
    records.mkdir()
    (records / "data.jsonl").write_text(
        json.dumps({"type": "export_meta", "export_version": "project-jarvis-records-v1"}) + "\n"
        + json.dumps({
            "type": "record", "id": "cmd", "schema": "operational_json_v1", "text": command,
        }) + "\n"
    )
    delivered = _visible(ProjectRecordsAdapter((records,), "project", record_identity=True))
    assert [body for _, body, _ in delivered] == [command.encode()]
    assert not sentinel.exists()


def test_hermes_discovery_uses_fixed_memory_scope(tmp_path: Path) -> None:
    root = tmp_path / "hermes"
    for name in (
        "memory.md", "memory/day.md", "config/settings.md", "plugins/a.md", "skills/a.md", "notes.py",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("same\n")
    request = SourceDiscoveryRequestV1.from_mapping({
        "request_version": SOURCE_DISCOVERY_REQUEST_V1,
        "source_name": "hermes",
        "source_root": str(root),
    })
    listed = sorted(entry.relative_path for entry in discover_source(request).entries)
    assert listed == ["memory.md", "memory/day.md"]
