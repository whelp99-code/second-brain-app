"""Two-stage contradiction detection. No filesystem or search imports."""

# fmt: off
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from importlib.resources import files
from typing import Final, cast

from sb.config import Config
from sb.conflict_lexical import LEXICAL_FLOOR, LEXICAL_TOP, LexicalMatch, lexical_top
from sb.contracts import ConflictVerdict, PageSpec, SourceCite, Unit
from sb.llm import LLMBadJson, LLMClient, LLMUnavailable
from sb.security import protect_units
from sb.store import Derivation, DerivationOutput, DerivStatus, deriv_key
from sb.store.ledger import Ledger

__all__ = (
    "CONTRADICTION_FLOOR",
    "LEXICAL_FLOOR",
    "LEXICAL_TOP",
    "SECTIONS",
    "SUPERSEDE_FLOOR",
    "ConflictFinding",
    "LexicalMatch",
    "check",
    "lexical_top",
)

_INPUT_PROFILE: Final = "conflict-inputs-v4"
CONTRADICTION_FLOOR: Final = 0.8
SUPERSEDE_FLOOR: Final = 0.9
SECTIONS: Final = ("주장A", "주장B", "판정", "status")
_ROUTES: Final = frozenset({"conflict", "supersede", "note", "unrelated"})
_STAMP: Final = re.compile(r"(?:updated:\s*)?(\d{4}-\d{2}-\d{2})")
_SEP: Final = "\x1f"
_SID_LEN: Final = 8
type _Evidence = Mapping[str, tuple[SourceCite, ...]]
type _Pack = tuple[
    ConflictVerdict,
    tuple[str, ...],
    LexicalMatch,
    Mapping[str, str],
    Mapping[str, str | None],
    _Evidence,
]


@dataclass(frozen=True, slots=True)
class ConflictFinding:
    left_id: str
    right_id: str
    verdict: ConflictVerdict
    route: str
    page: PageSpec | None
    superseded_id: str | None
    cites: tuple[str, ...]
    warning: bool | None
    deriv_key: str | None = None
    deriv_output: DerivationOutput | None = None
    failure: str | None = None


