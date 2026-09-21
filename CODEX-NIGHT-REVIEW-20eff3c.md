# CODEX NIGHT REVIEW — 20eff3c

작성자: 지정된 **기존 감시 Codex `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`**. 원래 Codex는 조정·전달만 했고 제품수정·중복 독립검토를 하지 않았다는 전달을 기록한다. 검토 갱신 UTC 2026-09-12T16:36:57.714576+00:00.

**판정: 1fc3d7a의 일반 후속 두 항목은 한정 완료. 전체 제품·운영 인수는 미완료.** 실행 가능한 새 일반 기능 결함이나 필수 핀 정합성 문제는 이번 범위에서 확인되지 않았다. 작업량을 채우기 위한 추가 재개를 하지 않는다.

## 범위와 원본 보존

일반 기능만 계속하는 범위는 콘텐츠 안내 이후 **원래 Codex의 조정 지시**에서 비롯됐다. 사용자 원 A–F/M1–M14 인수 요구가 축소된 것이 아니다. `CODEX-NIGHT-REVIEW-01cedbb.md/.json`, `CODEX-NIGHT-REVIEW-1fc3d7a.md/.json`의 원 미충족·보류·외부 조건과 이전 harness 해석 정정을 유지한다. 화면24954 안내의 발생 검사는 원인 미확정이며 정책·비공개 추론을 추측하지 않는다. 보안 경계/삭제 경합 등 관련될 수 있는 분기를 재시도하거나 다른 모델/세션/도구/Grok로 이전하지 않았다.

이번 증거 `/var/tmp/codex-night-20eff3c-e0rs0m_6`. 기존 `/var/tmp/codex-night-1fc3d7a-5o71nu5f`와 그 이전 원본은 수정하지 않았다. 합성 fixture와 `TMPDIR=/var/tmp`만 사용했다.

## 고정 출처와 실제 바이트

- HEAD `20eff3cae87f271d81e7df141ad564dfd22a8380`, source/archive `e13cd3b699695fa08fbde521f7a7866c9dfef6a0`.
- 후보 `/var/tmp/sb-candidate-e13cd3b/releases/d9c6825b9a94cf6637ba01416562e4eb777db7a2`. wheel `1847b5994392cde8f76e21604a26ed2aee3bb4a43bd7eb04e783615465b317fb`.
- source의182개 Python 파일과 wheel/설치물 직접 대조 불일치0. 제품 바이트는 f7c1945와 동일. 확인 전후 HEAD 동일, 제품 tracked diff 비어 있음. 제품 재빌드가 필요한 구휠 결함 아님.
- 새 git archive SHA256 `75a5a4eaa97ba5d5995dc7561953948d5ac0e38e2d7a67b76512bcdc6ff9c16d`. 변경 테스트 SHA256 `6adc5589ca26e086606954d178c782acbf68a7cbae194c6a9c3ebe08138a2e03`, HEAD와 고정 복사본 동일.
- JARVIS `1672626c5f2b0b06f7fb93c900cf8771536b58cd`, dist `/var/tmp/jarvis-artifact-1672626/source/dist`. inventory34768개 SHA256 `e9751dfaf955bab6a1ea15792733e0af576f7bac540ca5efeb0b69d9bccbf9cd` 일치.
- deploy/scripts는 실제 과거 게이트 실행 핀 f7c1945와 바이트 동일. 이 비교 대상에서 바뀐 harness는 정상 M11 테스트뿐이다. `identity.json`, `product-bytes.json`, `harness-bytes.json`, `post-check.json`에 기록.

## 새 직접 실행 결과

| 검사 | 결과 | 원본/해석 |
|---|---|---|
| 제출 정상 M11 테스트 | **1 passed, 5.60s, EXIT0** | ordinary-test.log / ordinary-observation.json |
| 평범한 합성 worker TypeError | **예상대로 1 failed + 1 error, 5.49s, EXIT1** | ordinary-worker-error.log; 한 테스트의 assertion 실패와 teardown 경고 오류. 제품 결함이 아님 |
| 변경 테스트 Ruff | EXIT0 | ruff.log |
| 변경 테스트 타입 | 0 errors, 54 warnings, EXIT1 | changed-test-types.log |

새 정상5.60초를 과거8.11초 또는 기존86회귀/4.78초와 합산하지 않는다. 합성 오류 결과도 성공 테스트 수나 제품 결함 수로 세지 않는다. 타입54경고는 경로·행번호를 제외한 경고 메시지별 개수가 이전 동일 테스트와 일치한다(`type-comparison.json`). 타입 검사가 완전 통과했다고 쓰지 않으며 과거 제품3파일6경고와 비교하지 않는다. 불변 전체·DR·일반성능·운영/native 검사는 반복하지 않았다. 시간은 pytest 실행시간이고 MCP p95가 아니다.

정상 테스트는 고정 복사본에서 파일 수정 없이 실행했다. 이전의 read-only trace observer 복사본으로 테스트 로컬 응답·순서만 기록했다. 이전 검토 명령의 추가 `-W error`는 **이번에는 넣지 않았다**. 제출 모듈 자체의 filterwarnings와 예외 처리 보장을 검증하기 위해서다.

## M11 정상 본문과 시간 관계 — 완료 범위

