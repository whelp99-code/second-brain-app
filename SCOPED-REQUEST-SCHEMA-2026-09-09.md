# scoped v4 요청 원장의 명시적 스키마 전환

2026-09-09. 이전 단계의 v4 codec 구현·실행 검증·커밋은 진전으로 확인했다. 이번 단계는 v4 요청 수락에 필요한 원장 스키마 전환을 구현했다.

## 구현과 경계

`sb/request_schema.py`의 기존 v3 전환 알고리즘을 공통 함수로 추출하고 `migrate_scoped_v4`를 추가했다. 기존 1/2→1/2/3 전환의 목적과 결과는 유지한다. 새 함수는 1/2/3→1/2/3/4를 명시적으로 전환하며 더 오래되거나 알 수 없는 제약은 거부한다. BEGIN IMMEDIATE 이후 현재 schema를 다시 확인하여 복수 초기화가 같은 결과로 수렴한다.

기존 DDL에서 버전 CHECK만 바꾸고 모든 열·다른 CHECK·기본값을 유지한다. 데이터 복사·테이블 교체·의존 객체 복구를 하나의 transaction으로 묶고 외래 키를 전후 검사한다. 실패하면 원래 테이블로 rollback하고 외래 키/legacy ALTER 설정을 복원한다.

**RequestStore 자동 초기화에는 아직 연결하지 않았다.** 현재 RequestExecutor가 v4를 처리하지 않으므로 새 schema만 운영에 적용하면 구형 초기화가 `REQUEST_SCHEMA_UNSUPPORTED`로 거부된다. 이것은 호환 인수 완료가 아니며 자동 전환을 보류하는 근거다. v4 수락·실행·영수증·관련 reader를 함께 연결한 후 활성화해야 한다. 운영 원장을 수정하지 않았다.

## 검증

- schema/store/v4 codec/walking skeleton **26 passed / 3.41초**. 새 schema 집중 검사 5개는 이 실행에 포함된다. 전체 Ruff 및 diff 검사 통과.
- 원본 데이터, 자식 외래 키, view, index, trigger 보존; schema 5 및 잘못된 본문 거부; ALTER 단계 강제 실패 후 dump 전체 동일·재시도 성공; caller transaction 안에서 전환 거부를 확인했다.
- 실제 임시 RequestStore에 기존 `accept_stable_v3_request`로 요청 하나를 수락했다. 이어 별도 Python 프로세스 2개를 준비시킨 뒤 전환을 실행했다. **17개 테이블 데이터·53개 인덱스/트리거/뷰·pending 파일1개 보존**, 외래 키 오류0. 실제 동시 잠금 경합이 반드시 발생했다는 주장은 하지 않는다. 두 독립 초기화의 성공·동일 결과를 확인한 증거다.
- [실행 결과](SCOPED-REQUEST-SCHEMA-2026-09-09.json), `scripts/scoped-request-schema-acceptance.py`로 재현한다. 합성 요청과 임시 DB이며 완료 후 정리했다. 전체 Python·JARVIS 검사를 재실행하지 않았다.

## 이어갈 작업

v4 원장 수락에는 요청 digest·scope identity·원본 v3 요청·provider·소비된 검토 증거가 함께 보존돼야 한다. 기존 요청을 재수락하거나 범위를 변경하는 대신 같은 원장의 idempotency/lane과 receipt 검증을 사용해야 한다. 자비스의 검토 단일 소비와 outbox 삽입, provider 수락·실행·완료 영수증, 인증된 다른 agent 새 세션 회수까지 연결하는 전체 목표는 남아 있다. 이번 schema 함수만으로 v4 저장 지원 또는 운영 완성을 선언하지 않는다.
