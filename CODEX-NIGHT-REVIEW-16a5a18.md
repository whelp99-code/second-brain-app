# 고정 후보 독립 검토 — 16a5a18

작성자: 지정된 기존 감시 Codex `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`. UTC 2026-09-13T06:39:18.750563+00:00. 원래 Codex는 조정만 수행하고 중복 검토/제품수정을 하지 않았다는 전달을 기록한다.

**판정: N1–N4 부분 개선, 일반 연결 및 최종 준비 인수 미통과. 전체 제품·운영 인수 미완료.** 아래 정상 잔여만 하나의 통합 후속으로 기존 Grok에 전달한다. 기본 테스트 성공을 실제 모델 세션 연결로 확대하지 않는다.

`GROK-COMPLETION-CONTINUATION-2026-09-13.md`, triage, progress-control 정본과 a48cd07 N1–N4 및 원 A–F/M1–M14를 유지한다. 콘텐츠 안내 후 보류 결정은 Codex 조정에서 비롯됐으며 사용자 목표 축소가 아니다. 정확한 발생 검사는 원인 미확정이다. 보류 보안/삭제/경합/복원 수명은 이번 검사·수정·다른 도구/모델/세션/Grok 이전에 포함하지 않았다.

## 1. 핀·실제 바이트·산출물

원본 `/var/tmp/codex-night-16a5a18-ryi0ca9x`. 이전 `/var/tmp/codex-night-a48cd07-eif_t0ak` 및 더 오래된 원본은 보존했다. 고정 git archive 복사본·합성 fixture·TMPDIR=/var/tmp만 사용했다. 제품 체크아웃은 수정하지 않았다.

| 항목 | 직접 확인 |
|---|---|
| 제출 HEAD | `16a5a1855d09225de5ba74b882696b6e80caf6d4` |
| SB source | `f8c7bcd2c8f79e1f42d7eb7b5f6274edec7a02b8` |
| SB archive SHA256 | `b225b4ddb1a8778937fb87544f730bd1be0a242bec4feee659a724b42d31da16` |
| 설치 후보 | `/var/tmp/sb-candidate-f8c7bcd/releases/7e52e867e67215baa5ff10f29207eb914f849ae6` |
| wheel SHA256 | `3264d2c6d4baed7cdc31d99992d57a4eebb1068dcbc4c616aa91210bb3dce675` |
| 제품 대조 | 183 Python source/wheel/installed 불일치0 |
| JARVIS source | `a3c111cd0774eedfd6e2015cb6f0a1c5fff56cfe` |
| JARVIS archive SHA256 | `1703d2fbd5b891226efb423052b95177d915e5b99f1c4c09044de20d165f5407` |
| 제출 source archive | `/var/tmp/jarvis-artifact-a3c111c/source`, 고정 트리와 파일 바이트 불일치0 |
| 제출 dist | `/var/tmp/jarvis-artifact-a3c111c/dist`, metadata의1216파일과 실제 SHA 불일치0 |
| 제출 dist digest | `sha256:f83a8cf44f0ef8fcfe2e4a89debeb3819cd65d3d0b5844481f03afc92ae904d8` |

검토 복사본에서 같은 lockfile의 로컬 node_modules를 참조해 backend를 빌드했다. TypeScript 및 backend build EXIT0. **재빌드1216파일과 제출 dist의 내용 SHA 불일치0**. 파일 mode 차이104개로 artifact vector digest는 다르다(`dist-rebuild-comparison.json`). 서로 다른 digest만으로 구 dist 결함을 단정하지 않는다. source metadata의 dirty=true/null 차이도 실제 바이트 대조와 구분한다. 검토 후 두 repo의 제품/src/tests/scripts/deploy 고정 파일과 실제 트리 불일치0이며 HEAD도 각각 위 핀이다. 원래 제출 dist/설치물을 덮어쓰지 않았다.

## 2. 직접 검사와 보존할 개선

| 직접 실행 | 결과 | 원본 |
|---|---|---|
| SB 훅 제출 테스트 | 10 passed / 4.48s | sb-tests.log |
| SB 변경 CLI/훅/테스트 Ruff | EXIT0 | sb-ruff.log |
| 해당 SB 타입 | 0 errors / 10 warnings / EXIT1 | sb-types.log |
| JARVIS postcompact 제출 테스트 | 8 passed / 총9.12s | jarvis-tests.log |
| 명시 dispatch 정상·중복키·동일키 동시 호출 | 3 passed / 21 선택 제외 / 총5.41s | dispatch-normal.log |
| JARVIS 변경 파일 ESLint | EXIT0 | jarvis-lint.log |
| JARVIS backend build/TypeScript | EXIT0 / wall9.98s | jarvis-build.log |

