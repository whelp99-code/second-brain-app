# 최근 수정 전체 회귀 — 2026-09-09

검증 커밋: cf2be5a3bc48a87859f83c2135aade27c65478eb.

`uv run pytest -q --ignore=tests/test_embeddings.py`: **1,435 passed / 2 skipped / 263.15초**, exit 0. `uv run ruff check sb tests`: 통과. 실행 중 소스 변경 없음.

이전 전체 회귀 이후 브리핑 재시도 보류, 컴파일 키 공유와 과거 이력 진단, 대용량 삭제 재유입 SQL 분할, 삭제 차단 원자 반영, inbox descriptor 읽기, 실제 프로세스 간 대기 기억 보존 검증이 누적되어 전체 검사를 갱신했다. 이번 검사에서 새 실패는 발견하지 않았다.

원본 출력은 `/var/tmp/second-brain-current-full-suite.out`, SHA256은 동명 JSON에 기록했다. 제외한 test_embeddings.py 및 skipped 2개를 실행 완료로 계산하지 않는다. pytest 요약에 skip 사유가 출력되지 않았으므로 이번 기록에서 개별 skip 원인을 단정하지 않는다.

전체 자동 검사 통과는 운영 활성화·실제 모델 간 최종 인수·모든 사본 삭제 완료의 증거가 아니다. 운영 서비스/설정/DB 변경 없음. 전체 M1–M14 목표는 계속 진행 중이다.
