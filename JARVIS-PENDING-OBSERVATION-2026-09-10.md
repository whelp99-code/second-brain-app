# 운영 대기 상태 집계와 관측 권한 한계

관리자 읽기 재관측을 sudo -n으로 시도했으나 interactive authentication is required로 거절되어 실행되지 않았다. 인증 설정을 바꾸거나 비밀번호를 요청하지 않았다. 기존 관측불가17개를 해소했다고 주장하지 않는다.

새 deploy/check-jarvis-pending-state.py는 명시한 SQLite를 mode=ro/query_only=ON, 단일 BEGIN 읽기 트랜잭션으로 열고 정해진6개 큐의 상태별 건수와 커서/lease 건수만 반환한다. payload·소유자·요청 원문은 출력하지 않으며 drain_authorized=false를 항상 유지한다. 테이블 또는 상태 열이 없으면 오류이며 빈 큐로 해석하지 않는다. SQLite의 큰따옴표 미확인 열→문자열 fallback도 피했다.

실제 운영 관측 exit0: memory_outbox, memory_outbox_attempts, memory_candidate_dispatch_publications, collaboration_bridge_outbox, pre_gjc_report_outbox, outbox 모두0행. memory_effect_dispatch_cursor1행/active_lane_id 지정0행, gjc_runtime_leases1행, microloop_leases0행. 원시 지역 결과 /var/tmp/sb-jarvis-pending-20260910.json. 해당 이름의 큐만 관측했으며 전체 사용자 작업이 없는 증거는 아니다. lease 행1개만으로 실행 활성/만료를 판정하지 않는다.

격리 테스트3개/0.23초 및 Ruff/diff 통과. 비어 있지 않은 큐의 count 정확성, payload 미노출·DB bytes 불변, 스키마/열 부재 거부를 검사했다. 원래 운영 데이터와 서비스는 변경하지 않았다.

현재 대기 기록이0이어도 두 서비스의 DB 핸들과 관측 권한 부족은 남는다. 운영 전환은 보류한다. 다음 조율 대상은 authority와 dashboard의 새 작업 접근 중단 및 종료 후 관측 범위 확보다. 다른 독립 개발·검증은 계속 가능하며 전체 M1–M14를 완료/blocked 처리하지 않는다. push 없음.