제출10/8/3pass 주장을 복사한 수치가 아니라 이번 고정 복사본 직접 로그다. 기존 회귀86건/과거 성능·DR·a48cd07 결과와 합산하지 않는다. 이번 전체 regression/DR/보류 분기/native/실모델 실행은0. frontend 전체 build도 해당 backend 변경의 검증으로 주장하지 않는다. 타입10경고는 남아 있으며 완전 통과가 아니다. 이전 `_ignoredFence` lint 오류는 이번 변경에서 해소됐다.

설치 SB CLI를 합성 이벤트 등록표의 명령으로 호출하는 `probe-sb.py`에서 PostCompact의 stdout{}→UserPromptSubmit의 문맥 JSON, 같은 prompt의 재호출{}, **요약이 달라진** 새 compaction의 재주입, 긴 반복 요약의 정상 처리, no_data의 문맥 미출력을 확인했다. 이것은 합성 dispatch→실제 설치 CLI이며 Claude native 등록/모델 소비가 아니다. 합성 settings는 검토 디렉터리에만 있고 실제 개인 settings에 등록하지 않았다.

최종 JSON 예산과 page 중복 제거는 개선됐다. 제출 예산/중복 테스트가 통과했고 독립 다국어 helper 입력8개는 3개 record/최종 JSON12785bytes로 축소됐다. 이 정상 크기 범위의 예산 개선을 보존하며 모든 경계 인수를 주장하지 않는다.

새 JARVIS host 옵션과 stdin 기본 읽기·event ledger가 추가됐다. 독립 `probe-jarvis.mjs`는 공개 execute dispatcher에 합성 reader를 주입하고 **새 hostMemoryReferenceOptions의 FileModelTransport**를 사용했다. 기록420bytes의 본문/source_id/version/session ID를 확인했다. 합성 provider/reader 구성과 파일 기록은 실제 배포 CLI 또는 모델 수신과 구분한다.

## 3. N1 — 문서화된 출력은 개선, 실제 다음 요청 연결은 미완료

