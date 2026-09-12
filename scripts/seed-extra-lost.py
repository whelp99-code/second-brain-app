#!/usr/bin/env python3
"""Accepted remember used only as a post-backup durable receipt that crash restore must lose."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from sb.mcp_contract import JsonObject, canonical_bytes, write_fixture_request
from sb.request_executor import RequestExecutor
from sb.stable_requests import accept_stable_v1_request
from tests.task30_process_harness import executor_config
from tests.task30_restore_factory import NOW


def _digest(domain: bytes, value: JsonObject) -> str:
    return "sha256:" + hashlib.sha256(domain + canonical_bytes(value).rstrip(b"\n")).hexdigest()


def _remember_request(content: str) -> JsonObject:
    material = hashlib.sha256(content.encode()).hexdigest()
    request = write_fixture_request()
    request["candidate_id"] = "memcand:pos:v1:" + material
    request["candidate_digest"] = "sha256:" + material
    request["classification_digest"] = "sha256:" + hashlib.sha256(b"class-" + content.encode()).hexdigest()
    request["payload"] = {"content": content}
    receipt = request["receipt"]
    assert isinstance(receipt, dict)
    receipt["candidate_id"] = request["candidate_id"]
    receipt["candidate_digest"] = request["candidate_digest"]
    receipt["classification_digest"] = request["classification_digest"]
    request["receipt_digest"] = _digest(b"orca-jarvis/memory-write-receipt/v1\0", receipt)
    identity: JsonObject = {
        "candidate_id": request["candidate_id"],
        "candidate_digest": request["candidate_digest"],
        "classification_digest": request["classification_digest"],
        "operation": "remember",
    }
    request["idempotency_key"] = "memidem:pos:v1:" + _digest(b"orca-jarvis/memory-write-idempotency/v1\0", identity)[7:]
    request.pop("request_id", None)
    request.pop("request_digest", None)
    request_digest = _digest(b"orca-jarvis/memory-write-request/v1\0", request)
    request["request_id"] = "memreq:pos:v1:" + request_digest[7:]
    request["request_digest"] = request_digest
    return request


root = Path(sys.argv[1])
config = executor_config(root)
accepted = accept_stable_v1_request(config.request_root, _remember_request("ExtraLostAfterBackup"), NOW)
executor = RequestExecutor(config)
try:
    result = executor.apply_once(now=NOW)
    print(json.dumps({"state": result.state, "request_id": accepted.request_id}))
finally:
    executor.close()
