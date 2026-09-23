"""Status must read the generation pinned for this HTTP request."""

from contextlib import contextmanager

from sb.effect_values import is_json_object
from sb.store import Run
from sb.store.ledger import Ledger
from tests.test_web import _ready, _request, _running


def test_status_uses_pinned_generation_for_failure_inventory(tmp_path, monkeypatch):
    _old_config, pinned = _ready(tmp_path / "pinned")
    active_config, _active = _ready(tmp_path / "active")
    (pinned / ".sb/runs.log").write_text("pinned run status\n")
    (_active / ".sb/runs.log").write_text("different active run\n")
    with Ledger(pinned) as ledger:
        ledger.record_run(Run("pinned-run", "2099-01-01T00:00:00Z", None, None, "failed"))
        ledger.ensure_derivation("historical-brief", "brief", "old-run")
        ledger.mark_running("historical-brief", "old-run")
        ledger.mark_failed("historical-brief", "unresolved citation")

    @contextmanager
    def pin(_config):
        yield pinned

    monkeypatch.setattr("sb.web.read_root", pin)
    with _running(active_config) as base:
        status, payload = _request(f"{base}/api/status")
    assert status == 200
    assert isinstance(payload, dict) and is_json_object(payload)
    status_text = payload["status"]
    last_run_status = payload["last_run_status"]
    assert isinstance(status_text, str) and isinstance(last_run_status, str)
    assert status_text == "최근 단계 실행 pinned-run: failed"
    assert last_run_status == "failed"
    failures = payload["failures"]
    assert is_json_object(failures)
    items = failures["items"]
    assert isinstance(items, list) and is_json_object(items[0])
    assert failures["total"] == 1
    assert items[0]["key"] == "historical-brief"
