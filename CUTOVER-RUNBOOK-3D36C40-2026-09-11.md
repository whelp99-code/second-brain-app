# 전환 런북 — 후보 `3d36c40` (실행하지 않음)

게이트된 격리 후보. **전환하지 않는다.** JARVIS 운영 CC에 dist를 섞지 않는다.

| | 운영 | 목표 | 실패 시 |
|---|---|---|---|
| SB current | `41f0751` | 복사본 `3d36c4048c1f31f2c12b25c6bb9b8f23d88c5fb1` | **자동 링크 복원 금지** |
| JARVIS dist | 운영 CC | `/var/tmp/jarvis-artifact-195b1a7/source/dist` (격리 전용) | 운영 CC 불변 |

`41f0751`은 `revoked-jarvis-signing-key-ids`를 읽지 않는다. 전환 후 그 파일이 있으면:

```bash
python deploy/check-rollback-compat.py "$STATE_ROOT" /home/jm/.local/state/second-brain/app/releases/41f0751aca8906d612961e704bc60dd0855fdabd
```

EXIT 2 (`ROLLBACK_UNSAFE_REVOCATION_STORE`)면 구버전으로 current를 되돌리지 않는다. 복구: 새 바이너리를 유지한 채 검증된 백업을 `restore --to`로 격리 복원한 다음, 같은 새 릴리스로 서비스를 올린다.
