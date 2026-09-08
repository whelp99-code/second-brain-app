# 본문 없는 정정 취소 계약: 구현·교차 검증

2026-09-08. 세컨드브레인 중앙 기억 완성 목표의 P0 자동 복구 선행 단위.

**구현한 것은 취소 의향의 생성·검증 계약이다. 중단된 정정 요청의 자동 복구는 아직 완료하지 않았다.**
원래 정정 본문을 보내지 않으면서 그 요청의 권한·대상·삭제 이력을 식별할 수 있는 계약을
JARVIS TypeScript와 Second Brain Python에 구현했다. 검증된 의향도 발신자의 진술이며,
provider 미수신 증거나 실제 삭제 완료 증거로 사용하지 않는다.

- JARVIS 제품·회귀: `0ea62c8`.
- SB 제품·교차 런타임 도구: `e7efd62`.
- 결정: [취소 의향 ADR](../Orca-JARVIS/docs/planning/adr-memory-correction-cancellation-intent.md).
- 선행 결함: [V2 차단과 혼합 delta 거부](V2-CORRECTION-SUPPRESSION-2026-09-08.md).

## 기존 복구 시제품을 대체하는 방향

이전 방식은 미전송 정정의 삭제 이력을 후속 삭제 요청에 섞어 보내려 했으나 양쪽 V2 검증기에서
거부됐다. 이번에는 `memory_correction_cancellation_intent`, schema version 1이라는 별도 객체를
사용한다. 기존 V2 요청 union이나 MCP 프로필에 이 객체를 추가하지 않았다.

코드를 더 대조한 결과, provider의 tombstone 원장만 갱신해도 충분하지 않다. 실제 활성 세대의
checkpoint가 다르면 `sb_generation_status`는 `tombstone_stale`을 보고하고 내용 조회는
`TOMBSTONE_SET_STALE`로 거부한다. 따라서 취소 접수→원본 요청 재수신 차단→원본 대상 억제→
새 세대 봉인·활성화→결과 증거 확인까지 연결해야 후속 요청이 진행된다.

Sequence 1의 취소·억제를 provider가 독립적으로 완료하고 그 checkpoint를 자비스가 확인한 뒤
sequence 2만 기존 V2로 보내는 경로를 우선 검증한다. 혼합 delta 허용이나 V2 해시 검사 완화가
반드시 필요한 것으로 가정하지 않는다. 아직 이 전체 경로를 구현·실행한 상태는 아니다.

## 구현 범위

| 항목 | 구현된 검사 |
|---|---|
| 본문 제외 | 원래 `payload`/`content`를 생성 객체에서 제외하고 루트·중첩의 알 수 없는 필드 거부 |
| 원 요청의 역사적 권한 | 원본 owner delegation의 canonical digest·ID·Ed25519 서명·발급 구간 검증 |
| 현재 취소 의향 | 현재 허용 키 역할을 별도 map으로 받고 현재 서명·nonce·발급 시각·5분 이하 만료 검증 |
| 만료된 원 요청 | 과거 시점에 유효했던 delegation/target은 취소 의향의 근거로 허용. 새 실행 권한으로 사용하지 않음 |
| 대상·범위 | target digest, manifest, scope, expected prior, provider가 원본 delegation과 정확히 일치해야 함 |
| 삭제 이력 | 단일 correction entry의 root·ID·sequence·lane·payload digest·유효 시각 결합 |
| 미전송 진술 | 후보 ID·suppression event digest, attempt 0·fence 0·active cursor false의 닫힌 구조 |
| 범위 제한 | `provider_local_suppression`만 허용. `managed_erasure` 등 물리 삭제 완료를 나타내는 값 거부 |
| 입력·출력 | 16KiB 상한, 정규 시간·NFC·정수, TS 깊은 동결, Python 불변 canonical bytes와 복사 반환 |

원본 request digest는 원본 delegation 서명으로 결합한다. 원본 envelope digest는 새 현재 서명으로
결합하며, 원문 없이 다시 계산했다고 주장하지 않는다. 두 key map은 허용 역할을 분리한 것으로,
항상 서로 다른 물리 키를 요구하는 것은 아니다. 실제 key registry의 purpose·revocation·기간
정책과 DB 근거 생성은 실행 연결 단계에서 집행해야 한다.

SB의 기존 target metadata 검증기를 공개된 공통 함수로 재사용했다. 기존 V2의 검증 의미는 유지했다.
새 DB·migration·서버·Proxy·외부 OSS 의존성은 추가하지 않았다.

## 이전 테스트 접수기의 결함도 수정

이전 자동 skip 시제품에서 사용한 JARVIS `AcceptedWriter`는 실제 V2 요청 검증을 생략했다.
이제 실제 `requireMemoryEffectWriteRequest`를 통과한 입력만 접수 기록에 추가한다.
정상 정정 1건을 먼저 접수한 뒤, 새로 서명한 혼합 chain 요청을 주면
`EFFECT_TOMBSTONE_DELTA_INVALID`로 거부하고 접수 수는 1로 유지하는 회귀를 추가했다.
이 수정으로 해당 fixture를 사용한 후속 복구 실험이 동일한 잘못된 성공을 반복하지 않게 했다.

