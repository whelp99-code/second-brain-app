# 배치·원본 선택 누적 전체 회귀

제품 소스7674b63에서 지정 전체 명령 `uv run pytest -q --ignore=tests/test_embeddings.py`를 실행했다. 결과 **1,563 passed, 4 failed, 2 skipped / 303.25초**, 종료1. [전체 로그](BATCH-FULL-REGRESSION-2026-09-10.txt).

실패3개는 ingest budget 테스트가 sources=inbox 설정을 유지하면서 first/deferred/small 또는 empty 대역을 주입한 불일치였다. 새 원본 사전 검증이 이를 거부했다. 테스트 설정에 실제 대역 ID를 명시해 예산 경계·커서·유예 검증을 계속 수행하도록 수정했다.

실패1개는 웹 pinned generation 테스트가 이전 log.md 요약을 기대한 경우였다. pinned 원장에 고유 ID/failed 실행을 기록하고 요약·last_run_status·실패 목록이 pinned 세대에서 나오는지 검증하도록 수정했다. 제품의 설정 제한이나 snapshot 경계를 완화하지 않았다.

수정 후 실패파일 및 configured selection/run_all 관련 **24 passed / 4.64초**, Ruff/diff 통과. 전체 검사를 다시 실행한 것은 아니므로 최신 전체가 모두 통과했다고 표현하지 않는다. 이번 커밋의 제품 소스 변경은 없으며 테스트·보고서 수정이다.

병행 조사에서 일반 SearchIndex의 VERIFIED가 registry의 page_id별 ACTIVE/APPROVED로 계산되고 source_hash를 대조하지 않음을 격리 재현했다. [승인 표시·본문 검증 경계](REGISTRY-CONTENT-BINDING-AUDIT-2026-09-10.md). 이를 scoped JARVIS 인증 우회나 새로운 자동 승인 구현으로 보고하지 않는다. 관리형 자동 승인 연결·운영 및 M1–M14는 남는다.
