# 취소 결과의 실제 증거·서명·불변 저장·교차 검증

SB 제품 `44ab911`, JARVIS 제품 `cabfba2`.
[결과 계약](CANCELLATION-RESULT-CONTRACT-2026-09-08.md),
[기계 판독 인수 기록](CANCELLATION-RESULT-ACCEPTANCE-2026-09-08.json).

**판정: provider-local 취소 결과를 실제 증거로 발행·저장·재생하고 자비스가 검증하는 단위를
구현했다. 외부 MCP 취소/결과 조회와 자비스 cursor 자동 완료는 아직 연결하지 않았다.**
전체 native 삭제, 사용자/프로젝트 권한, 원작업 계보, 실제 앱 순환을 포함한 중앙 기억 목표는 유지한다.

## 기존 구현 대조와 결과의 의미

기존 정정 proof는 새 correction 본문의 적용을 요구하므로 replacement를 전송·적용하지 않는
취소에 사용할 수 없다. 기존 취소 의향에 정의된 `provider_local_suppression`을 유지하고
별도의 결과 도메인/종류/상태를 사용했다. 정상 정정 proof나 전체 삭제 receipt로 위장하지 않는다.

- 도메인: `second-brain/memory-correction-cancellation-result/v1\0`.
- 종류/상태: `memory_correction_cancellation_result` / `provider_local_suppressed`.
- exact intent와 원 request/envelope/lane, target/scope, base/result generation 및 tombstone에 결합.
- provider 서명 키와 client의 의향 서명 키를 다른 용도로 검증. consumer는 신뢰하는 provider 키를
  명시적으로 공급한다. 결과를 받을 때 서명·digest·시각·각 결합 필드·닫힌 schema를 확인한다.

## 이번 구현과 실제 증거

| 증거/동작 | 구현·거부 조건 |
|---|---|
| 세대와 원본 처분 | 기존 activation journal의 proved, manifest, reader drain, predecessor disposal 확인 |
| 새 세대 본문 부재 | 원본이 있는 동안 실제 successor 파일/CAS/Git 객체를 검사. 세대별 내용 목록 digest를 원장에 저장하고 재시작 시 대조 |
| 백업/export 처분 | 이전 단위의 copy checkpoint와 현재 내용 목록 일치, export lifecycle 유효성 확인 |
| 원 요청 재접수 차단 | 실제 immutable alias 행 8개가 원 intent의 request/delegation/nonce/envelope/idempotency/lane과 정확히 일치 |
| 재유입 차단 | source/content/citation/subject 차단 행의 tombstone prefix와 실제 ingress 거부 확인. 활성 예외가 허용하면 발행 거부 |
| 결과 내구성 | 기존 FULL 동기 SQLite journal의 immutable 결과 행. 별도 DB·queue를 추가하지 않음 |
| 응답 유실 | 결과 저장 후 종료돼도 같은 canonical 결과를 재생. 후속 세대가 과거 파일을 지워도 이미 저장한 결과 재생 가능 |
| 권한 재확인 | 긴 부재 검사 직후 현재 취소 키와 tombstone을 다시 확인한 뒤 pointer 전환 |

검사 없이 억제 함수가 성공만 반환하도록 만든 경우에도 새 세대에 기존 본문이 남으면
`MANAGED_COPY_REMAINS`로 전환·결과 발행을 거부한다. alias/absence/copy/reingress 증거가
누락되거나 변경돼도 결과 행은 0개다. 새 부재 검사 도중 키 철회를 재현한 검사에서는 처음에
예외 없이 활성화되는 실패를 확인했고, 마지막 권한 재검사를 추가하여 전환을 거부하도록 수정했다.

서명은 위 제한된 provider 동작의 증거를 전달하는 방법이다. 임의 관리 표면의 완전 삭제를
서명 자체가 입증하는 것은 아니다. 현재 generation_active API는 이전 내부 호출과 호환되며
issuer callback을 연결한 호출만 새 결과를 발행한다.

## 검증 수치

