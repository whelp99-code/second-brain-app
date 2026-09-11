# Grok 제출 — `c5b4308` × JARVIS `6ce2356` (running, 최종 아님)

인계 A–F/M1–M14와 Codex R1–R7. **운영 전환 없음.** 옛 실패 `/var/tmp/codex-final-26cf158-ufpeOW` 보존.

## 핀

| | |
|---|---|
| SB source | `839f718` |
| 후보 | `/var/tmp/sb-candidate-839f718/releases/c5b4308e7a4277d526c8d73e7332b0450b17021d` |
| wheel | `69b9bab0a0dc4b4a86ccde91dd4656c213ec47c2499353353a7f93b3b0548d7f` |
| JARVIS | `6ce2356` `/var/tmp/jarvis-artifact-6ce2356/source/dist` `sha256:2ec1f727…` |
| 운영 current | `41f0751` |

`dc493f1`은 직전 핀. 이번 휠은 deny 소스 로컬 compile을 포함한다.

## 게이트

`/var/tmp/w3-839f718-maint.log` MAINT:0. `/var/tmp/w3-839f718-integ.log` EXIT 0. `/var/tmp/w3-839f718-work.log` EXIT 0. `production_activated=false`.

관련 테스트: `tests/test_security.py` `tests/test_compile.py` `tests/test_conflict.py` 45 passed (`839f718` compile/conflict 변경). `tests/test_web.py` 16 passed는 이전 `#run` 커밋. 전체 회귀 1820은 `edd2cb5` 트리이며 `839f718` 전체에 대해 반복하지 않았다.

## R1–R7

| ID | 상태 | 증거 |
|---|---|---|
| R1 | verified 격리 | 커밋된 손편집 제안. HEAD seeding 없음 |
| R2 | verified 격리 | 철회 store 유실 fail-closed. CLI/MCP/취소 |
| R3 | verified 격리 | symlink rollback EXIT 2 |
| R4 | implemented_unverified | 격리 `RecordingModelTransport` 전송 직전 JSON: query·본문·출처·version·omitted. 새 세션, untrusted/stale/no_data. persistAssembledContext가 prepareModelTransport 호출. live LLM HTTP 없음. JARVIS `87fc787` |
| R5 | verified 격리 | compact only, Latin case/newline |
| R6 | implemented_unverified | Chrome fail+recover. tiny p50 0.56s. MCP 재시도 EXIT 0. deny compile는 LLM 없이 로컬 페이지. 복원 dest ingest+compile 후 **sealed 기본 검색 1** (`wiki/inbox-…after-restore-d77cfc33`). 옛 scope=all 복사본은 sealed 성공이 아님 |
| R7 | implemented_unverified | 이 핀 |

## M1–M14 (CURSOR-HANDOFF 7절 원문)

| ID | 원문 | 상태 |
|---|---|---|
| M1 | 실제 신원/권한 | blocked_external 실로그인 |
| M2 | 실제 업무 공유 계보 | implemented_unverified 격리 `--work`. 실사용자 업무 blocked_external |
| M3 | 철회 수명 | implemented_unverified R2/R3 격리 |
| M4 | 검증 결과 원계보 | implemented_unverified 격리. 실작업 계보 blocked_external |
| M5 | native 사본 수명 | blocked_external 인증 복사 금지 |
| M6 | 단일작성자·전환복구 | implemented_unverified 격리. 운영 writer 배제 drain |
| M7 | 전체 읽기 범위 | implemented_unverified fixture 거부. 전 표면 운영 미검증 |
| M8 | 제품별 공유연결 | blocked_external 실클라이언트 |
| M9 | 문맥·compaction | implemented_unverified R4 JSON. live 세션 없음 |
| M10 | 검색품질 | implemented_unverified 하드셋. user_curated 없음 |
| M11 | 성능 | implemented_unverified 후보 MCP 소30 p50 0.061s p95 0.220s / 중100 p50 0.083s p95 0.097s / 대300 p50 0.161s p95 0.189s, RSS 84592KiB. 동시 조회·정정 후 최신·timeout 재시도 로그 `M11-MCP-CORPUS-LATENCY-2026-09-11.json`. 권한 불변은 scoped library (`M11-SCOPED-PERMISSION-2026-09-11.json`). 운영 17k p95 아님 |
| M12 | DR | implemented_unverified 복원+deny compile+sealed 검색 1 |
| M13 | GUI | implemented_unverified Chrome. 운영 timer 없음 |
| M14 | 관계검색 | not_implemented |
