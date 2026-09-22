# 통합 개발 전 상태 보존

2026-09-21 사용자 요청에 따른 커밋·푸시용 작업 스냅샷이다. 출시 또는 운영 인수 완료가 아니다.

- 기준 HEAD: `8e9491aec02aeeff60672ebd51c624ae8fc5e81d`
- 보존 브랜치: `codex/pre-integration-snapshot-20260921`
- 포함: 기존 추적 파일 수정, Phone History 소스·계약·문서, 검토 보고서와 증거 JSON, AGENTS 문서, 통합 계획 및 Grok 지시서.
- 제외: `.claude/` 별도 worktree, `2n`, 날짜별 `.bak`, 에이전트 전송·감시 원시 JSON 3개, Phone History 생성 로그. 제외 파일은 로컬에 유지한다.
- 기존 보존본: `/var/tmp/second-brain-pre-sync-20260921/`.

이번 확인:

| 명령 | 결과 |
|---|---|
| `TMPDIR=/var/tmp uv run pytest -q tests/test_uploads.py tests/test_web.py tests/test_macos_client_contract.py` | 47 passed, 13.00초 |
| `uv run ruff check sb tests` | 통과 |
| Phone History에서 `python3 -m pytest -q` | 34 passed, 2 failed, 1 warning, 2.85초 |

Phone History 실패: JSON Schema에서 PhoneEvent 객체를 찾지 못하는 계약 생성기, privacy manifest의 수집 데이터 선언과 테스트 기대 불일치. 이 스냅샷에서는 수정하지 않고 통합 개발 잔여로 보존한다.

전체 pytest·basedpyright·build는 이번 보존 작업에서 재실행하지 않았다. 앞선 다른 기준선의 1,946개 통과 결과를 이 커밋에 적용하지 않는다. 기존 전체 타입 검사 실패도 해결됐다고 주장하지 않는다. 운영 전환은 수행하지 않는다.
