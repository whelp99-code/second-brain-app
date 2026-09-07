# 자비스 공통 기억 계약 조율 자료

2026-09-07. Second Brain 작업에서 작성한 후속 인계 파일이다. 후속으로 사용자의 연동 완성 지시에 따라 자비스 기억 소비 코드도 좁은 범위에서 수정했다. 최신 상태는 마지막 절을 따른다. 외부 메시지는 발송하지 않았다.

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


## 후속 구현 증거 — 2026-09-07

Second Brain `fb47313`, `77f3bad`에서 공개 metadata와 경로가 동등한 논리 page ID 투영을 수정했다. frozen schema 4/계약 해시/도구 수는 그대로다. 인계 문서의 초기 PAGE_MALFORMED는 수정 전 재현이며, 수정 소스 MCP로는 해당 오류가 사라졌다.

별도 managed generation에 실제 Vault로 기록한 한국어 단일 사실을 **기존 자비스 dist transport + read adapter**로 소비하여 `data 1`, `current`, `evidence 1`을 확인했다. mock transport나 adapter 검증 완화는 사용하지 않았다. 운영의 다중 사실/과거 기억은 아직 `conflicts` / `SECOND_BRAIN_RECORD_IDENTITY_INVALID`로 실패한다.

자비스 쪽 다음 변경 지점은 parser의 resolveDuplicates뿐 아니라 `second-brain-read-values.ts`의 집계 중복 키도 포함한다. 양쪽 모두 bound record의 ID/digest를 기준으로 하고, 같은 sid인 서로 다른 사실을 출처 중복만으로 충돌 처리하지 않아야 한다. 시간 계약은 producer valid_until 하루 고정과 consumer 페이지 expiry·record expiry·freshness를 함께 정리해야 한다. 현재 응답 검증을 끄거나 단순히 1일을 임의의 큰 수로 바꾸지 않는다.

요청 기억의 CAS/인용과 정정 이후 출처를 보강했으며 전체 Python 테스트 527개 통과·2개 건너뜀. 아직 운영 배포나 실제 자비스 outbox/settled 인수는 수행하지 않았다. 상세 증거는 [구현 원장](IMPLEMENTATION-STATUS.md)과 `/var/tmp/sb-b1-20260907/`에 있다.

## 최신 조율 결과 — 다중 record와 시간 처리

자비스 `5c44b1f`에서 두 중복 판정과 page별 선택 유실을 수정했다. `f9513d0`에서는 정상 유효기간 경과를 ID 오류와 분리하고, 조회 TTL을 사실의 종료와 구분했다. Second Brain의 하루 기본값 제거와 함께 실제 `업무` 검색이 invalid에서 **current / evidence 10**으로 바뀌었다. 현재·다음 날·35일 후의 주입 시계에서도 같은 record ID와 유한 응답 TTL을 확인했다. 단순 transport 응답이나 mock만의 검증이 아니다.

Python 전체 548개 통과·2개 건너뜀, 자비스 기억 관련 단위 244개 통과, 양쪽 변경 파일 lint 및 자비스 backend build 통과. strict wire 필드·계약 해시·generation binding·record digest 계산은 완화하지 않았다. `current`가 실행 성공이나 현실의 사실 검증을 뜻하지 않으며 untrusted/authority none을 유지한다.

배포 시 주의할 계약은 [시간 계약](MEMORY-TIME-CONTRACT-2026-09-07.md)에 있다. 소비자 선행, provider 실행 파일과 새 generation의 유지보수 경계 내 전환, 구형 selection/target 재조회가 필요하다. 기존 요청의 서명/digest를 새 값으로 치환하지 않는다. 이번 변경은 운영 배포가 아니며 actual candidate→outbox→settled→재사용과 실제 에이전트 앱 간 공유는 다음 인수 단계다.
