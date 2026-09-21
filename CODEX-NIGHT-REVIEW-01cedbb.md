# Codex 야간 독립 검토 — 01cedbb

**전체 인수 미완료. 정상 원문 정정→MemoryRecord 본문·버전 갱신→실제 MCP 최신 조회/이전 본문 제외 경로는 확인했다. 제출 M11 검증과 상태 문서의 정리가 필요하며, 콘텐츠 제한과 관련될 수 있는 분기는 보류/미검증으로 유지한다.** 작성자는 사용자 지정 기존 감시 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`다. 원래 Codex는 중복 검토/제품 수정을 하지 않았다는 사용자 전달을 기록한다.

원 `CODEX-NIGHT-REVIEW-d623089.md/.json`, 야간 정본과 A–F/M1–M14의 의미·한정 통과를 유지한다. 최신 사용자 지시가 계속 실행할 범위를 **일반 제품 기능과 출처 정합성**으로 제한했다. 보류 분기를 다른 모델/세션/도구/Grok에 맡기거나 재시도하지 않는다.

## 고정 대상과 출처

제출 `01cedbb0ecde3e022066090ea9ee9dfc255b6846`, source `f7c194594e21728678b118e7c0029cd3e1deb30b`, 후보 `/var/tmp/sb-candidate-f7c1945/releases/d9c6825b9a94cf6637ba01416562e4eb777db7a2`, wheel SHA256 `1847b5994392cde8f76e21604a26ed2aee3bb4a43bd7eb04e783615465b317fb`. JARVIS `1672626c5f2b0b06f7fb93c900cf8771536b58cd`, dist `/var/tmp/jarvis-artifact-1672626/source/dist`, inventory SHA256 `e9751dfaf955bab6a1ea15792733e0af576f7bac540ca5efeb0b69d9bccbf9cd`/34768 entries.

원본 `/var/tmp/codex-night-01cedbb-ngqqvboh`의 `submission.json`, `identity.json`, 이어서 일반 출처 검사 `normal-continuation/post-identity.json` 참조. **182 Python 파일 source/wheel/installed 실제 바이트 일치**, J inventory 동일, HEAD01cedbb와 제품 tracked diff 없음. 검토 harness는 frozen source에 대한 별도 복사본이다. 이전 d623089 원본과 이번 제한 안내 이전 원본을 덮어쓰지 않았다.

## 콘텐츠 제한과 실행 범위

사용자는 화면24954에 “This content can’t be shown / Daybreak isn’t available for Astra. Some cybersecurity requests may still be limited.” 안내와 입력 대기를 직접 확인했다고 전달했다. **어떤 검사에서 안내가 발생했는지는 원인 미확정**이다. 특정 검사·정책·비공개 추론 때문이라고 추측하지 않는다. 이 검토의 보안 경계/삭제 경합 등 관련될 수 있는 추가 재현은 중단했다. 해당 분기는 보류/미검증이며 전체 인수의 통과로 간주하지 않는다. 제한 뒤 새로 수행한 것은 아래 정상 제품 정정과 출처 검사뿐이다.

제한 전 저장된 결과는 그 당시 범위대로 보존한다. `race.json`에는 checked fd가 열린 상태의 교체 진단과 FIFO 거부가 기록돼 있고, `ui-result.json`과 제출 Chrome 로그에는 GUI·복원 진단이 있다. 이 보존은 재시도나 후속 실행 지시가 아니다. 삭제 전 백업에서의 재노출을 단순 RPO로 이름 바꿔 원 수명 계약을 충족했다고 판정하지 않는다. 삭제 후 백업 복원 테스트만으로 삭제 전 백업 수명을 대신하지 않는다. 이 분기의 추가 검사/수정 요청은 이번 Grok 전달 범위에서 제외한다.

## 실제 실행 결과의 구분

| 범위 | 저장된 결과 | 해석 |
| --- | --- | --- |
| 제한 전 연관 회귀 | 86 passed, 19.82s | related-regression.log; 반복하지 않음 |
| 제한 전 제출 MCP 테스트 | 1 passed, 5.83s | mcp-test.log; 본문/게시 중첩 전체 인수 아님 |
| 제한 전 Ruff | EXIT0 | ruff.log |
| 제한 전 제품 3파일 타입 | 0 errors/6 warnings, EXIT1 | changed-product-types.log; 기존 동일3파일 경고와 같은 범위 |
| 제한 전 설치 standard | EXIT0 | installed-standard.log |
| 제한 전 normal-overlap | 1 failed, 3.87s | local-deny fixture의 초기 scoped 본문 결과0 |
| 제한 전 record-overlap | pytest 1 passed, 33.47s | 본문 정정은 성공했지만 held_read는 실패. 동시성 성공 문구를 정정함 |
| **제한 후 새 일반 기능 검사** | **1 passed, 4.78s** | normal-continuation/run.log; 아래 정확한 범위 |

새 1개를 이전 86개나 기존 재현 수치에 합산하지 않는다. 기존 전체 회귀/paired DR/2scope/원장 retry/JARVIS 테스트도 재실행하지 않았다. 정상 검사에서만 합성 fixture·`TMPDIR=/var/tmp`·frozen source를 사용했다. 운영 인증/자료는 복사하지 않았다.

## 정상 M11 차단 원인과 재현 가능한 해결 경로

Grok 공개 화면은 `Goal blocked: M11 Omega-body scoped MCP overlap cannot be closed on this fixture`를 표시했다 (`worker-public-screen.json`의 제한 전 관측). 봉인된 generation의 .git PermissionError와 wiki만 Omega로 바꿔도 MemoryRecord가 Cited라 검색0이라는 구체 사유는 사용자 전달 내용이다. 이번 검토에서 그 제자리 수정 시도를 재실행하지 않았다.

코드상 `sb/pipeline.py:_CitedFake`는 입력 사실을 정정해도 `Cited.[^sid]`를 반환한다. `sb/compile.py:_compile_one`은 모델 본문을 정상 derivation/PageSpec 경로에 넣는다. 따라서 고정 fake Cited 출력이나 wiki 파일만의 별도 변경을 정정 MemoryRecord의 증거로 사용할 수 없다. 제한 전 local-deny 실험도 초기 scoped 결과0이었으므로 정상 본문 fixture로 성공했다고 주장하지 않는다. 이 결과만으로 local-deny 전체의 제품 결함을 단정하지 않는다.

`normal-continuation/test_normal_update.py`는 합성 모델 응답만 **현재 입력 unit의 본문과 실제 sid 인용**으로 결정적으로 만든다. 제품 ingest/compile/MemoryRecord 생성/writer/세대 게시/MCP 코드는 그대로 실행한다. 실제 운영 모델/인증 검증은 아니다. 봉인 세대 제자리 수정, chmod, wiki-only 변경, MemoryRecord 수동 삽입은 없다.

직접 결과 `normal-continuation/result.json`:

- 원문 `Alpha original unique memory.` 저장 후 정상 ingest/compile, 실제 in-process MCP의 MemoryRecord 본문 Alpha 확인.
- writer가 원문을 `Omega corrected unique memory.`로 정정하고 정상 ingest/compile의 새 본문 준비 단계에 들어감.
- 그 준비 단계에서 정상 MCP reader가 Alpha 본문을 오류 없이 읽고 완료.
- reader 완료 후 모델 응답을 반환하고 정상 writer가 새 generation을 게시.
- 최신 MCP는 정확한 Omega MemoryRecord 본문/다른 record_id/새 generation을 반환하고 Alpha 검색은 결과0. 모든 worker 예외를 수집·검사하며 thread 오류0.

관측 순서는 `writer_started → writer_preparing_new_compiled_body → normal_reader_started → normal_reader_completed → writer_model_response_released → writer_published`다. 정상 읽기와 writer 준비가 겹치며, **게시 자체는 reader 완료 뒤**다. 이를 게시와 pinned read의 동시 완료로 확대하지 않는다. 원 M11이 그보다 강한 보장을 요구하는 부분은 미검증으로 남긴다.

## 검토 harness의 잘못된 이전 통과 문구 정정

기존 `record-overlap.json`은 `held_read.error=true`, `reader_resumes_after_publish` 이벤트 없음, writer 게시가 약30초 뒤인 것을 기록한다. 그런데 검사에 held_read 성공 assertion이 없어 pytest는 pass였고 result 문구는 overlap 성공이라고 썼다. **이 문구는 잘못이며 취소한다.** 원본을 수정하지 않고 이 보고서와 `normal-continuation/interpretation.json`에 정정한다. Alpha→Omega 본문/record 변화와 이후 Alpha 제외 관측만 보존한다.

`sb/generations.py:637`의 reader pin은 응답 완료까지 공유 잠금을 유지하고 `sb/generation_locks.py:42`의 writer는 reader가 끝나야 게시를 위한 독점 잠금을 얻는다. 따라서 reader를 잡은 채 publication 완료를 기다리는 이전 검토 harness는 이 잠금 순서와 맞지 않았다. 시간 초과를 제품 결함으로 세지 않는다. 위 새 정상 검사는 writer 준비 단계에서 실제 읽기를 완료하게 하여 이 잘못된 대기를 제거했다.

## 일반 기능 후속과 F 상태 정합성

제출 `tests/test_mcp_generation_overlap.py`는 여전히 fake Cited/hex sid와 `allowed is not None`을 사용한다. 객체 존재는 정상 허용 응답 검증이 아니다. 새 정상 fixture의 방식으로 **현재 unit 기반 인용 본문**, 실제 reader 성공, 정정 MemoryRecord/body/record_id/generation, 이전 본문 제외, 정상 thread 예외 전파와 event 순서를 제출 테스트에 반영해야 한다. 보호 검사를 약화하거나 봉인 파일을 직접 바꾸는 방식으로 테스트를 맞추지 않는다. 이번 전달은 이 일반 제품 검증과 문서 정합화만 요청한다.

패키지 frozen source/gates는 f7c1945로 갱신됐지만 MD18행 source 표시는c519f55이고 JSON M11은 이전 helper, M13은no GUI delete control이다. resume는ready_for_final_review지만 실제 화면은blocked였다. 실제 단계·소스/테스트/harness/로그·성공과 미검증을 일치시켜야 한다. 대규모 corpus/실사용자 질문이 필요한 범위와 이번 합성 일반 기능 작업을 구분한다. 이번 source의 Ruff0와 기존 경고6은 과거 관측의 실패 수치로 덮어쓰지 않는다.

## 전달·보류·외부 조건

기존 Grok `term_dc97574f3e548cff6e25679d713ed8c2`에는 **정상 원문/본문 정정 검증과 출처·상태 정리만** 직접 전달한다. 콘텐츠 제한 관련 분기의 재현·수정·우회는 요청하지 않는다. 현재 목표의 실행 범위를 이 사용자 지시로 한정한 뒤 공식 `/goal resume`를 사용하고 ACK/실제 도구 착수/제품 변경/단계 간 지속을 구분한다. 이 일반 작업은 운영 인증이나 사용자 추가 답변이 필요한 차단이 아니다.

실인증/native 세션·compaction, 실사용자 업무·정답집/운영 corpus, 운영 전환·백업/timer는 기존 외부 조건으로 유지한다. 콘텐츠 제한은 외부 인증 대기와 별개의 미검증 사유다. 운영 current41f0751/production_activated=false는 제출 정보이며 새 운영 점검/전환은 없다. 제품 인수 미완료. 새 작업·구현자·모델·주기 변경, 인증 복사, 실사용자 삭제, push 없음. 기존30분enabled 유지, 이미 완료된 오전 알림은 반복하지 않는다.


2026-09-13 00:11:37 KST 실제 착수 확인: 기존 Grok 화면5832966에서 `Copy Codex test locally and read in chunks` 도구 완료와 정상 MCP 검토 파일의 실제 출력, Working4s/native Pursuing goal8h1m을 확인했다. 전달 접수와 공식 목표 재개에 더해 **일반 검증 파일 조사·복사 착수**가 확인됐다. 명시적 수신 답변, 제품 수정 완료와 단계 간 지속까지 확인한 것은 아니다. 증거는 `/var/tmp/codex-night-01cedbb-ngqqvboh/worker-public-screen.json` 및 `normal-continuation/delivery.json`이다. 다음 작업은 기존 Grok의 정상 본문 정정 테스트와 출처 문서 정합화이며, 제한된 분기는 보류한다.
