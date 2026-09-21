# 고정 제출 b279068 독립 검토

작성자: **기존 지정 감시 Codex `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`**. 검토 갱신 2026-09-13T07:12:53.435459+00:00. 원래 Codex는 조정만 했으며 아래 직접 실행은 본 기존 검토 작업의 실행이다.

**판정: 일반 후속 일부 해결, N2/N3/N4 잔여로 미통과. 제품/운영 전체 인수 미완료.** 원 A–F/M1–M14, completion/remaining-triage/progress-control 정본을 유지한다. 정상 연결 범위는 콘텐츠 안내 뒤 원래 Codex의 조정 결정이며 사용자의 원 목표 축소가 아니다.

## 고정과 출처

- 문서 HEAD `b2790682dc9248ff3c3e9183981fb16e28897f5f`; SB source `e02636e0c1ad8492b4698d39ce6723e97954e3bc`. 종료 시 HEAD 동일, SB/JARVIS 제품·테스트·스크립트·deploy 바이트 변경 없음.
- SB 후보 `/var/tmp/sb-candidate-e02636e/releases/b0871a409d2505fbc8f294a2ff9502972661a708`; wheel SHA256 `b61a5b67ebf6a47df3b2ccc0add16a6bbb802ca391fdb3cada72ce0dfc7ad70c`. archive SHA256 `efbfd2d7f491a8b7ad8735aa24c1e56fc898ebdf79802f1a53f8b1756743dfa0`. **183 Python 파일 source/wheel/installed 모두 일치**. release manifest도 실제 source 전체 핀과 일치.
- JARVIS `78e73077469d1d6067c46f9a7bb26966969fe570`, archive SHA256 `907ef3da600d25202b758e6f02220f9df4daccb5fd9c50d749a08d1c96fcad42`. `/var/tmp/jarvis-artifact-78e7307/source`의 tracked 바이트 모두 일치. 제출 dist **1,216개 SHA 일치**, digest `sha256:b5155a53b22c87eace13f72095a1f6b9f50df3164bb37200a17ef62c3959929a`. source-bound 메타데이터 dirty:true는 그대로 기록하고 stale 소스라고 추정하지 않았다.
- 별도 frozen archive에서 backend 재빌드 **1,216개 내용 일치**, mode 104개 차이는 별도로 기록했다. 과거 dist/gate를 새 구현 검증으로 사용하지 않았다.
- 제출 runtime **5,787개 파일 SHA 목록**, launcher SHA `b3742f4e511c651b515aaff67a3df069f0cdd60afd5d20862ad49ea4fe9700ce` 기록. dist/node_modules는 제출 runtime의 절대 경로 링크이며 해당 고정 경로에서 `bin/jarvis --help` **EXIT0**. 독립 빌드는 lock 바이트 동일 확인 후 개발 의존성을 사용했으므로 제출 runtime 실행 증거와 분리한다. 이동 가능한 패키지 전체 인수 주장은 하지 않는다.
- 원본 증거: `/var/tmp/codex-night-b279068-zv9rn1hc`. `identity.json`, `runtime-files.json`, `harness-sha256.json`, archive tar, 변경 없는 과거 harness 원본을 보존한 복사본, 각 명령 argv/exit/cwd/시간 JSON과 원본 log. 문서 스냅샷도 이 경로에 보존.

## 직접 실행한 정상 범위

| 검사 | 실제 결과 | 원본 |
|---|---|---|
| SB 변경 hook 테스트 | 11 passed / 4.52s | sb-tests.log/json |
| SB 변경 파일 Ruff | EXIT0 | sb-ruff.log/json |
| SB 변경 파일 타입 | **0 errors / 12 warnings / EXIT1** | sb-types.log/json |
| JARVIS postcompact | 9 passed / 총 9.49s | jarvis-tests.log/json |
| 기존 명시 dispatch 정상 3개만 | 3 passed / 나머지 21개 선택 제외 / 총 4.76s | dispatch-normal.log/json |
| JARVIS 영향 파일 ESLint | EXIT0 | jarvis-lint.log/json |
| 고정 archive backend build (TypeScript 포함) | EXIT0 / wall 9.9956s | jarvis-build.log/json |
| 제출 artifact 실제 launcher | --help EXIT0, 운영 DB 접근 없음 | submitted-cli-help.json |

