"""Measure relation/hybrid search vs lexical on a fixed two-page vault. Does not enable hybrid."""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from sb.search import SearchIndex
from sb.vault import init_vault
from tests.knowledge import stamp_knowledge

OUT = Path("/var/tmp/m14-relation-search-2026-09-14.json")
LEXICAL = "gateway deploy schedule"
RELATED = "배포 일정 게이트웨이"


def _vault(root: Path) -> Path:
    vault = root / "vault"
    init_vault(vault)
    wiki = vault / "wiki"
    wiki.mkdir(exist_ok=True)
    (wiki / "deploy.md").write_text(
        "---\nid: deploy\ntitle: deploy\nupdated: '2026-09-14'\n---\n\n"
        f"{LEXICAL} Tuesday evening.\n",
        encoding="utf-8",
    )
    (wiki / "unrelated.md").write_text(
        "---\nid: unrelated\ntitle: unrelated\nupdated: '2026-09-14'\n---\n\n"
        "invoice tax reminder only.\n",
        encoding="utf-8",
    )
    return vault


def _ids(hits: tuple[object, ...]) -> list[str]:
    return [str(getattr(hit, "page_id")) for hit in hits]


def main() -> None:
    root = Path("/var/tmp/m14-measure-vault")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir()
    vault = _vault(root)
    env = {
        **__import__("os").environ,
        "GIT_AUTHOR_NAME": "sb",
        "GIT_AUTHOR_EMAIL": "sb@local",
        "GIT_COMMITTER_NAME": "sb",
        "GIT_COMMITTER_EMAIL": "sb@local",
        "GIT_CONFIG_GLOBAL": __import__("os").devnull,
        "GIT_CONFIG_SYSTEM": __import__("os").devnull,
    }
    subprocess.run(["git", "-C", str(vault), "add", "wiki"], check=True, env=env)
    subprocess.run(["git", "-C", str(vault), "commit", "-m", "m14 pages"], check=True, env=env)
    stamp_knowledge(vault)
    query = RELATED
    lexical = SearchIndex(vault, hybrid=False)
    hybrid = SearchIndex(vault, hybrid=True)
    control_ids = _ids(lexical.search("gateway", limit=10))
    started = time.perf_counter()
    lex_hits = lexical.search(query, limit=10)
    lex_s = time.perf_counter() - started
    started = time.perf_counter()
    hyb_hits = hybrid.search(query, limit=10)
    hyb_s = time.perf_counter() - started
    lex_ids = _ids(lex_hits)
    hyb_ids = _ids(hyb_hits)
    extra = [page for page in hyb_ids if page not in lex_ids]
    report = {
        "query": query,
        "control_query": "gateway",
        "control_lexical_ids": control_ids,
        "lexical_ids": lex_ids,
        "hybrid_ids": hyb_ids,
        "hybrid_extra_ids": extra,
        "lexical_seconds": round(lex_s, 4),
        "hybrid_seconds": round(hyb_s, 4),
        "hybrid_default_from_config": False,
        "keep_hybrid_default_off": True,
        "value": "no extra recall" if extra == [] else "hybrid added pages lexical missed",
    }
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
