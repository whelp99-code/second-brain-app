from __future__ import annotations

from pathlib import Path


def test_inert_request_units_watch_stable_queue_and_run_once() -> None:
    path = Path("systemd/user/jm-second-brain-requests.path").read_text(encoding="utf-8")
    service = Path("systemd/user/jm-second-brain-requests.service").read_text(encoding="utf-8")
    assert "%h/.local/state/second-brain/requests/pending" in path
    assert "sb apply-requests --once" in service
    assert "NoNewPrivileges=yes" in service and "ProtectSystem=strict" in service
    assert "WantedBy=default.target" in path
