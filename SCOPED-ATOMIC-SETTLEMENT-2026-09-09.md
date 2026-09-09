# Scoped 기억 저장과 자비스 원작업의 원자적 완료

## 구현

settleMemoryScopedCompletion을 추가하여 현재 MCP 관찰·원래 요청/전송/수락·원작업 승인과 현재 철회/suppression·재조정 lease 검사를 한 완료 트랜잭션으로 연결했다. 네트워크 조회는 DB 트랜잭션 시작 전에 끝난다.

기존 관찰 기록 함수를 동기 내부 primitive로 분리하여 수락/관찰, scoped 전용 영수증, artifact_observed/settled event, outbox/candidate settled, control 효과·completed/event를 같은 IMMEDIATE 트랜잭션에서 기록한다. 마지막 현재 읽기 검사 이후 원래 권한과 lease를 다시 대조하고 상태를 변경한다. 실패는 전체 rollback한다.

새 migration080의 memory_scoped_settlements는 원래 관찰/control/fence에 결합된 불변 영수증을 보관한다. 기존 event 및 상태 전이 guard는 유지하고 scoped 전용 영수증을 추가했다. legacy receipt 식별자로 변환하거나 기존 legacy 검사를 제거하지 않았다.

readMemoryScopedSettlement는 원래 관찰 proof와 영수증/완료 상태/control 효과·완료 event를 대조하여 과거 완료 결과를 반환한다. 이미 완료된 요청의 settle 재호출은 provider 호출 없이 동일 결과를 반환한다. 시작 전에 취소된 호출은 완료 재조회도 거절한다. 역사 요청 복원은 settled까지 허용했지만 worker claim/release 경로는 reconciling 조건을 유지한다.

## 검증

- 관련62개/7파일 통과(55.94초). 최종 완료 event 누락 및 취소 재조회 검사를 추가한 뒤 focused5개 재실행 통과(11.65초); 이 5개는 중복으로 합산하지 않는다.
- 정상 기억/control 동시 완료 및 재조회 무변경, control effect 삽입 실패, control 상태 변경 후 실패, 최종 권한 철회, stale worker의 rollback을 확인했다.
- 타입 검사에서 신규 proof 반환 타입 참조 및 undefined narrowing 오류를 발견해 수정했다. 최종 격리 TypeScript emit과 변경 ESLint 통과.
- 실제 production client→stdio MCP로 저장 결과/proof/현재 페이지를 조회하고 완료했다. DB에서 outbox=settled, candidate=settled, 원작업 control=completed를 확인했다.
- 완료 트랜잭션 뒤 client 프로세스를 exit73으로 종료했다. 독립 Node 프로세스가 동일 receipt를 회수했고 settle 재호출 때 provider 호출0, settlement1/attempt1/FK0을 유지했다.
- 기존 관찰 전용 실제 프로세스 인수도 별도 fixture로 재실행하여 통과했다.
- 격리 패키징에서 migration080 원본/패키지 bytes 일치를 확인했다. SHA256 607e6ec5457cf95114fdc79ff91c5c365e7c8d0bf443fb47bdd49df09782c614.

[실제 프로세스 결과](SCOPED-ATOMIC-SETTLEMENT-2026-09-09.json). 신규 SQL failure 테스트는 오류/rollback이고, 이번 강제 프로세스 종료는 commit 직후다. 모든 commit 이전 명령 경계의 강제 종료를 별도로 검증했다는 의미는 아니다.

## 운영 완료와 남은 범위

이번에 완성한 것은 scoped 저장 결과와 자비스의 원래 기억 저장 명령을 원자적으로 완료하는 라이브러리 연결 및 실제 프로세스 인수다. 사용자 전체 업무의 성공이나 운영 서비스의 상시 자동 실행을 의미하지 않는다. 인증 세션·시계·provider 내부 쓰기는 fixture이며 운영 DB/서비스/vault는 변경하지 않았다.

운영 인증을 적용한 공개 쓰기, 실제 서로 다른 에이전트의 저장→새 세션 회수, 최초 활성 세대 이전 상태, 새 원장 테이블을 포함한 삭제·복원·보존/compaction inventory와 혼합 버전 rollout, 운영 환경 migration 인수, 클라이언트별 수집/주입, 한국어 검색 품질·운영 복구 등 M1–M14 전체 목표는 남는다. 이 검증 없이 운영 배포 완료로 판정하지 않는다. push/배포하지 않았다.

JARVIS 구현 커밋: `6241742`.
