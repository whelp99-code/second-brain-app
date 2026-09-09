# 웹 최근 단계 실행 이력

status_snapshot에 최근 단계 실행 10건을 추가하고 실제 웹에 표시한다. mode=ro SQLite 연결로 run_stage를 조회하며 실행 ID·단계·상태·오류 수·마스킹된 상세를 반환한다. 과거 스키마에 테이블이 없으면 빈 목록이다. 마지막 단계 성공과 전체 배치 성공이 다르며, 과거 실패 이력은 복구 후에도 남는다는 안내를 함께 표시한다.

기존 미해결 derivation 목록에 없던 단계 경계 예외를 확인할 수 있다. 전체 배치 ID나 영속적인 배치 집계 상태를 새로 구현한 것은 아니다.

초기 SQL에서 detail을 error로 잘못 지정한 회귀를 검사 중 발견해 수정했다. 최종 웹·운영·상세 검사 **30 passed, 10.03초**, Ruff 통과. 실제 실패 실험 vault를 읽는 웹 서버와 Chromium에서 HTTP mock 없이 단계7건·compile 정책 거부 표시·pageerror0을 확인하고 화면을 직접 검토했다. Browser plugin not available로 기존 Playwright를 사용했다. 화면: /var/tmp/sb-stage-history.png.

운영 vault·서비스는 변경하지 않았다. 개별 단계 이력과 미해결 실패 목록은 범위가 다르며 전체 배치 상태의 영속 집계는 후속 과제다.
