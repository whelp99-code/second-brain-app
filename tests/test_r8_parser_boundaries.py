"""Regression coverage for optional worker and literal metadata boundaries."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypedDict, Unpack

import pytest
from docx import Document

from sb.page_metadata import scalar_frontmatter
from sb.parsers import parse_document
from sb.parsers.docling_adapter import parse_isolated


class RunOptions(TypedDict):
    input: bytes
    stdout: int
    stderr: int
    check: bool
    timeout: int
    start_new_session: bool
    preexec_fn: Callable[[], None]
    env: dict[str, str]


@dataclass(frozen=True, slots=True)
class WorkerReply:
    """Fake only the optional external worker's process result."""

    output: bytes
    returncode: int = 0

    def __call__(
        self, command: list[str], **_options: Unpack[RunOptions],
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(command, self.returncode, stdout=self.output)


def test_worker_result_preserves_locator_scalars_and_source_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an external worker reply with retained and ignored locator values.
    payload = b"original document bytes"
    reply = json.dumps({
        "body": "  visible text\n",
        "parser_version": "docling:test",
        "model_version": "local-model",
        "locator": {"kind": "page", "ordinal": 2, "flag": True, "noise": [1], "ratio": 1.5},
        "partial": True,
        "future_field": "ignored",
    }).encode()
    monkeypatch.setattr(subprocess, "run", WorkerReply(reply))

    # When: the adapter crosses the process JSON boundary.
    result = parse_isolated(payload, ".pdf")

    # Then: provenance and accepted scalar values survive without coercion.
    assert result is not None
    assert result.body == "visible text"
    assert result.source_hash == "sha256:" + hashlib.sha256(payload).hexdigest()
    assert result.locator == {"kind": "page", "ordinal": 2, "flag": True}
    assert result.partial is True
    assert result.parser_version == "docling:test"
    assert result.model_version == "local-model"


@pytest.mark.parametrize("reply", [
    b"not json",
    b"[]",
    b"null",
    b'{"body":"ok"}',
    b'{"body":12,"parser_version":"x","model_version":"x","locator":{},"partial":false}',
    b'{"body":"ok","parser_version":1,"model_version":"x","locator":{},"partial":false}',
    b'{"body":"ok","parser_version":"x","model_version":1,"locator":{},"partial":false}',
    b'{"body":"ok","parser_version":"x","model_version":"x","locator":[],"partial":false}',
    b'{"body":"ok","parser_version":"x","model_version":"x","locator":{},"partial":1}',
    b'{"body":"  ","parser_version":"x","model_version":"x","locator":{},"partial":false}',
])
def test_invalid_worker_reply_requests_builtin_fallback(
    monkeypatch: pytest.MonkeyPatch, reply: bytes,
) -> None:
    # Given: invalid external JSON or a field that must not be coerced.
    monkeypatch.setattr(subprocess, "run", WorkerReply(reply))

    # When: the worker result is parsed.
    result = parse_isolated(b"document", ".pdf")

    # Then: the caller receives the established fallback signal.
    assert result is None


@pytest.mark.parametrize("returncode", [2, 3])
def test_unavailable_or_failed_worker_falls_back_with_builtin_provenance(
    monkeypatch: pytest.MonkeyPatch, returncode: int,
) -> None:
    # Given: a real DOCX document and an unavailable or failed optional worker.
    document = Document()
    _ = document.add_paragraph("Builtin fallback body")
    buffer = io.BytesIO()
    document.save(buffer)
    payload = buffer.getvalue()
    monkeypatch.setattr(subprocess, "run", WorkerReply(b"", returncode))

    # When: the document API routes a normalized suffix through the fallback.
    result = parse_document(payload, "DOCX")

    # Then: the built-in extraction retains the same source/provenance contract.
    assert result.body == "Builtin fallback body"
    assert result.source_hash == "sha256:" + hashlib.sha256(payload).hexdigest()
    assert result.parser_version == "builtin:.docx"
    assert result.model_version == "none"
    assert result.locator == {"kind": "document", "ordinal": 1}
    assert result.partial is False


def test_frontmatter_retains_literal_scalars_and_ignores_recursive_collections() -> None:
    # Given: literal YAML scalars and a recursive collection that is not a scalar field.
    block = 'title: "2026-09-27"\nflag: true\nitems: &items [*items]\ntitle: final\n'

    # When: scalar frontmatter is decoded without constructing YAML values.
    fields = scalar_frontmatter(block)

    # Then: scalar spelling, last duplicate value, and collection treatment remain stable.
    assert fields == {"title": "final", "flag": "true", "items": ""}