공식 [UserPromptSubmit 계약](https://code.claude.com/docs/en/hooks#userpromptsubmit)은 사용자가 prompt를 제출할 때 문맥을 추가하는 출력 형식을 설명한다. 따라서 PostCompact의 unsupported additionalContext를 제거하고 이 이벤트로 옮긴 점은 맞다(`public-contract.json`). 그러나 **auto compaction 뒤 같은 진행 중 turn의 다음 모델 요청**과 **다음 사용자 prompt 제출**은 같은 이벤트라는 근거가 없다. 이는 공개 계약과 코드상 연결 범위를 대조한 판단이며 native 실행에서 유실을 직접 관측했다는 뜻이 아니다. 현재 증거의 완료 범위는 다음 UserPromptSubmit까지다.

JARVIS `src/context-model-transport.ts:33–39`의 FileModelTransport는 JSONL append 후 accepted:true를 반환한다. src 검색에서는 이를 설정/내보내는 코드만 확인됐으며 같은 세션의 요청을 소비하는 연결은 제출되지 않았다. 실제 probe도 소비자를 시작하지 않았는데 success가 반환됐다. 메모리 배열 대신 파일에 recording하는 것으로 원 N1을 충족하지 않는다. 기록 기능 자체의 정상 성공은 보존한다.

완료조건: 지원 클라이언트의 공개 등록/호스트 callback과 같은 세션의 정상 요청 소비 지점을 연결해 제시한다. 다음 사용자 입력만 지원한다면 그 한계를 명시하고 원 auto-compaction 다음 요청 잔여를 남긴다. 구성 파일 출력만으로 모델 전달 성공을 반환/인수하지 않는다. 실제 consumer의 정상 수락 경계까지 합성 transport로 검증할 수 있는 부분을 끝내되 native 로그인 인수와 구분한다. 보류 수명을 대신 실행하지 않는다.

## 4. N2 — 본문 record 출처 및 정상 출력 실패/재시도 잔여

설치 CLI의 실제 stage에는 `page_id=wiki/omega`, **source_ref 빈값**, version=`sha256:570d724ecd5604961a5a74762528bba0c0071fd114e31cdf08e1eba0e8e414b3`가 저장됐다. snippet 안에는 원문 인용 경로가 있다. `sb/postcompact_hook.py:151–157`은 실제 SearchHit record_id/digest가 없으면 page/source/snippet의 해시를 만든다. 날짜 fallback 문제는 개선됐지만 이 값을 실제 MemoryRecord 본문 버전으로 인수하지 않는다. 임의 label을 바꾸는 것이 아니라 원 record identity/출처와 어떤 관계인지 증명해야 한다.

`handle_postcompact` 126행은 **CLI stdout 출력 전** stage를 delivered로 기록한다. 정상적인 출력 실패를 합성 `BrokenPipeError`로 만들었을 때 해당 예외가 발생했고, 뒤이어 정상 설치 CLI로 같은 UserPromptSubmit을 재시도하면 EXIT0/`{}`라 문맥이 사라졌다. 첫 실패는 frozen CLI main의 stdout만 합성 실패시킨 것이며 제품 파일 수정/경합/삭제 검사가 아니다. 증거 `sb-probe.json:normal_stdout_failure/retry_after_stdout_failure`, `probe-sb.py`.

완료조건: 실제 record/원문 근거/버전과 snippet 표시용 해시를 구분해 payload를 연결한다. stdout 성공 전에 전달 완료로 확정하지 않고 일반 출력 실패→정상 재시도에서 기억이 회수되는 계약을 갖춘다. 소비 ACK가 없는 hook 프로토콜의 한계도 정확히 적고 보장되지 않는 exactly-once를 주장하지 않는다. 최종 budget·page dedupe·no_data·긴요약 개선은 유지한다.

## 5. N3 — 요약 해시가 새 compaction까지 중복으로 처리

SB `_event_digest`(146행), JARVIS `parsePostCompactEvent`(약418행)는 session_id+summary만 해시한다. 아래 두 경우를 구별하지 못한다.

- 같은 이벤트의 재전달: 중복 제거가 정상이다. 이번 제출/독립 probe에서 확인했다.
- **이미 전달을 끝낸 뒤, 같은 세션에서 요약이 같은 새 compaction**: 다시 기억을 선택/제공해야 하는 새 수명이다. 새 prompt_id p2를 가진 합성 PostCompact를 설치 SB CLI로 보낸 뒤 해당 prompt를 실행해도 출력{}다. JARVIS도 새 prompt_id와 manual trigger로 바꾼 같은 summary가 duplicate:true이며 추가 파일 전송이 없다. session2 또는 다른 요약은 다시 전송된다.

증거는 `sb-probe.json:new_compaction_same_summary_new_prompt/next_prompt_after_new_compaction`, `jarvis-probe.json:results`다. 시간/경합·권한·삭제를 재현하지 않았다. 단순 정상 순차 이벤트 재현이다. 내용이 같다는 이유만으로 이미 소비된 이전 이벤트와 새 이벤트를 동일시할 수 없다. prompt_id 하나가 모든 compaction의 유일 키라는 해결책을 강제하는 것은 아니며 지원 host 이벤트 식별 계약을 먼저 정해야 한다.

완료조건: 실제 제공되는 세션/turn/compaction 식별·수명으로 **새 이벤트와 재전달**을 구별한다. 같은 요약의 새 이벤트, 같은 이벤트 재시도, 다른 세션, 일반 transport 실패 후 재시도의 정상 시나리오를 함께 닫는다. 새 요약만 달리해 성공시키는 테스트로 대체하지 않는다. 기존 명시 dispatch 정상3건 및 known-negative→성공/계속 실패의8테스트 범위는 보존한다.

## 6. N4 — 새 dist 바이트는 확인, 실행 포장·운영 문서 미완료

새 source-bound dist가 생겼고 실제 독립 재빌드와 내용이 일치한다. 이 부분은 a48cd07의 “dist 없음”에서 진전이다. 그러나 제출된 **그 절대 경로**의 `node /var/tmp/jarvis-artifact-a3c111c/dist/src/cli.js --help`는 EXIT1, `ERR_MODULE_NOT_FOUND: better-sqlite3`다(`submitted-cli-help.json`). 검토 복사본 node_modules를 통해 실행하는 것과 제출 artifact가 실행되는 것은 다르다. 기존 운영 CC 의존성을 섞거나 인증 입력으로 해결할 문제가 아니다.

MD/JSON에서 현재/과거 핀 구분은 개선됐다. 인계의 문서 HEAD13e5892는 최종16a5a18의 선행 핀 설명으로 읽되 최종 제출 HEAD를 명시해야 한다. 최신 readiness JSON의 current pins를 예전 gate에 붙이지 않은 점은 보존한다.

운영 문서는 서비스 이름과 stop/start 순서를 추가했지만 여전히 그대로 실행할 수 있는 검토 자료가 아니다. `python3 deploy/check-jarvis-pending-state.py` 및 `check-database-handles.py`는 **필수 database 인자가 빠져 있다**(두 파일 argparse 선언 직접 확인; 운영 도구 실행 안 함). writer 점검이 stop 전에만 있고 stop 후 holder/lease 확인과 재기동 방지 조건이 불명확하다. current 교체는 정확한 양쪽 경로/설정 변경 명령 대신 산문이며 “백업 집합 복원 후 start”는 실패 단계별 대상·복원 명령·검증/중단 기준이 아니다. 보류 검증 미완료를 적었다고 이 준비 결손이 완료되지는 않는다.

완료조건: 새 dist와 lock/runtime 의존성을 함께 묶은 **실행 가능한 격리 산출물**을 제출하고 그 경로에서 정상 help/entrypoint를 확인한다. 격리 backend 재빌드/타입/lint 증거와 source를 연결한다. 현재 SB/JARVIS 경로·필수 인자·설정 diff·중단→writer 배제 확인→전환→기동→실패 단계별 복구 대상을 한 문서에 구체화하되 운영 실행은 하지 않는다. 당일 PID/current/백업 hash는 점검 대기로 둔다. 구버전 rollback 안전성 또는 보류 검증 통과를 전제하지 않는다.

## 7. 통합 후속과 외부 조건

기존 Grok는 N1–N4의 **허용된 정상 연결·순차 이벤트/출력 실패 재시도·record/예산·산출물·문서** 잔여를 한 번에 처리한다. 새 helper/파일 recorder·짧은 요약 fixture 또는 문서 이름만으로 완료하지 않는다. 사용자/원래 Codex 추가 답변을 기다릴 일반 차단이 아니다. 실제 native 프로필/로그인·선택된 사용자 업무/프로젝트/공유 제품·실제 gold/corpus/지연 목표·운영전환/백업/timer 허가와 RPO/RTO는 별도 외부 조건이다.

M5/M13 등의 콘텐츠 관련 보류와 원 전체 미충족은 그대로 미검증이다. 새 stage 사본이 있다는 사실을 그 수명 검증 완료로 해석하지 않는다. 정확한 제한 원인도 추측하지 않는다. 기존30분 감시를 변경하지 않고 새 작업/모델/구현자·제품수정·운영 변경·auth/config 복사·실사용자삭제·push 없이 진행했다. root가 관리하는 control/야간보고서에는 동시 쓰지 않는다. 이 검토와 격리 증거 상태에 전달·재개·착수를 각각 추가한다.

## 직접 전달·재개·착수 및 후속 조사 확인

UTC 2026-09-13T06:42:50.480943+00:00: 기존 Grok `term_dc97574f3e548cff6e25679d713ed8c2`에 이 검토서를 단일 정상 후속으로 직접 전달, accepted:true를 확인했다. 전달 후 화면6038875의 native footer는 여전히 Goal achieved였다. 공식 `/goal resume` 전송 뒤 화면6039041에서 **Goal active / Status: active / Pursuing goal**과 검토 MD/JSON의 실제 read 도구를 확인했다. 그 다음 화면6039300에서는 `sb/postcompact_hook.py:90–169`, `sb/cli.py:285–309`의 실제 read 도구와 Pursuing goal을 확인했다. 접수→실제 검토 읽기 착수→관련 소스 조사 지속이 구분돼 관측됐다. 이 확인은 수정/새 후보 완료나 전체 인수가 아니다. 추가 구현자는 만들지 않았고 보류 분기는 전달하지 않았다. 기존30분 자동화의 enabled/Asia-Seoul를 공개 show로 확인했으며 변경하지 않았다. control/야간보고서 동시 쓰기는 없다.
