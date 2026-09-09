# Scoped 원장의 관리 목록과 삭제 재구성 누락 수정

## 재현한 문제

새 binding/완료 관찰/settlement 테이블이 outbox 관리 surface의 SQLite prefix 목록에서 빠져 있었다. 또한 outbox를 삭제 대상으로 지정하면 새 종속 원장이 남아 fresh DB foreign_key_check가 실패했다. 최초 회귀2개가 모두 실패했다.

첫 수정 후에는 후보만 삭제 대상으로 지정하는 경로를 추가로 검사했다. 기존 copy filter가 outbox와 attempt/event는 제외하지만 새 관찰/settlement를 복사하여 외래키 오류가 남는 것을 재현했다(추가 검사1실패/2통과).

## 수정

- 기존 surface:43/outbox_attempts_events에 scoped binding·completion·settlement 테이블 prefix를 포함했다. surface 수70과 기존 catalog 계약을 변경하지 않는다.
- outbox 삭제 시 settlement→관찰→binding을 기존 event/attempt/outbox보다 먼저 제거한다.
- 후보 단독 삭제에서도 그 후보의 outbox에 연결된 관찰/settlement를 새 DB에 복사하지 않는다. binding은 기존 candidate_id filter로 제외된다.
- 불변 trigger는 기존 fresh-builder의 새 DB 재구성 구간에서만 해제/복원된다. 운영 원장의 trigger를 제거하거나 기존 migration bytes를 수정하지 않는다.
- 여러 DB 재구성과 실제 FD 보유 프로세스를 포함하는 기존 물리 삭제 테스트의 timeout을 5초에서15초로 조정했다. 검증 assertion은 그대로 유지했다.

## 검증

최종 관련13개/4파일 통과(24.21초), 격리 TypeScript emit 및 변경 ESLint 통과. 신규3개는 scoped inventory의 실제 테이블/행 수, 후보 단독 및 후보+outbox 삭제 재구성, 원본 보존과 FK 무결성을 확인한다.

초기 확대 실행에서 신규/관련11개는 통과했으나 기존 물리 삭제 검사가5초 timeout으로 실패했다. timeout만 늘린 재실행에서5.04초에 통과했고, 테스트 제한 수정 뒤 기본 실행과 최종 확대 검사도 통과했다. 이는 시간 제한 조정이며 제품 검사를 완화한 것은 아니다.

실제 production client→stdio MCP로 저장/완료하고 commit 후 exit73→새 프로세스 replay를 수행했다. 이어서 별도 Node 프로세스가 후보만 삭제 대상으로 지정한 fresh DB를 만들었다. settlement/관찰/binding/outbox/candidate의 대상 행은 새 DB0건, 원본 각각1건이다. FK0/integrity ok, 모든 trigger의 name/SQL 일치, control row 수 보존과 generation1→2를 확인했다.

[실제 프로세스 결과](SCOPED-LEDGER-COMPACTION-2026-09-09.json).

## 검증 범위와 다음 작업

신규 scoped 인수는 DB 원장 재구성이다. 실제 사용자 forget 요청으로 대상 결정→원문 파일·spool·요약·로그·백업 제거→복원 억제를 전부 검증한 것은 아니다. 민감 본문 물리 제거는 신규 scoped 인수에서 확인하지 않았고, 기존 알림 데이터/FD/백업 물리 삭제 회귀는 별도로 통과했다. 삭제 대상 선택·재유입 억제·restore와 운영 quiescence를 포함한 전체 수명주기 인수는 남는다.

운영 인증 공개 쓰기, 실제 서로 다른 에이전트의 저장/새 세션 회수, 최초 활성 세대 이전 조회, 클라이언트별 수집/주입·검색 평가·운영 복구를 포함한 M1–M14 목표는 유지한다. 이번 작업은 fixture 및 새 임시 DB만 사용했고 운영 DB/서비스/vault·기존 migration을 변경하지 않았다. push/배포하지 않았다.

JARVIS 구현 커밋: `282f0f9`.
