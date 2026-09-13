# 현재 후보 운영 판단 (미실행)

당일 PID/current/백업 hash는 점검 대기. 구버전 링크만의 rollback을 안전하다고 하지 않음. 보류 검증 통과 전제 없음.

## 경로

- SB 후보: `/var/tmp/sb-candidate-e02636e/releases/b0871a409d2505fbc8f294a2ff9502972661a708/bin/sb`
- JARVIS 실행 산출물: `/var/tmp/jarvis-artifact-78e7307/bin/jarvis` (dist+runtime node_modules). `--help` EXIT0 확인됨. 예전 `node .../dist/src/cli.js`는 better-sqlite3 없이 실패한다.
- 운영 current (인용): SB `/home/jm/.local/state/second-brain/app/current` → `41f0751…`; JARVIS authority `/home/jm/.local/state/orca-jarvis/authority/current` → `a3cbbbe…`

```
SB_APP=/home/jm/.local/state/second-brain/app
AUTH=/home/jm/.local/state/orca-jarvis/authority
SB_DB 당일: readlink -f $SB_APP/current 아래 sqlite (이름 당일 확인)
AUTH_DB=$AUTH/current/jarvis-authority.sqlite
```

`AUTH_DB` 파일명이 다르면 당일 `find "$(readlink -f $AUTH/current)" -name '*.sqlite'`로 확인 (실행은 전환 승인 후).

## 중단 → writer 배제 → 전환 → 기동 (승인 후)

1. 기록: `readlink -f $SB_APP/current`; `readlink -f $AUTH/current`; `systemctl --user is-active jm-jarvis.service jm-jarvis-dashboard.service jm-jarvis-phone-gateway.service`; 백업 경로/hash.
2. stop 전 writer: `python3 deploy/check-jarvis-pending-state.py "$AUTH_DB"`; `python3 deploy/check-database-handles.py "$AUTH_DB"`. EXIT0만 진행. 큐0으로 대체하지 않음. `drain_authorized`는 항상 false.
3. `systemctl --user stop jm-jarvis.service jm-jarvis-dashboard.service jm-jarvis-phone-gateway.service`
4. stop 후 재확인: 같은 두 명령을 다시 실행. handles EXIT0(홀더 없음)이 아니면 전환하지 않음.
5. current를 새 후보 **절대 경로**로 교체 (`ln -sfn` 대상은 당일 후보 release dir). 설정 diff: 격리 `SB_CONFIG`, `JARVIS_MODEL_TRANSPORT_CMD`, Claude UserPromptSubmit/PostCompact 훅은 운영 `~/.claude`가 아닌 격리 settings.
6. `systemctl --user start jm-jarvis.service jm-jarvis-dashboard.service jm-jarvis-phone-gateway.service`

성공: `SB_CONFIG=… /ABS/bin/sb doctor` 0; 세 서비스 active; `sb search` 1건; PostCompact `{}` 후 UserPromptSubmit 문맥; `/var/tmp/jarvis-artifact-78e7307/bin/jarvis --help` 0.

## 실패 단계별 복구 (실행 금지, 명령만)

| 단계 | 대상 | 복원 | 검증 | 중단 |
|---|---|---|---|---|
| 3 stop 후 handles 잔여 | 프로세스 | start 하지 않음. 원인 확인 | handles EXIT0 | 전환 중지 |
| 5 current 교체 실패 | symlink | `ln -sfn` 이전 current 절대 경로 | readlink가 이전 값 | start 금지 |
| 6 start 실패 | 세 유닛 | `systemctl --user stop` 후 이전 current로 ln, 이전 바이너리 start | is-active | 새 current 유지 금지 |
| doctor/search 실패 | vault+authority sqlite 백업 집합 | 백업 아카이브를 vault와 `$AUTH_DB`(+wal/shm)에 복원 후 start | doctor0/search1 | 부분 파일만 되돌리지 않음 |

요청 oneshot/timer not-found는 설계. 보류 수명 미검증.
