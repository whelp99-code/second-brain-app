"""Worker entrypoint for the isolated Docling adapter."""

from __future__ import annotations

import json
import socket
import sys
import tempfile
from collections.abc import Buffer
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import Protocol, override, runtime_checkable


class _Document(Protocol):
    def export_to_markdown(self) -> str: ...


class _ConversionResult(Protocol):
    @property
    def document(self) -> _Document: ...


class _Converter(Protocol):
    def convert(self, source: str) -> _ConversionResult: ...


@runtime_checkable
class _DoclingModule(Protocol):
    """The optional SDK capability used by this isolated worker."""

    def DocumentConverter(self) -> _Converter: ...


class _NoNetworkSocket(socket.socket):
    @override
    def connect(self, address: str | Buffer | tuple[str | bytes | int, ...]) -> None:
        raise OSError("docling network disabled")


socket.socket = _NoNetworkSocket


def main() -> int:
    try:
        module = import_module("docling.document_converter")
    except ImportError:
        return 3
    if not isinstance(module, _DoclingModule):
        return 3
    suffix = sys.argv[1] if len(sys.argv) == 2 else ".bin"
    payload = sys.stdin.buffer.read(64 * 1024 * 1024 + 1)
    if len(payload) > 64 * 1024 * 1024:
        return 2
    with tempfile.NamedTemporaryFile(prefix="sb-docling-", suffix=suffix, delete=False) as handle:
        path = handle.name
        try:
            _ = handle.write(payload)
            handle.close()
            converted = module.DocumentConverter().convert(path)
            body = converted.document.export_to_markdown()
            parser_version = f"docling:{version('docling')}"
        except (OSError, RuntimeError, TypeError, ValueError, PackageNotFoundError):
            return 2
        finally:
            try:
                import os

                os.unlink(path)
            except OSError:
                pass
    if not body.strip():
        return 2
    json.dump(
        {
            "body": body,
            "locator": {"kind": "document", "ordinal": 1},
            "parser_version": parser_version,
            "model_version": "docling-default",
            "partial": False,
        },
        sys.stdout,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
