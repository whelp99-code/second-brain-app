# 현재 후보 운영 판단 (전환 실행 아님, 2026-09-13)

재사용: `GROK-CANDIDATE-OPS-JUDGMENT-PREP-2026-09-13.md`, 스냅샷 `/var/tmp/codex-completion-20260913-u7qerm73/operational-readonly-snapshot.json` (2026-09-13T12:15:12+09:00, read_only). 서비스 재시작·설정 변경·운영 백업 없음.

## 핀 구분

| 종류 | 값 | 의미 |
|---|---|---|
| 실행 제품 핀 | `f7c1945` / wheel `1847b599…` / release `d9c6825b…` | 과거 게이트 실행. 로그 `/var/tmp/sb-gates-f7c1945.log`. 이번 M9 훅 소스와 **바이트가 다름** |
| 직전 문서 아카이브 | `e13cd3b` | 20eff3c 정합 아카이브. 이번 훅 없음 |
| 이번 소스 | 본 커밋 (SB `postcompact-hook`) | 새 아카이브 대상. 실행 핀 이름으로 바꾸지 않음 |
| JARVIS artifact | `1672626` dist `/var/tmp/jarvis-artifact-1672626/source/dist` | 이번 변경 없음 |
| 운영 current (스냅샷) | SB `41f0751…`, authority `a3cbbbe…` | 후보가 아님 |
| 활성화 | `production_activated=false` | 유지 |

구버전 `current` 링크만 되돌리는 rollback을 안전하다고 보장하지 않음.

## 서비스 (스냅샷, 재조회 없음)

- `jm-jarvis.service`, dashboard, phone-gateway: active running
- `jm-second-brain-requests.service`: Type=oneshot, inactive/dead, 마지막 성공 2026-09-03 23:53:58 KST
- `jm-second-brain-requests.timer`: LoadState not-found. oneshot 설계와 구분. timer 필요/장애로 단정하지 않음
- `jm-jarvis-backup.timer`: active waiting

당일 점검 대기: 전환 직전 current 타깃, PID, 백업 파일/hash.

## writer/lease 배제

공개 점검 도구: `deploy/check-jarvis-pending-state.py`, `deploy/check-database-handles.py`. 이번에 실행하지 않음. 큐 0으로 배제를 대체하지 않음.

## 비밀 없는 설정 변경안 (미실행)

격리 `SB_CONFIG=/var/tmp/sb-client-readiness/config.toml` + 후보 `bin/sb` 절대 경로. 운영 `~/.config/second-brain` 및 `~/.codex/config.toml` 미변경. Claude `PostCompact` 훅 등록도 운영/개인 settings에 쓰지 않음.

## 전환 순서 (승인 후)

1. 당일 current/프로세스/백업 hash 기록
2. writer/lease 점검 도구 실행
3. 격리 후보에서 `sb doctor` 후 심볼릭 `current` 전환 (별도 승인)
4. 실패 시 구버전 링크만 복원하지 말고 런북의 복구 집합을 따른다

성공/실패 판단: doctor 0, 서비스 active, 검색 1건. 보류 보안/삭제 검증을 통과로 쓰지 않음.

## 인용 한계

- M11 RSS: 7d97af7 당시 표본. 현재 운영 크기 충족 아님
- 단계 시간: c04dee1 격리. 현재 p95 아님
- DR: b9fc3d4 격리. 운영 RPO/RTO 미확정

## 필요 입력 (비밀 아님)

- 격리 Codex/Claude **로그인 프로필 이름**
- 제안 원문 경로: `Orca-JARVIS/docs/second-brain-oss-absorption-handoff-2026-09-07.md` (아직 기억/native 미전송)
- 한글 gold 100–300: M10, 이번 범위 아님
