# 야간 독립 검토 — 6507ab1 미통과

작성자: 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`, 야간 독립 검증 위임. 원래 Codex 직접 실행 아님. 2026-09-11T21:05:22.121135+00:00. 제품 준비/운영 인수 아님.

## 고정 후보와 검사 무결성

제출 `6507ab1098f11c25dcdc2f80e208f317d397e118`, SB source `bbab80b53e3d2d5bb453870913b334e89f7aa4ba`, release `0ecdb5617a1fe95697e55366f631ee4373f407b1`, wheel `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57`, 후보 `/var/tmp/sb-candidate-bbab80b/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1`. SB182 Python archive/휠/설치물 동일. JARVIS `3e2b93b` / `/var/tmp/jarvis-artifact-3e2b93b/source/dist`: Git제품tracked1138파일 동일, tscEXIT0/재빌드1110JS 동일. 전체inventory `fe88c09d4ce35e3ee417c1539a219ac6e849c5e6770f4d441d48167e73d67562`/34770이 제출값 및 검사전후 동일하다.

증거 `/var/tmp/codex-night-6507ab1-_cyi7h_9`. Vitest는 독립전체복사본, node재현은 실제제출dist를사용했다. SB제품바이트변화없음. DRharness는 이번정본 그대로에서 interpreter경로만 검토용으로바꿔 실행했으며 전회진단용새요청/재조회수정을추가하지 않았다. 원본제품소스/테스트/운영상태수정없음, 종료HEAD고정.

## N1 전송 복구: 기존 독립 실패 재현 해소

**내부 첫negative→두번째accepted후exit99→새프로세스재시도**가 remote접수1/retrysend0/unknown으로개선됐다 (`dispatch-inner-negative-crash.json`). 물리전송별attempt도입이 이전실패를 해결했다.

negative→retryfence거부→권한정정은 명시적negative1회+성공1회로정상복구. 첫접수후ECONNRESET, 첫/이전명령negative뒤접수후crash, 일반timeout, remote reconciliation원장기록, 권한/스키마거부 및 최초/재시도정정, 살아있는worker경합 등 기존 독립재현도 현재제출에서유지됐다. 이번 검토에서 새N1결함을 확인하지 않았다. 이를 임의remote에 대한보편적exactly-once나운영실적로확대하지 않는다.

## M12 정본 인수 스크립트: 이전 오류 정정 후 직접 통과

이번 `scripts/jarvis-restore-acceptance.mjs`는 별도accepted기억ID와 새쓰기후freshtarget조회가정본에반영됐다. 경로만조정한독립실행 **EXIT0**, 전회의원본REPLAY_CONFLICT/세대target오류는해소됐다. `paired-restore.log/.result`(JSON파일 `paired-restore-result.json`), root `/var/tmp/sb-jarvis-restore-ZUasjf`.

통과범위: runtimebackup `.recovery`에서request/generation journal2개삭제후복구→JARVIS삭제효과/증명→providerrestore→삭제기억0/보존기억1→새scoped client2개의같은복원세대/본문·독립철회2→동일runtime새accepted요청proved→freshtarget두번째삭제/highwater2→재복원두기억0. model_calls0/운영전환false. 이격리연결경로는완료로보존하고같은오류를다시지적하지않는다.

다만 journal소실은backup직후/새삭제전이고나머지세대·설정·신뢰근거는살아있다. `rpo_source_generation_id`는각SB/JARVIS의시점/손실량RPO가아니다. **16903ms**는backup시작부터여러삭제/복원/인수검사까지포함하며정의된장애→업무가능RTO와다르다. 원5E측정과B/F복구준비가남는다. 신뢰근거없는anchor는안전거부를유지한다.

## V1: 새 메서드는 실제 compaction 트리거·재선택에 연결되지 않음 (P2)

`memory-reference-production.ts:69`의 reselectAndDeliver는 **caller가준 input/evidence를 modelSession.deliver에넘기는래퍼**다. reader.read/현재기억선택을호출하지않는다. 정본src에서호출하는곳이없고 두테스트가직접호출한다 (`compaction-call-sites.log`). 실제 `cli-memory-reference.ts`는 reader.read결과만반환하며새메서드를호출하지않는다.

새integrationtest는 correction lane의 **저장자료삭제/정정용 compactor**를실행하고, 별도 `contextAssemblerInput()`의기억과증거를테스트가만든뒤 wrapper를직접호출한다. 이는모델세션문맥compaction이기억재선택을일으키는증거가아니다.

독립재현 `compaction-boundary.mjs/.json`: 해당 correction compactor뒤모델send0, providerCalls0. 이어래퍼에fixture본문을직접전달하면send1/session=compacted-session. 공급된fixture본문/출처/version전달은확인되지만 fresh선택이나실제제품세션이벤트연결은없다. 최초검토실행의fixture정책파일cwd오류는JARVIS복사본cwd로수정했으며제품결함으로세지않았다.

완료기준: **기존승인된실제제품의새세션/문맥compaction진입점**에서현재scoped reader/selector로필요기억을다시얻고선택세션transport로연결한다. 테스트가새memories/evidence를직접조립해주는대체경로가아니라제품trigger부터실행한다. 철회/만료/no_data·원본문/출처/version·최종직렬화예산을동일경로에서검증한다. 권한이없는자료를선택하지않고native/live인증없음과auth없이가능한제품경로를구분한다. 메서드명 reselect, compaction직후다른함수수동호출, 또는Recording buffer만으로verified를붙이지않는다. 사용자가처음부터명시한V1기준이다.

## F 및 전체 요구

런북의현재핀은bbab80b/3e2b93b로맞춰졌고전회stalepin은해소됐다. 하지만원B/F의서비스·설정·백업hash·성공/실패조건·구버전상태호환성또는검증된복구절차와M12측정은계속준비해야한다. 운영전환허가부재를준비작업차단으로확대하지않는다.

직접검사: GJC16+assembled-session7+새compactiontest1 **24passed/29.05s**(테스트21.18s), RuffEXIT0, tscEXIT0. revoked_keys타입0errors/2warnings/EXIT1(완전통과아님). 설치standard/work/maintenance **3게이트EXIT0**, 실제pinnedsource harness/설치물, 전후전체inventory불변. 새compactiontest의통과범위는위래퍼호출에한정한다.

Grok복구집중 `/var/tmp/sb-focused-restore-bbab80b.log` **13passed/EXIT0**는기존로그를읽은것이며Codex직접13회귀수치가아니다(SHA256 `c983aeddb73fe6da898feb5bc6a0578269695296abad72acfc897c0306aca2d0`). 동일SB전체회귀재반복없음. 이전M6writer중단복구·브라우저실패정정재실행·한정된검색품질/성능·키/marker보존은각기존고정트리와정확한경로로보존한다. A–F/R1–R7/V1–V5/M1–M14범위/의미유지, M14임의추가없음.

기존Grok의현재승인목표에서 **실제V1이벤트연결 + M12각RPO/업무가능RTO + 최종핀복구준비**를마친다. 이번에해결된N1과정본DR를다시부분패치하지말고남은실행가능영역으로계속한다. 진짜native/사용자입력과운영drain은오전보고에구체적으로모은다. 최종제품/운영인수없음, 새worker/인증복사/운영전환/사용자삭제/push없음. 30분감시유지.
