# Grok 최종 제출 — Codex 독립 검증용

인계: [GROK-INTEGRATED-COMPLETION-HANDOFF-2026-09-11.md](GROK-INTEGRATED-COMPLETION-HANDOFF-2026-09-11.md). 착수: [ACK](GROK-HANDOFF-ACK-2026-09-11.md). **운영 전환 없음. 메인 기억 저장소 완성 아님.**

## 버전

| | |
|---|---|
| source | `63bdaf68e7f2079f320ad4c63574ed291fa4d5a2` tree `cd2babee91a3c896779b202cef507a8f0ec63b30` |
| 후보 | `/var/tmp/sb-candidate-63bdaf6/releases/3d36c4048c1f31f2c12b25c6bb9b8f23d88c5fb1` |
| wheel SHA-256 | `2dd0ae860946b42daf2a4439c1f8fb02c6b6cdb920bfe5801c1a9e33aaf03afc` |
| 준비 시 working_tree_modified | true (미추적 bak/2n/phone-history. git-archive는 HEAD) |
| JARVIS | `/var/tmp/jarvis-artifact-eeac005/source/dist` (소스 `eeac005`, artifact `80e3c6a1…`). `3d36c40` 유지보수/연동/`--work` EXIT 0. 운영 CC 불변 |
| 운영 current | `41f0751` 유지 |

이전 실패 증거 `CODEX-6FB150B-RECHECK-2026-09-11.json`은 덮지 않았다.

## A–F / M1–M14

| ID | 상태 | 증거 |
|---|---|---|
| A 편집/정정 | **verified** (격리) | 관리형 compile `USER_EDIT` 보존·무수정 정정. probe `edit_after=true`, proposals=1 |
| B 철회/복원 | **implemented_unverified** | flock·symlink·새 키. `check-rollback-compat.py`가 store가 있을 때 `41f0751` 자동 rollback을 EXIT 2로 거부. 복구는 새 바이너리+격리 restore |
| C 검색·문맥 | **implemented_unverified** | SQL/record Unicode 일치. `assembleModelRequest`가 확정 기억 본문·출처·버전·잔여 예산을 넣음. live 모델 **없음**. user_curated **blocked_external** |
| D native 수명 | **blocked_external** | 인증 복사 금지. 빈 프로필은 제품 미지원으로 일반화하지 않음 |
| E 지연/DR/GUI | **implemented_unverified** | MCP 3.535s. 복원 dest `remember` 16.9s. Chrome dump-dom 후 실패 행 유지. timeout 목표 아님 |
| F 후보/런북 | **implemented_unverified** | `3d36c40` × JARVIS `eeac005` dist 게이트 EXIT 0. MCP 4프로필 3.535s. 전환 미실행 |
| M1–M7 운영 종단 | **blocked_external** | drain_authorized=false |
| M14 그래프 | **not_implemented** | 핵심 인수 아님. 채택 보류 |

## 테스트

```bash
cd /home/jm/orca/projects/second-brain-app
TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py
# 1813 passed, 2 skipped, 546.76s, EXIT 0
uv run ruff check --no-cache sb tests   # 통과
TMPDIR=/var/tmp python deploy/prepare-release.py /var/tmp/sb-candidate-63bdaf6 --offline
TMPDIR=/var/tmp python deploy/check-release-maintenance.py /var/tmp/sb-candidate-63bdaf6/releases/3d36c4048c1f31f2c12b25c6bb9b8f23d88c5fb1
TMPDIR=/var/tmp python deploy/check-release-integration.py /var/tmp/sb-candidate-63bdaf6/releases/3d36c4048c1f31f2c12b25c6bb9b8f23d88c5fb1 /var/tmp/jarvis-current-pair-_mq15nmd/source/dist
TMPDIR=/var/tmp python deploy/check-release-integration.py ... --work REAL-WORK-ITEM-2026-09-10.json
```

로그: `/var/tmp/sb-full-pytest-handoff.log`, `/var/tmp/w3-3d36c40-*.log`. embeddings 제외.

## 운영

전환하지 않았다. 새 JARVIS lockfile artifact와 drain 허가 없이 `3d36c40`를 운영에 올리지 마라. 롤백 ID `41f0751`은 철회 store를 읽지 않는다.