위 수치를 Grok 자체 9+3 또는 과거 10/8/3·전체86·DR와 합산하지 않는다. 타입 경고 때문에 EXIT1이므로 타입 완전 통과로 쓰지 않는다. 별도 probe는 아래 사례별 관측으로 기록하며 pytest 성공 수에 더하지 않는다.

## N1 — 실제 consumer 경계 한정 확인, native/자동 다음 모델 요청은 잔여

`probe-jarvis.mjs`는 hostMemoryReferenceOptions의 실제 CommandModelTransport를 구성하고 제품 `execute(memory postcompact)`를 호출했다. 합성 외부 consumer 프로세스는 stdin 캡처의 session_id, request/json 동일성, 실제 UTF-8 bytes, memories 배열을 검사한 뒤 exit0을 반환한다. 처음 exit1에서는 `MODEL_TRANSPORT_UNAVAILABLE`, 동일 이벤트 정상 재시도 exit0에서는 수락되고 이후 재전달은 중복이었다. 정상 accepted 캡처는 4개(세션1 두 요청, 세션2 정상/empty), 요청 420/420/420/224bytes. FileModelTransport의 성공 오인은 코드상 accepted:false로 수정됐다.

이는 **합성 reader + 실제 제품 dispatcher + 실제 command consumer 프로세스의 수락 경계**다. 단순 Recording 버퍼와 구분하지만 로그인된 native 모델이나 실제 기존 대화에 합류한 증거는 아니다. provider/read options는 합성 fixture를 주입했다. 제출 bin --help 성공도 native 연결 증거가 아니다.

SB는 합성 등록표→설치 CLI PostCompact `{}`→같은 session UserPromptSubmit additionalContext를 확인했다. 공개 UserPromptSubmit 경로는 다음 **사용자 입력** 경로이며 auto-compaction 직후 같은 turn의 다음 모델 요청과 다르다. 최신 constraint 문서가 이를 미완료로 명시한 점은 보존한다. 공개 계약이 없는 이벤트를 지어내도록 요구하지 않는다. 실제 native 프로필·consumer 연결 구성은 외부 입력과 준비 범위로 남긴다.

## N2 — stdout 재시도는 해결, 원 record 버전 보존은 미해결

`probe-sb.py`에서 합성 정상 stdout write BrokenPipe는 EXIT1, 동일 설치 CLI의 재시도는 다시 본문을 출력했다. 코드 `sb/cli.py:307–314`가 flush 성공 뒤 confirm_delivery를 호출한다. 긴 요약·no_data·중복 출력 검사도 통과했고, helper 최종 직렬화 probe는 3 records/12,572bytes였다. 이는 native ACK/정확히 한 번 전달 증거가 아니다.

직접 `git show HEAD:wiki/omega.md` 합성 committed 바이트를 기존 `parse_page_records`로 읽은 실제 record digest는 `sha256:6a44da03370362ff363212e6efb0848cce46c599ff36c607f7ee3e3da90e6ea9`. 하지만 설치 hook의 version은 `5bece8808585fc9b96d3d8ab8b394b765077776e58b61496d6784659b05df588`이다. 이는 `_identity`(`sb/postcompact_hook.py:169–178`)가 **첫 SourceCite의 CAS hash**를 우선 반환하기 때문이다. 출처가 비던 문제는 단일 인용 fixture에서 해결됐지만 원 MemoryRecord 버전과 같지 않다. 다중 인용 페이지에서 첫 인용을 모든 hit에 쓰는 방식도 정확한 record별 출처 완료조건에 맞춰야 한다(다중 인용 별도 재현을 했다고 주장하지 않음).

