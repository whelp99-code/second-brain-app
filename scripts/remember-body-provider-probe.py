"""Isolated characterization of the frozen V1 remember body boundary.

Only synthetic inputs; no configured vault or operational journal is opened.
Output includes fixture requests for the companion cross-language probe.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from sb.effect_values import is_json_object, strict_loads
from sb.mcp_contract import write_fixture_request
from sb.write_request_values import JsonValue, canonical_bytes, digest
from sb.write_requests import WriteRequestRejected, accept_memory_write_request

NOW = datetime(2026, 8, 31, tzinfo=UTC)
# name, synthetic body, provider accepts, JARVIS accepts, candidate text accepts
CASES = (
    ("single", "결정 하나", True, True, True),
    ("lf", "결정 하나\n결정 둘", False, False, False),
    ("crlf", "결정 하나\r\n결정 둘", False, False, False),
    ("cr", "결정 하나\r결정 둘", False, False, False),
    ("tab", "결정\t하나", False, False, False),
    ("unicode_separator", "결정 하나\u2028결정 둘", True, True, True),
    ("nel_separator", "결정 하나\u0085결정 둘", True, True, True),
    ("leading_bom", "\ufeff결정 하나", True, False, False),
    ("leading_nel", "\u0085결정 하나", False, True, True),
    ("record_overflow", "\u2028".join(["결정"] * 65), False, False, True),
    ("escaped_record_overflow", "[^" * 1_365, False, False, True),
    ("utf8_overflow", "결" * 1_366, False, False, False),
)


def main() -> None:
    results: list[dict[str, JsonValue]] = []
    for name, content, expected, jarvis, candidate in CASES:
        request = write_fixture_request()
        request["payload"] = {"content": content}
        base = {key: value for key, value in request.items()
                if key not in {"request_id", "request_digest"}}
        request_digest = digest("request", base)
        request["request_digest"] = request_digest
        request["request_id"] = "memreq:pos:v1:" + request_digest[7:]
        original = canonical_bytes(request)
        replayed = False
        with TemporaryDirectory(prefix="sb-body-contract-") as temporary:
            root = Path(temporary)
            request_root = root / "requests"
            try:
                accepted = accept_memory_write_request(root / "vault", request_root, request, NOW)
            except WriteRequestRejected as exc:
                assert not expected, (name, exc.code)
                assert exc.code == "WRITE_REQUEST_INVALID", (name, exc.code)
                # A rejected body must not create the pending queue or its journal.
                assert list(root.iterdir()) == [], name
                state = "rejected"
            else:
                assert expected, name
                replay = accept_memory_write_request(root / "vault", request_root, request, NOW)
                assert not accepted.replayed and replay.replayed, name
                assert accepted.request_id == replay.request_id, name
                files = list((request_root / "pending").glob("*.v1.json"))
                assert len(files) == 1, name
                envelope = strict_loads(files[0].read_bytes(), 17_408)
                assert is_json_object(envelope), name
                stored_request = envelope["request"]
                assert is_json_object(stored_request), name
                stored_payload = stored_request["payload"]
                assert is_json_object(stored_payload), name
                assert stored_payload["content"] == content, name
                state, replayed = "accepted", True
            assert canonical_bytes(request) == original, name
        results.append({"case": name, "request": request, "provider": state,
                        "jarvis_accepts": jarvis, "candidate_accepts": candidate,
                        "exact_replay": replayed, "input_unchanged": True})
    print(json.dumps({"cases": results}, ensure_ascii=True))


if __name__ == "__main__":
    main()
