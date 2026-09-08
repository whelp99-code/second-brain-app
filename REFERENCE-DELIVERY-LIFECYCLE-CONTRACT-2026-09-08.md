# 자비스 문맥 전달 수명 — 구현 전 계약안

상태: **C6/C7 구현에 사용할 계약안. 신규 wire 계약·DB migration·운영 활성화 완료가 아니다.**
근거: [실제 모델의 정정·삭제 및 과거 사본 재전송](REFERENCE-MODEL-LIFECYCLE-2026-09-08.md).
기존 [인계 계획](OSS-ABSORPTION-INTEGRATION-PLAN-2026-09-07.md)의 범위를 구체화한다.

## 1. 책임과 완료의 의미

세컨드브레인은 현재 세대·record·출처·삭제 high-water의 정본을 유지한다. 자비스는 기존
`MemoryReferenceReader`, `memory-read-privacy`, context/projection 저장 경로를 통해
실제 클라이언트에 보낼 문맥과 전송 상태를 관리한다. 세컨드브레인에 모델별 전달 원장이나
별도 권한 엔진을 만들지 않는다. 자비스의 작업·승인·실행 성공과 기억 전달 확인은 구분한다.

검증된 새 조회가 삭제 기억을 반환하지 않아도, 이미 받은 사본을 소비자가 다시 전송하면
모델이 그 내용을 사용할 수 있다. provider 삭제 성공을 기존 클라이언트 문맥·모델 서비스·
로그의 물리 삭제 증거로 표현하지 않는다. 소비자 전달 계보와 세션 처리를 별도로 구현한다.

## 2. 전달 상태와 재시도

아래 이름은 설계 상태다. 기존 테이블에 해당 의미가 있는지 대조한 뒤 필요한 확장만 한다.

| 상태 | 진입 조건 | 가능한 후속 동작 |
|---|---|---|
| prepared | 기존 reader가 원문·예산·scope/suppression·세대 검사를 통과 | 전송 직전 재검사. 준비만으로 세션 중복 억제 금지 |
| dispatching | 동일 세션/epoch/문맥에 대한 단일 전송 claim 획득 | claim과 제출 시각 기록. 두 worker가 같은 문맥을 동시에 전송하지 않음 |
| confirmed | 해당 전송과 상관관계가 있는 native client 확인을 관측 | 확인 수준을 기록하고 동일 유효 범위의 중복 억제 가능 |
| failed_before_submit | 전송 전에 실패했고 본문이 제출되지 않았음이 관측됨 | 새 검증 후 재시도 가능 |
| unconfirmed | 제출 후 timeout·프로세스 종료 등으로 수신 여부 불명 | 실패로 단정해 자동 재전송하지 않음. 기존 client 상태/동일 요청 재개 기능으로 확인 |
| invalidated | 정정·삭제·정책/범위 철회·만료 또는 폐기된 epoch와 연결 | 기존 본문 재전송·새 epoch로 복사 금지. 새 조회와 세션 처리 필요 |

CLI 종료 코드 0만으로 confirmed를 만들지 않는다. client별 native event를 검증하고 전송 ID,
정확한 payload digest, 실제 session/turn ID를 로컬 전송 기록과 연결한다. 이 확인은 모델이
모든 record를 답변에 사용했다는 증거가 아니다. 답변에 사용한 근거는 별도 대응으로 검증한다.

## 3. 중복·compaction의 식별 단위

- provider identity, 실제 client identity, 실제 session ID, 관측된 context epoch를 묶는다.
- canonical payload digest, record ID/digest, generation binding, privacy revision과 유효 시점을 결합한다.
- 임의 project 문자열·사용자가 입력한 epoch를 접근 권한 또는 native compaction 완료로 사용하지 않는다.
- 같은 유효 epoch에서 확인된 동일 record만 중복 억제한다. 전송 실패/불확실 상태는 별도 처리한다.
- 실제 compaction이나 새 세션이 관측되면 최신 상태를 다시 조회하여 필요한 문맥만 공급한다.
  과거 serialized payload를 새 epoch에 그대로 복사하지 않는다.
- compaction 관측이 없는 client는 지원 미확인으로 표시한다. 타이머·턴 수로 성공을 추정하지 않는다.

## 4. 정정·삭제와 전송 중 변경

1. 준비 시와 실제 제출 직전에 기존 provider generation/fence, 자비스 privacy revision,
   suppression, 만료·범위 검사를 적용한다. 준비된 문맥만 들고 provider 장애를 우회하지 않는다.
2. 네트워크 요청을 기다리는 동안 SQLite 쓰기 transaction을 열어 두지 않는다. 전송 claim과
   확인 처리는 짧은 transaction으로 관리하고 그 사이의 변경을 완료 직전에도 재검사한다.
3. 전송 중 삭제가 발생하면 뒤늦게 도착한 확인으로 다시 유효하게 만들지 않는다. 해당 전달과
   세션이 무효화된 상태를 유지하고 후속 출력을 사용하기 전에 정책을 적용한다.
4. 이미 제출된 내용을 회수할 수 있다고 주장하지 않는다. 클라이언트가 문맥 제거/분기를
   검증 가능하게 지원하면 그 경로를 사용하고, 지원이 없으면 오염된 기존 문맥으로 후속 작업을
   자동 진행하지 않는다. 새 세션에서 최신 기억을 조회하는 경로와 사용자 표시를 구현한다.
5. 원문은 전달 이력 DB에 별도 복제하지 않는다. 기존 projection 계보를 재사용하고 필요한
   식별자·digest도 동일한 suppression/보존 정책 아래 둔다. 일반 hash를 익명화로 간주하지 않는다.
6. 오래된 receipt를 백업에서 복원해 현재 세션의 confirmed로 재사용하지 않는다. 복구 후
   provider 상태·삭제 high-water·privacy·실제 세션/epoch를 다시 검증한다.

## 5. 구현 위치와 인수 기준

| 위치 | 필요한 연결 | 인수 증거 |
|---|---|---|
| 자비스 reader/실제 client 제출 경계 | prepared 검증 결과와 제출 직전 재검사 | 준비 이후 정정/삭제/키 철회 시 오래된 본문 제출 0 |
| 자비스 기존 context/projection | 원문 없는 전송 claim·확인·무효화 계보 | 두 worker 동시 요청, 응답 직전 종료, 삭제와 확인의 경합에서 중복/재활성화 0 |
| client adapter | native session/turn/compaction 확인 | Codex/Claude 등 지원 client별 실제 확인. 지원되지 않는 항목 명시 |
| 복구 경로 | 불확실 전송과 복원 이력 재검사 | 재시작 후 불확실 요청 맹목 재전송 0, 삭제된 문맥 재공급 0 |
| 세컨드브레인 인수 도구 | provider 변경→소비 결과 대조 유지 | 현재의 정정 새 값/삭제 no_data에 전송 경합·세션 검사 추가 |

기존 `PersonalContextStore`는 추천용 snapshot 계약을 저장한다. 참고 문맥을 그 타입으로
억지 변환하거나 snapshot 행 생성만으로 전송 확인을 대신하지 않는다. schema 변경이 필요하면
자비스의 기존 migration을 수정하지 않고 새 migration 및 이전 DB 업그레이드 검증을 추가한다.

보류: 전역 자동 주입, 원본 차단 전파 없는 task 자동 수집, client 관측 없는 가짜 compaction,
모든 모델·세션에서 삭제가 끝났다는 표시. 실제 사용자 평가·접근 범위·운영/DR의 나머지 조건은 유지한다.
