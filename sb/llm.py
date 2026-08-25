"""Single LLM seam: subprocess CLI adapter plus a deterministic FakeLLM."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol, assert_never, override

ATTEMPT_LIMIT: Final = 2


@dataclass(frozen=True, slots=True)
class LLMUnavailable(Exception):
    """Raised when the CLI adapter exhausts its retry budget."""

    attempts: int
    reason: str

    @override
    def __str__(self) -> str:
        return f"LLM unavailable after {self.attempts} attempts: {self.reason}"


@dataclass(frozen=True, slots=True)
class LLMBadJson(Exception):
    """Raised when json_mode cannot parse a JSON object from model text."""

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
    ) -> str:
        """Return model text, or canonical JSON when json_mode is True."""
        ...


class ProcessRunner(Protocol):
    def __call__(
        self,
        argv: Sequence[str],
        *,
        stdin_text: str | None,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        """Run argv once and return the completed process."""
        ...


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


def _extract_first_json_object(text: str) -> str:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        return json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    raise LLMBadJson(raw=text)


def _render_invocation(
    template: list[str],
    prompt: str,
    system: str | None,
) -> tuple[list[str], str | None]:
    has_prompt_slot = any("{prompt}" in part for part in template)
    has_system_slot = any("{system}" in part for part in template)
    payload = prompt if system is None or has_system_slot else f"{system}\n\n{prompt}"
    argv = [
        part.replace("{prompt}", payload).replace("{system}", system or "")
        for part in template
    ]
    stdin_text = None if has_prompt_slot else payload
    return argv, stdin_text


class FakeLLM:
    """Deterministic LLMClient. `.calls` mutates; that is the purpose."""

    def __init__(self, responses: list[str] | dict[str, str]) -> None:
        self._responses: list[str] | dict[str, str] = responses
        self._index: int = 0
        self.calls: int = 0

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
        raw = self._next_response(prompt)
        if json_mode:
            return _extract_first_json_object(raw)
        return raw

    def _next_response(self, prompt: str) -> str:
        match self._responses:
            case list() as items:
                if self._index >= len(items):
                    raise LLMUnavailable(attempts=self.calls, reason="fake responses exhausted")
                text = items[self._index]
                self._index += 1
                return text
            case dict() as mapping:
                if prompt not in mapping:
                    raise LLMUnavailable(attempts=self.calls, reason="no fake response for prompt")
                return mapping[prompt]
            case unreachable:
                assert_never(unreachable)


class CliLLM:
    """LLMClient that runs a local argv template via subprocess."""

    def __init__(
        self,
        argv_template: list[str],
        *,
        runner: ProcessRunner | None = None,
    ) -> None:
        self._argv_template: list[str] = list(argv_template)
        self._runner: ProcessRunner = _run_subprocess if runner is None else runner

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
        for _attempt in range(ATTEMPT_LIMIT):
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
                if json_mode:
                    return _extract_first_json_object(text)
                return text
            last_reason = f"exit {completed.returncode}"
        raise LLMUnavailable(attempts=ATTEMPT_LIMIT, reason=last_reason)
