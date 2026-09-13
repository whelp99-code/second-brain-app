# 현재 후보 운영 판단 자료 준비 (실행 아님, 2026-09-13)

전환을 실행하지 않는다. 사용자가 승인할 대상·순서·복구안을 적는다.

## 후보 vs 운영

| | 값 |
|---|---|
| 제출 아카이브 | `e13cd3b` / `d9c6825b…` / wheel `1847b599…` |
| 동일 제품 바이트 실행 핀 | `f7c1945` (게이트 로그 `/var/tmp/sb-gates-f7c1945.log`) |
| 운영 current (스냅샷) | SB `41f0751…`, JARVIS authority `a3cbbbe…` |
| 스냅샷 | `/var/tmp/codex-completion-20260913-u7qerm73/operational-readonly-snapshot.json` 2026-09-13 12:15 KST read_only |

`production_activated=false`. current를 후보로 바꾸지 않음.

## 공개 관측 (재시작 없음)

- JARVIS / dashboard / phone-gateway: active
- `jm-second-brain-requests.service`: oneshot, inactive, 마지막 성공 2026-09-03 23:53:58 KST
- `jm-second-brain-requests.timer`: not-found — 설계상 oneshot과 구분. timer 필요/장애로 단정하지 않음.

당일 점검 대기: 전환 직전 current 링크, 프로세스, 백업 파일/hash. 과거 DR 시간/서버 RSS를 현재값으로 쓰지 않음.

## 복구 준비 vs 보장

기존 격리 DR/런북 핀은 후보 바이트용. 보류된 보안/삭제경합 검증이 통과된 것처럼 복구를 보장하지 않음.

## 다음 승인 대상 (실행 전)

1. 격리 Codex `mcp add` (후보 `bin/sb` 절대 경로, 격리 `SB_CONFIG`) — 운영 config 아님
2. 제안 원문(handoff md)을 격리 remember에 쓸지 여부
3. 운영 current 전환은 별도 승인
