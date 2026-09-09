"""Status must read the generation pinned for this HTTP request."""

from contextlib import contextmanager

from sb.store.ledger import Ledger
from tests.test_web import _ready, _request, _running


def test_status_uses_pinned_generation_for_failure_inventory(tmp_path, monkeypatch):
    _old_config, pinned = _ready(tmp_path / "pinned")
    active_config, _active = _ready(tmp_path / "active")
    (pinned / ".sb/runs.log").write_text("pinned run status\n")
    (_active / ".sb/runs.log").write_text("different active run\n")
    with Ledger(pinned) as ledger:
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
    assert payload["status"] == "pinned run status"
    assert payload["failures"]["total"] == 1
    assert payload["failures"]["items"][0]["key"] == "historical-brief"
