# Codex 야간 독립 검토 — 36e86ab

**미통과. 새 inbox 폐기 경로에서 vault 밖 파일 삭제를 격리 재현했다. 원 M13 GUI 기억 수명과 M11 읽기 중 정정 계약도 미완료다.** 작성자는 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`이며 원래 Codex가 직접 실행한 것으로 표기하지 않는다. 제품 준비 인수와 운영 인수 모두 미완료. 원 `CODEX-GROK-OVERNIGHT-2026-09-11.md`, `CODEX-NIGHT-REVIEW-b9fc3d4.md`, A–F/M1–M14 및 R1–R7/V1–V5의 의미와 이전 한정 통과를 유지한다.

## 고정 대상과 직접 검증

제출 `36e86aba0587392d12ebefdffa7a90e68d272af9`, 선언 source `bafb832dc0c86dc4c82be39d587f6356908d8ee5`, release `/var/tmp/sb-candidate-27cb576/releases/55a8b68b7039a355a1562b1b0b0c551c9f3d2a56`, wheel SHA256 `a3679d532fc3bd591017d7dbc39056703d73581292c97c1025c45c32c1d1dc19`. JARVIS `1672626c5f2b0b06f7fb93c900cf8771536b58cd`, dist `/var/tmp/jarvis-artifact-1672626/source/dist`, inventory SHA256 `e9751dfaf955bab6a1ea15792733e0af576f7bac540ca5efeb0b69d9bccbf9cd`/34768 entries.

증거 루트는 `/var/tmp/codex-night-36e86ab-b4ysfcvi`이다. `identity.json`과 `post-identity.json`에 실제 manifest/runtime, 전후 HEAD·wheel·J inventory, 소스/검토 harness/로그 SHA256을 보존했다. **SB Python 182개는 frozen source/wheel/installed 실제 바이트가 모두 일치한다.** manifest source `27cb576eeeacb7a224a4f5d34d9b512ae036ba3b`와 bafb832 사이 sb/ diff는 없다. bafb832의 Chrome harness 추가는 제품 휠이 낡았다는 증거가 아니다. c519f55에서는 실제 sb/inbox.py와 sb/web.py가 변경되었다.

이번 직접 실행:

| 검사 | 결과 | 원본 |
| --- | --- | --- |
| 변경 연관 web/inbox/generation 회귀 7파일 | 50 passed, 18.24s, EXIT0 | related-regression.log |
| 새 MCP 테스트 + 원 호출 관측 plugin | 1 passed, 6.77s, EXIT0 | mcp-test.log, mcp-observation.json |
| Ruff sb tests | EXIT0 | ruff.log |
| 변경 제품 inbox/web 타입 | 0 errors, 5 warnings, EXIT1 | changed-product-types.log |
| a4b228f 동일 2파일 타입 대조 | 0 errors, 동일 5 warnings, EXIT1 | baseline-types.log |
| 새 후보 설치 standard | EXIT0 | installed-standard.log |
| 실제 Chrome 버튼/실제 pipeline 수명 진단 | 처리 전 폐기 성공, 처리 후 기억 삭제 미충족 | ui-result.json, ui.log, PNG |
| 합성 fixture 실제 HTTP 삭제 경계 | 외부 canary 삭제 재현 | discard-safety.json/log |
| 제출 Chrome harness 관측 복사본 | EXIT1; run_invoked=true이나 실제 run failed | submitted-browser.log, submitted-browser/evidence.json |

정확한 pytest/ruff/type/설치 argv·cwd·환경은 `run.py`에 있다. GUI는 `ui.py`/`ui.mjs`, HTTP 경계는 `discard-safety.py`로 재현한다. `TMPDIR=/var/tmp`, frozen archive와 제품 venv, 합성 fixture만 사용했다. MCP plugin은 원 호출을 그대로 실행하며 시작/종료와 결과를 기록한다. 결과 대역이나 sleep으로 동시성을 만들지 않았다. 타입 경고는 기존 web run 응답 처리의 동일 위치에 있어 새 타입 회귀로 세지 않으며 타입 통과라고도 쓰지 않는다.

기존 복원/만료 fence 거부/fresh 2scope/원장 retry/JARVIS 테스트는 해당 불변 바이트와 이전 원본 범위로 유지했다. 이번에 다시 실행하거나 51개에 합산하지 않았다. 전체 회귀도 반복하지 않았다. 이전 전체 1837 passed/1 failed/2 skipped와 후속 결정적 cold 1 pass는 각 실행의 결과로 유지하며 이번 전체 통과로 바꾸지 않는다.

## P1 — 새 discard API가 symlink inbox를 통해 vault 밖 파일을 삭제함

위치: `sb/inbox.py:70–81`, `sb/web.py:477–482`. `discard_inbox`는 `(root / "inbox").resolve()`를 허용 경계로 사용하지만 그 경계가 vault 안인지 확인하지 않는다. vault/inbox 자체가 외부 디렉터리 symlink이면 `inbox/canary.md`는 문자열 검사와 resolved inbox 검사를 모두 통과하고 외부 파일에 `unlink()`한다.

실제 HTTP `/api/inbox-discard` 재현 (`discard-safety.py/.json`): 정상 pending 파일은 200/삭제, `../outside-vault/canary.md`는 400, 개별 외부 파일 symlink도 400/외부 파일 보존. 그러나 합성 vault의 inbox를 합성 outside-vault 디렉터리 symlink로 바꾼 뒤 `{"inbox_path":"inbox/canary.md"}`를 보내면 **200이고 외부 canary가 실제 사라졌다**. fixture `/var/tmp/codex-discard-safety-mrnjja40` 밖 실사용자 파일은 건드리지 않았다. 단순 경로 검토나 helper 호출만의 추측이 아니다.

완료 기준: 원 inbox 파일 경계를 vault 기준으로 강제하고 symlink 부모·대상/경로 교체에도 외부 unlink가 불가능하게 처리한다. 기존 안전한 filesystem primitive와 writer/generation 계약을 사용한다. 정상 폐기, 잘못된 경로, 파일/부모 symlink 거부, 실패 후 정상 입력 복구와 파일 보존을 함께 검증한다. `..`만 추가 검사하는 것으로 끝내지 않는다.

## P2 — M13: 처리 전 receipt 폐기는 처리된 기억 삭제 수명을 대체하지 못함

Codex는 실제 Chrome의 보이는 컨트롤을 클릭했다. 빈 폐기 입력 400 → 기억 입력/저장 201 → 같은 폐기 버튼 200은 통과했다. 이어 `codex36processedneedle`을 새 기억으로 저장하고 실제 처리 버튼으로 원 `run_all`을 실행했다. deny 로컬 소스/briefing cap0 합성 설정에서 run `533a6e93be52421d8d6f2292ca378964`는 status ok, pages1, errors0, exit0이다. 검색 버튼에서 해당 기억 1개를 확인한 뒤 원 receipt를 같은 폐기 버튼으로 보내면 **400 inbox receipt missing**, 다시 검색해도 **동일 기억 1개가 남는다**.

`ui-result.json`은 `inbox/.done/2026-09-12T115128145301-processed-memory.md` 원문과 `wiki/inbox-2026-09-12t115128145301-processed-memory-f18f26f8.md`, 최종 git `b8127127756a7a3b1cb3ba7142b074e957aa5c48`도 기록한다. 이는 receipt 폐기의 설명과 다른 동작이라는 주장이 아니라, 그 한정 기능으로 원 GUI 정정/삭제·원문/영수증·검색/범위 반영 수명을 인수할 수 없다는 판정이다. 이전 실제 충돌 정정 GUI 통과는 유지한다.

완료 기준: 원 M13에 필요한 처리된 기억의 최소 삭제 연결을 기존 요청/실행/영수증/철회 계약으로 구현하고 합성 fixture의 실제 GUI에서 원문·영수증·검색·범위 조회와 삭제 후 재실행/재색인에서의 수명을 확인한다. 실패 원인 표시 → 입력 정정 → 동일 경로 성공과 실패 이력 보존을 함께 끝낸다. 무관한 새 기능이나 실제사용자 삭제는 요구하지 않는다.

제출 `scripts/isolated-browser-m13-lifetime.py:100–158`은 새 기억을 처리 전에 폐기하고 다른 기존 TERM의 검색 유지 여부를 확인한다. CDP에서 페이지 전역 함수를 직접 호출하며 실제 버튼 클릭 증거와 구분해야 한다. `conflict_fail`은 어떤 비어 있지 않은 문자열도 참이고 `conflict_ok_commit`은 required에 없다. bafb832의 `run_invoked`는 요약문이 비어 있지 않으면 참이다. frozen 복사본에서 포트와 raw 응답 관측만 변경한 이번 재현은 **전체 EXIT1**이었고 remember 오류 문구 검사가 실패했다. 동시에 실제 run은 `SafeSourceFilesystemError: source mutation observed: .`, pages0/errors1/exit1인데 run_invoked=true였다. 전체 harness가 통과했다고 주장하지 않는다. 이 실패를 제품 결함으로 추가 집계하지 않는다. 성공 요약 존재만으로 실제 작업 성공을 인수하지 말고 관련 입력과 status/실제 결과를 연결해야 한다. 복사본 변경은 `browser-adaptations.txt`와 frozen 원본/hash로 추적된다.

## P2 — M11: 실제 MCP 조회는 있으나 읽기 중 정정이 없음

`tests/test_mcp_generation_overlap.py:64–144`는 실제 in-process MCP Client로 허용/거부 조회를 동시에 시작한다. 이를 과거 helper 검사와 동일시하지 않는다. 다만 `anyio.run(overlap)`가 94행에서 모두 끝나고 client가 닫힌 뒤 107행 원문 수정, 116–117행 ingest/compile을 수행한다. 다음 새 client에서 다시 읽는다.

직접 관측은 MCP read4, writer stage2이며 **rpc_overlaps_mutation=false**이다. 첫 두 읽기의 종료가 ingest 시작보다 앞서고 다음 두 읽기는 compile 종료 뒤다. 수정 원문은 `Omega replacement memory.`인데 전후 검색은 모두 `Cited`; 실제 반환 record_text도 전후 `Cited.`다. 세대·sid 변경은 검증하지만 정정된 본문 회수와 이전 본문/버전 제외를 입증하지 않는다. 외부 stdio MCP 성능 측정으로 확대하지도 않는다.

완료 기준: 합성 fixture, 실제 MCP 클라이언트와 제품이 수락한 정정 경로, 결정적 barrier/event를 사용해 읽기 중 writer commit/세대 갱신을 실제로 겹치게 한다. 허용/거부 scope, 정정 전후 body/version, old version 제외 및 새 fence 이후 일관된 조회를 함께 검증한다. fake compile의 고정 `Cited.` 반환으로 본문 정정을 대신하지 않는다. 운영 corpus 없이 실행 가능한 원 계약이다.

## P2 — F: 제출 출처와 상태를 정확히 통합해야 함

패키지 MD13행의 “sb 제품 바이트는 a4b228f와 동일”은 `git diff a4b228f..c519f55 -- sb`의 inbox/web 변경과 모순이다. manifest27cb576과 선언bafb832는 제품 바이트가 같으므로 구휠 결함은 아니다. 제품 source, 테스트 source27, Chrome harness sourcebafb, 각 실제 실행 source·명령·로그를 구분해야 한다. c519f55 gate log에 bafb832 harness_commit을 붙이는 경우 해당 harness 동일 바이트를 근거로 이전 실행임을 명시해야 한다. resume 상태는 아직32e58fe이며 JSON M13은 새 pending 폐기 컨트롤을 반영하지 않은 “no GUI delete control”이다. 정확히 pending 폐기 구현/compiled 수명 미완으로 갱신한다.

이전 RTO 숫자 불일치는 이번 1958/9418/46ms로 정정됐으므로 해소로 인정한다. 재측정하지 않았다. 새 품질 게이트를 과거 로그 source로 다시 이름 붙이지 말고 구체적인 구현/검증/보류 상태를 한 진입점에서 정합화한다.

## 통합 재개와 외부 조건

위 네 항목을 단일 지시로 기존 Grok에 전달하고 현재 승인된 native goal을 공식 `/goal resume`로 재개한다. 제품 및 검증 구현은 Grok가 맡는다. 좁은 receipt/helper 성공을 원 계약 전체 완료로 해석한 반복 중단을 완료 audit에서 바로잡는다. 추가 사용자 답변을 요구하는 새 게이트를 만들지 말고 관련 정상/실패/복구를 함께 끝낸 고정 후보를 제출한다. 전달 ACK, native active, 실제 도구 착수, 수정 후 다음 단계 지속은 별도 증거로 JSON/상태에 기록한다.

실인증/native 프로필·사본/compaction, 실사용자 업무·한글 정답집/운영 corpus, 운영 백업·전환 허가/timer는 정확한 외부 조건으로 남는다. 위 M11/M13 격리 작업과 경계 결함 수정은 외부 입력 대기 항목이 아니다. 운영 current41f0751/production_activated=false는 패키지 제출 정보이며 이번 운영 health를 새로 검증한 것은 아니다. Codex 제품 소스 수정, 인증 복사, 운영 전환, 실사용자 삭제, push는 없었다. 기존 30분 스케줄을 유지한다.

재개 확인: 2026-09-12 20:59:27 KST 공식 resume ACK `6558767a-810b-4b31-a5d0-0e27bbb428ca`, 통합 지시 ACK `1522b252-3a5b-40d8-a6c5-fa8bdda9d2fa`. 21:00:44 화면5818200에서 P1 관련 O_NOFOLLOW/unlink primitive 탐색 도구 완료, 후속 read 실행, native Pursuing6h12m 확인. 실제 결함 조사 착수는 확인했으며 제품 패치 완료·단계 간 지속은 아직 미확인이다. `delivery.json`/`worker-public-screen.json` 참조.
