# 야간 독립 검토 — f6ce2e9 미통과

작성자: 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`, 위임된 야간 독립 검증. 원래 Codex 직접 실행 아님. 2026-09-11T19:36:13.954329+00:00. 제품 준비/운영 최종 인수 아님.

## 후보와 검증 대상

제출 `f6ce2e9f8d6b6cced888e1d5031e082cf9f61ad1`, SB source `f7cce7eef28a9df9ba14ad4156db24a9effa6842`, release `0ecdb5617a1fe95697e55366f631ee4373f407b1`, wheel `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57`, 후보 `/var/tmp/sb-candidate-f7cce7e/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1`. SB182 Python archive/휠/설치물 동일. 이전537ec9b 대비 sb제품바이트 변화 없음. JARVIS `5f13ea1` / `/var/tmp/jarvis-artifact-5f13ea1/source/dist`, Git 제품tracked1137파일 동일, 직접tscEXIT0, 재빌드1109JS 모두 제출dist와 일치. 증거 `/var/tmp/codex-night-f6ce2e9-i5gubtbx`. 검토 종료 SB HEAD 동일.

**검토 harness 제한 정정:** 직접 Vitest를 후보 source에서 병렬 실행하여 `node_modules/.vite/vitest/da39a3ee5e6b4b0d3255bfef95601890afd80709/results.json`이 갱신됐다(mtime1789155119.6696455). 이에 설치standard/work 첫 실행은 ACCEPTANCE_CANDIDATE_CHANGED:jarvis/EXIT1이었다. 이는 Codex 검사 캐시로 인한 후보 부수파일 변경이며 제품 결함으로 집계하지 않는다. 코드/재빌드JS는 동일하다. 캐시가 멈춘 뒤 두 게이트를 재실행해 EXIT0이고 전후 inventory `fd696731b34b9a394da111b26dab5b6ba63688c591c97cab379257eaa686e52b`/34780이 동일하다. 이는 제출 inventory `f6d4221094db332bffcfc0ec04fd8ffe89f3b24807b59394951507c66999c2b3` 그대로를 검증한 결과가 아니다. 최초실패 로그도 보존한다. 다음 검토부터 후보에 캐시를 쓰는 검사는 별도 검토 복사본/비캐시 설정으로 분리하고 검사전 전체inventory를 보존한다. 현재 후보의 캐시를 추정 복원하지 않았다.

## 보존할 개선

- 기존 첫 remote접수/exit99, **이전 명시적 실패 뒤 다음 accepted/exit99**, 일반 accepted후 예외 재시도는 모두 remote접수1/send재실행0으로 개선됐다 (`dispatch-accepted-crash`, `dispatch-fail-accepted-crash`, `dispatch-accepted-timeout`). 이전 df3dce4의 이 실패를 반복 판정하지 않는다.
- 죽은 owner의 remote reconcile후 **model_dispatched=true**로 원장에 기록된다 (`dispatch-reconcile-accepted.json`). 기존 silent no-op 문제 개선.
- public `executeGjcCommand` nested dispatch에서 실제 주입된 transport의 capture.session_id가 task.session_id **s**, 직렬화431bytes와 capture.bytes431 일치, 중복재요청send0 (`dispatch-selected-session.json`). 이전 시각 기반 세션ID 문제는 이 경로에서 해결됐다. 이는 합성transport 경계이며 native/live 인증 인수와 같지 않다.
- 명시적 거절후 정정·최초preflight거부후 정정·옵션추가후 정상·스키마거부·설정철회·재시도권한철회·살아있는worker경합은 현재 재현범위에서 유지됐다. 직접 JARVIS focused **12passed/14.31s**(테스트8.50s).

## N1: 내부 disconnect 분류가 불명확 결과를 다시 전송 (P2)

`dispatch-accepted-disconnect.mjs/.json`에서 합성 remote는 접수를 배열에 기록한 뒤 `ECONNRESET after remote acceptance`를 던진다. **첫 명령에서2회, 다음 명령에서1회: 총3회 접수**다. 첫 명령은 MODEL_TRANSPORT_UNAVAILABLE가 되고 다음 명령은 정상응답이다.

`assembled-model-session.ts`의 isRetryableTransportFailure/sendOnce는 disconnect/ECONNRESET/UND_ERR_SOCKET/EPIPE 또는 retryable:true 예외를 accepted:false로 바꾼다. deliver가 즉시 재전송하고 마지막 실패를 MODEL_TRANSPORT_UNAVAILABLE로 바꾸면 외부 dispatch가 명시적 실패처럼 기록한다. 외부 catch를 고쳐도 내부 의미 변환이 남았다. 실제운영 요청/사용자데이터를 쓰지 않은 합성transport 재현이다.

완료 기준: public dispatch→AssembledModelSession→transport 전체에서 **미전송·명시적negative·접수불명** 의미를 일관되게 유지한다. 정상정정은 가능하고 불명확 결과의 blind resend는 막는다. 일반오류뿐 아니라 socket/reset/retryable 예외, 이전실패, 크래시, 경쟁, durable receipt를 한 계약으로 검증한다. 무조건 exactly-once를 임의 remote에 요구하거나 모든 재시도를 막는 요구가 아니다.

## N1: 전송 직전 거부는 미전송인데 정정 후에도 묶임 (P2)

`dispatch-presend-deny.mjs/.json`: 첫 preflight fence는 통과하고, 다음 실제 전달 직전 fence가 거부한다. transport호출0. 이후 권한을 정정하고 동일 요청을 실행해도 **sendsTotal0, recovered:unknown_accepted, model_dispatched=false**다.

`cli-gjc-commands.ts:115`는 실제 session.deliver 내부 권한검사 전에 send_started를 기록한다. `AssembledModelSession.deliver`의 첫 authorize에서 거부되면 미전송이 확실하지만 이후 reservation이 unknown으로 남는다. 앞의N1과 같은 상태계약의 반대쪽 실패다. 권한검사를 제거하지 말고 아직 transport를 호출하지 않은 거부/정정은 안전하게 회복하게 한다. first-preflight거부만 테스트하여 대체하지 않는다.

## M12: 같은 세대 연결은 개선, 실제 DR 진입점과 소실 복구는 남음 (P2)

독립 출력경로만 바꾼 새 검사 **2passed/8.93s**. missing source anchor 안전거부 유지. `restore_fixture(full_source=True)`→sanitize→**같은 executor.mutations**에서 기억 페이지를 쓰는 연결은 확인됐다. 복원세대 `sbgen:v1:ed5c068a103b5a6e20b278eb8a522e61d9bc21bffbedec510cf260d684b44b34`, 후속쓰기세대 `sbgen:v1:32691d2cea321549c306f2385ce2b9ef87503fb8222f6d139085abb460994283`, tombstone_sequence1, blocked_matches0, post_pages1. 기록4.8529초는 이 fixture의 생성·삭제·sanitize·helper쓰기 시간이다. 이전의 별도빈vault 문제는 개선됐으므로 그대로 실패라 쓰지 않는다.

남은 경계: `task30_restore_factory`는 원본 generation/request journal을 보존한다. 새쓰기는 `GenerationAuthority(None,None)`로 `materialize_remember`를 mutation callback에서 직접 호출한다. 이 helper의 docstring도 승인된 request분류에서 source_access를 받아야 하며 스스로 권한을 부여하지 않는다고 명시한다. 실제 accepted request→executor 처리·원장·재시도 경로와 같지 않다. scoped reader허용/거부, 삭제재유입, controljournal소실 뒤 복원, 별도SB/JARVIS RPO도 이번 검사에 없다.

기존 통합5E/CURSOR9대로 **동일 복원된 runtime**에 실제 제품 요청을 받아 executor를 실행하고, 원본/제어소실은 신뢰된 백업·anchor/처분근거로 복구한다. JARVIS실제fixture의 tombstone/fence/scopedreader와 연결하여 삭제기억부활/재유입차단·정상/거부·새쓰기·RPO/전체사용가능RTO를 증명한다. anchor없는안전거부는 유지하고 해시예외로 우회하지 않는다. 기존 `scripts/jarvis-restore-acceptance.mjs`와 runtimebackup 근거를 확장해야지 helper수준의 작은 새검사로 원계약을 계속 대체해서는 안 된다.

## F: 복구 런북이 이전 후보를 가리킴 (P2)

`GROK-PIN-RECOVERY-RUNBOOK.md:7,:22`는 여전히 SB537ec9b/JARVISa935751 경로다. 이번f7cce7e/5f13ea1 핀과 불일치하며 DR설명도 이전 verified_restore_source→run_all로 남아있다. 패키지와 문서의 pin을 자동 대조하고 원 B/F 서비스·설정·백업hash·성공실패조건·구버전상태호환성 또는 검증된 복구절차를 최종핀에 맞춘다. 운영 실행 승인과 이 준비 작업을 구분한다.

## 검사 수치 및 전체 요구

직접 RuffEXIT0, tscEXIT0, revoked_keys타입0errors/2warnings/EXIT1. maintenance게이트EXIT0. standard/work는 위 harness캐시문제 때문에 최초EXIT1, **캐시후재실행 각각EXIT0**. 원본 `installed-*-retry.log`와 최초로그 모두 보존.

Grok 전체로그 `/var/tmp/sb-full-pytest-f7cce7e.log`은 **1834passed/2skipped/630.39s/EXIT0**, SHA256 `93a2518543d1dadeaa57a8706f3c2eb483dc1eba13923d877962601cb6100ca8`. 읽어 확인한 기존로그이며 Codex 직접 전체회귀 수치가 아니다. 동일SB바이트 전체검사는 반복하지 않았다. 기존 M6 SIGKILL후 제품커밋/키보존, 한정된검색성능/브라우저/공유restore 통과는 해당기존고정트리와 경로로 보존한다.

원 A–F/R1–R7/V1–V5/M1–M14 유지. V1의 task.session_id 전달은 위 경로에서 통과했지만 새세션·compaction 재선택/철회·만료·no_data를 실제 제품 경로로 엮은 인수는 아직 남는다. 실제native 인증만 외부입력이며 auth없이 가능한 경로는 계속 진행한다. M14를 임의로 새기능으로 추가하지 않는다. M1/M2/M5/M8의 구체적native/사용자조건, 운영drain 등은 오전보고에 모으고 새 승인으로 해석하지 않는다.

## 다음 작업과 후보 종료 기준

기존 Grok의 현재 승인된 native목표에서 **N1의 외부/내부전송 및 거부정정 상태계약, 동일runtime DR의 실제요청 경로, 세션/compaction 및 최종핀 복구준비**를 하나의 통합 잔여표로 관리한다. 한 오류의 focused통과나 중간커밋을 목표완료로 쓰지 말고 다음 미완료항목으로 이어간다. 구현 가능 항목의 정상/실패/복구 근거 또는 정확한외부입력만 남은 상태까지 끝낸 뒤 일관된 후보를 제출한다. 새worker/제품소스Codex수정/운영전환/인증복사/사용자삭제/push 없음. 30분감시 유지.
