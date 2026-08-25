"""Two-stage contradiction detection. No filesystem or search imports."""

# fmt: off
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.resources import files
from typing import Final

from sb.config import Config
from sb.contracts import ConflictVerdict, PageSpec, SourceCite, Unit
from sb.llm import LLMBadJson, LLMClient, LLMUnavailable
from sb.store import Derivation, DerivationOutput, DerivStatus, deriv_key
from sb.store.ledger import Ledger

CONTRADICTION_FLOOR: Final = 0.8
SUPERSEDE_FLOOR: Final = 0.9
LEXICAL_FLOOR: Final = 1
LEXICAL_TOP: Final = 10
SECTIONS: Final = ("주장A", "주장B", "판정", "status")
_ROUTES: Final = frozenset({"conflict", "supersede", "note", "unrelated"})
_STR: Final = re.compile(r'"((?:\\.|[^"\\])*)"')
_NUM: Final = re.compile(r"-?\d+(?:\.\d+)?")
_STAMP: Final = re.compile(r"(?:updated:\s*)?(\d{4}-\d{2}-\d{2})")
_SEP: Final = "\x1f"
type _Pack = tuple[ConflictVerdict, tuple[str, ...], LexicalMatch, Mapping[str, str], Mapping[str, str | None]]


@dataclass(frozen=True, slots=True)
class LexicalMatch:
    left_id: str
    unit_id: str
    score: float


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


def check(
    units: Sequence[Unit], pages: Sequence[PageSpec], ledger: Ledger, llm: LLMClient, config: Config,
) -> list[ConflictFinding]:
    matches = lexical_top(units, pages)
    template = (files("sb") / "prompts" / "conflict.md").read_text(encoding="utf-8")
    version, model = config.llm.prompt_version, config.llm.model_id
    texts: dict[str, str] = {unit.unit_id: unit.text for unit in units}
    texts.update({page.page_id: page.body_md for page in pages})
    stamps = {unit.unit_id: _stamp(unit, pages) for unit in units}
    for page in pages:
        found = _STAMP.search(page.body_md)
        if found is not None:
            stamps[page.page_id] = found.group(1)
    used = 0
    findings: list[ConflictFinding] = []
    cap = config.caps["max_llm_calls_conflict"]
    for pair in matches:
        key = deriv_key((pair.left_id, pair.unit_id), "conflict", version, model)
        row = ledger.get_derivation(key)
        if row is not None and row.status == DerivStatus.DONE.value:
            findings.append(_restore(row, pair))
        elif used >= cap or (row is not None and row.status != DerivStatus.PENDING.value):
            continue
        else:
            findings.append(_judge((pair, texts, stamps, ledger, llm, template, key)))
            used += 1
    return findings


def _tokens(text: str) -> tuple[str, ...]:
    tokens: list[str] = []
    buf: list[str] = []
    for char in unicodedata.normalize("NFC", text).casefold():
        if char.isalnum():
            buf.append(char)
        elif buf:
            tokens.append("".join(buf))
            buf = []
    if buf:
        tokens.append("".join(buf))
    return tuple(tokens)


def lexical_top(units: Sequence[Unit], pages: Sequence[PageSpec]) -> tuple[LexicalMatch, ...]:
    docs = [(unit.unit_id, _tokens(unit.text)) for unit in units]
    docs.extend((page.page_id, _tokens(page.body_md)) for page in pages)
    ids = {unit.unit_id for unit in units}
    hits = [hit for unit in units for hit in _rank(_tokens(unit.text), docs, unit.unit_id)]
    hits.sort(key=lambda h: (0 if h.left_id in ids and h.unit_id in ids else 1, -h.score, h.left_id, h.unit_id))
    seen: set[tuple[str, str]] = set()
    unique: list[LexicalMatch] = []
    for hit in hits:
        pair = (min(hit.left_id, hit.unit_id), max(hit.left_id, hit.unit_id))
        if pair in seen:
            continue
        seen.add(pair)
        unique.append(hit)
        if len(unique) == LEXICAL_TOP:
            break
    return tuple(unique)


def _rank(query: tuple[str, ...], docs: Sequence[tuple[str, tuple[str, ...]]], exclude: str) -> list[LexicalMatch]:
    keys = list(dict.fromkeys(query))
    if not keys:
        return []
    grouped: dict[str, Counter[str]] = {}
    ordinals: dict[str, int] = {}
    df: dict[str, int] = {}
    count = 0
    want = set(keys)
    for ordinal, (doc_id, tokens) in enumerate(docs):
        if doc_id == exclude:
            continue
        count += 1
        ordinals[doc_id] = ordinal
        freqs = Counter(tokens)
        grouped[doc_id] = freqs
        for token in freqs:
            if token in want:
                df[token] = df.get(token, 0) + 1
    ranked: list[tuple[int, int, str, int]] = []
    for doc_id, freqs in grouped.items():
        score = 0
        for key in keys:
            tf = freqs.get(key)
            if tf is not None:
                score += tf * max(count - df.get(key, 0) + 1, 1)
        if score >= LEXICAL_FLOOR:
            ranked.append((-score, ordinals[doc_id], doc_id, score))
    ranked.sort()
    return [LexicalMatch(exclude, doc_id, float(score)) for _n, _o, doc_id, score in ranked[:LEXICAL_TOP]]


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


