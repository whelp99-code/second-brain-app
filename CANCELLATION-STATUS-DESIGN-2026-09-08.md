# 취소 상태 조회 경계

기존 취소 결과 계약의 후속 구현. 별도 DB·서명 체계·자동 취소 정책을 추가하지 않는다.

`read_cancellation_status`는 기존 request journal을 SQLite `mode=ro`로 열고 한 읽기 transaction에서 검증된 tombstone snapshot, 현재 memory_status/status fence, 정확한 intent ID/digest, 저장 결과를 대조한다. fence는 genesis와 not_found에도 필수다. 원장이 없거나 손상된 경우 not_found로 숨기지 않는다. 현재 provider 식별자와 intent provider를 대조한다.

조회는 개인키·issuer·executor를 받지 않는다. 신뢰하는 provider 공개키와 철회 ID 집합으로 과거 결과를 검증하며 재서명하지 않는다. 저장 intent의 본문 digest를 요청 식별자와 대조하고, 저장 result digest·accepted_at·서명과 intent binding을 검증한다. 과거 intent TTL을 재접수 조건처럼 적용하지 않는다. 현재 fence TTL은 반드시 검증한다.

미접수는 not_found, 접수 이후 최종 결과가 없으면 suppression_pending, 검증된 최종 결과가 있으면 provider_local_suppressed다. generation_active만으로 최종 완료를 추론하지 않는다. 결과의 과거 tombstone과 응답의 조회 snapshot tombstone을 구분한다. 결과에는 원문이나 intent 전문을 포함하지 않는다.

이 라이브러리는 후속 MCP 상태 도구의 필수 읽기 경계다. 기존 schema3/4/5 계약을 바꾸지 않는다. 명시적 후속 프로필·JARVIS transport 연결·cursor 완료는 별도 인수 전까지 미완료이며 자동 route를 활성화하지 않는다. DB 조회의 snapshot 일관성은 동시 변경 이후 최신 상태까지 영구 보장한다는 의미가 아니다.
