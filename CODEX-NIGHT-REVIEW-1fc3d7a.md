# CODEX NIGHT REVIEW — 1fc3d7a

작성자: 지정된 기존 감시 Codex `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`. 원래 Codex는 전달·상태 조정만 했으며 이번 후보를 중복 독립 검토하거나 제품 수정하지 않았다는 전달을 기록한다.

판정: **정상 기능 실행 통과, 제출 출처·테스트 예외 보장 정합화 잔여. 전체 제품/운영 인수 미완료.** 작성 UTC 2026-09-12T16:07:06.168664+00:00.

## 범위와 출처

콘텐츠 안내 뒤 일반 기능만 계속하라는 지시는 **원래 Codex가 보낸 조정 지시**이며, 사용자가 원 A–F/M1–M14 전체 요구를 축소한 지시가 아니다. 원 계약과 `CODEX-NIGHT-REVIEW-01cedbb.md/.json`의 미충족·보류·외부 조건을 유지한다. 화면24954 안내의 발생 검사는 원인 미확정. 경계/삭제 경합 등 보류 분기는 이번에 재실행·타 도구/모델/세션/Grok 이전하지 않았다. 과거 원본은 보존하며 기존 잘못된 record-overlap 통과 해석의 정정도 유지한다.

## 고정 후보와 바이트

- HEAD `1fc3d7a3597e60e28a1b8f5edfa873e340b51afb`, 아카이브 소스 `8edb9d4f8806a802d2c391e459fa7f5960a57a8d` (84e2c43 테스트 포함).
- 후보 `/var/tmp/sb-candidate-8edb9d4/releases/d9c6825b9a94cf6637ba01416562e4eb777db7a2`. wheel `1847b5994392cde8f76e21604a26ed2aee3bb4a43bd7eb04e783615465b317fb`. 제품 바이트 f7c1945와 동일하며 182개 Python 파일의 아카이브/휠/설치물 직접 대조 불일치0. 구휠 결함 아님.
- 새 git archive SHA256 `a8569affc1a29777458f60aa93fdec29c070cc25f69a96e26781fd182c8d0afd`. 제출 테스트 SHA256 `07c8e625bb68168d9dedcbb65f37d73222bea6bb605c3047e36d69b4056a7f22`, HEAD와 고정 복사본 동일.
- JARVIS `1672626c5f2b0b06f7fb93c900cf8771536b58cd`, dist `/var/tmp/jarvis-artifact-1672626/source/dist`. 기존 inventory34768개 SHA256 `e9751dfaf955bab6a1ea15792733e0af576f7bac540ca5efeb0b69d9bccbf9cd` 재대조 동일.
- deploy/scripts 바이트는 f7c1945→8edb9d4 동일. 이 비교 범위에서 변경된 실행 파일은 M11 테스트뿐이다. identity.json, product-bytes.json, harness-bytes.json 참조. 확인 전후 HEAD 동일·제품 tracked diff 비어 있음.

원본 증거: `/var/tmp/codex-night-1fc3d7a-5o71nu5f`. 기존 `/var/tmp/codex-night-01cedbb-ngqqvboh/normal-continuation`은 변경하지 않았다.

## 직접 실행과 정확한 정상 기능 범위

고정 source에서 제출 `tests/test_mcp_generation_overlap.py`를 수정 없이 실행했다. read-only Python trace 플러그인은 테스트 로컬 응답과 실행 순서만 기록하며 제품 동작을 대체하지 않는다. pytest에 `-W error::pytest.PytestUnhandledThreadExceptionWarning`을 적용했다. 이 경고 설정은 이번 검토 명령의 추가 조건이며 제출 자체 설정으로 주장하지 않는다.

| 새 실행 | 결과 | 원본 |
|---|---|---|
| 변경 M11 테스트 | 1 passed, 8.11s, EXIT0 | ordinary-test.log, ordinary-observation.json |
| 변경 테스트 Ruff | EXIT0 | ruff.log |
| 변경 테스트 basedpyright | 0 errors, 54 warnings, EXIT1 | changed-test-types.log |

타입 경고54개를 타입 통과로 쓰지 않는다. 과거 제품3파일 경고6과 대상이 다르므로 회귀 증가량으로 계산하지 않는다. 이번8.11초는 추적을 포함한 테스트 실행시간이며 MCP 성능 p95가 아니다. 과거86pass19.82초·정상1pass4.78초·제품타입0errors6warnings·f7c1945 게이트·전체/DR는 이번 실행 수에 합산하거나 반복하지 않았다.

합성 원문 Alpha 저장→제품 `run_ingest/run_compile`→실제 in-process MCP Alpha MemoryRecord 조회→원문 Omega 정정→같은 정상 pipeline→MCP Omega/다른record ID/새generation/Alpha결과0을 확인했다. 모델 응답만 현재 입력 unit+실제 sid 인용을 반환하는 합성 fixture다. 제품 MemoryRecord/MCP/writer 코드를 대신하지 않으며 native/운영 인증·실모델 검증이 아니다.

