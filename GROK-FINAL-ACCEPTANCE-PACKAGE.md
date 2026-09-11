# Grok 최종 제출 — `c5b4308` × JARVIS `87fc787`

Codex 독립 검증 요청. **운영 전환 없음. Codex 최종 인수 아님.** 옛 실패 `/var/tmp/codex-final-26cf158-ufpeOW` 보존.

## 핀

| | |
|---|---|
| SB source | `839f718` (docs HEAD는 이 커밋 뒤) |
| 후보 | `/var/tmp/sb-candidate-839f718/releases/c5b4308e7a4277d526c8d73e7332b0450b17021d` |
| wheel | `69b9bab0a0dc4b4a86ccde91dd4656c213ec47c2499353353a7f93b3b0548d7f` |
| JARVIS source | `87fc787` |
| JARVIS dist | `/var/tmp/jarvis-artifact-87fc787/source/dist` |
| JARVIS inventory | `b1fed737e5b9ca91ae17326d4eefe06be55e815a1b336c12c1952419d10f5894` (34768) |
| 운영 current | `41f0751` |
| production_activated | false |

## 재현

```bash
cd /home/jm/orca/projects/second-brain-app
REL=/var/tmp/sb-candidate-839f718/releases/c5b4308e7a4277d526c8d73e7332b0450b17021d
JARVIS=/var/tmp/jarvis-artifact-87fc787/source/dist
TMPDIR=/var/tmp python deploy/check-release-maintenance.py "$REL"   # /var/tmp/w3-87fc787-maint.log MAINT:0
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS"  # /var/tmp/w3-87fc787-integ4.log EXIT:0
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS" --work REAL-WORK-ITEM-2026-09-10.json
# /var/tmp/w3-87fc787-work4.log EXIT:0
TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py
# 1820 passed, 2 skipped, 594.31s  /var/tmp/sb-full-pytest-e0143d4.log
uv run ruff check --no-cache sb/compile.py sb/conflict.py sb/security.py sb/web.py
```

## R1–R7

| ID | 상태 | 증거 |
|---|---|---|
| R1 | verified 격리 | 커밋된 손편집 제안. HEAD seeding 없음 |
| R2 | verified 격리 | 철회 store 유실 fail-closed |
| R3 | verified 격리 | symlink rollback EXIT 2 |
| R4 | implemented_unverified | 격리 transport 전송 직전 JSON. persistAssembledContext→prepareModelTransport. live LLM 없음. `R4-TRANSPORT-SESSION-2026-09-11.json` |
| R5 | verified 격리 | compact only |
| R6 | implemented_unverified | Chrome fail+recover. sealed 기본 검색 1. `R6-SEALED-RETRIEVE-2026-09-11.json` |
| R7 | implemented_unverified | 이 단일 핀. 현재 트리 전체 회귀 1820 passed / 2 skipped |

## M1–M14 (CURSOR-HANDOFF 7절)

| ID | 원문 | 상태 |
|---|---|---|
| M1 | 실제 신원/권한 | blocked_external 실로그인 |
| M2 | 실제 업무 공유 계보 | implemented_unverified 격리 `--work`. 실사용자 업무 blocked_external |
| M3 | 철회 수명 | implemented_unverified R2/R3 |
| M4 | 검증 결과 원계보 | implemented_unverified 격리 |
| M5 | native 사본 수명 | blocked_external 인증 복사 금지 |
| M6 | 단일작성자·전환복구 | implemented_unverified 격리. 운영 writer drain |
| M7 | 전체 읽기 범위 | implemented_unverified fixture |
| M8 | 제품별 공유연결 | blocked_external 실클라이언트 |
| M9 | 문맥·compaction | implemented_unverified R4. live 세션 없음 |
| M10 | 검색품질 | implemented_unverified 하드셋. user_curated 없음 |
| M11 | 성능 | implemented_unverified MCP 30/100/300 p50/p95. `M11-MCP-CORPUS-LATENCY-2026-09-11.json` |
| M12 | DR | implemented_unverified 복원+deny compile+sealed 1 |
| M13 | GUI | implemented_unverified Chrome |
| M14 | 관계검색 | not_implemented |

## 외부 입력 (한 묶음)

실로그인·운영 drain 허가·인증 복사 금지 유지·user_curated 질문·native 클라이언트 세션. 전환 절차는 drain 후에만.

## 복구

운영 current `41f0751` 유지. 철회 store가 있으면 구버전 자동 링크 복원 거부.
