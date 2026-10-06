from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Literal, TypedDict

from pydantic import TypeAdapter, ValidationError

UNKNOWN: Final = "unknown"
SCOPES: Final = frozenset({"personal", "company", UNKNOWN})
BASES: Final = frozenset({"quoted", "inferred"})
Action = Literal["record", "correct", "cancel"]


class _QuoteHistoryRow(TypedDict):
    identity: str
    revision: int
    state: str
    quote: str
    owner: str
    due: str
    scope: str
    basis: str
    prior_quote: str | None


_QUOTE_HISTORY_ROW: Final[TypeAdapter[_QuoteHistoryRow]] = TypeAdapter(_QuoteHistoryRow)


class TextDecisionError(ValueError):
    pass


@dataclass(frozen=True)
class TextDecision:
    identity: str
    revision: int
    state: str
    quote: str
    owner: str
    due: str
    scope: str
    basis: str
    prior_quote: str | None


@dataclass(frozen=True)
class JarvisProposal:
    identity: str
    revision: int
    quote: str
    executed: bool = False


def _stated(value: str | None) -> str:
    if value is None or value.strip() == "":
        return UNKNOWN
    return value


def link_text_decision(
    source_text: str,
    *,
    identity: str,
    quote: str,
    owner: str | None,
    due: str | None,
    scope: str | None,
    basis: str,
    action: Action,
    prior: TextDecision | None = None,
) -> TextDecision:
    if not identity or basis not in BASES:
        raise TextDecisionError("DECISION_FIELDS")
    if action == "cancel":
        if prior is None or prior.identity != identity:
            raise TextDecisionError("CANCEL_REQUIRES_PRIOR")
        if prior.state == "cancelled":
            return prior
        return TextDecision(
            identity,
            prior.revision + 1,
            "cancelled",
            prior.quote,
            prior.owner,
            prior.due,
            prior.scope,
            prior.basis,
            prior.quote,
        )
    if quote == "" or quote not in source_text:
        raise TextDecisionError("QUOTE_NOT_IN_SOURCE")
    scope_value = _stated(scope)
    if scope_value not in SCOPES:
        raise TextDecisionError("SCOPE")
    owner_value = _stated(owner)
    due_value = _stated(due)
    if action == "record":
        if prior is not None:
            raise TextDecisionError("RECORD_HAS_PRIOR")
        return TextDecision(
            identity, 1, "recorded", quote, owner_value, due_value, scope_value, basis, None
        )
    if prior is None or prior.identity != identity or prior.state == "cancelled":
        raise TextDecisionError("CORRECT_REQUIRES_OPEN_PRIOR")
    if (
        prior.quote == quote
        and prior.owner == owner_value
        and prior.due == due_value
        and prior.scope == scope_value
        and prior.basis == basis
    ):
        return prior
    return TextDecision(
        identity,
        prior.revision + 1,
        "corrected",
        quote,
        owner_value,
        due_value,
        scope_value,
        basis,
        prior.quote,
    )


def _journal_path(directory: str | Path, identity: str) -> Path:
    if not identity or identity in {".", ".."} or "/" in identity or "\\" in identity:
        raise TextDecisionError("DECISION_FIELDS")
    root = Path(directory).resolve()
    path = (root / f"{identity}.jsonl").resolve()
    if path.parent != root:
        raise TextDecisionError("DECISION_FIELDS")
    return path


def save_quote_history(directory: str | Path, decision: TextDecision) -> None:
    """Append one quote-history revision to a caller-owned journal directory."""
    path = _journal_path(directory, decision.identity)
    _ = path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(asdict(decision), ensure_ascii=False, sort_keys=True)
    with path.open("a", encoding="utf-8") as handle:
        _ = handle.write(line + "\n")


def load_quote_history(directory: str | Path, identity: str) -> TextDecision:
    """Return the latest stored revision after the writing object is gone."""
    path = _journal_path(directory, identity)
    if not path.is_file():
        raise TextDecisionError("QUOTE_HISTORY_MISSING")
    last: _QuoteHistoryRow | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                loaded = _QUOTE_HISTORY_ROW.validate_json(line, strict=True)
            except ValidationError as exc:
                raise TextDecisionError("QUOTE_HISTORY_MALFORMED") from exc
            last = loaded
    if last is None:
        raise TextDecisionError("QUOTE_HISTORY_MISSING")
    if last["identity"] != identity:
        raise TextDecisionError("QUOTE_HISTORY_MISSING")
    if last["revision"] < 1:
        raise TextDecisionError("QUOTE_HISTORY_MALFORMED")
    state = last["state"]
    if state not in {"recorded", "corrected", "cancelled"}:
        raise TextDecisionError("QUOTE_HISTORY_MALFORMED")
    prior = last["prior_quote"]
    scope = _stated(last["scope"])
    if scope not in SCOPES:
        raise TextDecisionError("QUOTE_HISTORY_MALFORMED")
    basis = last["basis"]
    if basis not in BASES:
        raise TextDecisionError("QUOTE_HISTORY_MALFORMED")
    return TextDecision(
        identity=identity,
        revision=last["revision"],
        state=state,
        quote=last["quote"],
        owner=_stated(last["owner"]),
        due=_stated(last["due"]),
        scope=scope,
        basis=basis,
        prior_quote=prior,
    )


def propose_confirmed(record: TextDecision) -> JarvisProposal | None:
    if record.state == "cancelled" or record.basis != "quoted":
        return None
    if record.owner == UNKNOWN or record.scope == UNKNOWN or record.due == UNKNOWN:
        return None
    return JarvisProposal(record.identity, record.revision, record.quote)