현재 입력 unit 본문+실제 sid 인용을 반환하는 합성 모델 응답 이외에는 정상 제품 ingest/compile/MemoryRecord/세대/MCP 경로를 실행한다. 봉인 세대 제자리 수정이나 fake Cited/wiki-only 변경을 정정으로 바꾸지 않는다. 이는 실제 **in-process 제품 MCP** 검사이고 운영/native 인증·실모델 검증은 아니다.

정상 원문 Alpha 저장→ingest/compile→MCP Alpha body/record 조회→원문 Omega 정정→정상 pipeline→MCP Omega body/다른 record ID/새 generation 확인, 이후 Alpha 결과0. 중간 reader의 Alpha record ID는 초기와 같지만 ingest가 갱신한 generation은 다르다. 모든 정상 조회의 error는false, worker errors 배열은빈값이며 join 후 종료했다.

관측: compile 준비 이벤트2682645840403001ns → reader 호출2682645840674970ns → reader완료 후 read_done2682645914245636ns → compile/writer 반환2682646612929442ns → 최신Omega·구본문제외 확인. **ingest 세대는 중간 읽기 전에 갱신되고 Omega compile 게시가 읽기 완료 뒤**라는 정확한 범위다. 모든 writer 게시가 reader 이후라거나 pinned read를 붙잡은 채 동시 게시가 입증됐다고 확대하지 않는다. async query trace의 반복return은 suspension/resumption 때문에 생기므로 호출 수로 합산하지 않는다.

## Worker 예외 실패 보장 — 완료

`tests/test_mcp_generation_overlap.py`는 worker의 BaseException을 errors에 기록하고 preparing을 깨운 뒤 다시 raise한다. 모듈 pytestmark는 `PytestUnhandledThreadExceptionWarning`을 오류로 강제한다. join/alive·정상본문·record·generation·구본문제외 검사는 유지됐다.

별도 `ordinary_fault.py`는 **테스트 모듈의 run_compile 바인딩만** 합성 wrapper로 바꿔 worker thread에서 평범한 TypeError(`codex_synthetic_ordinary_worker_error`)를 발생시켰다. 메인 초기 compile은 원본대로 호출했고 제품 파일은 수정하지 않았다. errors 배열의 traceback으로 assertion이 실패했고, 재발생한 thread 예외도 제출 모듈 marker에 의해 teardown 오류가 됐다. 따라서 이전 네 예외에 포함되지 않았던 일반 TypeError가 조용한 pass로 남지 않는 것을 직접 확인했다. 모든 예외 종류를 일일이 실행한 것은 아니며 코드의 공통 포착/재전파 경로와 이 대표 일반 예외 결과를 근거로 판정한다.

## F 실행 핀·아카이브·상태 — 한정 완료

JSON gates.executed_pin/harness_commit은f7c1945, current_archive_pin은e13cd3b로 분리됐다. MD70행도 과거 f7c1945 실행·현재 아카이브와 같은 wheel·새 실행이 아님을 명시한다. 실제 `/var/tmp/sb-gates-f7c1945.log` SHA256 `a41a9ed1953a1ed7981356db1da49fb0415bd626faae07d26fe02a53a870fe36`는 이전 검토와 동일하며 INTEG/WORK의 실행 핀f7c1945와 맞는다. 동일 deploy/scripts 바이트를 이번에 대조했지만 이 과거 로그를 e13cd3b에서 새로 실행한 결과로 바꾸지 않았다.

MD53/121행은 현재 정상 테스트명과 Alpha/Omega·읽기 후 compile 게시 범위로 수정됐고 보류·미검증을 외부입력만으로 지우지 않는다. resume는 ready 인계와 native 검토대기blocked를 분리하며 과거 fakeCited 기술 차단과 구분한다. resume의 날짜만 적힌 2026-09-12 머리말은 정밀한 현재 runtime 시각이 아니다. 이번 실제 상태는 **UTC 2026-09-12T16:33:53.535000+00:00 / KST 2026-09-13 01:33:53, 화면5836939**의 native Goal blocked·새 검토 대기로 연결한다. 문서의 ready는 제품인수나 실행중이라는 뜻이 아니다. 패키지84e2c43 표기는 최초 정상본문 테스트 도입 커밋이며 현재 아카이브는e13cd3b이다.

## 전체 미완료와 다음 행동

두 일반 후속은 완료했으므로 **Grok에 추가 resume·새 구현 요청을 보내지 않았다**. 일반 범위의 새 결함 없이 불필요한 변경·재검사를 만들지 않는다. 원 A–F/M1–M14 미충족은 유지한다. M13 전체 수명과 이전 경계/삭제 관련 보류, 더 강한 pinned-read 게시 보장은 이 정상 pass로 닫지 않는다. M14 not_implemented도 운영허가 부족으로 재분류하지 않는다.

콘텐츠 관련 보류는 발생 검사 미확정에 따른 미검증이다. native 신원·세션·compaction/클라이언트 경로, 실제 업무·원문/운영corpus·한글gold, 운영전환·백업·timer 허가와 자료는 별도 외부 조건이다. 이들 전체가 완료됐다고 주장하지 않는다.

기존30분 자동화 enabled/`*/30 * * * *`/Asia-Seoul 읽기 확인, 설정 변경 없음. 다음 기존 감시 실행은 실제 새 제출·상태 변화를 확인하되 제한 분기는 재시도하지 않는다. 운영current41f0751/production_activated=false는 제출 정보이며 새 운영 점검/전환 없음. 새 작업·구현자·모델·주기·Codex 제품수정·auth복사·실사용자삭제·push 없음. 이미 완료된 오전 알림은 반복하지 않는다.
