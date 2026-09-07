# Linux 운영 및 복구 — 2026-09-07

실행 파일은 `~/.local/state/second-brain/app/current/bin/`으로 통일한다. `~/.local/bin/sb`도 이 경로를 가리킨다. 기존 uv tool 설치는 롤백 참고용이며 운영 진입점이 아니다. `current`는 wheel과 잠금된 의존성으로 만든 릴리스를 가리킨다. 릴리스의 `release-manifest.json`은 wheel·의존성 해시와 원본 Git HEAD, 미커밋 변경 여부를 기록한다.

## 경로와 설정

- 활성 vault: `~/.local/share/second-brain/vault` → `vault-generations/<generation-id>`
- 제어 상태: `~/.local/state/second-brain`
- 요청: 위 상태 디렉터리의 `requests`; 내보내기: `exports`; 백업: `backups`
- CLI·웹·자비스 MCP: `~/.config/second-brain/config.toml`
- 정기 inbox 처리: `~/.config/second-brain/jarvis-provider.toml`

두 설정의 세대·상태·요청·백업 경로, provider 식별자와 키는 같아야 한다. 수집 범위는 의도적으로 다르다. 정기 실행은 inbox만 처리하며, 일반 설정의 Hermes 소스는 기존 정책을 유지한다. 새 소스 연결은 별도 명시적인 설정 작업이다. MCP launcher는 호출자가 지정한 SB_CONFIG를 덮어쓰지 않는다.

## 확인과 일정

```bash
sb doctor --json
sb status --json
sb search '업무' --json
curl --max-time 60 http://127.0.0.1:8765/ready
systemctl --user list-timers --all
```

`/health`는 프로세스 생존, `/ready`는 초기화·원장 스키마·세대 검색 인덱스·최근 실행 성공·48시간 이내 백업을 확인한다. 갱신 중 읽기는 세대 잠금을 기다릴 수 있다. `last_run_success`가 실패하면 먼저 아래 로그와 실패 파생물을 확인한다. 과거 실패 기록은 삭제하지 않는다.

- `jm-second-brain-refresh.timer`: 매시간 inbox → compile → briefing
- `second-brain-backup.timer`: 매일 체크섬 백업
- `jm-second-brain-maintenance.timer`: export 보존기간 정리
- `jm-second-brain-requests.path`: durable 요청 처리
- 이전 `jm-second-brain-backup.timer`는 이름과 달리 maintain 작업이었으므로 비활성화했다.

```bash
journalctl --user -u jm-second-brain-refresh.service -n 50 --no-pager
sb retry --stage compile
systemctl --user start jm-second-brain-refresh.service
systemctl --user start second-brain-backup.service
```

Codex Node 실행기는 `MemoryDenyWriteExecute=true`에서 실제로 중단된다. refresh 서비스에는 저장소의 `systemd/user/jm-second-brain-refresh.service.d/20-llm-runtime.conf`를 적용한다. Codex 상태 디렉터리의 쓰기를 허용하되 vault의 sealed 디렉터리를 직접 수정해서는 안 된다.

## 배포

```bash
python deploy/prepare-release.py
```

이 명령은 새 릴리스를 준비만 한다. 반환된 릴리스의 MCP 계약·검색과 테스트를 검증한 뒤 두 운영 설정의 `provider_release_sha`를 릴리스 ID로 맞추고 `app/current` symlink를 원자적으로 교체한다. 웹 서비스는 재시작해야 하며, 이미 연결된 클라이언트는 MCP를 다시 연결해야 새 프로세스를 사용한다. 기존 릴리스와 변경 전 설정을 함께 보존한다. 배포 준비 도구는 개발 소스를 실행 경로에 연결하지 않는다.

## 백업과 복원

```bash
sb backup
sb restore /absolute/path/backup.tar.gz --to /absolute/path/new-recovery-directory
```

백업은 세대와 요청 쓰기를 잠근 상태에서 SQLite backup API로 WAL까지 반영한다. `.recovery/state`와 `.recovery/requests`에 제어 원장·요청 자료도 포함한다. 백업 자체에 서명 키와 호스트 설정은 포함되지 않는다. 키·설정은 별도 비밀 관리 경로로 보존해야 한다.

복원 명령은 체크섬·경로·인용 무결성을 검증한다. 활성 symlink 위에 `restore --force`를 사용해서는 안 되며 CLI도 이를 거부한다. 복원 검증용 디렉터리는 검색 가능하지만 곧바로 운영 요청 처리기로 연결하지 않는다. 운영 재활성화에는 generation identity, tombstone high-water와 요청 원장의 일치를 확인하는 기존 복구 절차가 필요하다. 오래된 백업을 활성 경로에 수동으로 덮어쓰면 삭제된 기억이 재유입될 수 있다.

`raw/`, `.sb/`를 Git에 추가하지 말고 vault에 remote를 설정하지 않는다. 소스 리포의 push는 이 작업에서 수행하지 않았다.
