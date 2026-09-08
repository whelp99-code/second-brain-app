# 명시적 취소 접수 경계

schema6 조회 계약을 유지하고 별도 cancellation-submit-schema7 프로필에 sb_submit_cancellation을 추가한다. 현재 취소 권한은 cancellation_public_keys의 별도 목적 키 집합과 revoked_jarvis_signing_key_ids로 제한한다. 과거 원 요청 검증은 jarvis_public_keys를 사용하며 과거 키가 현재 취소 권한을 대신하지 않는다.

서버는 접수 전 및 실제 접수 잠금 내부의 각 인증에서 설정을 다시 읽고 provider와 저장 경로가 최초 설정에 일치하는지 검증한다. 설정 누락/손상/경로 변경은 거부한다. 원 요청의 본문은 입력받지 않으며 기존 intent의 닫힌 모델과 크기 제한, 실제 대상/세대 확인, pending→generation→DB 잠금 순서를 재사용한다.

접수는 기존 request journal에 suppression_pending을 저장한다. 새 작업 큐·watcher·DB를 만들지 않고 원문을 처리하거나 결과를 발급하지 않는다. 실제 처분·서명 결과와 JARVIS 로컬 증거/cursor 연결은 별도 완료 조건이다. 구 MCP 프로필·frozen artifact bytes 및 기본 선택은 유지한다.

JARVIS는 schema7만 접수 쓰기를 허용하며 전송을 write queue·write timeout·uncertain 결과 정책으로 분류한다. 연결/대기 후 동기 beforeSend 검사에서 기존 DB 의향을 현재 시각·키·미전송 근거로 다시 검증한다. 응답은 intent/provider/original request/tombstone/접수 시각이 정확히 일치한 suppression_pending만 인정한다. 연결 유실은 자동 재시도하지 않으며 호출자가 같은 저장 의향으로 명시적으로 재접수한다.

frozen artifact는 contracts/second-brain-mcp-v5.json이고 schema 번호는 7이다. 기존 파일 이름/버전은 변경하지 않는다. 실제 격리 검증은 scripts/cancellation-submit-acceptance.py와 .mjs로 재현한다. 실제 원장과 세대·Node/Python 프로세스를 쓰되 고정 시각과 합성 기억/키를 사용하므로 운영 배포 검증으로 확대하지 않는다.
