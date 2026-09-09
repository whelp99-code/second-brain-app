# Scoped 최종 완료를 위한 원래 권한·현재 철회 검사

## 구현

readMemoryScopedSettlementAuthority를 추가했다. 현재 reconciling 요청의 원래 private spool/binding/attempt를 복원하고 원작업 control command의 digest/target/action, 원래 redemption fence와 receipt, 승인 서명을 redemption 및 dispatched_at 시점에서 검증한다. dispatch spool의 원래 source request와 예상 artifact도 정확히 대조한다.

범위 검토는 이미 해당 outbox에 소비된 원래 검토를 재사용한다. source authority와 범위 검토의 만료는 원래 전송 시점에서 검사하지만, 현재 DB에 있는 원작업·승인·key/nonce/signature 철회, source 철회 및 projection suppression을 그대로 적용한다. 새로운 쓰기 권한이나 승인 소비를 만들지 않는다.

쓰기 승인 만료로 control 상태가 uncertain으로 복구된 경우도 역사 검증할 수 있다. 취소에 따른 uncertain은 철회 기록 때문에 거절된다. 완료 증거와 별도로 사용할 current read 및 reconciliation lease 검사는 호출자가 같은 DB 트랜잭션 안에 유지해야 한다.

반환값은 spent_authority_currently_unrevoked다. 이 결과 단독으로 outbox settled/control completed를 기록하지 않는다. 기존 provider 쓰기 validator의 현재 만료 조건을 완화하지 않았고, 서버 쓰기 권한 발행이나 배포 변경도 없다.

## 검증

- 신규8개 포함 관련48개/4파일 통과(53.36초).
- 정상 만료 후 역사 검증, expired control→uncertain 후 검증, source/범위 검토/dispatch command/key/command digest 철회, projection suppression 거절을 확인했다.
- suppression 테스트는 임시 DB view로 억제된 projection을 주입한다. 운영 DB나 실제 삭제 상태를 변경하지 않았다.
- 격리 TypeScript emit 및 변경 ESLint 통과.
- 실제 production client→MCP로 관찰을 기록한 뒤, 독립 Node 프로세스에서 권한 만료 후 control.recoverExpired를 실행했다. uncertain 명령의 원래 승인 관계를 검증했고, 임시 트랜잭션의 현재 철회는 거절했다. 해당 철회 트랜잭션을 rollback한 뒤 원래 결과가 다시 일치했다.
- 기존 증거 재구성, 다른 provider 거절, 관찰1/attempt1/수락event1/FK0 및 outbox reconciling 상태를 유지했다.

[실제 프로세스 결과](SCOPED-SETTLEMENT-AUTHORITY-2026-09-09.json). 인증 세션·시계·provider 내부 쓰기는 fixture이며 운영 전체 인수가 아니다. SB 제품 및 기존 migration bytes, 운영 DB/서비스/vault는 변경하지 않았고 push/배포하지 않았다.

## 남은 완료 연결

다음은 새 scoped settlement receipt/event와 원자적 control 완료 연결이다. 현재 읽기, 재조정 fence, 이 원작업 권한 검사와 durable evidence 대조를 한 완료 트랜잭션에서 실행하고 commit 전후 장애 복구를 검증해야 한다. legacy receipt/식별자 검사를 제거하는 우회는 계속 보류한다.

공개 쓰기 인증, 최초 활성 세대 이전 상태 조회, 실제 서로 다른 에이전트 저장→새 세션 회수, 정정/삭제/복원과 정책 수명, 수집/주입·한국어 검색 평가·운영 복구를 포함한 M1–M14 전체 목표는 유지한다.

JARVIS 구현 커밋: `bae55ae`.
