"""Two-stage contradiction detection. No filesystem or search imports."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.resources import files
from typing import Final, Protocol

from sb.config import Config
from sb.conflict_k3 import (
    FAIL_OPEN,
    FAIL_ROUTE,
    RANK,
    ConflictFinding,
    LexicalMatch,
    PairOut,
    encode,
    parse_pair,
    restore,
)
from sb.contracts import PageSpec, Unit
from sb.llm import LLMBadJson, LLMClient, LLMUnavailable
from sb.store import Derivation, DerivationOutput, DerivStatus, deriv_key

CONFLICT_STAGE: Final = "conflict"
CONFLICT_RUN_ID: Final = "conflict"
LEXICAL_FLOOR: Final = 0.15
LEXICAL_TOP: Final = 10

__all__ = ["ConflictFinding", "ConflictResult", "LexicalMatch", "check"]


class ConflictLedger(Protocol):
    """Ledger derivation surface used by conflict. Matches sb.store.ledger.Ledger."""

    def get_derivation(self, key: str) -> Derivation | None: ...

    def ensure_derivation(self, key: str, stage: str, run_id: str) -> None: ...

    def mark_running(self, key: str, run_id: str) -> None: ...

    def mark_done(self, key: str, output: DerivationOutput) -> None: ...


@dataclass(frozen=True, slots=True)
class ConflictResult:
    lexical_matches: tuple[LexicalMatch, ...]
    findings: tuple[ConflictFinding, ...]
    route: str
    cites: tuple[str, ...]
    superseded_id: str | None
    warning: bool


@dataclass(frozen=True, slots=True)
class _Run:
    ledger: ConflictLedger
    llm: LLMClient
    template: str
    prompt_version: str
    model_id: str


def check(
    units: Sequence[Unit],
    pages: Sequence[PageSpec],
    ledger: ConflictLedger,
    llm: LLMClient,
    config: Config,
) -> ConflictResult:
    """Lexically rank pairs, then emit one K3 json_mode verdict per pair.

    Signature is the pipeline contract: units, pages, ledger, llm, config.
    """
    matches = _lexical_top(units, pages)
    run = _Run(
        ledger,
        llm,
        (files("sb") / "prompts" / "conflict.md").read_text(encoding="utf-8"),
        config.llm.prompt_version,
        config.llm.model_id,
    )
    texts = {unit.unit_id: unit.text for unit in units}
    for page in pages:
        texts[page.page_id] = page.body_md
    used = 0
    route, cites, superseded, warning = FAIL_ROUTE, (), None, False
    findings: list[ConflictFinding] = []
    cap = config.caps["max_llm_calls_conflict"]
    for pair in matches:
        key = deriv_key(
            (pair.left_id, pair.unit_id), CONFLICT_STAGE, run.prompt_version, run.model_id
        )
        row = run.ledger.get_derivation(key)
        if row is not None and row.status == DerivStatus.DONE.value:
            out = restore(row)
        elif used >= cap or (row is not None and row.status != DerivStatus.PENDING.value):
            continue
        else:
            out = _judge(pair, texts, run)
            used += 1
        warning = warning or out.warning
        if out.finding is not None:
            findings.append(out.finding)
        if RANK[out.route] > RANK[route]:
            route, cites, superseded = out.route, out.cites, out.superseded_id
    return ConflictResult(matches, tuple(findings), route, cites, superseded, warning)


def _lexical_top(units: Sequence[Unit], pages: Sequence[PageSpec]) -> tuple[LexicalMatch, ...]:
    unit_docs = [(unit.unit_id, unit.text) for unit in units]
    scored: list[LexicalMatch] = []
    for index, left in enumerate(unit_docs):
        for right in unit_docs[index + 1 :]:
            _push(scored, left, right)
        for page in pages:
            _push(scored, left, (page.page_id, page.body_md))
    scored.sort(key=lambda item: (-item.score, item.left_id, item.unit_id))
    return tuple(scored[:LEXICAL_TOP])


def _push(scored: list[LexicalMatch], left: tuple[str, str], right: tuple[str, str]) -> None:
    if left[0] == right[0]:
        return
    left_tok, right_tok = frozenset(left[1].split()), frozenset(right[1].split())
    inter = len(left_tok & right_tok)
    if not left_tok or not right_tok or inter == 0:
        return
    score = inter / len(left_tok | right_tok)
    if score < LEXICAL_FLOOR:
        return
    first, second = (left[0], right[0]) if left[0] <= right[0] else (right[0], left[0])
    scored.append(LexicalMatch(first, second, score))


def _judge(pair: LexicalMatch, texts: Mapping[str, str], run: _Run) -> PairOut:
    prompt = (
        run.template.replace("{left_id}", pair.left_id)
        .replace("{left_text}", texts.get(pair.left_id, ""))
        .replace("{right_id}", pair.unit_id)
        .replace("{right_text}", texts.get(pair.unit_id, ""))
    )
    key = deriv_key((pair.left_id, pair.unit_id), CONFLICT_STAGE, run.prompt_version, run.model_id)
    run.ledger.ensure_derivation(key, CONFLICT_STAGE, CONFLICT_RUN_ID)
    run.ledger.mark_running(key, CONFLICT_RUN_ID)
    try:
        raw = run.llm.generate(prompt, json_mode=True)
    except (LLMUnavailable, LLMBadJson):
        out = FAIL_OPEN
    else:
        out = parse_pair(raw, pair)
    payload = encode(out, pair)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    run.ledger.mark_done(key, DerivationOutput(digest, payload))
    return out
