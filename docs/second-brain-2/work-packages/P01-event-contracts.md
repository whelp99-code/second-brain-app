# P01 — 사건·시간·상태·민감도 계약

상태: 명세 등록, 구현/검증 NOT_RUN. Refs #3. 선행 P00 (#4). R1 / REQ-01·REQ-06 / Core / 4–6인일 추정.
기준: 개발계획 v1.0 4·12·13장. 원문 파일명·SHA-256과 GitHub 기준점은 #3을 따른다. 신규 경로·API는 제안이며 현존·가동을 의미하지 않는다.

## 목표와 호환성
문서 중심 기억에 사건을 연결하되 기존 `MemoryRecordV1` ID/digest/consumer 계약을 깨지 않는다. `LifeEventV1`과 연결 레코드를 별도 추가하고 L0 계약은 stdlib-only, frozen data로 둔다. 접수 상태, 실제 사건 상태, 근거·검토 상태를 혼합하지 않는다.

## 필드 계약
|그룹|필드와 규칙|
|---|---|
|식별|event_id는 개정에도 안정; revision은 증가; source_id/source_item_id/source_version 보존|
|종류/상태|event_type 허용 목록; planned/occurred/cancelled/unknown|
|근거/검토|observed/inferred/user_asserted와 unreviewed/confirmed/rejected/disputed를 별도 필드|
|시간|occurred_start/end, observed_at, recorded_at, timezone, time_precision, valid_from/until|
|관계/근거|entity_refs와 evidence_refs; source identity/hash/span/record ID/digest 포함|
|정책|sensitivity/scope, inherited/local_only/explicitly_allowed|
|결측|value=null + value_status + reason; missing/unavailable를 숫자 0 또는 false로 바꾸지 않음|

## 구현 체크리스트
- [ ] 명세·직렬화 예제·경계 validator를 먼저 고정하고 구버전 소비자 호환 fixture를 작성한다.
- [ ] 사건 ID와 항목 버전·멱등키 충돌 규칙을 정의한다. 기기 시각이나 본문만으로 ID를 만들지 않는다.
- [ ] 모든 시각을 명시 시간대/정밀도로 파싱한다. 발생 시각 미상은 null 또는 범위이며 파일 수정일을 대입하지 않는다.
- [ ] KST 사용자 날짜→UTC 질의 구간 변환, 여행/DST/자정/지연 업로드 사례를 포함한다.
- [ ] planned 일정이 observed라는 이유로 occurred로 승격되지 않도록 상태전이를 제한한다.
- [ ] source policy 상속을 정의하고 여러 출처 결합 시 더 느슨한 외부 전송 정책으로 내려가지 않게 한다.
- [ ] `expected_revision`, receipt, 오류 분류, schema_version/capability 버전의 계약을 고정한다.
- [ ] 기존 MemoryRecord 링크와 새 사건 revision 연결을 정의하고 기존 digest 재해시가 없음을 검사한다.

## 예상 코드 책임
`sb/life_contracts.py`, `sb/life_normalize.py`, 계약 예제/validator/tests는 신규 후보. 기존 `sb/contracts.py`, `sb/memory_records.py`는 호환성 비교 대상이며 무조건 교체하지 않는다. 이 PR의 실제 변경은 이 명세 파일뿐이다.

## 인수시험
- AC-01/02: 같은 입력 10회는 동일 사건 식별자, 날짜가 다른 동일 본문은 서로 다른 사건.
- AC-03: 10시 일정→취소와 18시 녹음 업로드에서 예정/실제/발생/접수가 혼동되지 않음.
- AC-04: KST 자정, DST 반복 시간, 범위 시각, timezone 미상 처리에서 손실·이중 배치 없음.
- 잘못된 enum, NaN/inf confidence, 잘못된 시간 범위, scope 없는 입력을 명시적으로 거부/격리.
- 구버전 record/요청 fixture 직렬화 불변; L0에 I/O·third-party import 없음.

## 오류·보안·적용
모호한 시각을 정밀값으로 조작하지 않는다. 개인정보와 정책은 별개로 취급하며 저장 동의가 외부 모델 동의가 되지 않는다. 상세 오류는 필드·코드만 반환하고 원문 비밀을 재노출하지 않는다. schema 변경은 추가형을 우선하고 feature OFF에서 기존 경로를 유지한다.

## 의존성과 완료
P02/P03/P04/P10의 선행 계약. P05 이후 집계는 이 필드를 재정의하지 않는다. 계약 예제, 실패 테스트, 회귀 결과, ID 호환성 증거와 독립 검토가 있어야 구현 인수 가능하다. 현재 구현 NOT_STARTED, 모든 실행 검증 NOT_RUN.
