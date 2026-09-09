# Scoped 완료 관찰의 영구 기록

## 구현과 경계

JARVIS에 migration079와 observeMemoryScopedCompletion을 추가했다. 원래 scoped binding/dispatch attempt/reconciliation fence와 MCP에서 검증한 status·현재 artifact의 내용 없는 증거를 연결한다. 본문이나 excerpt를 기록하지 않는다. 기존 migration bytes 및 legacy settlement 검사는 변경하지 않았다.

클라이언트 withRememberedCompletion은 기존 상태→페이지→상태 검증을 재사용한다. 소비 callback 안에서 현재 로컬 읽기 권한을 다시 검사할 수 있으며 callback 반환 후 검사 함수는 사용할 수 없다. 네트워크 조회가 끝난 후에 DB IMMEDIATE 트랜잭션을 시작한다.

기록자는 원래 요청을 spool/원장과 다시 대조하고 현재 worker lease를 검사한다. 원래 provider 수락 기록과 관찰 삽입은 같은 트랜잭션이다. commit 직전에 현재 읽기 권한/취소/lease/원래 요청을 다시 검사한다. 만료가 더 짧아졌으면 과거 만료 범위를 기록하지 않고 rollback한다. 같은 fence의 같은 증거는 replay, 다른 증거는 conflict다. DB trigger가 UPDATE/DELETE/REPLACE 및 잘못된 attempt/lease 결합을 거절한다.

이 결과는 completion_observation_recorded다. 현재 provider snapshot을 새로 갱신하거나 쓰기 권한을 부여하지 않는다. 아직 outbox settled 또는 control completed를 만들지 않는다. 소비 port는 신뢰된 내부 클라이언트 조합이며 외부 JSON을 관찰로 변환해 넣는 API가 아니다.

## 검증

- 완료 관찰/재조정/수락/신규 기록 관련 33개/4파일 통과(29.13초).
- 기존 migration bytes·적용, production 구성, 요청 상태, scoped client 추가 회귀 22개/4파일 통과(10.32초). 총55개/8파일이다.
- 격리 TypeScript emit 및 변경 파일 ESLint 통과.
- 신규 기록 테스트는 trusted client port stub으로 transaction 실패를 주입한다. 정상 replay/변경 conflict, 현재 권한 철회, stale worker, 만료 단축, SQL 삽입 실패에서 관찰/수락/event/worker 변경의 원자적 rollback을 확인했다. callback 반환 후 refresh 재사용도 거절된다.
- 실제 production client→stdio MCP에서는 원래 scoped 요청으로 status/페이지/proof를 검증하고 원래 자비스 DB에 관찰1건을 기록했다. 두 번째 조회는 같은 observation ID로 replay했다. 별도 수락 기록 프로세스의 commit 후 exit73 및 replay에도 관찰1/attempt1/수락event1/FK0을 유지했다.
- exit73은 기존 수락 기록 프로세스에서 발생한다. 이번 새 관찰 트랜잭션의 정확한 commit 경계 강제 종료를 별도로 검증한 것은 아니다.
- 패키징은 새 임시 디렉터리에서 실행했고 migration079 bytes 일치를 확인했다. SHA256: 149a60afd2b431fbd483790a8e9fe1b2e6daeee573af87d361775cf1f8475abe.

[실제 프로세스 결과](SCOPED-DURABLE-OBSERVATION-2026-09-09.json). 인증 세션·시계·provider 내부 쓰기는 fixture다. 운영 DB/설정/서비스와 vault는 변경하지 않았다. SB 제품 소스 변경이 없어 전체 SB 검사 수치를 이번 결과로 재사용하지 않는다.

## 후속 완료 조건 및 보류

다음은 영구 증거 재구성 검증과 scoped settlement, 원래 command/승인 및 현재 철회/suppression 검사를 결합한 control 완료다. 새 관찰의 commit 전후 별도 프로세스 복구도 이 연결에서 검증한다. 기존 legacy receipt 식별자 검사를 제거해 scoped 결과를 성공으로 통과시키는 방식은 보류한다.

공개 쓰기 인증, 최초 활성 세대 이전 상태 조회, 실제 서로 다른 에이전트의 저장→새 세션 재조회, 삭제/복원·정책 철회 전체 범위, 에이전트별 수집/주입, 한국어 검색 평가와 운영 복구를 포함한 M1–M14 전체 목표는 유지한다.

JARVIS 구현 커밋: `67abebd`.
