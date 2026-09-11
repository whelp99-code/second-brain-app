"""Accepted remember request with a distinct candidate after restore."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from sb.request_executor import RequestExecutor
from sb.stable_requests import accept_stable_v1_request
from tests.task30_process_harness import executor_config
from tests.task30_restore_factory import NOW
from tests.test_restore_journal_loss import _remember_request

root = Path(sys.argv[1])
config = executor_config(root)
accepted = accept_stable_v1_request(config.request_root, _remember_request("post-restore-product-write"), NOW)
executor = RequestExecutor(config)
try:
    result = executor.apply_once(now=NOW)
    print(json.dumps({"state": result.state, "request_id": accepted.request_id}))
finally:
    executor.close()
