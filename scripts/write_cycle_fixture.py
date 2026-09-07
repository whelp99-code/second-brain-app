"""Synthetic corpus and deterministic LLM for opt-in managed write acceptance."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import cast

from sb.compile import page_id_for_origin
from sb.config import Config
from sb.contracts import Blob, PageSpec, SourceCite
from sb.normalize import normalize
from sb.store import DerivationOutput, deriv_key
from sb.store.ledger import Ledger
from sb.vault import Vault

SEED_TERM = "반복쓰기기준기억"


def source_text(index: int) -> str:
    return "\n\n".join(
        " ".join([f"원본{index:05d}단위{part:02d}"] + ["a"] * 598) + "."
        for part in range(20)
    )


class NoPreviousHash:
    def last_compiled_hash(self, page_id: str) -> str | None:
        del page_id
        return None


def seed_pages(config: Config, page_count: int, conflict_count: int) -> str:
    """Commit baseline fixtures in bulk, then finalize their compile derivations.

    This is fixture setup, not measured production compilation. The later inbox
    items use the real CLI compile stage and the explicit subprocess fixture.
    """
    root = Path(config.vault_root)
    pages: list[PageSpec] = []
    outputs: list[tuple[str, DerivationOutput]] = []
    with Ledger(root) as ledger:
        sources = ledger.list_source_items()
        for item in sources:
            origin = f"{item.source_id}:{item.source_uri}"
            payload = (root / "raw" / item.content_hash[:2] / item.content_hash).read_bytes()
            units = normalize(Blob(item.content_hash, len(payload)), payload.decode(), origin)
            assert len(units) == 20
            key = deriv_key([unit.unit_id for unit in units], "compile",
                            config.llm.prompt_version, config.llm.model_id)
            page_id = page_id_for_origin(origin)
            body = f"{SEED_TERM} {item.source_uri}.[^{item.content_hash[:8]}]"
            pages.append(PageSpec(page_id, item.source_uri, body,
                                  [SourceCite(item.content_hash[:8], origin, item.content_hash)],
                                  "active", prompt_version=config.llm.prompt_version,
                                  model_id=config.llm.model_id, derivation_key=key))
            outputs.append((key, DerivationOutput(hashlib.sha256(body.encode()).hexdigest(),
                                                 f"wiki/{page_id}.md")))
        first_page = "wiki/" + pages[0].page_id
        for index in range(page_count - len(pages) + conflict_count):
            is_conflict = index >= page_count - len(sources)
            item = sources[index % len(sources)]
            page_id = f"{'conflicts' if is_conflict else 'wiki'}/write-load-{index:05d}"
            pages.append(PageSpec(page_id, page_id,
                                  f"구조부하기억 {index}.[^{item.content_hash[:8]}]",
                                  [SourceCite(item.content_hash[:8],
                                              f"{item.source_id}:{item.source_uri}", item.content_hash)],
                                  "conflicted" if is_conflict else "active"))
        written = Vault(root).write_pages(pages, "write-load-fixture", NoPreviousHash())
        assert written.pages == page_count and written.conflicts == conflict_count
        for key, output in outputs:
            ledger.ensure_derivation(key, "compile", "write-load-fixture")
            ledger.mark_running(key, "write-load-fixture")
            ledger.mark_done(key, output)
    return first_page


def generate(prompt: str) -> str:
    if "relation, confidence, rationale" in prompt:
        return json.dumps({"relation": "unrelated", "confidence": 1,
                           "rationale": "독립 합성 자료"}, ensure_ascii=False)
    if "available-citations:" in prompt:
        table = prompt.split("available-citations:\n", 1)[1].split("\n\n", 1)[0]
        sids = cast(list[str], re.findall(r"\[\^([0-9a-f]{8})\]", table))
        return "\n".join(f"- 합성 점검 {index} [^{sid}]" for index, sid in enumerate(sids[:3])) or "없음"
    match = re.search(r"\n슬롯: (.*?)\n슬롯:", prompt, re.DOTALL)
    if match is None:
        raise ValueError("unrecognized fixture prompt")
    rows = cast(list[tuple[str, str]], re.findall(r"(?:^|\n)sid=([0-9a-f]{8})[^\n]*\n(.*?)(?=\nsid=|\Z)",
                      match.group(1), re.DOTALL))
    if not rows:
        raise ValueError("missing cited fixture units")
    return "\n".join(f"{line.strip()} [^{sid}]" for sid, body in rows
                     for line in body.splitlines() if line.strip())


if __name__ == "__main__":
    print(generate(sys.stdin.read()))
