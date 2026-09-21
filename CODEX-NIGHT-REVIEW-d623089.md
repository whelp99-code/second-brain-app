# Codex 야간 독립 검토 — d623089

**미통과. 이전 외부 파일 삭제는 해결됐고 실제 GUI 페이지 삭제와 현재 세대 검색 제외는 통과했다. 경합/FIFO 처리, 삭제의 복원 수명, M11 동시 정정과 본문 검증, F 상태·검증 자료의 잔여가 있다.** 작성자는 사용자 지정 기존 Codex 감시 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`다. 원래 Codex `term_133874c8`는 동일 후보 검토를 시작하지 않았다는 사용자 전달에 따라 이 작업에서 수행했다. 제품 준비 인수/운영 인수는 모두 미완료다.

원 `CODEX-GROK-OVERNIGHT-2026-09-11.md`, 본인 `CODEX-NIGHT-REVIEW-36e86ab.md/.json`, A–F/M1–M14 및 R1–R7/V1–V5의 의미와 한정 통과를 유지한다. pending receipt 폐기, compiled 페이지 삭제, 원문 보존, scoped 조회, 철회/복원 수명을 서로 대체하지 않는다.

## 고정 바이트와 실행 범위

제출 `d62308945e7905f72f9395861c60b6c4041674ef`, 제품 source `cf1c021dfa9fb15ac5dffbe619e42f6d3cdf4186`, 후보 `/var/tmp/sb-candidate-cf1c021/releases/9680e4fe7f1ea81ea81031bebbea8700346c12c3`, wheel SHA256 `8f7a8420bb790ef52dec3d557eb5c5a5bdda4bd5df9b312c9c7f7a088bf88948`. JARVIS `1672626c5f2b0b06f7fb93c900cf8771536b58cd`, dist `/var/tmp/jarvis-artifact-1672626/source/dist`, inventory SHA256 `e9751dfaf955bab6a1ea15792733e0af576f7bac540ca5efeb0b69d9bccbf9cd`/34768 entries.

증거 `/var/tmp/codex-night-d623089-cjrac1ji`의 `submission.json`, `identity.json`, `post-identity.json`, `evidence-sha256.json` 참조. **Python 182개 source/wheel/installed 실제 바이트 일치**, J inventory 전후 일치, 검토 종료 전 HEAD d623089 및 제품 tracked diff 없음. 16f69cf는 inbox/MCP/Chrome, cf1c021은 vault/web/Chrome 변경이다. 검토용 복사본과 새 합성 fixture만 작성했다. 이전 `/var/tmp/codex-night-36e86ab-b4ysfcvi` 원본은 보존했다.

| 이번 직접 검사 | 결과 | 원본 |
| --- | --- | --- |
| web/inbox/generation/vault 연관 회귀 9파일 | **84 passed, 21.37s, EXIT0** | related-regression.log, run.py |
| 새 MCP 테스트, 원 호출 forwarding 관측 | **1 failed, 1 warning, 35.74s** | mcp-test-first.log, mcp-observation-first.json |
| 관측 없는 원본 MCP 테스트 확인 | **1 passed, 5.67s** | mcp-uninstrumented.log |
| 실패 원인 확인용 상세 응답 관측 | **1 failed, 1 warning, 36.13s** | mcp-observed-confirmation.log, mcp-observation.json |
| Ruff sb tests | **EXIT1**, F841 allowed 미사용 | ruff.log |
| 변경 제품 inbox/web/vault 타입 | 0 errors/6 warnings, EXIT1 | changed-product-types.log |
| 36e86ab 동일 3파일 타입 대조 | 동일 0 errors/6 warnings, EXIT1 | baseline-types.log |
| 설치 standard | EXIT0 | installed-standard.log |
| 실제 Chrome 버튼과 실제 pipeline/forget | 한정 수명 통과, 복원 후 재노출 | ui-result.json, ui.log, PNG |
| 합성 generation의 실제 HTTP forget→새 MCP 조회 | 진단 1 passed, 3.00s; 현재 결과0 | scoped-forget.json/log, test_forget_scoped.py |
| 제출 Chrome harness, 포트만 바꾼 복사본 | EXIT0, conflict_fail=false | submitted-browser/evidence.json/log |
| 삭제 경계/경합/FIFO 진단 | 외부 canary 보존; 교체 파일 삭제/FIFO 대기 | discard-safety.json/log, race.json/log |

pytest 숫자는 각각의 실제 실행이며 MCP 재실행을 고유 테스트 수로 더하지 않는다. scoped 진단의 pass는 아래 제한을 관측한 harness 완료이며 원 삭제 수명 전체 pass가 아니다. 이전 전체 회귀/복원/2scope/원장 retry/JARVIS 검사는 반복하거나 새 실행으로 합산하지 않았다. 새 vault 삭제의 영향은 해당 vault/web/generation 회귀와 실제 새 경로로 검증했고, 이미 구체적 실패가 있는 같은 트리의 전체 회귀를 반복하지 않았다. 타입 경고는 동일 세 파일의 이전 바이트와 같고 새 타입 오류로 세지 않는다. 원본 명령은 `run.py` 및 각 검토 harness, 환경은 `TMPDIR=/var/tmp`, frozen source PYTHONPATH/제품 venv다.

## 이전 P1 해결 및 P2 — 삭제 경합/특수 파일 처리

`sb/inbox.py:72`는 이제 vault/inbox를 dir_fd + O_NOFOLLOW로 연다. 이전 HTTP 재현의 정상 파일200, 경로 이탈400, 개별 외부 symlink400, inbox 부모 외부 symlink400이고 합성 외부 canary가 보존됐다. **이전 vault 밖 unlink P1은 해결로 인정한다.** cf1c021 forget도 동일한 디렉터리 fd 방식이다.

남은 직접 재현은 `race.py`/`race.json`이다. 합성 inbox/receipt.md를 검사한 fd가 닫힌 후 실제 unlink 직전, 검토 hook으로 원래 파일을 original-preserved.md로 옮기고 같은 이름에 NEW_PENDING_CANARY를 만든 결정적 교체 순서를 실행했다. 제품의 원 unlink를 그대로 호출하면 새 파일이 삭제되고 receipt 성공을 반환하며 원본은 남는다. 검사한 inode와 실제 제거 대상이 연결되지 않는 경합이다. 외부 경계가 다시 뚫렸다는 주장은 아니다. 이는 helper의 시스템 호출 경계 진단이며 실제 GUI 버튼 경합으로 표기하지 않는다.

동일 fixture에 FIFO를 두고 별도 프로세스에서 원 discard_inbox를 실행하면 3초 제한까지 반환하지 않았다. 검토 harness가 자식만 종료했다. 파일 open에 O_NONBLOCK이 없어 fstat의 regular-file 거부 전에 대기한다. `sb/vault.py:294`의 신규 forget도 같은 blocking open 형태지만 그 FIFO 사례는 별도로 실행하지 않았으므로 확인된 재현은 inbox에 한정한다.

완료 기준: 삭제 대상을 검증한 뒤 다른 대상이 제거되지 않는 안전한 처리/경합 거부를 정하고 기존 writer·filesystem 계약과 연결한다. 특수 파일을 blocking open 없이 거부한다. 정상/부모·대상 symlink/교체/특수 파일/실패 후 정상 입력 복구와 파일 보존을 함께 검증한다. 외부 canary 보호 개선을 되돌리지 않는다.

## P2 — M13: 현재 페이지 삭제는 통과, 지속되는 기억 철회/복원 계약은 미완료

`ui.py`/`ui.mjs`는 실제 Chrome 보이는 버튼을 클릭했다. 기억 저장201 → 실제 pipeline status ok/pages1/errors0/exit0 → 해당 기억 검색1 → 처리된 receipt의 pending 폐기400 → 같은 기억 검색1을 확인했다. 이후 없는 page_id로 **페이지 삭제400**, 실제 검색된 page_id로 입력 정정 후 **동일 버튼200/commit `dfdb4e33e334c3ce197782ab009592a9d3b3ae22`**, 검색0을 확인했다. 후속 실제 처리 버튼은 pages0/errors0/exit0/검색0이었다. 별도 원 run_compile도 pages0/검색0이다. 이전의 “처리된 기억 삭제 버튼 없음”은 해소됐고, 정상 후속 처리에서 즉시 부활한다는 결함은 관측되지 않았다.

세대형 합성 fixture에서도 실제 HTTP forget200 후 새 MCP scoped 검색은 결과0/새 generation이며 tombstone_sequence는 전후0이었다 (`scoped-forget.json`). 원문 source는 남는다. 단순 owner 검색0을 scoped 전체 통과로 치환하지 않고 이 실제 한정 MCP 관측을 따로 인정한다.

다만 삭제 전 제품 create_backup으로 만든 **합성** archive를 삭제 후 새 격리 경로에 제품 restore_backup으로 복원하고 실제 HTTP 검색하면 같은 기억이 다시1건 반환된다. 원 inbox `.done` 원문도 남는다. 이는 저수준 백업 복원 자체의 새 버그라는 판정이 아니며, 현재 GUI forget가 git 파일 제거/commit만 반환하고 기존 철회 원장·high-water/복구 수명과 연결됐다는 증거가 없다는 직접 경계 확인이다. 원문 보존 자체도 A 계약 위반으로 세지 않는다. 보존된 원문·백업이 삭제/철회 뒤 어느 읽기·재진입 경로에서 배제되는지 원 계약에 맞게 연결해야 한다. 운영/native 백업을 시험한 결과가 아니다. 이전 paired DR 게이트도 이번 GUI forget의 복원 수명을 검증한 것으로 확대할 수 없다.

완료 기준: 새 GUI 동작을 기존 승인된 기억 수명/요청·영수증·철회 계약과 연결하고, 페이지 제거와 원문 보존/삭제 범위 및 복원 후 배제 기준을 명시한다. 합성 자료에서 정정/삭제 후 원문·영수증·scoped 조회, 재색인/재진입·복원 시 금지된 재노출 방지를 증명한다. 해당 세대 정상 삭제 통과는 보존한다. 실사용자 삭제나 새 무관 기능은 요구하지 않는다.

## P2 — M11: barrier가 거부 경로 도달을 가정하며 정정 본문 검증도 없음

새 테스트 `tests/test_mcp_generation_overlap.py:64–91`의 Barrier(3)는 허용 helper/거부 helper/writer를 기다린다. forwarding observer를 넣은 직접 두 실행에서 거부 MCP 요청은 약 3ms 안에 **MEMORY_SCOPED_READ_DENIED**로 반환했고 helper barrier에 도달하지 않았다. 허용 helper와 writer는 BrokenBarrierError, writer ingest/compile 호출0, 최종 generation 동일 assertion 실패다. `mcp-observation-first.json` 및 상세 `mcp-observation.json`은 read4/write0/rpc_overlaps_mutation=false를 기록한다.

관측 없는 원 테스트는 별도 실행에서 1 pass였다. 따라서 “항상 실패하는 제품 결함”으로 단정하지 않는다. 관측 plugin은 원 call_tool/ingest/compile을 그대로 forwarding하고 시간/결과만 기록하며 반환을 바꾸지 않는다. 타이밍에 민감한 허용/거부 진입 순서와 fixture barrier 가정이 드러났고, 거부가 정상적으로 일찍 반환할 수 있는 계약을 deterministic overlap으로 검증하지 못한다. 이 제출 테스트/harness 문제를 새로운 MCP 제품 결함 수로 올리지 않는다.

또 127행 `allowed`를 받아 놓고 기존 허용 응답 검사를 제거했다. Ruff F841이 직접 발생한다. writer는 여전히 fake compile, 수정 입력은 Omega지만 검색/본문 검사는 Cited/hex sid다. 새 본문 회수와 구본문/구버전 제외가 없다. barrier 동시 출발만으로 writer commit이 읽기 진행 중 발생했는지도 강제하지 않는다.

완료 기준: 허용 읽기와 writer의 결정적 동기화, 별도의 정상 거부 경로, thread 예외 전파와 read/commit 경계 관측으로 실제 중첩을 입증한다. 허용 응답 검사를 복구하고 정정된 실제 body/version 및 이전 버전 제외를 함께 확인한다. fake 고정 Cited 응답을 정정 본문 증거로 삼지 않는다. 합성 fixture로 가능한 원 M11 계약을 외부 입력 대기로 돌리지 않는다.

## P2 — F 및 Chrome 실패 검증 정합성

wheel/source 핀과 a4b 제품 동일 문구는 수정됐다. 새 source/wheel/installed 일치를 위에서 직접 확인했고 이전 RTO1958/9418/46 정정도 유지한다. 그러나 resume 파일은16f69cf/compiled forget pending, 패키지 MD18행은c519f55, JSON M13 remaining은no GUI delete control이다. 실제cf1c021 구현 상태와 모순이다. M11 증거도 여전히 이전 helper테스트를 가리킨다. 최신 실제 실행 출처·성공/실패·미검증을 한 진입점으로 정리해야 한다.

제출 Chrome harness는 실제 button.click과 run status/pages/errors/exit 검사를 추가했고 이번 frozen 복사본 직접 **EXIT0**, pages1/errors0/exit0/삭제commit/검색제외를 기록했다. 이전 요약문 존재만으로 run 성공 처리한 문제는 개선됐다. 하지만 evidence의 **conflict_fail=false인데 required에서 제외**되어 전체 성공한다. `_click_wait`의 busy 빈 문자열/기존 결과 읽기 경로와 필수 assertion을 고쳐 실패→정정→성공을 실제 응답에 연결해야 한다. `NEEDLE not in search_forgotten`도 정확한 HTTP200/구조화 results=[] 확인으로 보강해야 한다. 이는 기존 Codex 실제 충돌 정정 GUI 통과를 취소하는 것이 아니라 이번 제출 harness의 주장 범위를 제한하는 판정이다. 기존 실패 원본/이력은 보존한다.

## 후속과 외부 조건

현재 네 항목을 단일 통합 지시로 기존 Grok `term_dc97574f3e548cff6e25679d713ed8c2`에 전달하고 현재 승인된 공식 native goal을 `/goal resume`로 재개한다. ACK/실제 수신·조사 도구 착수/제품 패치/단계 간 지속은 JSON과 night_shift에 구분한다. 구현자는 Grok이며 이 Codex는 제품 소스·테스트를 수정하지 않았다.

실인증/native 프로필·사본/compaction, 실사용자 업무·한글 정답집/운영 corpus, 운영 백업·전환 허가/timer는 외부 조건으로 유지한다. 위 격리 잔여는 외부 조건이 아니다. 운영 current41f0751/production_activated=false는 제출 정보이며 이번 운영 health를 새로 검증하지 않았다. 새 작업/구현자/주기 생성, 인증 복사, 운영 전환, 실사용자 삭제, push 없음. 기존 30분 감시와 알림 완료된 오전 보고의 정책을 유지한다.

재개 확인: 2026-09-12 22:12:40 KST resume ACK `a467f76d-ed54-4717-8d8a-65eeec12ebfa`, 통합 지시 ACK `54ec213b-a20e-4bee-8146-b7fc4cc362a6`. 22:14:20 화면5825415에서 새 검토서 검색 도구의 실제 출력 `d623 True`, Working37s/nativePursuing7h 확인. 실제 검토 조사 착수는 확인됐고 제품 패치/단계 간 지속은 미확인이다. JSON delivery와 원본 화면 기록에 구분했다.
