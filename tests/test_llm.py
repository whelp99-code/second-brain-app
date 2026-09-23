"""Tests for the LLMClient seam: FakeLLM counting, CliLLM retry, JSON extract."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence

import pytest

from sb.llm import CliLLM, FakeLLM, LLMBadJson, LLMUnavailable

type ScriptItem = subprocess.CompletedProcess[str] | subprocess.TimeoutExpired


class ScriptedRunner:
    """Mutable test double; `.calls` is the documented purpose."""

    def __init__(self, script: list[ScriptItem]) -> None:
        self.calls: int = 0
        self._script: list[ScriptItem] = script

    def __call__(
        self,
        argv: Sequence[str],
        *,
        stdin_text: str | None,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        del stdin_text, timeout
        self.calls += 1
        item = self._script[self.calls - 1]
        match item:
            case subprocess.CompletedProcess():
                return item
            case subprocess.TimeoutExpired():
                raise item


def _ok(stdout: str, argv: Sequence[str] = ("stub",)) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=list(argv), returncode=0, stdout=stdout, stderr="")


def _fail(argv: Sequence[str] = ("stub",)) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=list(argv), returncode=1, stdout="", stderr="fail")


def test_fakellm_increments_calls_when_generate_succeeds() -> None:
    fake = FakeLLM(["one", "two"])
    assert fake.generate("first") == "one"
    assert fake.calls == 1
    assert fake.generate("second") == "two"
    assert fake.calls == 2


def test_fakellm_returns_mapped_text_when_responses_are_dict() -> None:
    fake = FakeLLM({"hello": "world"})
    assert fake.generate("hello") == "world"
    assert fake.calls == 1


def test_generate_reserializes_first_object_when_json_mode_and_fenced() -> None:
    raw = 'intro\n```json\n{"b": 2, "a": 1}\n```\ntrailing'
    fake = FakeLLM([raw])
    assert fake.generate("q", json_mode=True) == '{"a":1,"b":2}'
    assert fake.calls == 1


def test_generate_reserializes_first_object_when_json_mode_and_bare() -> None:
    raw = 'noise {"b": 2, "a": 1} more {"z": 9}'
    fake = FakeLLM([raw])
    assert fake.generate("q", json_mode=True) == '{"a":1,"b":2}'


@pytest.mark.parametrize("response", [
    '{"relation":"supports","relation":"unrelated"}',
    '{"relation":"supports","confidence":NaN}',
])
def test_json_mode_preserves_invalid_semantics_for_boundary(response: str) -> None:
    """Given ambiguous model JSON, when extracted, then downstream parsing still sees it."""
    fake = FakeLLM([response])
    assert fake.generate("q", json_mode=True) == response


def test_generate_raises_bad_json_when_json_mode_and_no_object() -> None:
    fake = FakeLLM(["not json at all"])
    with pytest.raises(LLMBadJson) as excinfo:
        _ = fake.generate("q", json_mode=True)
    assert fake.calls == 1
    assert excinfo.value.raw == "not json at all"


def test_clillm_raises_unavailable_after_exactly_two_attempts_when_argv_is_false() -> None:
    client = CliLLM(["false"])
    with pytest.raises(LLMUnavailable) as excinfo:
        _ = client.generate("x")
    assert excinfo.value.attempts == 2


def test_clillm_counts_two_runner_calls_when_both_attempts_fail() -> None:
    runner = ScriptedRunner([_fail(), _fail()])
    client = CliLLM(["false"], runner=runner)
    with pytest.raises(LLMUnavailable) as excinfo:
        _ = client.generate("x")
    assert runner.calls == 2
    assert excinfo.value.attempts == 2


def test_clillm_returns_stdout_when_second_attempt_succeeds() -> None:
    runner = ScriptedRunner([_fail(), _ok("recovered")])
    client = CliLLM(["tool"], runner=runner)
    assert client.generate("p") == "recovered"
    assert runner.calls == 2


def test_clillm_retries_timeout_then_raises_unavailable() -> None:
    runner = ScriptedRunner(
        [
            subprocess.TimeoutExpired(cmd=["sleep"], timeout=1),
            subprocess.TimeoutExpired(cmd=["sleep"], timeout=1),
        ]
    )
    client = CliLLM(["sleep", "999"], runner=runner)
    with pytest.raises(LLMUnavailable) as excinfo:
        _ = client.generate("x", timeout=1)
    assert runner.calls == 2
    assert excinfo.value.attempts == 2


def test_clillm_substitutes_prompt_slot_and_skips_stdin() -> None:
    captured: list[tuple[list[str], str | None]] = []

    def runner(
        argv: Sequence[str],
        *,
        stdin_text: str | None,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        del timeout
        captured.append((list(argv), stdin_text))
        return _ok("ok", argv)

    client = CliLLM(["echo", "{prompt}"], runner=runner)
    assert client.generate("hello") == "ok"
    assert captured == [(["echo", "hello"], None)]


def test_clillm_sends_prompt_on_stdin_when_template_has_no_prompt_slot() -> None:
    captured: list[tuple[list[str], str | None]] = []

    def runner(
        argv: Sequence[str],
        *,
        stdin_text: str | None,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        del timeout
        captured.append((list(argv), stdin_text))
        return _ok("ok", argv)

    client = CliLLM(["cat"], runner=runner)
    assert client.generate("hello") == "ok"
    assert captured == [(["cat"], "hello")]


def test_clillm_extracts_fenced_json_when_json_mode() -> None:
    runner = ScriptedRunner([_ok('```json\n{"b": 2, "a": 1}\n```')])
    client = CliLLM(["tool"], runner=runner)
    assert client.generate("q", json_mode=True) == '{"a":1,"b":2}'


@pytest.mark.skipif(os.environ.get("SB_LIVE_LLM") != "1", reason="optional live smoke")
def test_live_cli_smoke_when_enabled() -> None:
    client = CliLLM(["claude", "-p", "{prompt}"])
    text = client.generate("Reply with the single word pong.", timeout=60)
    assert text.strip() != ""
