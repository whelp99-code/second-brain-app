# Grok 최종 제출 — `48686de` × JARVIS `635b4b5`

CODEX-FINAL-REVIEW-D26DD7A 후속. **운영 전환 없음. Codex 최종 인수 아님.** 옛 실패 `/var/tmp/codex-final-d26dd7a-uemozlpf` 보존.

## 핀

| | |
|---|---|
| SB source | `bda08041771859e129ec59c325d7fe259560ed4d` |
| 후보 | `/var/tmp/sb-candidate-bda0804/releases/48686de7744355ac51fa7a91807ce3160860b4d5` |
| wheel | `23025b89dd82d3022d291088d915f0eb6ad69fea21f3cd649c011ddcd7fb8c7b` |
| JARVIS | `635b4b5` `/var/tmp/jarvis-artifact-635b4b5/source/dist` |
| JARVIS inventory | `827217404a053390408d0284bbc76cef003997ef69dda223ce17e252cdedf17d` (34776) |
| 운영 current | `41f0751` |
| production_activated | false |

## 재현

```bash
cd /home/jm/orca/projects/second-brain-app
REL=/var/tmp/sb-candidate-bda0804/releases/48686de7744355ac51fa7a91807ce3160860b4d5
JARVIS=/var/tmp/jarvis-artifact-635b4b5/source/dist
TMPDIR=/var/tmp python deploy/check-release-maintenance.py "$REL"   # /var/tmp/w3-bda0804-maint.log MAINT:0
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS"  # integ EXIT 0
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS" --work REAL-WORK-ITEM-2026-09-10.json
TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py
# 1823 passed, 2 skipped, 604.65s  /var/tmp/sb-full-pytest-bda0804.log
uv run pytest -q tests/test_compile.py tests/test_revoked_keys.py tests/test_search.py tests/test_search_query.py tests/test_security.py
# 74 passed
```

## V1–V5 / R4–R6

| ID | 상태 | 증거 |
|---|---|---|
| V1/R4 | implemented_unverified | `persistAssembledContextSnapshot` → `modelTransport.record`. JARVIS 단위 7 passed. live LLM 없음 |
| V2 | verified 격리 | 실패 LLM cap=1에서 calls=1 |
| V3/R5 | verified 격리 | compact 빈도 순위. `wiki/a-focused`가 long 30개보다 앞. Unicode 일치 유지 |
| V4 | verified 격리 | dangling init marker symlink 거부, 외부 파일 없음 |
| V5/R6 | implemented_unverified | Chrome `#fix=` remember+run, `run_body_status=ok`, 실패 이력 보존, 선삽입 없음 |

## M1–M14 (CURSOR-HANDOFF 7절)

| ID | 원문 | 상태 |
|---|---|---|
| M1 | 실제 신원/권한 | blocked_external 실로그인 |
| M2 | 실제 업무 공유 계보 | implemented_unverified `--work`. 실사용자 세션 blocked_external |
| M3 | 철회 수명 | implemented_unverified R2+V4 |
| M4 | 검증 결과 원계보 | implemented_unverified fixture |
| M5 | native 사본 수명 | blocked_external 인증 복사 금지 |
| M6 | 단일작성자·전환복구 | implemented_unverified 격리. 운영 drain |
| M7 | 전체 읽기 범위 | implemented_unverified fixture |
| M8 | 제품별 공유연결 | blocked_external native |
| M9 | 문맥·compaction | implemented_unverified V1. live 세션 없음 |
| M10 | 검색품질 | implemented_unverified V3. user_curated 없음 |
| M11 | 성능 | implemented_unverified 기존 MCP corpus + V2 cap |
| M12 | DR | implemented_unverified 이전 sealed 회수 |
| M13 | GUI | implemented_unverified V5 |
| M14 | 관계검색 | not_implemented |

## 외부 입력

실로그인, drain 허가, native 클라이언트 세션, user_curated 질문. 전환은 drain 후에만.

## 복구

운영 `41f0751` 유지. 철회 store가 있으면 구버전 자동 링크 복원 거부.
