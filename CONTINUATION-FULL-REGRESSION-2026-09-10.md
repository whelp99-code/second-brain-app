# 인계 이후 전체 검증 갱신 — d4cbdda

인계서(`CURSOR-HANDOFF-2026-09-10.md`) 8-A의 첫 작업으로 현재 HEAD에서 전체 회귀·정적 검사를 다시 실행했다. 이전 13cab77 수치(1,767 passed)를 현재 결과로 복사하지 않는다.

## 대상 상태

- 작업공간 `/home/jm/orca/projects/second-brain-app`, 브랜치 `codex/shared-memory-completion-20260907`.
- HEAD `d4cbdda68932b788f91b462d283249b84779e344` (직전 개발 커밋 `b0d35b5`, 그 뒤 인계 문서 커밋).
- 추적 파일에 미커밋 변경 없음. 기존 미추적 자료(`2n`, `phone-history/`, `sb/*.bak-20260906-214804`)는 건드리지 않았다.
- 실행 중 제품 코드·테스트를 수정하지 않았다.

## 실행 결과

| 검사 | 명령 | 결과 |
|---|---|---|
| 전체 회귀 | `TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py` | **1,785 passed / 2 skipped, 569.06초, exit 0** |
| Lint | `uv run ruff check --no-cache sb tests` | All checks passed, exit 0 |
| 타입 | `uv run basedpyright sb/pipeline.py sb/connectors/sessions_opencode.py` | 0 errors, 0 warnings, 0 notes, exit 0 |

원본 출력은 [실행 로그](CONTINUATION-FULL-REGRESSION-2026-09-10.txt)에 보존했다.

## 범위와 한계

- `tests/test_embeddings.py`는 리포 지침대로 제외했다. 선택적 실제 LLM/DB 검사는 별도 환경 조건이며 이 실행에 포함되지 않았다.
- 13cab77 대비 증가분(1,767 → 1,785)은 그 뒤 커밋(`1bdfb17`…`b0d35b5`)이 추가한 읽기 실패·재유입 검증·깊은 JSON 격리 회귀를 포함한다. 과거 확대 회귀 97개와 이 전체 수치를 합산하지 않는다.
- 이 실행은 같은 시간대에 진행한 설치 후보 준비/인수와 CPU를 공유했다. 569.06초를 단독 성능 기준으로 쓰지 않는다.
- 전체 통과는 소스 회귀의 결과이며, 실제 운영 전환·실제 업무 인수·M1–M14 완료를 뜻하지 않는다.
