"""Opt-in real Codex/Claude CLI interoperability using one isolated MCP provider.

Uses the installed clients' existing authentication and real model calls. Requires
both CLIs. Writes only synthetic memories; never alters global MCP configuration.
The compile stage uses the explicit deterministic fixture, not an external LLM.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkdtemp
from typing import cast
from uuid import uuid4

# Executed by file path: Python puts this sibling module on sys.path.
from agent_memory_events import (  # pyright: ignore[reportImplicitRelativeImport]
    audit_claude,
    audit_codex,
    require_recall,
    require_write,
)

from sb.config import Config
from sb.generation_runtime import GenerationMutationService
from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationMutation,
    GenerationOperation,
)
from sb.vault import init_vault


def main() -> None:
    repository = Path(__file__).resolve().parent.parent
    base = Path(mkdtemp(prefix="sb-agent-memory-acceptance-"))
    clients = {name: shutil.which(name) for name in ("codex", "claude")}
    if any(path is None for path in clients.values()):
        raise RuntimeError("Codex and Claude CLI are both required")
    vault = base / "share/vault"
    config_file = base / "provider.toml"
    compiler = repository / "scripts/agent-memory-compiler-fixture.py"
    raw = {"vault_root": str(vault), "share_root": str(base / "share"),
           "state_root": str(base / "state"), "request_root": str(base / "requests"),
           "export_root": str(base / "exports"), "backup_root": str(base / "backups"),
           "knowledge_registry": str(base / "registry.sqlite")}
    config_text = "\n".join(f"{key} = {json.dumps(value)}" for key, value in raw.items())
    config_text += ('\n[[sources]]\nid = "inbox"\nadapter = "inbox-documents"\n'
                    'llm_policy = "allow"\n[llm]\nmodel_id = "agent-acceptance-fixture"\n'
                    f'argv_template = {json.dumps([sys.executable, str(compiler)])}\n')
    _ = config_file.write_text(config_text)
    _ = init_vault(vault)
    service = GenerationMutationService.from_config(Config(raw=raw))
    try:
        _ = service.mutate(GenerationMutation(
            mutation_id="agent-acceptance:genesis", operation=GenerationOperation.RUN,
            now=datetime.now(UTC), authority=GenerationAuthority(None, None), apply=lambda _root: None))
    finally:
        service.close()
    env = {"SB_CONFIG": str(config_file), "SB_MCP_CONTRACT_PROFILE": "remember-schema5",
           "PYTHONPATH": str(repository), "TMPDIR": str(base)}
    mcp_config = base / "claude-mcp.json"
    _ = mcp_config.write_text(json.dumps({"mcpServers": {"second_brain": {
        "command": sys.executable, "args": ["-m", "sb.mcp"], "env": env}}}))
    marker_a, marker_b = "공유실측A" + uuid4().hex[:10], "공유실측B" + uuid4().hex[:10]
    answer_a, answer_b = "청록" + uuid4().hex[:16], "보라" + uuid4().hex[:16]
    content_a = f"{marker_a} 장비 점검 예약 코드는 {answer_a}입니다."
    content_b = f"{marker_b} 문서 검토 확인 코드는 {answer_b}입니다."
    evidence: dict[str, object] = {"state": "running", "workspace": str(base),
        "started_at": datetime.now(UTC).isoformat(), "marker_a": marker_a, "marker_b": marker_b,
        "limitations": ["real CLI clients, not desktop GUI or automatic context injection",
                         "single trusted owner at tombstone genesis; no project/user isolation",
                         "legacy inbox capture and fixture compile; not JARVIS approved write saga"]}
    for name, client in clients.items():
        evidence[name + "_version"] = subprocess.check_output([str(client), "--version"], text=True).strip()

    def save() -> None:
        _ = (base / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2))

    def run(label: str, arguments: list[str], *, prompt: str | None = None) -> str:
        working = base / label
        working.mkdir()
        _ = (working / "prompt.txt").write_text(prompt or "")
        # Expected recall answers are never written in the reader's working directory.
        save()
        print(f"Starting {label}", flush=True)
        started = time.perf_counter()
        with (base / f"{label}.jsonl").open("w") as output, (base / f"{label}.stderr").open("w") as error:
            result = subprocess.run(arguments, input=prompt, cwd=working, env={**os.environ, **env},
                                    stdout=output, stderr=error, text=True, timeout=240, check=False)
        evidence[label] = {"exit_code": result.returncode,
                           "seconds": time.perf_counter() - started}
        save()
        if result.returncode:
            raise RuntimeError(f"{label} exit {result.returncode}; see retained stderr/events")
        print(f"Completed {label}", flush=True)
        return (base / f"{label}.jsonl").read_text()

    def codex_arguments(tools: list[str]) -> list[str]:
        settings = {"approval_policy": "never", "web_search": "disabled",
                    "features.apps": False, "features.shell_tool": False,
                    "features.multi_agent": False,
                    "mcp_servers.second_brain.command": sys.executable,
                    "mcp_servers.second_brain.args": ["-m", "sb.mcp"],
                    "mcp_servers.second_brain.enabled_tools": tools}
        arguments = [str(clients["codex"]), "exec", "--ignore-user-config", "--ephemeral",
                     "--skip-git-repo-check", "--sandbox", "read-only", "--json"]
        for key, value in settings.items():
            arguments += ["-c", f"{key}={json.dumps(value)}"]
        for tool in tools:
            arguments += ["-c", f'mcp_servers.second_brain.tools.{tool}.approval_mode="approve"']
        for key, value in env.items():
            arguments += ["-c", f"mcp_servers.second_brain.env.{key}={json.dumps(value)}"]
        return [*arguments, "-"]

    def compile_inbox(label: str) -> None:
        environment = {**os.environ, **env}
        for step in ("ingest", "compile"):
            result = subprocess.run([sys.executable, "-m", "sb.cli", step], env=environment,
                                    capture_output=True, text=True, check=False, timeout=120)
            _ = (base / f"{label}-{step}.log").write_text(result.stdout + result.stderr)
            assert result.returncode == 0, result
        with closing(sqlite3.connect(f"{(vault / '.sb/ledger.db').as_uri()}?mode=ro", uri=True)) as db:
            statuses = cast(list[tuple[str]], db.execute("SELECT status FROM run").fetchall())
            assert statuses and all(row == ("ok",) for row in statuses), statuses

    try:
        save()
        print(f"Evidence directory: {base}", flush=True)
        written = run("codex-write", codex_arguments(["sb_remember"]), prompt=(
            "This is a bounded MCP interoperability test. Call second_brain sb_remember exactly once "
            f"with title 'client-a' and this exact content: {content_a}\n"
            "Use no other tools. Report the returned inbox_path. Do not claim the note is searchable yet."))
        writer_audit = audit_codex(written)
        assert tuple(call.name for call in writer_audit.calls) == ("sb_remember",)
        require_write(writer_audit, content_a)
        assert sum(path.read_text() == content_a for path in (vault / "inbox").glob("*.md")) == 1
        compile_inbox("after-codex")
        claude_prompt = (
            "This is a bounded MCP interoperability test. Use only the second_brain MCP tools. "
            f"First call sb_search for '{marker_a}' and then sb_read_page for the matching page. "
            "Report the stored reservation code from its body; do not guess. "
            f"Then call sb_remember exactly once with title 'client-b' and this exact content: {content_b}\n"
            "Finally return JSON with recalled_code and inbox_path. Do not claim the new note is searchable yet.")
        claude = run("claude-read-write", [str(clients["claude"]), "-p", "--output-format", "stream-json",
                     "--verbose", "--no-session-persistence", "--setting-sources", "",
                     "--strict-mcp-config", "--mcp-config", str(mcp_config), "--tools", "",
                     "--disable-slash-commands", "--permission-mode", "dontAsk", "--allowedTools",
                     "mcp__second_brain__sb_search,mcp__second_brain__sb_read_page,mcp__second_brain__sb_remember"],
                     prompt=claude_prompt)
        claude_audit = audit_claude(claude)
        assert tuple(call.name for call in claude_audit.calls) == ("sb_search", "sb_read_page", "sb_remember")
        require_recall(claude_audit, marker_a, answer_a)
        require_write(claude_audit, content_b)
        assert sum(path.read_text() == content_b for path in (vault / "inbox").glob("*.md")) == 1
        compile_inbox("after-claude")
        recalled = run("codex-read", codex_arguments(["sb_search", "sb_read_page"]), prompt=(
            f"Call second_brain sb_search for '{marker_b}', then sb_read_page for the matching page. "
            "Return the stored verification code and page_id using only these MCP results. Do not guess."))
        reader_audit = audit_codex(recalled)
        assert tuple(call.name for call in reader_audit.calls) == ("sb_search", "sb_read_page")
        require_recall(reader_audit, marker_b, answer_b)
        with closing(sqlite3.connect(f"{(vault / '.sb/ledger.db').as_uri()}?mode=ro", uri=True)) as db:
            assert db.execute("SELECT count(*) FROM source_item").fetchone() == (2,)
        for body in (content_a, content_b):
            payload = body.encode()
            digest = hashlib.sha256(payload).hexdigest()
            assert (vault / "raw" / digest[:2] / digest).read_bytes() == payload
        evidence.update({"state": "passed", "source_items": 2, "reciprocal_recall": True,
                         "raw_content_preserved": True, "verified_mcp_calls": 6,
                         "codex_warnings": [*writer_audit.warnings, *reader_audit.warnings],
                         "source_tree_sha256": hashlib.sha256(b"".join(
                             str(path.relative_to(repository)).encode() + b"\0" + path.read_bytes() + b"\0"
                             for path in sorted((repository / "sb").rglob("*.py")))).hexdigest(),
                         "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    except BaseException as exc:
        evidence.update({"state": "failed", "failure": type(exc).__name__ + ": " + str(exc)})
        raise
    finally:
        save()


if __name__ == "__main__":
    main()
