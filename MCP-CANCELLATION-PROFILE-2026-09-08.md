# MCP 취소 조회 프로필 확장

기존 취소 상태 읽기 경계를 `cancellation-schema6`의 `sb_cancellation_status(intent_id, intent_digest, read_fence)`로 연결한다. 새 프로필만 도구 10개를 노출하고 기존 schema3/4/remember-schema5 계약 파일·기본 선택은 유지한다. schema6은 remember V3를 포함한다. 새 artifact는 second-brain-mcp-v4.json이며 파일 버전과 wire schema 번호는 기존 관례처럼 별개다.

조회 도구는 원장 snapshot의 현재 status fence를 검사하는 기존 read_cancellation_status에 직접 위임한다. 세대 pin/maintenance/issuer를 실행하지 않는다. 응답의 tombstone은 조회 원장 snapshot이고 중첩된 결과는 과거 완료 증거다. 현재 generation healthy나 모든 native 사본 삭제를 주장하지 않는다.

Config의 provider_result_public_keys와 revoked_provider_result_key_ids로 검증 키를 공급한다. provider_private_key에서 검증 키를 자동 유도하지 않는다. JARVIS reader 키는 기존 현재 키/철회 설정을 따른다. 설정 변경은 새 서버 인스턴스에서 반영되는 기존 정책을 유지한다.

JARVIS는 새 프로필에서만 메서드를 허용하고 고정 계약·도구 schema·응답 형식을 검사한다. 이 변경은 조회 전송 연결이다. 저장 결과의 의미 검증은 기존 cancellation result verifier를 사용하며 DB의 의향 생성·전송 경합·cursor 완료는 후속이다. 자동 취소 실행 route를 활성화하지 않는다.
