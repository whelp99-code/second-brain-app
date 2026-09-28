"""Worker entrypoint for the isolated Docling adapter."""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
import tempfile
from importlib.metadata import PackageNotFoundError, version


class _NoNetworkSocket(socket.socket):
    def connect(self, address: object) -> None:
        raise OSError("docling network disabled")


socket.socket = _NoNetworkSocket


def main() -> int:
    if importlib.util.find_spec("docling") is None:
        return 3
    try:
        from docling.document_converter import (  # pyright: ignore[reportMissingImports]
            DocumentConverter,
        )
    except ImportError:
        return 2
    suffix = sys.argv[1] if len(sys.argv) == 2 else ".bin"
    payload = sys.stdin.buffer.read(64 * 1024 * 1024 + 1)
    if len(payload) > 64 * 1024 * 1024:
        return 2
    with tempfile.NamedTemporaryFile(prefix="sb-docling-", suffix=suffix, delete=False) as handle:
        path = handle.name
        try:
            handle.write(payload)
            handle.close()
            converted = DocumentConverter().convert(path)
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
            "locator": {"kind": "page" if suffix == ".pdf" else "paragraph", "ordinal": 1},
            "parser_version": parser_version,
            "model_version": "docling-default",
            "partial": False,
            "partial_reason": None,
        },
        sys.stdout,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
