# 야간 독립 검토 — a7df330 미통과

작성자: 기존 Codex 감시 작업에 야간 독립 검증을 위임받은 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`. 원래 Codex가 직접 실행한 검토가 아니다. 제품 소스/테스트는 수정하지 않았다.

**제품 준비 인수 미통과. 운영 인수/전환 승인 아님.** N2 기존 순위 재현과 N4의 격리 정상 UI 복구는 진전했다. N1과 N3는 부분 수정이며 실행 가능한 잔여 결함이 있다. 이전 A–F/R1–R7/M1–M14와 외부 조건을 유지한다.

## 고정 후보와 바이트

- 제출 `a7df3309b80329569cf13b6a8187f35f08720871`, SB source `5b67bbad6d4c011e8bd6079242f3b1433e649a01`.
- 후보 `/var/tmp/sb-candidate-5b67bba/releases/e51b068d7601aa97279b96080faf20ae059c83a7`.
- wheel SHA-256 `646f0577070be044ae3412df56247cb307b4901ba72d3d7ba07e9288b7bb867e`.
- JARVIS `401f0c18dc4aa21f947b7e4f654a49ec18fc48f0`, `/var/tmp/jarvis-artifact-401f0c1/source/dist`.
- 설치 inventory `f4f82237c2207534f32ffd7db05e859140eeed0828fa1ef1db7697ed334b55dd` / 34776 entries.
- 독립 증거 `/var/tmp/codex-night-a7df330-zli4d5wc`; 고정 git archive는 그 아래 `source/`.

SB Python 182개가 archive/wheel/설치물에서 일치했다. JARVIS 추적 src/tests 1132개가 git 소스와 일치했고, 별도 출력 폴더로 다시 컴파일한 src JS 584개도 dist와 일치했다. artifact 안 AGENTS.md 3개는 추적 제품 소스 외 문서로 별도 기록했다. 설치 gate가 실제 inventory도 재검사했다. `sb-identity.json`, `jarvis-identity.json`, `installed-standard.log` 참고. 검토 종료 확인 시 HEAD는 동일 제출이다.

## 직접 검증과 기존 로그 구분

- 관련 회귀 **125 passed / 26.78s**, `focused-pytest.log`. Ruff `sb tests` EXIT0.
- Python 관련 5모듈 타입 검사 **0 errors, 7 warnings, EXIT1** (`python-types.log`). JARVIS TypeScript 컴파일/타입 검사 EXIT0 (`jarvis-tsc.log`).
- 설치 표준·실제 work-item fixture·유지보수 **각 EXIT0**. `installed-standard.log`, `installed-work.log`, `installed-maintenance.log`. 격리 실제 TLS/CLI/MCP 경로이며 실사용자 로그인/native 인수는 아니다.
- R1 관리형 정상 정정, 미커밋/커밋 사용자 편집 및 사람이 작성한 본문 보존 4조합 통과. 기존 철회/cancellation/store 유실 및 rollback 거부 재현 통과.
- V2 cap1 실패4개→calls1; 혼합 실패/성공과 재시도도 cap 이내. 로컬 deny 관련 회귀 포함.
- V4 dangling/기존 symlink/디렉터리 marker 거부 및 외부 파일 불변. store가 보존된 marker 유실/초기화 중단도 기존 철회 유지.
- N2: 긴 문서30개 quartz4회 vs 짧은 핵심3회 재현에서 핵심 top1. 경로 a/z 교환 양쪽 통과. Unicode/줄바꿈 parity 6개 통과. 새 반환 score 관련 회귀도 통과. 이는 synthetic lexical/SQLite 및 관련 테스트 범위이며 전체 검색품질/MCP 성능 인수가 아니다.
- N1: 거부된 evidence는 send0/record0/capture 없음으로 개선. 정상 helper는 실제 본문·출처·버전을 포함한 431byte capture를 recording send1에 전달. helper 예산 6268/8000byte와 만료/untrusted 본문 제외 재현도 통과. 세션 연결은 아래 잔여 N1.

Grok 전체 회귀 **1825 passed, 2 skipped / 599.98s**는 `/var/tmp/sb-full-pytest-5b67bba.log`를 읽어 확인한 수치다. 이번 검증자가 전체 회귀를 직접 재실행한 수치가 아니다. 원본 SHA/tail은 `grok-full-regression-log-observed.json`에 있다. 결정적인 인수 실패가 남아 동일 트리 전체 검사는 반복하지 않았다.

## 잔여 결함 — 한 통합 구현으로 처리

### N1 / V1 / R4 — 실제 세션 진입점과 transport 결과 미연결 (P1)

JARVIS `src/authority-progress-store.ts:29`의 `persistAssembledContextSnapshot`은 production 호출자가 여전히 없다. `sendAssembledModelRequest`도 production 소비자가 없다. `src/personal-context-persistence.ts:55-61`은 저장 뒤 `void this.modelTransport.send(capture)`를 호출하지만 기본/실제 연결은 여전히 RecordingModelTransport다. 보조 함수의 record를 send로 바꾸는 것으로 실제 세션 연결은 생기지 않았다.

독립 dist probe `transport-positive.mjs`에서 정상 evidence는 저장/send1을 통과했다. 같은 public helper에서 transport가 `{accepted:false, reason:'synthetic unavailable'}`를 돌려주면 **저장은 정상 반환, 오류 없음, recorded_send_count0**이며 capture만 남는다. 이는 transport 결과가 호출 경로에 전달되지 않는 재현이다. 저장 자체를 성공으로 반환하는 API와 실제 요청 전달 성공을 구분해야 한다. 외부 유출이나 live 모델 호출을 주장하지 않는다.

완료 기준: 기존 제품의 실제 세션 요청 진입점을 먼저 특정하고 그 진입점에서 기억 선택→evidence 검증→최종 직렬화→주입 가능한 transport의 결과/실패/재시도를 연결한다. 그 진입점으로 정상·거부·새 세션·compaction·철회·만료·no_data와 예산을 실행한다. 단순 호출되지 않는 새 메서드와 recording unit test를 다시 제출하지 않는다. live 인증 없이 가능한 transport 경계와 실제 native 인증 조건을 분리한다.

### N3 / R2 / M3 — 비어 있지 않은 철회 파일 절단은 여전히 권한 복구 (P1)

`sb/revoked_keys.py:28-42`는 빈 파일만 추가로 거부한다. 독립 fixture에서 초기화 marker를 유지하고 store의 마지막 3바이트를 절단하면 다음이 된다.

```text
정상: key:other\nkey:test\n  → active_policy_keys=[key:new]
절단: key:other\nkey:te       → active_policy_keys=[key:new,key:test]
```

`partial-truncation.py/.json` 참고. 최초 미초기화 상태는 두 유효 키를 허용하고, 정상 철회 상태는 새 유효 키만 허용한다. 손상 뒤 기존 철회 키가 다시 policy 대상이 된다. 실제 사용자 기록을 읽은 재현은 아니다.

완료 기준: 초기화된 정본의 형식·완전성·세대 일관성을 확인하고 파손/부분 기록/기록 단위 유실을 안전하게 처리한다. 단순 not-empty 조건에서 멈추지 않는다. 재시작·초기화 중단·신뢰 가능한 복원 후에도 철회가 유지되어야 하며, 새 정상 키의 허용도 함께 검증한다. 운영 정본을 실험하거나 권한 우회하지 않는다.

## N4 / V5 / R6 — 격리 정상 UI 복구 확인, 범위 한정

이 후보의 보고 harness는 임의 성공 하위 stage 대신 실제 last_batch를 확인하도록 개선됐다. 제출의 `#run` harness만으로 UI 인수를 선언하지 않았다. 검증자는 별도 Chrome/Playwright로 **일반 title/content 폼→기억하기→일반 처리 버튼**을 눌렀다.

