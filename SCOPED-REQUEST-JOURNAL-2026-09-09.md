# v4 요청의 기존 원장 식별자·재개 연결

2026-09-09. 이전 schema 전환 구현·검증·커밋은 진전으로 확인했다. 이번에는 scoped v4 metadata와 기존 RequestStore의 replay 규칙을 연결했다.

## 변경

`prepare_scoped_journal_entry`는 v4 원본을 기존 codec으로 다시 검증하고 RequestIdentity를 만든다. request ID/digest·idempotency는 v4 값을 보존하며, payload_digest에는 원문 content digest, scope_digest에는 후보·출처·owner·projects·revision이 결합된 scoped identity digest를 저장한다. 기존 `legacy:<candidate>:remember` lane을 공유하므로 같은 후보가 기존 v3와 다른 scoped key로 두 번 등록되지 않는다. 검토 receipt를 effect delegation 필드에 위장해서 넣지 않는다.

`RequestStore(..., scoped_v4=True)`는 명시적 내부 호출에서만 v4 schema 초기화·재개를 허용한다. 기본값은 False이며 기존 v3 초기화 경로를 유지한다. 기존 v4 원장을 기본 V3-only 초기화로 열면 지원하지 않는 schema로 거부한다. 운영 config/CLI/MCP에는 이 옵션을 연결하지 않았다.

준비 entry 생성 자체는 쓰거나 수락하지 않는다. 이번에 검증한 `RequestStore.accept`는 내부 원장 metadata 저장 API다. 아직 공개 v4 요청 수락 함수, 실제 요청 파일 발행, 검토 소비 증거 및 실행기 연결이 없으므로 이 결과를 provider accepted 영수증으로 내보내면 안 된다.

## 검증

- scoped journal/store/schema/v4 codec/walking skeleton **29 passed / 3.47초**. 전체 Ruff·실행 helper Ruff·diff 검사 통과.
- 재개 후 동일 identity의 replay, scope/payload 변경 거부, v3 후보를 v4로 중복 등록할 때 lane 충돌, 기본 journal의 v4 INSERT rollback과 alias 미생성을 확인했다.
- 서로 다른 Python 프로세스 2개가 동일 임시 원장을 열었다. 첫 실행 replayed=false, 두 번째 true, scope/request digest 일치. 각각 범위 digest 변경 시 오류와 DB dump 전체 불변을 확인했다. provider 호출0.
- [실행 JSON](SCOPED-REQUEST-JOURNAL-2026-09-09.json), `scripts/scoped-request-journal-acceptance.py`로 재현한다. 합성 v4와 임시 원장 metadata만 사용했고 모두 정리했다. 전체 Python/Vitest 및 실제 운영/모델 세션 검사를 재실행하지 않았다.

## 보류·다음 연결

다른 프로젝트나 버전별로 새 lane을 만들어 동일 후보를 중복 저장하는 방식은 보류했다. 구형 실행기가 v4를 읽도록 version 검사를 완화하지 않았다. 명시적 v4 원장을 운영에 활성화하면 현행 기본 진입점이 재개하지 못하므로, 수락·실행·조회 경로를 함께 연결하기 전 배포하면 안 된다.

다음은 실제 v4 요청 bytes의 원자적 발행·replay, 자비스 검토 단일 소비와 outbox 삽입, provider 실행기의 source_access 전달 및 완료 영수증 검증이다. 이 연결과 실제 MCP→다른 agent 인증 세션 회수, M1~M14 및 운영·삭제·복구 인수까지 전체 완성 목표에 남아 있다.
