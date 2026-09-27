"""Single LLM seam: subprocess CLI adapter plus a deterministic FakeLLM."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol, cast, override

ATTEMPT_LIMIT: Final = 2
_WS: Final = frozenset(" \t\n\r")
_NUMBER: Final = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")
_ESCAPES: Final = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}
type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class LLMUnavailable(Exception):
    attempts: int
    reason: str

    @override
    def __str__(self) -> str:
        return f"LLM unavailable after {self.attempts} attempts: {self.reason}"


@dataclass(frozen=True, slots=True)
class LLMBadJson(Exception):
    raw: str

    @override
    def __str__(self) -> str:
        return f"no JSON object in LLM output ({len(self.raw)} chars)"


class LLMClient(Protocol):
    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
        timeout: int = 120,
    ) -> str: ...


class ProcessRunner(Protocol):
    def __call__(
        self,
        argv: Sequence[str],
        *,
        stdin_text: str | None,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]: ...


def _run_subprocess(
    argv: Sequence[str],
    *,
    stdin_text: str | None,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        input=stdin_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )


def _skip_ws(text: str, index: int) -> int:
    while index < len(text) and text[index] in _WS:
        index += 1
    return index


def _parse_string(text: str, index: int) -> tuple[str, int] | None:
    if index >= len(text) or text[index] != '"':
        return None
    index += 1
    chunks: list[str] = []
    length = len(text)
    while index < length:
        char = text[index]
        if char == '"':
            return "".join(chunks), index + 1
        if char != "\\":
            if ord(char) < 32:
                return None
            chunks.append(char)
            index += 1
            continue
        if index + 1 >= length:
            return None
        escaped = text[index + 1]
        if escaped != "u":
            mapped = _ESCAPES.get(escaped)
            if mapped is None:
                return None
            chunks.append(mapped)
            index += 2
            continue
        hexpart = text[index + 2 : index + 6]
        if len(hexpart) != 4:
            return None
        try:
            chunks.append(chr(int(hexpart, 16)))
        except ValueError:
            return None
        index += 6
    return None


def _parse_value(text: str, index: int) -> tuple[JsonValue, int] | None:
    index = _skip_ws(text, index)
    if index >= len(text):
        return None
    char = text[index]
    if char == "{":
        return _parse_object(text, index)
    if char == "[":
        return _parse_array(text, index)
    if char == '"':
        return _parse_string(text, index)
    if text.startswith("true", index):
        return True, index + 4
    if text.startswith("false", index):
        return False, index + 5
    if text.startswith("null", index):
        return None, index + 4
    matched = _NUMBER.match(text, index)
    if matched is None:
        return None
    token = matched.group(0)
    parsed_number: int | float = float(token) if any(m in token for m in ".eE") else int(token)
    return parsed_number, matched.end()


def _closed(text: str, index: int, closer: str) -> int | None:
    index = _skip_ws(text, index)
    if index < len(text) and text[index] in {closer, ","}:
        return index + 1
    return None


def _parse_object(text: str, index: int) -> tuple[dict[str, JsonValue], int] | None:
    if index >= len(text) or text[index] != "{":
        return None
    index = _skip_ws(text, index + 1)
    if index < len(text) and text[index] == "}":
        return {}, index + 1
    result: dict[str, JsonValue] = {}
    while True:
        parsed_key = _parse_string(text, _skip_ws(text, index))
        if parsed_key is None:
            return None
        key, index = parsed_key
        index = _skip_ws(text, index)
        if index >= len(text) or text[index] != ":":
            return None
        parsed_value = _parse_value(text, index + 1)
        if parsed_value is None:
            return None
        value, index = parsed_value
        result[key] = value
        after = _closed(text, index, "}")
        if after is None:
            return None
        if text[after - 1] == "}":
            return result, after
        index = after


def _parse_array(text: str, index: int) -> tuple[list[JsonValue], int] | None:
    if index >= len(text) or text[index] != "[":
        return None
    index = _skip_ws(text, index + 1)
    if index < len(text) and text[index] == "]":
        return [], index + 1
    values: list[JsonValue] = []
    while True:
        parsed = _parse_value(text, index)
        if parsed is None:
            return None
        value, index = parsed
        values.append(value)
        after = _closed(text, index, "]")
        if after is None:
            return None
        if text[after - 1] == "]":
            return values, after
        index = after


def _extract_first_json_object(text: str) -> str:
    start = text.find("{")
    while start != -1:
        try:
            parsed, end = cast(tuple[JsonValue, int], json.JSONDecoder().raw_decode(text, start))
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        if isinstance(parsed, dict):
            raw = text[start:end]
            try:
                value = cast(JsonValue, json.loads(raw, object_pairs_hook=_unique_json_fields,
                                                   parse_constant=_invalid_json_constant))
            except ValueError:
                return raw  # Preserve invalid semantics for the conflict boundary.
            return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        start = text.find("{", start + 1)
    raise LLMBadJson(raw=text)


def _unique_json_fields(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    fields: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in fields:
            raise ValueError("duplicate JSON key")
        fields[key] = value
    return fields


def _invalid_json_constant(value: str) -> JsonValue:
    del value
    raise ValueError("nonfinite JSON constant")


def _render_invocation(
    template: list[str],
    prompt: str,
    system: str | None,
) -> tuple[list[str], str | None]:
    has_prompt_slot = any("{prompt}" in part for part in template)
    has_system_slot = any("{system}" in part for part in template)
    payload = prompt if system is None or has_system_slot else f"{system}\n\n{prompt}"
    argv = [
        part.replace("{prompt}", payload).replace("{system}", system or "") for part in template
    ]
    return argv, None if has_prompt_slot else payload


class FakeLLM:
    def __init__(self, responses: list[str] | dict[str, str]) -> None:
        self.calls: int = 0
        self._index: int = 0
        self._queue: list[str] = []
        self._by_prompt: dict[str, str] = {}
        self._use_queue: bool = False
        match responses:
            case list() as items:
                self._queue = items
                self._use_queue = True
            case dict() as mapping:
                self._by_prompt = mapping

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
        timeout: int = 120,
    ) -> str:
        del system, timeout
        self.calls += 1
        if self._use_queue:
            if self._index >= len(self._queue):
                raise LLMUnavailable(attempts=self.calls, reason="fake responses exhausted")
            raw = self._queue[self._index]
            self._index += 1
        elif prompt not in self._by_prompt:
            raise LLMUnavailable(attempts=self.calls, reason="no fake response for prompt")
        else:
            raw = self._by_prompt[prompt]
        return _extract_first_json_object(raw) if json_mode else raw


class CliLLM:
    def __init__(self, argv_template: list[str], *, runner: ProcessRunner | None = None,
                 attempt_limit: int = ATTEMPT_LIMIT) -> None:
        if type(attempt_limit) is not int or not 1 <= attempt_limit <= ATTEMPT_LIMIT:
            raise ValueError("invalid model attempt limit")
        self._argv_template: list[str] = list(argv_template)
        self._runner: ProcessRunner = _run_subprocess if runner is None else runner
        self._attempt_limit: int = attempt_limit

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
        timeout: int = 120,
    ) -> str:
        argv, stdin_text = _render_invocation(self._argv_template, prompt, system)
        last_reason = "no attempt"
        for _attempt in range(self._attempt_limit):
            try:
                completed = self._runner(argv, stdin_text=stdin_text, timeout=timeout)
            except subprocess.TimeoutExpired:
                last_reason = f"timeout after {timeout}s"
                continue
            except FileNotFoundError:
                last_reason = f"command not found: {argv[0]}"
                continue
            except OSError as exc:
                last_reason = f"os error: {exc}"
                continue
            if completed.returncode == 0:
                text = completed.stdout or ""
                return _extract_first_json_object(text) if json_mode else text
            last_reason = f"exit {completed.returncode}"
            for line in (completed.stderr or "").splitlines():
                text = line.strip()
                if text:
                    last_reason = f"{last_reason}: {text[:200]}"
                    break
        raise LLMUnavailable(attempts=self._attempt_limit, reason=last_reason)
