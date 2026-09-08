# 취소 결과 계약 v1 — provider local suppression

기존 취소 의향의 disposition=provider_local_suppression에 대한 결과다. 정정의 새 본문 적용
증거나 모든 native 보존면의 삭제 증거로 사용하지 않는다. 최종 전체 목표와 자비스 cursor의
로컬 suppression/전송 경합 검증 조건을 그대로 유지한다.

- 별도 도메인 `second-brain/memory-correction-cancellation-result/v1\0`으로 canonical JSON
  digest와 Ed25519 서명을 결합한다. 의향·정정·삭제 영수증과 혼용하지 않는다.
- exact intent/원 요청 envelope/lane/target/scope/tombstone과 실제 결과 세대에 결합한다.
- provider journal의 접수 시각, alias 8개 영구 차단, 활성화/reader drain/원본 처분,
  backup/export 체크포인트와 reingress 차단을 확인한 뒤 발행한다.
- 처음 발행할 때 기존 generation writer와 pending lock을 유지한다. 결과를 기존 request
  journal에 불변 행으로 저장한다. 영수증 저장 뒤 응답 유실은 동일 바이트 재생으로 복구한다.
- 처음 발행할 증거가 없으면 생성하지 않는다. 이미 저장한 결과는 후속 세대가 과거 파일을
  제거해도 재생할 수 있다. 현재 상태 조회와 과거 결과의 의미를 구분한다.
- Python producer/validator와 자비스 TypeScript validator를 실제 런타임에서 교차 검증한다.
  외부 MCP 취소 route/자비스 cursor는 검증된 결과와 로컬 suppression/전송 경계가 함께
  구현되기 전 자동 활성화하지 않는다. 이 결과만으로 전체 managed/native erasure를 완료시키지 않는다.

원본 제거 전에 후속 세대의 실제 본문·CAS·Git loose object 등을 검사하고 원장에 해당 세대의
내용 목록 digest를 저장한다. 결과의 generation_absence_digest는 이 검사에 결합된다.
원본이 사라진 재시작에서는 같은 파일 내용 목록인지 재확인하며, 증거를 소급 합성하지 않는다.
이 검사 후에도 현재 취소 키와 tombstone을 다시 확인한다.

결과 발행 API는 내부 issuer callback이다. MCP 결과 조회/취소 route와 자비스 DB 경합·cursor
완료는 이 계약의 producer/validator 검증 다음 단계다. 키 회전 시 과거 결과 조회의 공개키
보존/철회 정책도 별도 읽기 경계에서 완성해야 하며, 현재 issuer 재생은 설정된 provider 키로
검증한다. 재유입 예외가 아직 대상 접근을 허용하면 결과 발행을 거부한다.