JARVIS consumer 캡처의 version도 `sha256:9707dea54b1efd17d1200d6c02e0335734f74b3460a3d4acadd165245b719c3d`로, 합성 reader가 준 원 record digest `sha256:14bceffe96d805724df6447a923a4327bda6c5f97dac3085397feb2cac17fcbd`와 다르다. `src/cli-gjc-commands.ts:283–302`가 원 record를 excerpt digest/sid로 축약하고 `src/context-assembler.ts:182`가 이를 version으로 내보낸다. 원 record_id/digest가 최종 consumer 요청에 없다. **정규화한 본문 해시와 원 record 버전은 서로 다른 값**이다.

완료조건: 선택된 정상 committed record의 식별자·출처 연결·record 버전을 최종 요청까지 보존하고 source-content/excerpt hash와 구별할 것. 정상 정정/재선택에서 최신 record가 바뀌며 원 식별자가 손실되지 않음을 함께 증명할 것. 성공한 stdout 실패/재시도·예산·no_data를 유지한다. 삭제·철회·복원 검사는 이 완료조건에 포함하지 않는다.

증거: `sb-identity-probe.json/.log`, `jarvis-probe.json`, `consumer-accepted.jsonl`.

## N3 — 새 prompt는 해결, 같은 prompt의 새 occurrence가 중복됨

동일 session/summary에서 p1→p2는 재전송되고 다른 session도 구분됐다. 그러나 **prompt_id=p1을 유지하고 명시 compaction_id=c1→c2**로 바꾸면 SB 설치 CLI의 두 번째 UserPromptSubmit은 `{}`, JARVIS는 duplicate:true였다. 실제 두 코드의 occurrence 선택이 prompt_id를 먼저 반환하므로 뒤의 명시 compaction_id/event_id를 버린다(`sb/postcompact_hook.py:155–166`, JARVIS `src/cli-gjc-commands.ts:427–435`).

완료조건: 제공된 명시 occurrence ID를 같은 prompt 안의 새로운 사건과 재전달을 구분하는 데 사용할 것. 같은 이벤트 재전달, 다른 세션, consumer 실패 후 재시도와 함께 한 묶음으로 확인한다. host가 occurrence ID를 제공하지 않는 경우의 구분 한계는 계속 문서화한다. 이 합성 ID를 실제 Claude가 제공했다고 주장하지 않는다.

## N4 — artifact 실행 가능성 해결, 운영 판단 문서는 정정 필요

새 제출 dist/runtime/bin의 고정 바이트와 --help 실행은 확인됐다. 따라서 이전 missing better-sqlite3 결함을 이 후보에 승계하지 않는다. 다만 현재 운영 자료는 승인 가능한 구체 절차가 아직 아니다. 다음은 **기존 문서/소스의 읽기 비교이며 운영·보류 검사를 실행한 것이 아니다.**

1. `GROK-CURRENT-OPERATIONS-REVIEW-2026-09-13.md:15–18`은 `AUTH_DB=$AUTH/current/jarvis-authority.sqlite` 및 release 아래 DB 검색을 안내한다. JARVIS 고정 소스 `deploy/jm-jarvis.service:12–13`, dashboard:14, backup:7은 `/home/jm/.local/state/orca-jarvis/jarvis.sqlite`를 지정한다. binary current와 상태 DB를 혼동했다. SB DB도 release 아래라고만 쓰여 정확한 vault/state/config 대상이 빠졌다. 새 비밀 입력 없이 공개 설정/파서로 먼저 정정할 수 있다.
2. 같은 문서:23은 stop 전에 handles EXIT0만 다음 단계로 진행하도록 한다. 정상 서비스가 DB를 연 상태의 **관측**과 stop 후 **배제 확인**의 의미·분기 및 SB 요청 writer/timer 대상을 구별해야 한다. 도구 자체 `drain_authorized:false`/same-UID snapshot 한계를 유지해야 하며 현재 운영 상태를 추측하지 않는다.
3. :37은 start 실패 때 이전 current/이전 바이너리 start를 지시한다. 앞부분의 구버전 rollback 안전 미보장 및 원 `CUTOVER-RUNBOOK-3D36C40-2026-09-11.md:7–18`의 자동 구버전 복원 금지와 충돌한다. :38의 일반 백업 복원 문장도 준비된 정확한 집합/호환 제약/정지 상태가 없다. **기존 문서의 제약을 정정·명시하는 작업만** 요구하며 rollback 호환성/삭제 전 백업 수명 검사를 실행하거나 Grok에게 대신 시키지 않는다.

