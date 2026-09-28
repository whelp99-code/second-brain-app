"""Bounded, data-only Docling adapter executed in a short-lived subprocess."""

from __future__ import annotations

import hashlib
import json
import os
import resource
import subprocess
import sys
from pathlib import Path

from sb.parsers import PARTIAL_REASONS, DocumentParseResult, LimitExceeded, WorkerFailure

MAX_BYTES = 64 * 1024 * 1024
TIMEOUT_SECONDS = 20
MAX_OUTPUT_BYTES = 8 * 1024 * 1024


def _limits() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (TIMEOUT_SECONDS, TIMEOUT_SECONDS))


def parse_isolated(payload: bytes, suffix: str) -> DocumentParseResult | None:
    """Return a Docling result, or ``None`` when Docling is unavailable.

    The worker receives bytes on stdin, writes only JSON on stdout, runs with
    a fresh interpreter, a bounded timeout, and a temporary input lifetime.
    Document text is never interpreted as instructions by this adapter.
    """
    if len(payload) > MAX_BYTES:
        raise LimitExceeded("docling payload size")
    worker = Path(__file__).with_name("docling_worker.py")
    try:
        completed = subprocess.run(
            [sys.executable, "-I", str(worker), suffix],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=TIMEOUT_SECONDS,
            start_new_session=True,
            preexec_fn=_limits,
            env={"PATH": os.environ.get("PATH", ""), "PYTHONNOUSERSITE": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkerFailure("timeout") from exc
    except OSError as exc:
        raise WorkerFailure("start") from exc
    if completed.returncode == 3:
        return None
    if completed.returncode != 0:
        raise WorkerFailure("exit")
    if len(completed.stdout) > MAX_OUTPUT_BYTES:
        raise WorkerFailure("output size")
    try:
        value = json.loads(completed.stdout)
        body = value["body"]
        parser_version = value["parser_version"]
        model_version = value["model_version"]
        locator = value["locator"]
        partial = value["partial"]
        reason = value.get("partial_reason")
        expected_kind = "page" if suffix == ".pdf" else "paragraph"
        if (
            not isinstance(body, str)
            or not body.strip()
            or not isinstance(parser_version, str)
            or not parser_version.startswith("docling:")
            or not isinstance(model_version, str)
            or not isinstance(locator, dict)
            or locator.get("kind") != expected_kind
            or type(locator.get("ordinal")) is not int
            or locator["ordinal"] < 1
            or not isinstance(partial, bool)
            or (reason not in PARTIAL_REASONS if partial else reason is not None)
        ):
            raise WorkerFailure("invalid result")
    except (ValueError, TypeError, KeyError) as exc:
        raise WorkerFailure("invalid result") from exc
    return DocumentParseResult(
        body=body.strip(),
        source_hash="sha256:" + hashlib.sha256(payload).hexdigest(),
        locator={
            str(key): value
            for key, value in locator.items()
            if isinstance(value, (str, int))
        },
        parser_version=parser_version,
        model_version=model_version,
        partial=partial,
        partial_reason=reason,
    )
