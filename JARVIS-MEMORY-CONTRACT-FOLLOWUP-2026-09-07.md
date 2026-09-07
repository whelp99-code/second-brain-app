# 자비스 공통 기억 계약 조율 자료

2026-09-07. Second Brain 작업에서 작성한 후속 인계 파일이다. 자비스 코드 수정이나 외부 메시지 발송을 수행한 문서가 아니다.

## 적용한 방향

[OSS 통합 계획](OSS-ABSORPTION-INTEGRATION-PLAN-2026-09-07.md)을 따른다. Second Brain 정본을 유지하고 자비스 및 여러 에이전트의 공통 기억 사용을 1차 범위로 한다. 다른 업무 실행자 연결은 후속이다.

## 현재 확정된 증거

- 기존 운영 transport는 Second Brain schema 4와 통신하고 검색·페이지 데이터를 반환한다.
- 실제 자비스 read adapter는 compile 산출물의 derivation_key 필드를 PAGE_MALFORMED로 거부한다.
- 해당 필드만 메모리상 제거한 진단에서 conflicts가 반환됐다. 자비스 evidence parser의 page_id+sid 중복 키가 같은 출처의 서로 다른 문장을 충돌로 분류한다.
- 시계를 다음 날로 옮긴 진단에서 RECORD_IDENTITY_INVALID. Second Brain이 valid_until을 updated UTC 날짜 + 1일로 생성하고 자비스가 만료를 거부한다.
- 서명된 fixture 요청은 proved로 저장되지만 Second Brain backup/restore 경로에서 인용 모델 불일치로 복원 실패했다.
- Second Brain의 입력 유실 R1은 작업공간 소스 수정·전체 520개 테스트 통과. 이번 후속 수정은 아직 운영에 배포하지 않았다.

## 조율할 변경

| 주제 | Second Brain 담당 | 자비스 담당 | 호환성 조건 |
|---|---|---|---|
| 공개 페이지 metadata | 내부 derivation_key 보존, 기존 공개 필드의 명시적 투영 | 허용 키 검증·실제 생성 산출물 fixture | 검증 완화나 원본 metadata 삭제 금지 |
| record 중복/충돌 | record ID·digest·출처/span 유지 | 동일 record의 재전달과 동일 출처의 여러 record를 구분. source sid 중복만으로 의미 충돌 판정 금지 | 출처가 같은 정상 문장 2개가 근거 2개로 유지 |
| 장기기억 시간 | 사실 유효기간·관측·재검토 분리 제안 | evidence freshness/expiry 및 소비 정책 | 하루 고정·31일 일괄 폐기 등 정책의 용도를 함께 확인. wire 확장은 버전 합의 |
| 프로젝트 범위 | 저장/검색/원문/파생 인덱스 공통 범위 모델 | 실제 허용 범위를 요청에 결합 | producer_agent 문자열은 권한이 아님. 현 scope 의미와 혼용 금지 |
| 문맥 공급 | bounded selection·근거·generation·전달 receipt 제안 | 실제 주입 성공 확인, session/compaction 구간 전달 | 선택만으로 전달 완료 처리 금지. strict schema 4 도구 목록 임의 변경 금지 |
| 전체 기억 순환 | 접수→처리→결과 record·복원 일치 | 검증된 업무 결과→candidate→outbox→settled→adapter 소비 | 양쪽 요청 ID·digest·generation을 연결한 증거 |

## 다음 인수 시나리오

하나의 실제 업무 결과를 자비스가 검증하고 저장 요청한다. receipt와 완료 상태를 확인한 뒤 다른 연결부가 같은 record를 회수한다. 같은 출처의 여러 사실, 다음 날 조회, 중복 요청, 정정·삭제, 프로세스 종료, 백업 복원을 포함한다. 운영 데이터의 사용자 내용을 테스트용 고정 fixture에 복제하지 않는다.

이 파일은 합의 요청이며 frozen schema·해시를 변경하지 않았다. 자비스 내부 실행·권한 결함을 Second Brain의 우회 코드로 해결하지 않는다.