1. 기존 최소 `_ready` 설정에서는 실제 처리 실패가 재현됐다 (`SafeSourceFilesystemError: source mutation observed: .`). 설정이 없는 fixture를 전체 정상 배포의 무조건적 결함으로 확대하지 않는다.
2. inbox root와 `llm_policy=deny`를 명시한 격리 설정에서는 일반 폼/버튼만으로 pages1, 재실행 pages0, 두 번 모두 exit0이었다 (`configured-browser-result.json`).
3. 같은 서버·브라우저에서 실제 처리 실패 후, 검증 harness가 **격리 Config.raw를 inbox/deny로 정정**하고 정상 UI로 새 입력을 저장한 다음 동일 버튼을 재실행했다. 실패 run `cdbdfb8bf7ef42bea0b4a2281d45bf4d` → 성공 run `b0d59019f6644f3c83b3b2e668b8ecca`, **status ok / pages1 / exit0**, 실패 이력 보존. 새 본문 needle이 실제 Git HEAD의 wiki 파일에 기록된 것도 확인했다.

`recovery-output-browser-result.json`, `.html`, `.png`, `.log`와 harness가 근거다. 성공 stage 주입/Python POST/숨은 URL fragment는 사용하지 않았다. 설정 정정은 검증 harness의 메모리 내 Config 변경이며 GUI 설정 편집·영구 config 재시작·실제 운영 복구를 검증한 것은 아니다. **N4의 정상 UI 실행·실패 이력·결과 연결은 이 격리 범위에서 확인**했다. 이 근거와 한계를 다음 제출에 반영하고 별도 제품 코드 변경을 만들어 시간을 채우지 않는다.