완료조건: 실제 공개 service/config에 근거한 DB·state·current·writer 대상과 명령 인자, 기동/점검/실패 단계별 중단 및 복구 제약을 한 자료로 완성한다. 당일 current/PID/백업 hash와 운영 허가는 별도로 미실행으로 남긴다. 이전 핀의 gate와 최신 실행을 계속 구별하고 readiness JSON의 `current_sb_docs=2393f71`도 역사적 핀/최종 제출 관계가 분명하도록 정합화한다.

## 원 전체 요구·외부 조건·보류

16a5a18 및 remaining-triage의 통과 범위는 원 핀/진입점/로그와 함께 보존한다. 과거 정상 M11 Alpha/Omega·worker 예외 전파, 검색/MCP 성능, 제한 전 복원/2scope/원장 retry는 이번 신규 실행이나 최신 전체 인수로 승격하지 않는다. A–F/M1–M14 전체 미완료다.

외부 입력은 지정 실제 업무/task/원문·공유 대상, 격리 native 프로필과 소비자 연결 구성, 실제 한글 gold/자료 규모·지연 목표, 운영 중단·전환·백업·timer 허가 및 RPO/RTO다. 이 입력을 요구하기 전에 준비 가능한 N2/N3 일반 구현과 N4 문서가 남는다. 사용자 답변 대기로 돌리지 않는다.

콘텐츠 안내 관련 보안/삭제/경합/복원 수명 분기는 **미검증·보류**, 안내 발생 검사의 정확한 원인은 미확정이다. 재시도/수정/다른 모델·도구·세션·Grok 이전을 하지 않았고 이번 정상 소비자 검증으로 닫지 않는다. 제품 소스·운영·실인증/config·실사용자 자료·push·새 작업/주기 변경 없음. root 관리 control/야간보고에는 동시 쓰지 않았다.

## 통합 후속

기존 Grok에 본 문서 하나로 **N2 원 record 식별자/버전, N3 명시 occurrence, N4 읽기 전용 운영 자료 정합화**를 전달한다. 위 한정 정상 작업만 현재 승인된 native 목표로 이어가며, 수신 ACK·공식 resume·실제 도구 착수·지속 관측은 아래에 별도로 기록한다. N1 public/native 한계와 보류 분기를 새 구현 의뢰로 바꾸지 않는다.

### 전달 및 공식 재개 관측

기존 Grok `term_dc97574f3e548cff6e25679d713ed8c2`에 통합 문서 경로·한정 완료조건을 직접 전달했고 accepted:true를 받았다. 직후 화면6066954는 여전히 Goal achieved였다. 공식 `/goal resume` accepted:true 뒤 **화면6067144에서 Goal active/Pursuing goal**, 본 MD/JSON 읽기 및 다음 자료 단계인 JARVIS `deploy/jm-jarvis.service:1–25`와 SB 기존 CUTOVER-RUNBOOK:1–30 읽기를 확인했다. ACK뿐 아니라 실제 수신·도구 착수와 후속 자료 조사까지 관측됐으며 수정 완료/새 후보 인수를 뜻하지 않는다. 내부 thinking은 보고하지 않았다.

기존 자동화는 읽기 조회에서 enabled:true, Asia/Seoul을 확인했다. 설정/주기는 변경하지 않았다. `delivery-message.txt`, 각 ACK와 screen JSON을 증거 루트에 보존한다. root 소유 control/야간보고에는 쓰지 않았다.