| 검사 | 결과 |
|---|---|
| SB 기본 전체 | **1,045 passed, 2 skipped / 220.34초**. 마지막 검사 후 키 재확인 추가 전 실행 |
| 마지막 키 재확인 이후 관련 회귀 | **37 passed / 22.14초**. 위 전체와 중복, 새 철회 검사 1개 포함 |
| SB Ruff/diff | 통과 |
| 변경 제품 5개 모듈 basedpyright | 오류 0, 경고 0 |
| JARVIS 결과/의향/V2/정정 saga/destructive dispatcher | **5파일 38 passed / 5.36초** |
| JARVIS backend typecheck·변경 파일 ESLint | 통과 |
| 격리 TS emit | `/var/tmp/jarvis-cancellation-result-build-fo7qh113`, 운영 dist 미변경 |
| 실제 Python→Node | 정상/재서명 변조 **13개 입력의 수락·거부 일치** |

양 리포의 `contracts/cancellation-result-v1.json`은 실제 provider 취소 실행에서 얻은 같은
합성 계약 vector다. 논리 모델만 만들어 통과시키는 성공 fixture와 구분한다.

실제 프로세스 증거: `/var/tmp/cancellation-result-acceptance-wuu_1q4i/result.json`.
실행 스크립트: `/var/tmp/cancellation-result-process-acceptance.py`.

- parent PID 3918303, 결과 저장 후 worker exit **77**.
- 새 worker PID 3918577 복구, PID 3918630 재생. 결과 1행과 canonical 바이트 일치 확인.
- 실제 Node PID **3918746**이 격리 빌드된 자비스 검증기로 결과를 검증.
- 결과 **2,785바이트**, digest `sha256:39d9dc64234a71081a5c6d4e9cf78d780015ac085e3f0e6a1adba94af303f92c`.
- 관련 archive/export 제거, absence checkpoint 1행, 서명 결과 1행 확인.
- 변조는 상태/범위/원 요청/대상/sequence/별칭 수·boolean/미래 시각/활성화 digest/세대/schema
  boolean/추가 본문을 포함한다. 잘못된 결합을 provider 키로 다시 서명해도 거부한다.

운영 데이터/서비스 변경 0회, 모델 호출 없음. 이번 새 결과 전달은 Python worker→Node verifier이며
MCP 취소 endpoint나 자비스 앱의 cursor 완료를 검증한 것으로 계산하지 않는다.

## 다음 P0와 보류

1. 저장된 결과를 현재 읽기 권한으로 조회하는 provider 상태 경계와 MCP 계약을 연결한다.
   단순 조회에 과거 개인키가 필요하지 않게 하고 공개키 보존/철회·현재 발행 권한을 분리한다.
2. 자비스 DB의 실제 candidate/suppression/attempt/cursor snapshot에서 취소 의향을 발급한다.
   현재 함수의 unsent attestation만으로 전송 부재를 인정하지 않는다.
3. provider 결과를 exact intent와 로컬 suppression/처분 증거에 연결한 뒤 cursor를 완료한다.
   실제 취소 seq1 완료→정상 V2 seq2를 검증한다. 원 요청 전송 이력이 있으면 기존 관측·복구로 보낸다.
4. 결과 유실/상태 재조회/재시작/동시 전송/키 변경의 양쪽 실제 프로세스 인수를 수행한다.

외부 취소 route·자동 lane skip·collector 확대는 위 조건 이전에 활성화하지 않는다. 과거 버전의
부재 체크포인트가 없거나 첫 발행 전에 해당 세대가 이미 제거됐다면 새 증거를 합성하지 않는다.
현재 issuer의 저장 결과 재생은 설정된 provider 키를 사용하므로 키 회전의 읽기 정책은 다음
상태 조회 경계에서 완성해야 한다. 재유입 예외 때문에 차단이 입증되지 않는 경우도 보류한다.

미지원 압축/Git pack 및 변경된 copy inventory의 복구, native 보존면·범위 권한·출처 계보·실제
자비스 앱 순환·수집/주입·검색 평가·GUI·운영/DR의 이전 전체 완료 조건을 유지한다.