## 검증 결과

| 검증 | 결과·범위 |
|---|---|
| SB 기본 전체 | `pytest -q --ignore=tests/test_embeddings.py`: **947 passed, 2 skipped**, 122.45초 |
| 최종 공통 target 함수 변경 후 집중 회귀 | 취소 의향·V2 값·접수 **30 passed**, 0.62초. 위 전체 결과와 중복 |
| Python 정적 검사 | 신규 제품·테스트 basedpyright: **0 errors, 0 warnings** |
| SB lint | `ruff check sb tests`: 통과 |
| JARVIS 관련 회귀 | 신규 의향·기존 V2·차단·정정 saga·완료 처리 **5파일 41 passed**, 43.85초 |
| JARVIS 타입·lint·build | backend TypeScript와 변경 파일 ESLint, 정규 격리 build 통과 |
| 실제 Node↔Python | **16개 입력**의 수락/거부 일치. 양쪽에서 생성한 의향·서명이 동일 |

정상 사례는 만료된 원 요청과 현재 취소 서명을 사용한다. 변조 사례에는 본문 추가, 대상/범위/chain
교체, 전송 흔적, boolean/float 타입 혼동, TTL·미래 시각, 원본 서명, 삭제 범위 확대, 미허용 키가 포함된다.

실제 교차 검증 결과: `/var/tmp/cancellation-intent-cross-runtime-2fhAuc/result.json`.
Node PID 3190337, Python PID 3190347. Canonical 문서 **5,775바이트**.
의향 digest: `sha256:a6122345c346b2de07439e01433b26f0093b987bce42046c75131b2a6519ccf6`.
격리 build는 `/var/tmp/jarvis-cancellation-intent-build-n_wuztw1`, 파일 1,063개·migration 71개이며
산출물 digest는 `sha256:b2f63b1c1dc0ca50ab3361b1bb4a50ac846d60859915afc0444efd2daea91482`다.
[기계 판독 결과](CORRECTION-CANCELLATION-INTENT-2026-09-08.json)에 이 증거를 보존했다.

이것은 실제 두 언어 런타임의 계약 사용 검증이다. provider mutation 0회, 운영 데이터 사용 없음,
모델 호출 없음이다. 자동 복구·세대 전환·실제 앱 인수 완료로 계산하지 않는다.

## 이어서 구현할 순서

| 단계 | 남은 구현 | 필요한 완료 증거 |
|---|---|---|
| 1. 자비스 생성 경계 | immediate DB snapshot에서 candidate·suppression·attempt·cursor와 원 요청을 결합해 의향 발급 | 임의 candidate/event 교체와 전송 경합 시 의향 발급 거부 |
| 2. provider 원자 접수 | 기존 요청의 journal·alias·pending 파일과 취소를 같은 publication lock/transaction에서 비교 | 지연된 원 요청과 취소의 양방향 경합에서 실행·취소 동시 성공 0 |
| 3. prefix·재생 방지 | sequence=current+1, previous_root exact 검사와 원본 요청 alias 영구 차단 | 재시작·응답 유실·의향 재전송에도 원 요청 부활 0 |
| 4. 실제 억제 세대 | 대상별 억제·재유입 방지, 새 세대 봉인·활성화와 reader 처리 | 억제 기억의 검색·원문·복원 노출 0, checkpoint 일치 |
| 5. 결과 증거·cursor | provider의 서명된 결과를 자비스가 exact request/target/root에 결합 | 실제 완료 전에 cursor를 전진시키지 않고 결과 유실 후 관측으로 복구 |
| 6. 양쪽 최종 인수 | 취소 완료 뒤 기존 V2의 다음 정정·삭제 실행 | 본문 전송 0, 새 요청 완료, 기존 차단·삭제 증거 보존 |

provider가 원 요청을 이미 수신했거나 실행 흔적이 있으면 미전송 의향만으로 처리하지 않고 기존
관측·복구로 넘겨야 한다. 기존 journal에 같은 request ID가 있으면 원본 envelope digest도 정확히
대조한다. 취소 의향의 서명 자체를 provider 미수신 증거로 승격하지 않는다.

전체 중앙 기억 목표의 native 보존·폐기, 사용자/프로젝트 범위, 원task→기억 계보, 실제 앱 세션,
자동 수집/주입, 검색 품질·성능, GUI·운영·복구 인수는 기존 [14개 우선 목록](V2-CORRECTION-SUPPRESSION-2026-09-08.md)의
완료 조건을 유지한다. 이번 단위는 그중 P0 복구의 계약 기반이며 전체 목표는 계속 미완료다.
