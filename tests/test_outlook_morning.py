"""Copy-vault proof for the Outlook morning chain. No network, send, or live vault."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "outlook-morning.sh"
ZONE = ZoneInfo("Asia/Seoul")


def _config(tmp: Path, morning: str) -> Path:
    vault = tmp / "vault"
    cfg = tmp / "config.toml"
    cfg.write_text(
        "\n".join(
            [
                f"vault_root = {json.dumps(str(vault))}",
                "[life]",
                "life_events = true",
                "life_briefing = true",
                'timezone = "Asia/Seoul"',
                "quiet_start = 0",
                "quiet_end = 0",
                "[life.sources.outlook]",
                "enabled = true",
                'allowed_types = ["calendar_event"]',
                "[source_access.outlook]",
                'owner = "principal:owner"',
                "projects = []",
                'policy_revision = "outlook-morning-test"',
                "[life_schedule]",
                f'morning = "{morning}"',
                'evening = "23:59"',
                "max_age_minutes = 120",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = {**os.environ, "SB_CONFIG": str(cfg), "PYTHONPATH": str(ROOT)}
    init = subprocess.run(
        [sys.executable, "-m", "sb.cli", "init"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert init.returncode == 0, init.stderr
    return cfg


def _run(tmp: Path, cfg: Path, **env_extra: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "SB_CONFIG": str(cfg),
        "PYTHONPATH": str(ROOT),
        "OUTLOOK_MORNING_STATE": str(tmp / "state"),
        "SB_LIFE_SOURCE": "outlook",
        "SB_PYTHON": sys.executable,
    }
    env.update(env_extra)
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _titles(path: Path) -> list[str]:
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["notifications_sent"] is False
    titles: list[str] = []
    for row in document["briefings"]:
        content = row["body"]["content"]
        assert content["slot"] == "morning"
        titles.extend(card["title"] for card in content["cards"])
    return titles


def test_two_events_reach_morning_cards_without_send(tmp_path: Path) -> None:
    now = datetime.now(ZONE)
    morning = (now - timedelta(minutes=30)).strftime("%H:%M")
    day = now.date().isoformat()
    cfg = _config(tmp_path, morning)
    socket_path = tmp_path / "calendar.sock"
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(socket_path))
    listener.listen(1)
    cli = tmp_path / "write-calendar"
    cli.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                'out=""',
                'while [ $# -gt 0 ]; do',
                '  if [ "$1" = "--out" ]; then out="$2"; shift 2; else shift; fi',
                "done",
                'printf "%s\\n" "$CALENDAR_FIXTURE" > "$out"',
                "exit 0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    cli.chmod(0o700)
    fixture = json.dumps(
        {
            "value": [
                {
                    "id": "synthetic-am",
                    "subject": "합성 오전",
                    "start": {"dateTime": f"{day}T09:00:00+09:00", "timeZone": "Asia/Seoul"},
                    "end": {"dateTime": f"{day}T10:00:00+09:00", "timeZone": "Asia/Seoul"},
                },
                {
                    "id": "synthetic-pm",
                    "subject": "합성 오후",
                    "start": {"dateTime": f"{day}T15:00:00+09:00", "timeZone": "Asia/Seoul"},
                    "end": {"dateTime": f"{day}T16:00:00+09:00", "timeZone": "Asia/Seoul"},
                },
            ]
        },
        ensure_ascii=False,
    )
    try:
        result = _run(
            tmp_path,
            cfg,
            MAIL_INTELLIGENCE_CALENDAR_SOCKET=str(socket_path),
            MAIL_CALENDAR_CLI=str(cli),
            CALENDAR_FIXTURE=fixture,
        )
    finally:
        listener.close()
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert _titles(tmp_path / "state" / "tick.json") == ["합성 오전", "합성 오후"]
    assert _titles(tmp_path / "state" / "briefing.json") == ["합성 오전", "합성 오후"]


def test_missing_socket_and_consent_keep_an_empty_briefing(tmp_path: Path) -> None:
    now = datetime.now(ZONE)
    morning = (now - timedelta(minutes=30)).strftime("%H:%M")
    missing = tmp_path / "missing"
    missing.mkdir()
    missing_cfg = _config(missing, morning)
    missed = _run(missing, missing_cfg)
    assert missed.returncode == 0, missed.stderr
    assert missed.stderr == "소켓 없음\n"
    assert _titles(missing / "state" / "tick.json") == []

    consent_root = tmp_path / "consent"
    consent_root.mkdir()
    consent_cfg = _config(consent_root, morning)
    socket_path = consent_root / "calendar.sock"
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(socket_path))
    listener.listen(1)
    cli = consent_root / "consent"
    cli.write_text("#!/bin/sh\nprintf '%s\\n' '동의 필요'\nexit 2\n", encoding="utf-8")
    cli.chmod(0o700)
    try:
        refused = _run(
            consent_root,
            consent_cfg,
            MAIL_INTELLIGENCE_CALENDAR_SOCKET=str(socket_path),
            MAIL_CALENDAR_CLI=str(cli),
        )
    finally:
        listener.close()
    assert refused.returncode == 0, refused.stderr
    assert refused.stderr == "동의 필요\n"
    assert _titles(consent_root / "state" / "tick.json") == []
    assert "--send" not in SCRIPT.read_text(encoding="utf-8")
    timer = (ROOT / "systemd/user/jm-second-brain-outlook-morning.timer").read_text(encoding="utf-8")
    assert "OnCalendar=*-*-* 06:30:00" in timer
    assert "Persistent=false" in timer
