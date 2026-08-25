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
_RANK: Final = {"contradicts": 4, "supersedes": 3, "note": 2, "supports": 2, "unrelated": 1}
_STR: Final = re.compile(r'"((?:\\.|[^"\\])*)"')
_NUM: Final = re.compile(r"-?\d+(?:\.\d+)?")
_STAMP: Final = re.compile(r"(?:updated:\s*)?(\d{4}-\d{2}-\d{2})")
_SEP: Final = "\x1f"

@dataclass(frozen=True, slots=True)
class LexicalMatch:
    left_id: str
    unit_id: str
    score: float


@dataclass(frozen=True, slots=True)
class ConflictFinding:
    left_id: str
    right_id: str
    confidence: float
    cites: tuple[str, ...]
    headings: tuple[str, ...]
    page: PageSpec


@dataclass(frozen=True, slots=True)
class ConflictResult:
    lexical_matches: tuple[LexicalMatch, ...]
    findings: tuple[ConflictFinding, ...]
    route: str
    cites: tuple[str, ...]
    superseded_id: str | None
    warning: bool


@dataclass(frozen=True, slots=True)
class _Out:
    route: str
    cites: tuple[str, ...]
    superseded_id: str | None
    warning: bool
    finding: ConflictFinding | None


FAIL_OPEN: Final = _Out("unrelated", (), None, True, None)


def check(
    units: Sequence[Unit], pages: Sequence[PageSpec], ledger: Ledger, llm: LLMClient, config: Config,
) -> ConflictResult:
    matches = _lexical_top(units, pages)
    template = (files("sb") / "prompts" / "conflict.md").read_text(encoding="utf-8")
    version, model = config.llm.prompt_version, config.llm.model_id
    texts: dict[str, str] = {unit.unit_id: unit.text for unit in units}
    texts.update({page.page_id: page.body_md for page in pages})
    stamps = {unit.unit_id: _stamp(unit, pages) for unit in units}
    for page in pages:
        found = _STAMP.search(page.body_md)
        if found is not None:
            stamps[page.page_id] = found.group(1)
    used, route, cites, superseded, warning = 0, "unrelated", (), None, False
    findings: list[ConflictFinding] = []
    cap = config.caps["max_llm_calls_conflict"]
    for pair in matches:
        key = deriv_key((pair.left_id, pair.unit_id), "conflict", version, model)
        row = ledger.get_derivation(key)
        if row is not None and row.status == DerivStatus.DONE.value:
            out = _restore(row)
        elif used >= cap or (row is not None and row.status != DerivStatus.PENDING.value):
            continue
        else:
            out = _judge((pair, texts, stamps, ledger, llm, template, key))
            used += 1
        if out.finding is not None:
            findings.append(out.finding)
        if _RANK[out.route] > _RANK[route]:
            route, cites, superseded, warning = out.route, out.cites, out.superseded_id, out.warning
        elif out.route == route:
            warning = warning or out.warning
    return ConflictResult(matches, tuple(findings), route, cites, superseded, warning)


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


def _lexical_top(units: Sequence[Unit], pages: Sequence[PageSpec]) -> tuple[LexicalMatch, ...]:
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


def _judge(job: tuple[LexicalMatch, Mapping[str, str], Mapping[str, str | None], Ledger, LLMClient, str, str]) -> _Out:
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
        out = FAIL_OPEN
    else:
        out = _parse(raw, pair, texts, stamps)
    payload = _dump(out, pair)
    ledger.mark_done(key, DerivationOutput(hashlib.sha256(payload.encode()).hexdigest(), payload))
    return out


def _parse(raw: str, pair: LexicalMatch, texts: Mapping[str, str], stamps: Mapping[str, str | None]) -> _Out:
    relation, rationale, score = _fstr(raw, "relation"), _fstr(raw, "rationale"), _fnum(raw, "confidence")
    cites = _fstrs(raw, "cites")
    if relation is None or rationale is None or score is None or cites is None:
        return FAIL_OPEN
    try:
        _ = ConflictVerdict(relation=relation, confidence=score, rationale=rationale)
    except ValueError:
        return FAIL_OPEN
    filled = cites or (pair.left_id, pair.unit_id)
    if relation in {"unrelated", "supports"}:
        return _Out(relation, filled, None, False, None)
    handler = _ROUTES.get(relation)
    return FAIL_OPEN if handler is None else handler((score, rationale, filled, pair, texts, stamps))


def _contra(pack: tuple[float, str, tuple[str, ...], LexicalMatch, Mapping[str, str], Mapping[str, str | None]]) -> _Out:
    score, rationale, cites, pair, texts, _stamps = pack
    if score < CONTRADICTION_FLOOR:
        return _Out("note", cites, None, False, None)
    mark = f"[^{cites[0]}]" if cites else ""
    body = "\n\n".join((
        f"## 주장A\n{texts.get(pair.left_id, '')}{mark}",
        f"## 주장B\n{texts.get(pair.unit_id, '')}{mark}",
        f"## 판정\n{rationale}{mark}", "## status\nopen",
    ))
    sid = (cites[0] if cites else pair.left_id)[:8]
    page = PageSpec(
        page_id=f"conflicts/{pair.left_id}-{pair.unit_id}", title="conflict", body_md=body,
        sources=[SourceCite(sid=sid, origin=pair.left_id, hash=sid, spans=[])], status="conflicted",
    )
    found = ConflictFinding(pair.left_id, pair.unit_id, score, cites, SECTIONS, page)
    return _Out("contradicts", cites, None, False, found)


def _super(pack: tuple[float, str, tuple[str, ...], LexicalMatch, Mapping[str, str], Mapping[str, str | None]]) -> _Out:
    score, _why, cites, pair, _texts, stamps = pack
    left, right = stamps.get(pair.left_id), stamps.get(pair.unit_id)
    if score < SUPERSEDE_FLOOR or left is None or right is None or left == right:
        return _Out("note", cites, None, True, None)
    older = pair.unit_id if left > right else pair.left_id
    return _Out("supersedes", cites, older, False, None)


_ROUTES = {"contradicts": _contra, "supersedes": _super}


def _dump(out: _Out, pair: LexicalMatch) -> str:
    finding = out.finding
    body = "" if finding is None else finding.page.body_md.replace("\n", "\\n")
    conf = "0" if finding is None else str(finding.confidence)
    return _SEP.join((out.route, "1" if out.warning else "0", out.superseded_id or "", ",".join(out.cites), pair.left_id, pair.unit_id, conf, body))


def _restore(row: Derivation) -> _Out:
    raw = row.output_path
    if raw is None:
        return FAIL_OPEN
    parts = raw.split(_SEP)
    if len(parts) != 8 or parts[0] not in _RANK:
        return FAIL_OPEN
    route, flag, target, cites_raw, left_id, right_id, conf_raw, body = parts
    cites = tuple(item for item in cites_raw.split(",") if item)
    finding: ConflictFinding | None = None
    if route == "contradicts" and body and conf_raw:
        page = PageSpec(page_id=f"conflicts/{left_id}-{right_id}", title="conflict", body_md=body.replace("\\n", "\n"), sources=[], status="conflicted")
        finding = ConflictFinding(left_id, right_id, float(conf_raw), cites, SECTIONS, page)
    return _Out(route, cites, target or None, flag == "1", finding)


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