정확한 시간 관계: `preparing.set()` 2680892672441001ns → 정상 reader 호출2680892672687360ns → query 완료 후 `read_done.set()`2680892736595855ns → writer 반환2680893352473273ns → Omega/구본문제외 조회. query trace의 여러 return 이벤트는 async suspension/resumption 때문에 중복되므로 RPC 수로 세지 않는다. 중간 MCP는 Alpha 본문/같은record ID를 반환하지만 generation은 초기와 다르다. 이는 **ingest 세대가 먼저 갱신된 후 compile 준비 단계에서 읽은 것**이다. Omega 컴파일 결과의 게시가 reader 완료 뒤라는 범위로 한정한다. 모든 writer 게시가 reader 뒤이거나 pinned read 중 동시 게시가 입증됐다고 쓰지 않는다.

실제 수집된 errors는 빈 배열이고 worker는 join 후 종료했다. 일반 본문 정정 기능의 실패는 이번 실행에서 재현되지 않았다.

## 필요한 일반 후속

1. **F 실행 출처·상태 정합화.** JSON23행 gates.harness_commit은8edb9d4지만 원본 `/var/tmp/sb-gates-f7c1945.log`의 INTEG/WORK는 harness_commit/source/import 경로 모두f7c1945다. 원본 SHA256 `a41a9ed1953a1ed7981356db1da49fb0415bd626faae07d26fe02a53a870fe36`. 동일 wheel 및 deploy/scripts 바이트로 과거 결과를 재사용할 수 있으나 새 소스에서 실행한 기록으로 바꾸면 안 된다. 실제 실행 핀과 동일 바이트 비교 핀을 별도 표시해야 한다. MD53/121행 옛 `test_concurrent_scoped_search_keeps_deny_and_allowed`은 현재 아카이브에 없고70행 '(이 소스)'도 모호하다. 현재 정상 테스트명·위 범위·과거/새 실행을 맞출 것. MD의 '외부만'도 콘텐츠 보류/원 미완료를 없애는 전체 판정으로 읽히지 않게 정리할 것.
2. **M11 스레드 예외 보장.** 테스트137행은 AssertionError/OSError/RuntimeError/ValueError만 수집한다. 나머지 일반 Exception은 errors 배열에 전달되지 않고 pytest thread warning 경로에 남는다. 이번 검토는 그 경고를 오류로 격상해 통과했으므로 숨은 thread 실패를 관측한 것은 아니다. 제출 테스트 자체에서 모든 일반 worker 예외를 실패로 전파하거나 해당 unhandled-thread 경고를 오류로 강제하는 최소 보강이 필요하다. 정상 본문/record/generation/구본문 제외·join/alive 검사를 보존한다. 광범위 타입 정리나 추가 제품 기능을 요구하지 않는다.

Grok 관측 UTC 2026-09-12T16:04:39.726487+00:00, 화면5835095: native Goal blocked / 'Ordinary M11 is on archive8edb9d4/84e2c43, wheel/gatesf7c1945. No newer Codex review.' 현재 상태는 **완료 인계 뒤 검토 대기**이며 과거 PermissionError/fake Cited 기술 차단과 다르다. resume의 ready는 인계 상태로 유지할 수 있지만 실제 native 대기 상태와 각 시각을 별도로 기록해야 한다. 사용자/운영 입력 부족이 이번 정상 후속의 차단 원인은 아니다.

## 인수와 후속 제한

위 두 일반 후속만 하나의 통합 지시로 기존 Grok에 전달하고 공식 목표를 재개한다. 제한된 분기의 실행·수정은 전달하지 않는다. ACK/실제 도구 착수/완료를 나누어 기록한다. M13 전체 수명 및 과거 경계/삭제 관련 보류, 더 강한 게시 중첩 보장, 원 A–F/M1–M14 잔여는 계속 미완료다. 실native 세션/auth/compaction, 실사용자 업무·한글gold/운영corpus, 운영 전환 허가는 별도 외부 조건이며 콘텐츠 제한과 혼동하지 않는다.

운영current41f0751/production_activated=false는 제출 정보이고 이번에 운영 점검·전환하지 않았다. Codex 제품수정/운영자료·auth복사/실사용자삭제/push 없음. 기존 자동화 enabled/`*/30 * * * *`/Asia-Seoul 읽기 확인, 변경 없음. 오전 알림 반복 없음.


2026-09-13 01:10:42 KST 전달 후 확인: 기존 Grok 화면5835386에서 `Read package JSON gates and M11; MD lines 50-75` 도구 완료와 gates/핀/M11 실제 출력, native Pursuing goal/Working을 확인했다. 지시 접수·공식 재개와 별도로 **일반 출처 문서 조사 착수**가 확인됐다. 명시적 수신 답변이나 수정 완료·다음 단계 지속까지 관측한 것은 아니다. 원본 `/var/tmp/codex-night-1fc3d7a-5o71nu5f/worker-after.json` 및 delivery.json. 일반 후속만 진행하며 제한된 분기는 보류한다.
