# 복원 수정 이후 전체 회귀

검증 소스: 1cfeafb551385d73e71a9e5c6f5341aff545b022. 명령 `uv run pytest -q --ignore=tests/test_embeddings.py`, exit0, **1491 passed, 2 skipped in 282.63s**. 원시 요약 출력은 동명 txt에 기록했습니다. `uv run ruff check sb tests`도 통과했습니다. 최근 겹치는 삭제 범위, 개행 끝 경계, 위치 변경/복제 내용 탐지, strict 최종 검사, 관리형 staging 보호를 포함한 결과입니다.

실제 모델 선택 검사는 이번 명령에 포함되지 않습니다. 전체 회귀 통과는 운영 인수나 대규모 복원 지원 완료의 증거가 아닙니다. [복원 처리량 측정](RESTORE-SCAN-CAPACITY-2026-09-09.md)에서 1MiB 단일 파일도 현재 검사 예산에 따라 거부됨을 확인했으므로 대규모 복원 인수 보류를 유지합니다. 운영 서비스·DB는 변경하지 않았습니다.