## 원 요구와 증거 누락 유지

이전 검토의 A–F/M1–M14 매핑을 유지한다. 새 패키지의 ‘원문 유지’ 한 줄은 요구별 상태/증거 표를 대체하지 않는다. N2 특정 재현/N4 격리 통과는 M10 검색품질·M13 운영 GUI 전체 완료가 아니다.

- M1 신원/권한, M2 실제 업무 공유 계보, M4 검증 결과 원계보: 설치 fixture와 실제 로그인/업무/제품 세션을 분리한다.
- M3 철회와 M7 전체 읽기: N3 및 전체 읽기 표면/오래된 권한 대조를 닫는다.
- M5 native 사본 수명, M8 제품별 공유연결, M9 문맥·compaction: N1과 실제 native 소유 사본/세션 외부 조건을 분리한다.
- M6 단일작성자·전환복구: 유지보수 검사 통과와 writer 배제/rollback 진입점 강제 적용/격리 왕복 인수는 별개다.
- M10 검색품질/M11 성능: 순위 변경 후 작은·중간·운영 규모 **실제 MCP** p50/p95/max/RSS, 동시 조회/정정·옛 버전 제외·timeout 여유의 직접 증거가 여전히 필요하다. `scripts/scoped-search-scale.py`는 자체 설명대로 library 경로이며 MCP라고 바꾸어 적지 않는다.
- M12 DR: 원장/원본 소실, high-water, 복원 후 허용/거부/새 쓰기, 전체 RPO/RTO가 연결된 기존 증거를 제출하거나 남은 승인 범위 격리 검증을 끝낸다.
- M13 GUI: 위 격리 통과를 보존하고 실제 운영/영구 설정 복구는 별도다. M14 관계검색 기존 보류는 유지한다.

위 기존 독립 실행 가능 작업은 운영 drain 부재만으로 blocked_external 처리하지 않는다. 재현된 결함과 증거 미제출 상태를 구분한다. 이미 존재하는 적합한 고정 후보 증거가 있으면 해당 경로와 결과를 연결하고 불필요한 재검사를 피한다.

## 재개 및 외부 조건

Grok는 N1/N3 및 위 기존 미충족을 현재 승인된 목표에 통합한다. 보조 함수 한 줄 수정 후 중간 ready 제출을 반복하지 말고 관련 정상/실패/복구 계약까지 완료한다. 현재 native 목표만 공식 `/goal resume`로 재개한다. 옛 W4 운영 blocked 목표나 내부 goal JSON을 복원하지 않는다.

실로그인·실제 업무/공유 범위·native 세션/사본·사용자 질문·운영 drain 허가는 외부 조건으로 유지한다. 야간 반복 승인을 묻지 않는다. 운영 current 보고값은 `41f0751`, 직접 설치 gate는 production_activated=false다. 전환·인증 복사·사용자 기록 삭제·push를 수행/승인하지 않았다. 기존 30분 감시는 유지한다.

검토 harness 3개의 최초 호출은 출력 경로 인수를 빠뜨려 출력 단계에서 실패했다. 원본 `.log`를 보존하고 인수를 넣은 `.fixed.log`/`.json` 재실행은 EXIT0이었다. 제품 결함으로 세지 않았다. 이전 원본 harness/검토는 보존했다.