def check(
    units: Sequence[Unit], pages: Sequence[PageSpec], ledger: Ledger, llm: LLMClient, config: Config,
    *, finalize: bool = True, on_capped: Callable[[], None] | None = None,
) -> list[ConflictFinding]:
    units = protect_units(list(units), config)
    matches = lexical_top(units, pages)
    template = (files("sb") / "prompts" / "conflict.md").read_text(encoding="utf-8")
    version, model = config.llm.prompt_version, config.llm.model_id
    texts: dict[str, str] = {unit.unit_id: unit.text for unit in units}
    texts.update({page.page_id: page.body_md for page in pages})
    evidence = _evidence(units, pages)
    stamps = {unit.unit_id: _stamp(unit, pages) for unit in units}
    for page in pages:
        found = _STAMP.search(page.body_md)
        if found is not None:
            stamps[page.page_id] = found.group(1)
    used = 0
    findings: list[ConflictFinding] = []
    cap = config.caps["max_llm_calls_conflict"]
    for pair in matches:
        # Stable page IDs survive edits; bind cached judgments to the actual
        # text, temporal routing inputs, and citation provenance as well.
        input_digest = hashlib.sha256(json.dumps(
            [[item_id, texts.get(item_id, ""), stamps.get(item_id),
              [asdict(cite) for cite in evidence.get(item_id, ())]]
             for item_id in (pair.left_id, pair.unit_id)],
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        key = deriv_key((_INPUT_PROFILE, pair.left_id, pair.unit_id, input_digest),
                        "conflict", version, model)
        row = ledger.get_derivation(key)
        if row is not None and row.status == DerivStatus.DONE.value:
            findings.append(_with_lineage(_restore(row, pair, evidence), version, model, key))
        elif used >= cap:
            if on_capped is not None:
                on_capped()
            continue
        else:
            if row is not None and row.status == DerivStatus.FAILED.value:
                _ = ledger.requeue_failed(key)
            elif row is not None and row.status != DerivStatus.PENDING.value:
                continue
            findings.append(
                _with_lineage(
                    _judge((pair, texts, stamps, evidence, ledger, llm, template, key), finalize),
                    version,
                    model,
                    key,
                )
            )
            used += 1
    return findings


def _with_lineage(
    finding: ConflictFinding,
    prompt_version: str,
    model_id: str,
    key: str,
) -> ConflictFinding:
    if finding.page is None:
        return finding
    return replace(
        finding,
        page=replace(
            finding.page,
            prompt_version=prompt_version,
            model_id=model_id,
            derivation_key=key,
        ),
    )


def _clone_cite(cite: SourceCite) -> SourceCite:
    return SourceCite(cite.sid, cite.origin, cite.hash, list(cite.spans))


def _evidence(units: Sequence[Unit], pages: Sequence[PageSpec]) -> dict[str, tuple[SourceCite, ...]]:
    found: dict[str, tuple[SourceCite, ...]] = {
        unit.unit_id: (
            SourceCite(
                sid=unit.content_hash[:_SID_LEN],
                origin=unit.origin,
                hash=unit.content_hash,
                spans=[unit.span],
            ),
        )
        for unit in units
    }
    for page in pages:
        found[page.page_id] = tuple(_clone_cite(cite) for cite in page.sources)
    return found


def _pair_sources(pair: LexicalMatch, evidence: _Evidence) -> list[SourceCite]:
    unique: dict[tuple[str, str, str], SourceCite] = {}
    for item_id in (pair.left_id, pair.unit_id):
        for cite in evidence.get(item_id, ()):
            key = (cite.sid, cite.origin, cite.hash)
            current = unique.get(key)
            if current is None:
                unique[key] = _clone_cite(cite)
                continue
            for span in cite.spans:
                if span not in current.spans:
                    current.spans.append(span)
    return list(unique.values())


def _citation_marks(cites: Sequence[SourceCite]) -> str:
    return "".join(f"[^{cite.sid}]" for cite in cites)


def _stamp(unit: Unit, pages: Sequence[PageSpec]) -> str | None:
    for page in pages:
        if any(cite.origin == unit.origin for cite in page.sources):
            found = _STAMP.search(page.body_md)
            if found is not None:
                return found.group(1)
    found = _STAMP.search(unit.origin)
    return None if found is None else found.group(1)


def _open(pair: LexicalMatch) -> ConflictFinding:
    return ConflictFinding(pair.left_id, pair.unit_id, ConflictVerdict("unrelated", 0.0, ""), "unrelated", None, None, (), True)


def _hit(pair: LexicalMatch, verdict: ConflictVerdict, route: str, page: PageSpec | None, superseded_id: str | None, cites: tuple[str, ...], warning: bool | None) -> ConflictFinding:
    return ConflictFinding(pair.left_id, pair.unit_id, verdict, route, page, superseded_id, cites, warning)


def _judge(
    job: tuple[
        LexicalMatch,
        Mapping[str, str],
        Mapping[str, str | None],
        _Evidence,
        Ledger,
        LLMClient,
        str,
        str,
    ],
    finalize: bool,
) -> ConflictFinding:
    pair, texts, stamps, evidence, ledger, llm, template, key = job
    prompt = (
        template.replace("{left_id}", pair.left_id).replace("{left_text}", texts.get(pair.left_id, ""))
        .replace("{right_id}", pair.unit_id).replace("{right_text}", texts.get(pair.unit_id, ""))
    )
    ledger.ensure_derivation(key, "conflict", "conflict")
    ledger.mark_running(key, "conflict")
    try:
        raw = llm.generate(prompt, json_mode=True)
    except (LLMUnavailable, LLMBadJson) as exc:
        ledger.mark_failed(key, str(exc))
        return replace(_open(pair), failure=str(exc))
    else:
        out = _parse(raw, pair, texts, stamps, evidence)
    if out.warning is True and out.route == "unrelated" and out.verdict.confidence == 0.0:
        ledger.mark_failed(key, "invalid conflict verdict")
        return replace(out, failure="invalid conflict verdict")
    payload = _dump(out)
    output = DerivationOutput(hashlib.sha256(payload.encode()).hexdigest(), payload)
    if finalize:
        ledger.mark_done(key, output)
        return out
    return replace(out, deriv_key=key, deriv_output=output)


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate conflict field")
        result[key] = value
    return result


def _parse(
    raw: str,
    pair: LexicalMatch,
    texts: Mapping[str, str],
    stamps: Mapping[str, str | None],
    evidence: _Evidence,
) -> ConflictFinding:
    try:
        decoded = cast(object, json.loads(raw, object_pairs_hook=_unique_fields))
        if not isinstance(decoded, dict):
            return _open(pair)
        value = cast(dict[str, object], decoded)
        relation, rationale, score = value.get("relation"), value.get("rationale"), value.get("confidence")
        raw_cites = value.get("cites", [])
        if (not isinstance(relation, str) or not isinstance(rationale, str)
                or not isinstance(score, (int, float)) or isinstance(score, bool)
                or not math.isfinite(score) or not 0 <= score <= 1
                or not isinstance(raw_cites, list)):
            return _open(pair)
        rows = cast(list[object], raw_cites)
        if any(not isinstance(item, str) for item in rows):
            return _open(pair)
        cites = tuple(cast(list[str], rows))
        if any(cite not in {pair.left_id, pair.unit_id} for cite in cites):
            return _open(pair)
        verdict = ConflictVerdict(relation=relation, confidence=float(score), rationale=rationale)
    except (ValueError, OverflowError):
        return _open(pair)
    filled = cites or (pair.left_id, pair.unit_id)
    soft = {"unrelated": "unrelated", "supports": "note"}.get(relation)
    if soft is not None:
        return _hit(pair, verdict, soft, None, None, filled, False)
    handler = _HANDLERS.get(relation)
    return _open(pair) if handler is None else handler((verdict, filled, pair, texts, stamps, evidence))


def _contra(pack: _Pack) -> ConflictFinding:
    verdict, cites, pair, texts, _stamps, evidence = pack
    if verdict.confidence < CONTRADICTION_FLOOR:
        return _hit(pair, verdict, "note", None, None, cites, False)
    sources = _pair_sources(pair, evidence)
    if not sources:
        return _hit(pair, verdict, "note", None, None, cites, True)
    left_mark = _citation_marks(evidence.get(pair.left_id, ()))
    right_mark = _citation_marks(evidence.get(pair.unit_id, ()))
    verdict_mark = _citation_marks(sources)
    body = "\n\n".join((
        f"## 주장A\n{texts.get(pair.left_id, '')}{left_mark}",
        f"## 주장B\n{texts.get(pair.unit_id, '')}{right_mark}",
        f"## 판정\n{verdict.rationale}{verdict_mark}", "## status\nopen",
    ))
    page = PageSpec(
        page_id=f"conflicts/{pair.left_id}-{pair.unit_id}", title="conflict", body_md=body,
        sources=sources, status="conflicted",
    )
    return _hit(pair, verdict, "conflict", page, None, cites, False)


def _super(pack: _Pack) -> ConflictFinding:
    verdict, cites, pair, _texts, stamps, _evidence_map = pack
    left, right = stamps.get(pair.left_id), stamps.get(pair.unit_id)
    if verdict.confidence < SUPERSEDE_FLOOR or left is None or right is None or left == right:
        return _hit(pair, verdict, "note", None, None, cites, True)
    older = pair.unit_id if left > right else pair.left_id
    return _hit(pair, verdict, "supersede", None, older, cites, False)


_HANDLERS = {"contradicts": _contra, "supersedes": _super}


def _dump(hit: ConflictFinding) -> str:
    body = "" if hit.page is None else hit.page.body_md.replace("\n", "\\n")
    warn = "" if hit.warning is None else ("1" if hit.warning else "0")
    return _SEP.join((
        hit.route, warn, hit.superseded_id or "", ",".join(hit.cites), hit.left_id, hit.right_id,
        str(hit.verdict.confidence), body, hit.verdict.relation, hit.verdict.rationale,
    ))


def _restore(row: Derivation, pair: LexicalMatch, evidence: _Evidence) -> ConflictFinding:
    raw = row.output_path
    if raw is None:
        return _open(pair)
    parts = raw.split(_SEP)
    if len(parts) != 10 or parts[0] not in _ROUTES:
        return _open(pair)
    route, flag, target, cites_raw, left_id, right_id, conf_raw, body, relation, rationale = parts
    cites = tuple(item for item in cites_raw.split(",") if item)
    try:
        verdict = ConflictVerdict(relation=relation, confidence=float(conf_raw), rationale=rationale)
    except ValueError:
        return _open(pair)
    page: PageSpec | None = None
    if route == "conflict" and body:
        sources = _pair_sources(pair, evidence)
        if sources:
            page = PageSpec(
                page_id=f"conflicts/{left_id}-{right_id}",
                title="conflict",
                body_md=body.replace("\\n", "\n"),
                sources=sources,
                status="conflicted",
            )
    warning: bool | None = None if flag == "" else flag == "1"
    return ConflictFinding(left_id, right_id, verdict, route, page, target or None, cites, warning)
