from __future__ import annotations

from pathlib import Path


def test_inert_request_units_watch_stable_queue_and_run_once() -> None:
    path = Path("systemd/user/jm-second-brain-requests.path").read_text(encoding="utf-8")
    service = Path("systemd/user/jm-second-brain-requests.service").read_text(encoding="utf-8")
    assert "%h/.local/state/second-brain/requests/pending" in path
    assert "sb apply-requests --once" in service
    assert "NoNewPrivileges=yes" in service and "ProtectSystem=strict" in service
    assert "WantedBy=default.target" in path


def test_inert_maintenance_units_run_provider_owned_oneshot() -> None:
    # Given: the shipped but inactive maintenance unit pair.
    service = Path("systemd/user/jm-second-brain-maintenance.service").read_text(encoding="utf-8")
    timer = Path("systemd/user/jm-second-brain-maintenance.timer").read_text(encoding="utf-8")

    # When / Then: the timer targets the hardened provider maintenance entrypoint.
    assert "sb maintain --once" in service
    assert "NoNewPrivileges=yes" in service and "ProtectSystem=strict" in service
    assert "Unit=jm-second-brain-maintenance.service" in timer
    assert "WantedBy=timers.target" in timer
