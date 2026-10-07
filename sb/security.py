"""Source-scoped LLM egress and prompt-time sensitive-data policy."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final, Protocol, cast

from typing_extensions import TypedDict

from sb.config import Config
from sb.contracts import BriefingInputs, PageSpec, Unit
from sb.llm import CliLLM, LLMClient
from sb.redaction import redact_credentials
from sb.source_access import SourceAccess, require_current_source_access
from sb.store import SourceItem

_EMAIL: Final = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_BEARER: Final = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}")
# The leading `[A-Za-z0-9_.-]*` matches a compound key's own prefix. A word boundary
# alone missed every real config spelling: `provider_private_key` and `client_secret`
# have a word character before the keyword, so `\bsecret\b` never matched them, and
# they went through unmasked.
_SECRET_ASSIGN: Final = re.compile(
    r"(?im)([A-Za-z0-9_.-]*"
    + r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|private[_-]?key|password|passwd|secret))\b"
    # The optional quote is TOML's `"key" = "value"`, which the operational provider
    # config is written in: without it the closing quote separated key from separator.
    + r"[\"']?\s*[:=]\s*([^\s,;]{4,})"
)
_PRIVATE_KEY: Final = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
_ORIGIN: Final = re.compile(r"(?:^|\s)origin=([^:\s]+):")
_LOCAL_COMMANDS: Final = frozenset({"ollama", "llama-server", "llamacpp", "lmstudio"})
_VALID_LLM_POLICIES: Final = frozenset({"allow", "deny", "local-only"})
_VALID_SENSITIVE_POLICIES: Final = frozenset({"mask", "allow", "deny", "credentials"})


class SourceAccessReader(Protocol):
    """Read-only subset of the ingest ledger used by the compile egress gate."""

    def list_source_items(self) -> tuple[SourceItem, ...]: ...

    def source_access_for(self, item: SourceItem) -> SourceAccess | None: ...


class SecurityPolicyError(RuntimeError):
    """Raised when configured data-egress policy refuses an LLM prompt."""

    source_id: str
    reason: str

    def __init__(self, source_id: str, reason: str) -> None:
        self.source_id = source_id
        self.reason = reason
        super().__init__(f"source {source_id}: {reason}")


def mask_sensitive(text: str) -> str:
    """Mask common secrets and personal identifiers in an LLM-bound copy."""
    # Each literal is required by its regex. Check the current intermediate
    # string so overlapping replacements retain the original policy order.
    protected = text
    if "-----BEGIN " in protected:
        protected = _PRIVATE_KEY.sub("[REDACTED_PRIVATE_KEY]", protected)
    protected = _BEARER.sub("Bearer [REDACTED_TOKEN]", protected)
    if ":" in protected or "=" in protected:
        protected = _SECRET_ASSIGN.sub(
            lambda match: f"{match.group(1)}=[REDACTED_SECRET]",
            protected,
        )
    if "@" in protected:
        protected = _EMAIL.sub("[REDACTED_EMAIL]", protected)
    return protected


def llm_is_external(config: Config) -> bool:
    """Return whether the configured model transports prompts outside this host."""
    raw_llm = _mapping(config.raw.get("llm"))
    # external=true can only tighten. external=false does not attest that a
    # configured wrapper stays on this host; a missing command has nothing to send.
    if raw_llm.get("external") is True:
        return True
    model = config.llm.model_id.casefold()
    # `unknown` is the default when no model_id is configured, so it means "not
    # stated", not "local". Reading it as local silently disarmed the protection:
    # the operational config names a Grok backend by argv alone, so every new
    # source defaulted to `allow` instead of `deny` and a `local-only` source
    # would have been sent outside the host without the error that forbids it.
    # `fake`/`test` name the in-memory seam. protect_compile_egress refuses to
    # treat an executable CLI as that seam just because the label was copied.
    if model in {"fake", "test"}:
        return False
    configured = raw_llm.get("argv_template")
    has_command = isinstance(configured, list) and bool(configured)
    if raw_llm.get("external") is False and not has_command:
        return False
    argv = configured if has_command else config.llm.argv_template
    if not isinstance(argv, list) or not argv or not isinstance(argv[0], str):
        return False
    return _command_name(argv[0]).casefold() not in _LOCAL_COMMANDS


def _command_name(value: str) -> str:
    return value.replace("\\", "/").rsplit("/", 1)[-1]


def source_llm_policy(config: Config, source_id: str) -> str:
    """Return the legacy dispatch decision, retaining the no-LLM fallback."""
    policy = _policies(config, source_id)[0]
    if (policy == "local-only" and llm_is_external(config)
            and not _text(_source_row(config, source_id).get("llm_policy"))):
        return "deny"
    return policy


def _credential_copy(text: str) -> str:
    # Keep the broader compound/quoted-key and Bearer coverage of the legacy
    # gate, plus the shared provider-token patterns. Do not redact contacts.
    protected = _PRIVATE_KEY.sub("[REDACTED_PRIVATE_KEY]", text)
    protected = _BEARER.sub("Bearer [REDACTED_TOKEN]", protected)
    protected = _SECRET_ASSIGN.sub(
        lambda match: f"{match.group(1)}=[REDACTED_SECRET]", protected,
    )
    return redact_credentials(protected)


def _prompt_copy(text: str, source_id: str, config: Config) -> str:
    _, sensitive = _policies(config, source_id)
    protected = mask_sensitive(text)
    if sensitive == "deny" and (protected != text or _credential_copy(text) != text):
        raise SecurityPolicyError(source_id, "sensitive content denied")
    if not llm_is_external(config):
        if sensitive == "allow":
            return text
        if source_id not in config.source_access:
            return protected
    # Explicit legacy mask continues masking contacts. Classified SB2 sources
    # default to credentials only; allow never bypasses external credential removal.
    return _credential_copy(protected if sensitive == "mask" else text)


def protect_unit(unit: Unit, config: Config, *, ledger: SourceAccessReader | None = None) -> Unit:
    """Apply source egress and sensitive-data policy to one prompt-bound unit."""
    source_id = unit.origin.partition(":")[0] or "unknown"
    policy, _ = _policies(config, source_id)
    if ledger is not None:
        configured = config.source_access.get(source_id)
        matches = [item for item in ledger.list_source_items()
                   if f"{item.source_id}:{item.source_uri}" == unit.origin
                   and item.content_hash == unit.content_hash]
        recorded = ledger.source_access_for(matches[0]) if len(matches) == 1 else None
        bound = require_current_source_access(recorded, configured)
        if configured is not None and bound is None and policy != "deny":
            policy = "local-only"
    _enforce_egress(source_id, policy, config)
    return replace(unit, text=_prompt_copy(unit.text, source_id, config))


def protect_units(
    units: list[Unit], config: Config, *, ledger: SourceAccessReader | None = None,
) -> list[Unit]:
    """Return prompt-safe copies while preserving immutable source objects."""
    return [protect_unit(unit, config, ledger=ledger) for unit in units]


@dataclass(frozen=True)
class _CompileEgress:
    client: LLMClient
    config: Config
    units: tuple[Unit, ...]
    ledger: SourceAccessReader
    previous: PageSpec | None
    untracked_context: bool

    def evidence(self) -> list[Unit]:
        """Units plus previous-page citations. Page prose is not a policy source."""
        evidence = list(self.units)
        if self.previous is not None:
            evidence.extend(
                Unit("context", cite.hash, "", "", cite.origin) for cite in self.previous.sources
            )
        return evidence

    def enforce(self) -> list[Unit]:
        """Refuse egress from the trusted binding, not from payload or page text."""
        evidence = self.evidence()
        if llm_is_external(self.config) and (
            self.untracked_context or (self.previous is not None and not self.previous.sources)
        ):
            raise SecurityPolicyError("unknown", "unclassified compile context is local-only")
        _ = protect_units(evidence, self.config, ledger=self.ledger)
        return evidence

    def generate(self, prompt: str, *, system: str | None = None,
                 json_mode: bool = False, timeout: int = 120) -> str:
        # Recheck at the actual call so a policy change between preparation and
        # transport cannot reuse an earlier allow.
        evidence = self.enforce()
        for source_id in sorted({unit.origin.partition(":")[0] for unit in evidence}):
            prompt = _prompt_copy(prompt, source_id, self.config)
            if system is not None:
                system = _prompt_copy(system, source_id, self.config)
        return self.client.generate(prompt, system=system, json_mode=json_mode, timeout=timeout)


def protect_compile_egress(
    client: LLMClient, units: Sequence[Unit], config: Config, ledger: SourceAccessReader,
    *, previous: PageSpec | None, untracked_context: bool,
) -> LLMClient:
    """Guard the entire rendered prompt without changing page/citation identity."""
    if isinstance(client, CliLLM) and config.llm.model_id.casefold() in {"fake", "test"}:
        # Legacy in-memory test clients use these names. An executable CLI does
        # not become that test seam by copying its model label into configuration.
        config = replace(config, raw={**config.raw, "llm": {
            "argv_template": config.llm.argv_template, "model_id": "unknown",
            "external": llm_is_external(config),
        }})
    gate = _CompileEgress(client, config, tuple(units), ledger, previous, untracked_context)
    # Refuse before the compiler marks a derivation running.
    _ = gate.enforce()
    return gate


def protect_briefing_inputs(inputs: BriefingInputs, config: Config) -> BriefingInputs:
    """Apply source policy and masking to all text that can enter briefing prompts."""
    return BriefingInputs(
        _briefing_lines(inputs.yesterday_items, config),
        tuple(mask_sensitive(line) for line in inputs.open_conflict_pages),
        _briefing_lines(inputs.stale_pages, config),
        _briefing_lines(inputs.upcoming_items, config),
        None if inputs.last_brief is None else mask_sensitive(inputs.last_brief),
        inputs.previous_run_status,
    )


def _briefing_lines(lines: Sequence[str], config: Config) -> tuple[str, ...]:
    """Keep the lines a briefing prompt may carry and drop the ones it may not.

    A refusing source withholds its own line here, the way compile falls back to
    no LLM and conflict filters the units it may not send. Raising instead would
    let one denied source fail the whole briefing, which is what happened once
    unified-db arrived with the `deny` its unjudged payloads call for.
    """
    kept: list[str] = []
    for line in lines:
        protected = _briefing_line(line, config)
        if protected is not None:
            kept.append(protected)
    return tuple(kept)


def _briefing_line(line: str, config: Config) -> str | None:
    """Return the prompt-safe line, or None when policy forbids sending it."""
    matched = _ORIGIN.search(line)
    if matched is None:
        return mask_sensitive(line)
    source_id = matched.group(1)
    # A malformed policy still raises: that is a configuration fault, not a refusal.
    policy, sensitive = _policies(config, source_id)
    if policy == "deny" or (policy == "local-only" and llm_is_external(config)):
        return None
    protected = mask_sensitive(line)
    if sensitive == "deny" and protected != line:
        return None
    return line if sensitive == "allow" else protected


class SourcePolicySnapshot(TypedDict, closed=True):
    id: str
    adapter: str
    root: str | None
    root_exists: bool | None
    llm_policy: str
    sensitive: str
    external_model: bool


def source_policy_snapshot(config: Config) -> tuple[SourcePolicySnapshot, ...]:
    """Return a redaction-safe operator view of configured source policies."""
    rows: list[SourcePolicySnapshot] = []
    raw_sources = config.raw.get("sources")
    if not isinstance(raw_sources, list):
        return ()
    for item in cast(list[object], raw_sources):
        row = _mapping(item)
        source_id = _text(row.get("id")) or ""
        adapter = _text(row.get("adapter")) or _text(row.get("type")) or ""
        raw_root = _text(row.get("root"))
        root = None if raw_root is None else config.resolve_path(raw_root)
        llm_policy, sensitive = _policies(config, source_id)
        rows.append(
            {
                "id": source_id,
                "adapter": adapter,
                "root": root,
                "root_exists": None if root is None else _expanded_exists(root),
                "llm_policy": llm_policy,
                "sensitive": sensitive,
                "external_model": llm_is_external(config),
            }
        )
    rows.sort(key=lambda row: (str(row["id"]), str(row["adapter"])))
    return tuple(rows)


def _enforce_egress(source_id: str, policy: str, config: Config) -> None:
    external = llm_is_external(config)
    if policy == "deny":
        raise SecurityPolicyError(source_id, "LLM egress denied by source policy")
    if policy == "local-only" and external:
        raise SecurityPolicyError(source_id, "source is restricted to a local model")


def _policies(config: Config, source_id: str) -> tuple[str, str]:
    row = _source_row(config, source_id)
    policy = _text(row.get("llm_policy")) or "local-only"
    # Preserve explicit legacy masking and the unclassified legacy copy format.
    default_sensitive = "credentials" if source_id in config.source_access else "mask"
    sensitive = _text(row.get("sensitive")) or default_sensitive
    if policy not in _VALID_LLM_POLICIES:
        raise SecurityPolicyError(source_id, f"invalid llm_policy {policy!r}")
    if sensitive not in _VALID_SENSITIVE_POLICIES:
        raise SecurityPolicyError(source_id, f"invalid sensitive policy {sensitive!r}")
    return policy, sensitive


def _source_row(config: Config, source_id: str) -> Mapping[str, object]:
    raw_sources = config.raw.get("sources")
    if not isinstance(raw_sources, list):
        return {}
    for item in cast(list[object], raw_sources):
        row = _mapping(item)
        if _text(row.get("id")) == source_id:
            return row
    return {}


def _mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    return {}


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _expanded_exists(raw: str) -> bool:
    return Path(raw).is_dir()
