"""Bounded, data-only Docling adapter executed in a short-lived subprocess."""

from __future__ import annotations

import hashlib
import json
import os
import resource
import subprocess
import sys
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

MAX_BYTES = 64 * 1024 * 1024
TIMEOUT_SECONDS = 20
MAX_OUTPUT_BYTES = 8 * 1024 * 1024


def _limits() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (TIMEOUT_SECONDS, TIMEOUT_SECONDS))


@dataclass(frozen=True, slots=True)
class DocumentParseResult:
    body: str
    source_hash: str
    locator: dict[str, str | int]
    parser_version: str
    model_version: str
    partial: bool


def parse_isolated(payload: bytes, suffix: str) -> DocumentParseResult | None:
    """Return a Docling result, or ``None`` when Docling is unavailable.

    The worker receives bytes on stdin, writes only JSON on stdout, runs with
    a fresh interpreter, a bounded timeout, and a temporary input lifetime.
    Document text is never interpreted as instructions by this adapter.
    """
    if len(payload) > MAX_BYTES:
        parser_errors = import_module("sb.parsers")
        raise parser_errors.LimitExceeded("docling payload size")
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
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode == 3:
        return None
    if completed.returncode != 0 or len(completed.stdout) > MAX_OUTPUT_BYTES:
        return None
    try:
        value = json.loads(completed.stdout)
        body = value["body"]
        parser_version = value["parser_version"]
        model_version = value["model_version"]
        locator = value["locator"]
        partial = value["partial"]
        if not isinstance(body, str) or not body.strip() or not isinstance(parser_version, str):
            return None
        if (
            not isinstance(model_version, str)
            or not isinstance(locator, dict)
            or not isinstance(partial, bool)
        ):
            return None
    except (ValueError, TypeError, KeyError):
        return None
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
    )
