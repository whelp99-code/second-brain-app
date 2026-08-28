"""Walking-skeleton gate: one real me-wiki file through the real CLI."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path

from pytest import MonkeyPatch, raises

from sb.cli import main
from sb.config import Config
from sb.contracts import PageSpec, SourceCite
from sb.llm import FakeLLM
from sb.store.ledger import Ledger, load_ledger_tables
from sb.vault import Vault, VaultLintError

ME_WIKI_FILE: Path = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "wiki-spike"
    / "me-wiki"
    / "identity"
    / "profile.md"
)
SOURCE_REL: str = "identity/profile.md"
K1_KEYS: tuple[str, ...] = ("id", "title", "updated", "compiled_by", "status")
K1_STATUS: frozenset[str] = frozenset({"active", "superseded", "conflicted"})
K4_H2: tuple[str, ...] = (
    "오늘의 추천",
    "새로 들어온 것",
    "충돌",
    "오래된 페이지",
    "다가오는 것",
)
FOOTNOTE_RE: re.Pattern[str] = re.compile(r"\[\^([^\]]+)\]")
RUNS_RE: re.Pattern[str] = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\S+ run ([0-9a-f]+) (ok|capped|failed) "
    + r"pages=(\d+) conflicts=\d+ errors=\d+$"
)
TAMPER_SID: str = "deadbeef"


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    data: bytes
    digest: str
    mtime_ns: int
    size: int


class _LlmSlot:
    """Holds the shared FakeLLM so CLI compile/brief increment one counter."""

    def __init__(self) -> None:
        self.client: FakeLLM | None = None

    def provide(self, config: Config, llm_mode: str) -> FakeLLM:
        del config
        assert llm_mode == "fake"
        assert self.client is not None
        return self.client


class _NoHash:
    def last_compiled_hash(self, page_id: str) -> str | None:
        del page_id
        return None


def _snapshot(path: Path) -> SourceSnapshot:
    stat = path.stat()
    data = path.read_bytes()
    return SourceSnapshot(data, hashlib.sha256(data).hexdigest(), stat.st_mtime_ns, stat.st_size)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=False, env=env
    )


def _git_count(root: Path) -> int:
    done = _git(root, "rev-list", "--count", "HEAD")
    assert done.returncode == 0, done.stderr
    return int(done.stdout.strip())


def _cli(argv: list[str]) -> tuple[int, str, str]:
    out, err = StringIO(), StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def _field(block: str, key: str) -> str:
    prefix = f"{key}:"
    for line in block.splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip().strip("'\"")
    raise AssertionError(f"missing K1 field {key}")


def _split_page(text: str) -> tuple[str, str]:
    assert text.startswith("---\n")
    rest = text[4:]
    end = rest.find("\n---")
    assert end >= 0
    return rest[:end], rest[end + 4 :].lstrip("\n")


def _source_sids(block: str) -> set[str]:
    found: set[str] = set()
    for line in block.splitlines():
        stripped = line.strip().removeprefix("- ")
        if stripped.startswith("sid:"):
            found.add(stripped.removeprefix("sid:").strip().strip("'\""))
    return found


def _assert_k1(path: Path) -> None:
    block, body = _split_page(path.read_text(encoding="utf-8"))
    for key in K1_KEYS:
        assert _field(block, key)
    assert _field(block, "status") in K1_STATUS
    sids = _source_sids(block)
    assert sids
    for match in FOOTNOTE_RE.finditer(body):
        assert match.group(1) in sids, match.group(0)


def _wiki_pages(vault: Path) -> list[Path]:
    return [path for path in (vault / "wiki").rglob("*.md") if "_proposed" not in path.parts]


def _run_lines(vault: Path) -> list[re.Match[str]]:
    raw = (vault / ".sb" / "runs.log").read_text(encoding="utf-8").splitlines()
    parsed = [RUNS_RE.match(line) for line in raw]
    assert all(item is not None for item in parsed), raw
    return [item for item in parsed if item is not None]


def _deriv_count(vault: Path) -> int:
    return len(load_ledger_tables(vault / ".sb" / "ledger.db").derivations)


def _prepare(tmp_path: Path, monkeypatch: MonkeyPatch) -> tuple[Path, SourceSnapshot, _LlmSlot]:
    snapshot = _snapshot(ME_WIKI_FILE)
    vault = tmp_path / "vault"
    source_root = tmp_path / "source"
    dest = source_root / SOURCE_REL
    _ = dest.parent.mkdir(parents=True)
    _ = dest.write_bytes(snapshot.data)
    cfg = tmp_path / "config.toml"
    _ = cfg.write_text(
        (
            f'vault_root = "{vault}"\n\n'
            f"[[sources]]\n"
            f'id = "me-wiki"\n'
            f'adapter = "markdown-vault"\n'
            f'root = "{source_root}"\n\n'
            f"[llm]\n"
            f'prompt_version = "v1"\n'
            f'model_id = "fake"\n'
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SB_CONFIG", str(cfg))
    slot = _LlmSlot()
    monkeypatch.setattr("sb.pipeline._llm", slot.provide)
    return vault, snapshot, slot


def _arm_fake(vault: Path, slot: _LlmSlot) -> tuple[FakeLLM, str]:
    with Ledger(vault) as ledger:
        items = ledger.list_source_items()
    assert len(items) == 1
    digest = items[0].content_hash
    sid = digest[:8]
    cited = f"이름은 박재민이다.[^{sid}]"
    fake = FakeLLM([cited, "없음", "없음", "없음"])
    slot.client = fake
    return fake, digest


def _assert_source_untouched(snapshot: SourceSnapshot) -> None:
    after = _snapshot(ME_WIKI_FILE)
    assert after.data == snapshot.data
    assert after.digest == snapshot.digest
    assert after.mtime_ns == snapshot.mtime_ns
    assert after.size == snapshot.size


def test_walking_skeleton_end_to_end_with_idempotency_when_one_me_wiki_file(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    vault, snapshot, slot = _prepare(tmp_path, monkeypatch)
    try:
        code, _out, err = _cli(["init"])
        assert code == 0, err
        assert _git_count(vault) == 1

        code, _out, err = _cli(["ingest"])
        assert code == 0, err
        assert _git_count(vault) == 1

        fake, _digest = _arm_fake(vault, slot)
        code, _out, err = _cli(["compile", "--llm", "fake"])
        assert code == 0, err
        assert _git_count(vault) == 2

        before = datetime.now().astimezone().date().isoformat()
        code, _out, err = _cli(["brief", "--llm", "fake"])
        after = datetime.now().astimezone().date().isoformat()
        assert code == 0, err
        assert _git_count(vault) == 3
        assert _git(vault, "status", "--porcelain").stdout == ""

        wiki = _wiki_pages(vault)
        assert wiki
        for page in wiki:
            _assert_k1(page)

        dailies = tuple((vault / "daily").glob("*.md"))
        assert len(dailies) == 1 and dailies[0].stem in {before, after}
        daily_text = dailies[0].read_text(encoding="utf-8")
        heading_at = [daily_text.index(f"## {heading}") for heading in K4_H2]
        assert f"# {dailies[0].stem} 브리핑" in daily_text and heading_at == sorted(heading_at)

        tracked = _git(vault, "ls-files").stdout.splitlines()
        assert not any(name.startswith(("raw/", ".sb/")) for name in tracked)
        assert (vault / "raw").is_dir()
        assert (vault / ".sb").is_dir()
        ignored = _git(vault, "check-ignore", "raw", ".sb")
        assert ignored.returncode == 0

        runs = _run_lines(vault)
        assert len(runs) == 3
        ingest_id, compile_id, brief_id = runs[0].group(1), runs[1].group(1), runs[2].group(1)
        log_text = (vault / "log.md").read_text(encoding="utf-8")
        assert compile_id in log_text
        assert brief_id in log_text
        assert ingest_id not in log_text

        shas = _git(vault, "log", "--reverse", "--format=%H").stdout.splitlines()
        assert len(shas) == 3
        compile_log = _git(vault, "show", f"{shas[1]}:log.md").stdout
        brief_log = _git(vault, "show", f"{shas[2]}:log.md").stdout
        assert compile_id in compile_log
        assert brief_id not in compile_log
        assert compile_id in brief_log
        assert brief_id in brief_log

        assert fake.calls == 2
        before_deriv = _deriv_count(vault)
        before_log = (vault / "log.md").read_bytes()

        code, _out, err = _cli(["ingest"])
        assert code == 0, err
        code, _out, err = _cli(["compile", "--llm", "fake"])
        assert code == 0, err
        code, _out, err = _cli(["brief", "--llm", "fake"])
        assert code == 0, err

        assert _git_count(vault) == 3
        assert _deriv_count(vault) == before_deriv
        assert fake.calls == 2
        assert (vault / "log.md").read_bytes() == before_log
        second = _run_lines(vault)
        assert len(second) == 6
        assert all(line.group(3) == "0" for line in second[3:])
    finally:
        _assert_source_untouched(snapshot)


def test_write_pages_raises_vault_lint_error_when_compiled_footnote_sid_is_tampered(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    vault, snapshot, slot = _prepare(tmp_path, monkeypatch)
    try:
        assert _cli(["init"])[0] == 0
        assert _cli(["ingest"])[0] == 0
        _fake, digest = _arm_fake(vault, slot)
        assert _cli(["compile", "--llm", "fake"])[0] == 0
        wiki = _wiki_pages(vault)
        assert wiki
        block, body = _split_page(wiki[0].read_text(encoding="utf-8"))
        sid = digest[:8]
        assert f"[^{sid}]" in body
        spec = PageSpec(
            page_id=_field(block, "id"),
            title=_field(block, "title"),
            body_md=body.replace(f"[^{sid}]", f"[^{TAMPER_SID}]", 1),
            sources=[SourceCite(sid=sid, origin=f"me-wiki:{SOURCE_REL}", hash=digest)],
            status=_field(block, "status"),
        )
        porcelain = _git(vault, "status", "--porcelain").stdout
        head = _git(vault, "rev-parse", "HEAD").stdout.strip()
        with raises(VaultLintError):
            _ = Vault(root=vault).write_pages([spec], "tamper-run", _NoHash())
        assert _git(vault, "status", "--porcelain").stdout == porcelain
        assert _git(vault, "rev-parse", "HEAD").stdout.strip() == head
    finally:
        _assert_source_untouched(snapshot)
