# P20 — JARVIS 연동: 개인 기억 API 게이트·전달 원장·실행 결과 완료 사건

명세 등록 / 구현·시험 NOT_RUN. Refs #3, #39. 선행 P02 #21, P07 #26, P15 #34; JARVIS 저장소. R2 (제안) / Core·Gateway / 6~10인일 추정(추정임을 명시).

## 목표
JARVIS가 SB 개인 기억을 인증된 게이트로 중계하고, 추천 전달을 영속 원장에 기록하며, 작업 실행 결과를 검증된 완료 사건으로 SB에 남긴다. 응답 유실 시 비즈니스 동작 재실행 없이 기억 기록만 독립 복구한다. JARVIS 저장소 쪽 변경이 중심이라 SB2 명세 범위 밖이었으나, 업무 완료를 인용 가능한 영속 사건으로 남기는 요구가 여기에 속한다.

제외: 새 상주 queue/event bus 금지. SB 원본 DB 직접 쓰기 금지. `sb.vault` 단일 writer 침범 금지. exit 0만으로 완료 처리 금지. `delivered` 기존 의미 변경 금지. query/원문의 URL·localStorage·log 기록 금지.

## 구현 체크리스트

### 계획 37: 추천 전달 원장
- [ ] JARVIS 새 `src/personal-memory-delivery.ts`를 만들고 additive migration과 K6를 기존 intent/claim/settle 구조에 연결한다.
- [ ] `delivered`의 기존 의미를 유지하면서 새 versioned facts를 별도로 둔다.
- [ ] scope/deletion/state 재검증 후 device destination별 delivery를 생성한다.
- [ ] 같은 logical recommendation이 retry/두 device/rewording에서 stable ID를 유지하는지 검증한다.
- [ ] completed/deleted/state stale인 항목은 dispatch 권한을 얻지 못하게 차단한다.

### 계획 40: 개인 기억 API 게이트
- [ ] JARVIS 새 `src/dashboard/personal-memory-routes.ts`, `src/personal-memory-relay.ts`로 K7 endpoints를 구현한다.
- [ ] 기존 HTTPS entry/session/CSRF를 재사용하고 webphone static gateway와 backend role을 구분한다.
- [ ] 브라우저에는 SB token/key/8765 주소가 노출되지 않으며 각 요청은 authenticated scope로 수행한다.
- [ ] unsupported profile은 명시적으로 실패 응답을 반환한다.
- [ ] query/원문을 URL·localStorage·access log에 넣지 않는다.

### 계획 45: 실행 결과를 검증된 완료 사건으로 전달
- [ ] JARVIS 작업 success criterion, operation/attempt/sequence와 result evidence를 K3 event로 만든다.
- [ ] 기존 memory outbox/transport를 재사용하고 새 profile로 기록한다.
- [ ] process exit 0만으로 업무 완료를 만들지 않는다. failed/cancelled/unknown attempt는 completed가 아니다.
- [ ] result criterion/evidence가 있는 결과만 applied completion receipt를 획득한다.
- [ ] pending completion이 durable해지면 신규 reminder를 suppress한다.

### 계획 46: 응답 유실 독립 복구
- [ ] outbox state/receipt 조회로 accepted_pending → applied를 reconcile한다.
- [ ] memory timeout이 비즈니스 action retry로 이어지지 않게 operation/attempt/request IDs를 분리한다.
- [ ] old causal sequence/다른 actor/오래된 fence는 거절한다.
- [ ] commit 전/후 crash 모두에서 최종 obligation set이 동일하고 business action count가 1임을 보장한다.
- [ ] wrong scope 조회가 0임을 검증한다.

## 코드·API

기존 모듈(sb2-specs 내 확인된 경로):
- `sb/life_delivery.py` — 전달 claim/unknown 상태, HTTPS 전송
- `sb/life_contracts.py` — K3 사건·상태·증거 계약
- `sb/life_workflow.py` — 워크플로 상태 전이
- `sb/scoped_request_status.py` — 범위 지정 요청 상태 조회
- `sb/store/life.py` — 영속 접수·receipt·CAS
- `tests/fixtures/jarvis_memory_provider.py` — JARVIS 기억 provider fixture
- `tests/test_life_transport_runtime.py` — transport 런타임 테스트
- `tests/test_jarvis_pending_state_audit.py` — pending 상태 감사

신규 후보(JARVIS 저장소):
- `src/personal-memory-delivery.ts` — 추천 전달 원장, intent/claim/settle
- `src/dashboard/personal-memory-routes.ts` — K7 API 게이트 라우트
- `src/personal-memory-relay.ts` — SB profile 중계
- `src/memory-outbox.ts` 보강 — outbox reconcile
- `src/second-brain-transport.ts` 보강 — receipt 조회, fence 검사

## 인수시험

AC-01 동일 이벤트 재전송 멱등: 전달 원장 stable ID, 완료 사건 중복 없음. AC-09 정정 후 전체 표면 일관성: 완료 사건 반영 포함. AC-11 전달 중복 억제: claim/settle 상태 분리. AC-15 범위 밖 누출 0: API 게이트 scope 검사. AC-16 경계 종료 후 영속: outbox crash 복구. AC-18 삭제 후 재활성화 차단: 완료 사건의 삭제 전파. AC-21 rollback 안전: 전달 원장과 outbox 보존. AC-24 전체 회귀: JARVIS 기존 notification 계약 호환.

패키지 고유 시험:

- T37-happy: 실제 SB profile → JARVIS journal → claim/settle 연결. 같은 recommendation을 retry/두 device/rewording으로 전달해 stable ID 확인.
- T37-failure: lease stale·claim 유실·삭제 race에서 duplicate effect 0, unknown 구분.
- T40-happy: HTTPS session으로 recall/list/status를 호출해 exact generation 반환.
- T40-failure: expired session/CSRF/profile drift/회사 scope 오류에서 내용 0.
- T45-happy: 실제 격리 JARVIS 작업 → 결과 proof → SB 반영 → 다음 추천 제외.
- T45-failure: failed tool/취소/검증 불가/기억 기록 유실에서 허위 완료 0.
- T46-happy: 재시작 후 동일 applied receipt와 최신 revision 회수.
- T46-failure: ACK 유실·중복 outbox·타임아웃·key rotation에서 blind action replay 0.

## 적용·중단·완료

`life_events` OFF가 기본이다. JARVIS 쪽 전달 원장과 API 게이트도 feature flag OFF로 시작하며, SB 연동이 인수된 이후 선택적으로 켠다.

롤백: flag OFF로 새 기록을 멈추되 기존 receipt·영속 사건·pending outbox·삭제 의도·tombstone은 보존한다.

인수 증거: T37/T40/T45/T46 happy·failure 로그, SB profile 연결 증거, transport receipt, scope 검사 결과로 인수한다.

현 diff는 이 문서 1개이며 구현·시험 모두 NOT_RUN.
