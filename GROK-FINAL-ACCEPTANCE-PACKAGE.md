# Grok 최종 제출 — `5b9687b` × JARVIS `6ce2356`

인계 A–F/M1–M14와 Codex R1–R7. **운영 전환 없음. 메인 기억 저장소 완성 아님.** 옛 실패 `/var/tmp/codex-final-26cf158-ufpeOW` 보존.

## 한 소스 / 한 설치 후보 / 한 JARVIS

| | |
|---|---|
| SB source | `edd2cb5cb547c72b169e86892a0ed07f5846b776` tree `d292c0802bde3a389ae5522d744b261f370336b9` |
| docs HEAD | `857f3aa` (이 패키지 커밋이 뒤를 이음) |
| 후보 | `/var/tmp/sb-candidate-edd2cb5/releases/5b9687bf912b9de314a7d4308b7e091f88d8008b` |
| wheel SHA-256 | `cdcb402733993f698b138f5f5a59ccf24f035517932b93ff6144d7f505548e83` |
| JARVIS | `6ce2356` `/var/tmp/jarvis-artifact-6ce2356/source/dist` artifact `sha256:2ec1f72757522e6d36f99b549c7dae4b3b787bea717395782d03964a1f104e42` |
| 운영 current | `41f0751` |

이전 `63bdaf6`/`3d36c40`/`eeac005`는 비교용이지 이번 제출 핀이 아니다.

## 재현

```bash
cd /home/jm/orca/projects/second-brain-app
TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py
# 1820 passed, 2 skipped, 545.98s  /var/tmp/sb-full-pytest-edd2cb5.log
TMPDIR=/var/tmp uv run pytest -q tests/test_compiled_marker_recovery.py tests/test_search.py tests/test_rollback_compat.py tests/test_revoked_keys.py
# 41 passed
TMPDIR=/var/tmp python deploy/prepare-release.py /var/tmp/sb-candidate-edd2cb5 --offline
REL=/var/tmp/sb-candidate-edd2cb5/releases/5b9687bf912b9de314a7d4308b7e091f88d8008b
JARVIS=/var/tmp/jarvis-artifact-6ce2356/source/dist
TMPDIR=/var/tmp python deploy/check-release-maintenance.py $REL   # MAINT:0  /var/tmp/w3-5b9687b-maint.log
TMPDIR=/var/tmp python deploy/check-release-integration.py $REL $JARVIS  # EXIT:0  /var/tmp/w3-5b9687b-integ.log
TMPDIR=/var/tmp python deploy/check-release-integration.py $REL $JARVIS --work REAL-WORK-ITEM-2026-09-10.json
# EXIT:0  /var/tmp/w3-5b9687b-work2.log
uv run python deploy/check-release-mcp.py $REL   # 3.543s then 3.422s, both EXIT 0
uv run python scripts/isolated-browser-fail-recover.py
```

## R1–R7

| ID | 상태 | 증거 |
|---|---|---|
| R1 | **verified** 격리 | 커밋된 손편집 테스트. HEAD seeding 삭제. `.sb/compiled` marker |
| R2 | **verified** 격리 | CLI/MCP/취소가 `effective_revoked_key_ids`. store 유실 fail-closed |
| R3 | **verified** 격리 | symlink store rollback EXIT 2. 가짜 python, 운영 경로 비의존 |
| R4 | **implemented_unverified** | `assembleModelRequest` JSON 431B, 본문·출처 있음, 예산 내. `persistAssembledContext`가 호출. **live LLM HTTP 없음** |
| R5 | **verified** 격리 | FTS MATCH AND 제거. Latin case/newline/quote 검색 테스트 |
| R6 | **implemented_unverified** | Chrome 실패+성공 행. 복원 dest remember 16.9s, inbox 회수. 검색 히트 0(미컴파일). MCP 재시도 2회 EXIT 0 |
| R7 | **implemented_unverified** | 이 문서의 단일 핀 |

## A–F / M1–M14

| ID | 상태 |
|---|---|
| A | verified 격리 (R1) |
| B | implemented_unverified (R2/R3). 운영 왕복 없음 |
| C | implemented_unverified (R5 SQL/record). user_curated blocked_external |
| D | blocked_external (인증 복사 금지) |
| E | implemented_unverified (MCP/브라우저/복원 쓰기) |
| F | implemented_unverified (`5b9687b` 게이트, 전환 없음) |
| M1 세대 포인터 | implemented_unverified 격리. 운영 종단 blocked_external (drain) |
| M2 컴파일 정정 | verified 격리 (R1) |
| M3 권한/철회 | implemented_unverified (R2/R3) |
| M4 검색 | verified 격리 Unicode/FTS (R5). 자연어/의역 0 |
| M5 native 수명 | blocked_external 인증 |
| M6 문맥 payload | implemented_unverified (R4, live 모델 없음) |
| M7 업무 `--work` | verified 격리 EXIT 0. 실사용자 ID blocked_external |
| M8 지연 | implemented_unverified MCP ~3.5s. remember 16.9s. timeout 목표 아님 |
| M9 DR | implemented_unverified 복원+쓰기. 검색 회수 0 |
| M10 GUI | implemented_unverified Chrome fail+recover |
| M11 쓰기비용 | implemented_unverified 이전 21s 표본, 이번 16.9s |
| M12 백업검증 | implemented_unverified 이전 격리 restore |
| M13 설치 게이트 | verified 격리 MAINT/integ/work EXIT 0 |
| M14 그래프 | not_implemented |

## 운영

전환하지 않았다. `check-rollback-compat.py`가 철회 store가 있을 때 `41f0751` 자동 링크 복원을 거부한다.
