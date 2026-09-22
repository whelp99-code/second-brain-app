# 야간 독립 검토 — 5fa8cfd 미통과

작성자: 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`, 야간 독립 검증 위임. 원래 Codex 직접 실행 아님. 2026-09-11T20:37:22.320003+00:00. 제품 준비/운영 인수 아님.

## 고정 대상과 바이트

제출 `5fa8cfd001c3fe4dd78bb85a512e51dd7a9e3d29`, SB source `8a98324d31098728bc17f052d29f3cc690898dcd`(패키지 short8a98324를 Git으로 해석), release `0ecdb5617a1fe95697e55366f631ee4373f407b1`, wheel `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57`, 후보 `/var/tmp/sb-candidate-8a98324/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1`. SB182 Python archive/휠/설치물 동일. JARVIS `86d3290` / `/var/tmp/jarvis-artifact-86d3290/source/dist`: Git제품tracked1137파일 동일, tscEXIT0/재빌드1109JS 동일. 전체inventory `23a795e2d4a3aefa5d5c4408895f068074fdb05cc8d20d5327b5ae220c524e67`/34768이 검사전후 및 제출값과 동일하다.

독립증거 `/var/tmp/codex-night-5fa8cfd-91uixhdq`. Vitest는 별도 전체복사본에만 캐시를 쓰고, 독립node재현은 실제제출dist를 실행했다. SB제품소스는 이전후보와 동일; 새복구harness를 고정source에서 실행했다. 원본제품소스/테스트를 수정하지 않았으며 아래 진단정정은 검토디렉터리의 harness에만 적용했다. 종료SB HEAD 동일.

## N1: 한 명령 안의 여러 실제 전송을 같은 fence로 묶으면 다시 중복 (P2)

이전 **negative→다음retry fence거부→권한정정**은 개선됐다 (`dispatch-negative-then-deny.json`): 첫negative호출1, 정정후성공호출1, model_dispatched=true. 첫accepted후throw/crash 재전송차단, 이전별도명령실패후unknown 및 reconcile도 유지된다.

하지만 `dispatch-inner-negative-crash.mjs/.json`에서 **하나의dispatch 첫 실제send는 accepted:false, 내부retry의 두번째send는 합성remote접수후 localreceipt전 child exit99**다. 새프로세스로 DB를 다시열어 같은요청을 실행하면 **remote접수2회/retry send1**이다. 이전negative가 후속unknown을 다시풀었다.

`assembled-model-session.ts:40`에서 knownNegative callback은 현재 reservation의 lease_fence에 실패를 기록하지만 내부의 다음실제send 전에 별도시도ID/결과경계를 만들지 않는다. `gjc-intent-store.ts`는 같은fence의 failed존재만 보고 안전한재시도로 오판한다. **reservation lease와 실제transport attempt는 서로 다른 단위**다. 이전별도명령fence만 다루거나 마지막probe 하나만 맞춰서는 전체계약이 끝나지 않는다.

완료 기준: 실제호출마다 durable attempt identity/시작/결과를 연결하여 가장최근실제호출의 미전송·negative·unknown을 구분한다. negative→negative, negative→권한거부/정정, negative→접수후크래시/연결끊김, 재시작, 경쟁, receipt정착을 함께 검증한다. 권한검사/owner안전성을 없애거나 임의remote에 무조건exactly-once를 요구하지 않는다. 합성transport일뿐 실제운영API/사용자자료를 쓰지 않았다.

## M12: 제출 harness 실패와 독립 정정 뒤 실제 통과를 구분

제출 `scripts/jarvis-restore-acceptance.mjs`를 고정source에서 실행하되 interpreter경로만 검토환경으로 바꾼 `codex-restore-observe.mjs`는 **후속 seed에서 WRITE_REQUEST_REPLAY_CONFLICT/EXIT1**이었다 (`paired-restore.log`). 초기seed와 동일fixture candidate/idempotency로 다른본문을 써서 제품이 정상적으로거부했다. **제품저장결함으로 집계하지 않는다.** 하지만 이harness는 제출한전체인수근거로 통과하지 않았다.

검토복사본에서 새기억요청만 `tests/test_restore_journal_loss._remember_request`의 별도candidate/receipt/idempotency로 만들어 accepted→executor경로를 실행하자, 다음삭제의 target이 새쓰기전 `keep`세대라 resolveTarget이 거부했다 (`paired-restore-distinct.log`). 이것도 오래된세대증명을 재사용한fixture문제다. 검토복사본에서 쓰기후 다시읽은최신target을 사용한 `codex-restore-fresh-read.mjs`는 **전체EXIT0**이었다.

직접통과한 정확한범위 (`paired-restore-result.json`, root `/var/tmp/sb-jarvis-restore-r4RLhZ`):

- runtimebackup의 `.recovery`에서 request/generation journal2개를 삭제후복구.
- 실제JARVIS effect삭제→providerrestore→참조reader: 삭제기억0, 보존기억1.
- 새scoped client2개의 동일복원세대/본문 및 독립철회2회.
- 동일provider runtime에 **별도accepted기억요청→proved**.
- 최신target을 재조회해2번째삭제→high-water2→재복원후두기억0.
- model_calls0/운영전환false. 위후속요청은 기존stable-v1 fixture이며 native/live 인증이 아니다.

따라서 기존에요구한 동일runtime journal복구·scopedreader·삭제high-water·새accepted쓰기의 **이격리연결경로는 진전으로 보존**한다. Grok는 두fixture식별/세대오류를 정본harness에서고치고 실제실행로그를 제출하면 된다. independent복사본의 성공을 원본harness가성공한것처럼 쓰지 않는다.

남은한계: journal소실은 backup직후, 새삭제전이며 다른세대파일/설정/신뢰근거는살아있다. 모든cold손실조건을포함하지 않는다. `rpo_source_generation_id`는별도SB/JARVIS RPO가아니며, 측정15085ms는backup시작부터삭제/복원/쓰기/두번째삭제검사전체로서정의된장애후사용가능RTO와다르다. 원5E의복구자료무결성·신뢰anchor·업무가능시점/각백업시점측정을정리한다. anchor없는안전거부를우회하지 않는다.

## V1/F 잔여와 반복중단 원인

패키지자체가compaction자동trigger를잔여로명시한다. 이번JARVIS변경은negative callback뿐이며 해당trigger/selector는아직변경되지않았다. 이전selectedsession/no_data/expired본문제외의명시입력경로는보존한다. 현재승인된제품새세션/compaction trigger→필요기억재선택→현재권한/철회·만료/no_data→실제transport 경계를마쳐야한다. 실제native인증만외부입력으로분리한다.

`GROK-PIN-RECOVERY-RUNBOOK.md`는다시이전 **2782f1b/69d8c9b**를가리킨다. 현재8a98324/86d3290(또는다음최종핀)과일치시켜원B/F 서비스·설정·백업hash·실패/복구/구버전상태호환성또는검증된대체복구준비를마친다.

화면이매번부분패치후Goal achieved/최종응답으로끝나지만위실행가능잔여가남는다. native목표완료기준을이미승인된전체잔여표에맞추고, 각부분개선후다음미완료단계로이어간다. 단일예외를고쳐전체목표가완료된것처럼표시하지 않는다. 미변경SB전체회귀를이번에반복하지않은점은적절하다.

## 검사 수치

직접별도복사본 GJC15+session6 **21passed/21.95s**(테스트14.93s), RuffEXIT0, tscEXIT0. revoked_keys타입0errors/2warnings/EXIT1(완전타입통과아님). 설치standard/work/maintenance **3게이트EXIT0**, source_commit을fullhash로해석하여후보harness사용, 전후전체inventory불변.

Grok복구집중로그 `/var/tmp/sb-focused-restore-8a98324.log`는 **13passed/10.27s/EXIT0**, SHA256 `90eb8dcf4883ad97e8793ca4d65c62b0c6831672b50b1368b43b0f9b87db60e8`. 읽어확인한기존로그이고Codex직접13회귀수치가아니다. 직전SB동일제품바이트1834passed/2skipped로그도이력으로보존하며새실행으로합산하지않는다. 이번직접DR원본실패/진단정정1실패/진단정정2통과로그는모두보존했다.

원A–F/R1–R7/V1–V5/M1–M14유지. 이전M6중단복구·검색품질/성능·브라우저·한정된nativefixture통과는해당고정트리와범위를보존한다. M14임의새기능없음. 진짜외부native/사용자입력과운영drain은오전보고에모으며승인우회없음. 제품소스Codex수정/운영전환/인증복사/사용자삭제/push없음. 30분감시유지.
