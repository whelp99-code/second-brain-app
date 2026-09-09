# 재시작 후 scoped 완료 관찰 증거 재구성

## 변경

readMemoryScopedCompletionProof는 trusted local DB와 원래 private spool에서 과거 관찰의 일관성을 재검증한다. 관찰 ID/hash/canonical JSON, 원래 request/binding/dispatch attempt/reconciliation fence, 정규화한 수락과 provider_accepted event, 상태/proof/receipt, 정확한 source 분류와 프로젝트 범위, page ID·generation·record ID 형식을 대조한다. 전송→수락→기록 시간 순서와 미래 관찰 거절도 검사한다.

이 함수는 읽기만 수행한다. 현재 reconciling인 원래 요청을 복원하는 기존 경로를 사용하며, 만료된 historical authorized_until을 현재 읽기 권한으로 사용하지 않는다. 반환값은 completion_evidence_consistent이고 outbox/control 완료가 아니다. 중첩 결과도 불변으로 반환한다.

저장된 내용 없는 관찰에는 원문 record bytes가 없으므로 원문을 다시 재생해 증명하는 함수가 아니다. 관찰 당시 인증된 MCP 소비 경로와 신뢰된 로컬 원장에 의존한다. DB 쓰기 권한을 가진 주체가 관련 증거 전체를 일관되게 다시 만들었을 때 이를 발신자 인증으로 거절할 수 있다는 주장은 하지 않는다. 최종 성공 처리에는 현재 원작업/승인·철회/suppression 및 현재 읽기 검사가 추가로 필요하다.

## 검증

- 신규12개 통과(15.03초): 만료 뒤 역사 재구성, 반환 불변, 미래 시각 거절, digest/provider/scope/proof/generation/record/acceptance/event/time/fence/attempt time 불일치 거절.
- 관련 회귀46개/5파일 통과(28.61초). 신규 최종 검사와 합계58개이며 초기 신규11개 실행은 중복으로 합산하지 않는다.
- 격리 TypeScript emit 및 변경 파일 ESLint 통과.
- 변조 테스트는 별도 임시 DB의 불변 trigger를 테스트에서 제거하여 reader를 직접 검증한다. 여러 변조는 관찰 최상위 hash도 다시 계산해 넣는다. 정상 쓰기에서 이 trigger를 우회하지 않는다.
- 실제 MCP로 기록한 동일 관찰을 새 Node 프로세스에서 읽기 권한 만료 후 복원한다. 다른 provider를 지정한 독립 프로세스는 거절한다. 같은 원장의 관찰1/attempt1/수락event1/FK0 및 reconciling 상태를 유지한다.

[실제 프로세스 결과](SCOPED-DURABLE-PROOF-READER-2026-09-09.json). 인증 세션·시계·provider 내부 쓰기는 fixture다. 운영 DB/설정/서비스·vault 변경 및 push/배포는 하지 않았다. SB 제품과 기존 migration bytes는 변경하지 않았다.

## 남은 연결

이번 reader는 현재 reconciling 상태의 역사 증거를 읽는다. 최종 scoped settlement의 receipt/event 설계와 원래 command/승인·현재 철회/suppression 검사, control 완료를 결합하는 구현이 다음 단계다. legacy receipt/식별자 검사 삭제 우회는 계속 보류한다.

새 관찰 commit 경계의 강제 종료 인수, 공개 쓰기 인증, 최초 활성 세대 이전 조회, 실제 서로 다른 에이전트의 저장·새 세션 재조회, 삭제/복원·전체 정책 수명과 M1–M14 운영 인수도 계속 남는다.

JARVIS 구현 커밋: `7ce5c10`.
