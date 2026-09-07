"""Opt-in real CLI/HTTP readiness probe using an isolated cited vault fixture."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from sb.config import Config
from sb.generation_runtime import GenerationMutationService
from sb.store import Run
from sb.store.ledger import Ledger
from tests.test_ops import _seed_vault
from tests.test_runtime_reliability import managed
from tests.test_web import _request, _running


def main() -> None:
    with TemporaryDirectory(prefix="sb-readiness-acceptance-") as directory:
        root = Path(directory)
        vault, _ = _seed_vault(root)
        now = datetime.now(UTC)
        with Ledger(vault) as ledger:
            ledger.record_run(Run("acceptance-seed", (now-timedelta(minutes=2)).isoformat(),
                (now-timedelta(minutes=1)).isoformat(), None, "ok"))
        config = Config(raw={"vault_root": str(vault), "backup_root": str(root / "backups"),
            "request_root": str(root / "requests"), "state_root": str(root / "state")})
        file = root / "config.toml"
        _ = file.write_text("\n".join(f"{key} = {json.dumps(value)}" for key, value in config.raw.items()))
        archive = root / "backups" / "acceptance.tar.gz"
        command = [sys.executable, "-m", "sb.cli"]
        environment = {**os.environ, "SB_CONFIG": str(file)}
        managed_config = managed(root / "managed")
        service = GenerationMutationService.from_config(managed_config)
        try:
            _ = service.remember("관리형 백업 실사용 검증", "backup", now)
        finally:
            service.close()
        managed_file = root / "managed.toml"
        _ = managed_file.write_text("\n".join(f"{key} = {json.dumps(value)}"
            for key, value in managed_config.raw.items() if isinstance(value, str)))
        managed_archive = Path(managed_config.backup_root) / "managed.tar.gz"
        managed_result = subprocess.run([*command, "backup", str(managed_archive)],
            text=True, capture_output=True, check=True,
            env={**os.environ, "SB_CONFIG": str(managed_file)})
        managed_receipt = json.loads(managed_result.stdout)["verification"]
        assert managed_receipt["origin"] == f"provider:{managed_config.provider_instance_id}"
        assert managed_receipt["generation"]["tombstone_sequence"] == 0
        with _running(config) as url:
            health, _ = _request(url + "/health")
            before, _ = _request(url + "/ready")
            result = subprocess.run([*command, "backup", str(archive)], text=True,
                capture_output=True, check=True, env=environment)
            backup = json.loads(result.stdout)
            ready, _ = _request(url + "/ready")
            assert health == 200 and before == 503 and ready == 200
            verified = subprocess.run([*command, "verify-backup", str(archive)],
                text=True, capture_output=True, check=True, env=environment)
            assert json.loads(verified.stdout)["archive_sha256"] == backup["checksum"]
            with archive.open("ab") as output:
                _ = output.write(b"damage")
            damaged, detail = _request(url + "/ready")
            health_after, _ = _request(url + "/health")
            rejected = subprocess.run([*command, "verify-backup", str(archive)],
                text=True, capture_output=True, check=False, env=environment)
            assert damaged == 503 and health_after == 200 and rejected.returncode != 0
            print(json.dumps({"fixture_run": "seeded", "initial_health": health,
                "initial_ready": before, "verified_ready": ready, "damaged_ready": damaged,
                "health_after_damage": health_after, "verify_damage_exit": rejected.returncode,
                "verification": backup["verification"]["validation"],
                "managed_backup_verified": True,
                "managed_backup_origin": managed_receipt["origin"],
                "verified_files": backup["verification"]["files"],
                "damage_report": detail, "temporary_vaults_remaining":
                    len(list(archive.parent.glob(".verify-backup-*")))}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
