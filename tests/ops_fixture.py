"""Cited, committed Unicode vault fixture for operations tests."""

from pathlib import Path
from typing import Final

from sb.config import Config
from sb.contracts import PageSpec, SourceCite
from sb.store.cas import ContentAddressedStore
from sb.store.ledger import Ledger
from sb.vault import init_vault
from tests.knowledge import stamp_knowledge

TERM: Final = "백업복원검증키워드"


class _NoCompiledHash:
    def last_compiled_hash(self, page_id: str) -> str | None:
        del page_id
        return None


def seed_vault(tmp_path: Path) -> tuple[Path, Config]:
    root = tmp_path / "vault-한글"
    vault = init_vault(root)
    payload = "원본 계약 데이터".encode()
    digest = ContentAddressedStore(root).put(payload)
    sid = digest[:8]
    page = PageSpec(
        page_id="계약-일정",
        title="계약 일정",
        body_md=f"# 계약\n{TERM}[^{sid}]",
        sources=[SourceCite(sid, "inbox:계약.md", digest, ["0-9"])],
        status="active",
    )
    result = vault.write_pages(
        [page],
        "seed-ops",
        _NoCompiledHash(),
        compiled_by=("prompt-ops", "fake-model"),
    )
    assert result.commit is not None
    stamp_knowledge(root)
    with Ledger(root):
        pass
    config = Config(
        raw={
            "vault_root": str(root),
            "llm": {"argv_template": ["missing-second-brain-test-llm"]},
        }
    )
    return root, config