def _judge(job: tuple[LexicalMatch, Mapping[str, str], Mapping[str, str | None], Ledger, LLMClient, str, str]) -> ConflictFinding:
    pair, texts, stamps, ledger, llm, template, key = job
    prompt = (
        template.replace("{left_id}", pair.left_id).replace("{left_text}", texts.get(pair.left_id, ""))
        .replace("{right_id}", pair.unit_id).replace("{right_text}", texts.get(pair.unit_id, ""))
    )
    ledger.ensure_derivation(key, "conflict", "conflict")
    ledger.mark_running(key, "conflict")
    try:
        raw = llm.generate(prompt, json_mode=True)
    except (LLMUnavailable, LLMBadJson):
        out = _open(pair)
    else:
        out = _parse(raw, pair, texts, stamps)
    payload = _dump(out)
    ledger.mark_done(key, DerivationOutput(hashlib.sha256(payload.encode()).hexdigest(), payload))
    return out


def _parse(raw: str, pair: LexicalMatch, texts: Mapping[str, str], stamps: Mapping[str, str | None]) -> ConflictFinding:
    relation, rationale, score = _fstr(raw, "relation"), _fstr(raw, "rationale"), _fnum(raw, "confidence")
    cites = _fstrs(raw, "cites")
    if relation is None or rationale is None or score is None or cites is None:
        return _open(pair)
    try:
        verdict = ConflictVerdict(relation=relation, confidence=score, rationale=rationale)
    except ValueError:
        return _open(pair)
    filled = cites or (pair.left_id, pair.unit_id)
    soft = {"unrelated": "unrelated", "supports": "note"}.get(relation)
    if soft is not None:
        return _hit(pair, verdict, soft, None, None, filled, False)
    handler = _HANDLERS.get(relation)
    return _open(pair) if handler is None else handler((verdict, filled, pair, texts, stamps))


def _contra(pack: _Pack) -> ConflictFinding:
    verdict, cites, pair, texts, _stamps = pack
    if verdict.confidence < CONTRADICTION_FLOOR:
        return _hit(pair, verdict, "note", None, None, cites, False)
    mark = f"[^{cites[0]}]" if cites else ""
    body = "\n\n".join((
        f"## 주장A\n{texts.get(pair.left_id, '')}{mark}",
        f"## 주장B\n{texts.get(pair.unit_id, '')}{mark}",
        f"## 판정\n{verdict.rationale}{mark}", "## status\nopen",
    ))
    sid = (cites[0] if cites else pair.left_id)[:8]
    page = PageSpec(
        page_id=f"conflicts/{pair.left_id}-{pair.unit_id}", title="conflict", body_md=body,
        sources=[SourceCite(sid=sid, origin=pair.left_id, hash=sid, spans=[])], status="conflicted",
    )
    return _hit(pair, verdict, "conflict", page, None, cites, False)


def _super(pack: _Pack) -> ConflictFinding:
    verdict, cites, pair, _texts, stamps = pack
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


def _restore(row: Derivation, pair: LexicalMatch) -> ConflictFinding:
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
        page = PageSpec(page_id=f"conflicts/{left_id}-{right_id}", title="conflict", body_md=body.replace("\\n", "\n"), sources=[], status="conflicted")
    warning: bool | None = None if flag == "" else flag == "1"
    return ConflictFinding(left_id, right_id, verdict, route, page, target or None, cites, warning)


def _rest(raw: str, key: str) -> str | None:
    token = f'"{key}":'
    start = raw.find(token)
    return None if start < 0 else raw[start + len(token) :].lstrip()


def _fstr(raw: str, key: str) -> str | None:
    rest = _rest(raw, key)
    matched = None if rest is None else _STR.match(rest)
    return None if matched is None else matched.group(1)


def _fnum(raw: str, key: str) -> float | None:
    rest = _rest(raw, key)
    matched = None if rest is None else _NUM.match(rest)
    return None if matched is None else float(matched.group(0))


def _fstrs(raw: str, key: str) -> tuple[str, ...] | None:
    rest = _rest(raw, key)
    if rest is None:
        return ()
    end = rest.find("]") if rest.startswith("[") else -1
    if end < 0:
        return None
    inner = rest[1:end].strip()
    return () if inner == "" else tuple(_STR.findall(inner))
