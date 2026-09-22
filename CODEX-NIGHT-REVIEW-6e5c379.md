# 야간 독립 검토 — 6e5c379 미통과

작성자: 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`, 위임된 야간 독립 검증. 원래 Codex 직접 실행 아님. 2026-09-11T20:05:14.089189+00:00. 제품 준비/운영 인수 아님.

## 고정 대상·바이트

제출 `6e5c3795d4f0fea7745cf840d1bcf41a266a46ec`, source `2782f1ba5a079efa8a9a0922cf14fb0666f0dc27`, release `0ecdb5617a1fe95697e55366f631ee4373f407b1`, wheel `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57`. 설치후보 `/var/tmp/sb-candidate-2782f1b/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1`. SB182 Python archive/휠/설치물 동일; 이전f7cce7e 대비 sb제품바이트 변경 없음. JARVIS `69d8c9b`, `/var/tmp/jarvis-artifact-69d8c9b/source/dist`: Git제품tracked1137파일 동일, tscEXIT0/재빌드1109JS 동일.

검사 전후 **전체inventory 동일**: `f9072b9be6899837f9673c04951ed5583baae1fc56616773eae0bad719ccc92d`/34768, 제출값과도 일치. `jarvis-inventory-before.json`, `jarvis-inventory-after-proof.json` 보존. Vitest는 별도 전체복사본 `jarvis-test-copy`에서 실행하여 지난 검토의 후보캐시갱신 문제를 피했다. 직접node 재현은 실제 제출dist에 수행했다. 증거 `/var/tmp/codex-night-6e5c379-et_xw99l`. 종료HEAD도 고정 제출과 동일.

## 해결된 범위 보존

- 접수후 ECONNRESET가 이제 remoteAccepted1/send1로 유지되고 재실행은 unknown (`dispatch-accepted-disconnect.json`). 이전 내부자동재전송 문제 개선.
- **첫 send 전 fence거부→정정**은 sends0→1로 개선 (`dispatch-presend-deny.json`). 이전 이 경로의 회복불가 문제를 다시 실패라 쓰지 않는다.
- 첫/이전실패이후 accepted-crash, 일반timeout, remote reconciliation원장기록, dead-worker전송전회수/살아있는worker경합, 최초preflight/스키마/옵션/철회 및 정정 경로는 기존 재현의 통과를 유지한다.
- 실제 public `executeGjcCommand`의 주입transport에서 session_id=s와 431bytes capture를 확인. 추가 **no_data입력은 memories[]/186bytes**, **만료기억입력은 memories[]/210bytes**, 두 경우 no_data=true/선택세션s 유지 (`dispatch-empty-expired.json`). 요청에 명시적으로 넣은 합성입력에 대한 실행이고 실제 compaction자동재선택이나 native인증 인수가 아니다.
- M12는 이제 복원된 **같은 executor에 accept_stable_v1_request→apply_once**를 호출해 applied_state=proved, 새페이지1개, tombstone_sequence1을 확인했다. accepted_request `memreq:pos:v1:e780e762e0c85216b84300e4724d4be6ded51f768d16e5c66544cda94ed89d64`, 복원세대 `sbgen:v1:ed5c068a103b5a6e20b278eb8a522e61d9bc21bffbedec510cf260d684b44b34`, 후속세대 `sbgen:v1:3cfcc2635dd9956be0669c2460e7e35ac650aec192b9a3e47e82d911a7cfd5b2`. 이전 직접helper만의 쓰기 문제 개선. 원본anchor없는안전거부도 유지.
- 런북의 source/후보/JARVIS 경로는 현재2782f1b/69d8c9b로 정정됐다. 이전 stale핀 실패는 해소된 것으로 보존한다.

## N1: 명시적 negative 이후 재시도 권한거부가 정상 정정을 막음 (P2)

`dispatch-negative-then-deny.mjs/.json`은 기존 공개handler/실제SQLite/제출dist에서 첫두권한검사를 통과시키고 **transport가 accepted:false를 반환**한다. 다음 재시도 직전 fence를 거부하면 그 명령은 CURRENT_READER_DENIED로 끝난다. 권한을 다시 허용하고 동일요청을 실행해도 **sendsTotal1(첫negative호출뿐), recovered:unknown_accepted, model_dispatched=false**다. 원격은 접수하지 않았는데 정상정정이 회복되지 않는다.

원인: `assembled-model-session.ts:35`의 negative는 재시도 전 durable결과로 남지 않으며, retry authorize가 throw하면 외부 `cli-gjc-commands.ts:120` catch에는 권한오류만 전달된다. send_started는 존재하지만 명시적 negative는 유실된다. 첫send전거부와 remoteaccepted후오류의 중간 경계가 남은 것이다.

완료 기준: 각 실제 전송의 **known-negative/not-sent/unknown 결과**를 다음권한검사 전에 기록하거나 명시적으로 전파한다. 현재거부시 전송중지는 유지하고 나중에 정당한권한정정 뒤는 안전하게 재전송 가능해야 한다. accepted:false→fence거부→허용정정과 재시작도 같은상태계약으로 검증한다. unknown disconnect/crash의 blind재전송을 다시 열거나 권한검사를 제거해서는 안 된다. 합성transport 검증이며 운영요청/사용자데이터는 사용하지 않았다.

## M12 및 V1 남은 원래 인수 경로

현재 M12검사는 직접 **2passed/9.80s**, fixture생성부터 sanitize/accepted요청증명까지 기록4.9028초다. 실제제품요청이 같은복원executor에 연결된 개선은 인정한다. 그러나 원본 generation/request journal은 `restore_fixture` 내부에 계속 살아 있고, fresh scoped reader의 허용/거부·삭제high-water/reingress·복구자료로 control소실복원·별도SB/JARVIS RPO는 실행하지 않았다. 이 시간을 전체운영RTO, backuptimestamp 하나를 RPO로 치환하지 않는다.

기존 통합5E/CURSOR9 및 기존 paired `scripts/jarvis-restore-acceptance.mjs`/runtimebackup근거에서 이어서: 신뢰복구자료·anchor를 명시하고 동일cold복원runtime의 scoped정상/거부, 삭제기억부활/재유입차단, high-water, 새 accepted요청/원장재시도, 별도SB/JARVIS RPO와 사용가능시점RTO를 하나의 실행근거로 마친다. anchor가 실제없으면 안전거부 유지; 운영자료/인증을 fixture로 복사하지 않는다.

V1은 현재 **명시입력에 대한 선택세션·빈데이터·만료제외 transport**까지 직접 통과했다. 남은 것은 기존 제품의 새세션/compaction이 기억을 다시선택해 현재권한/철회·만료/no_data를 반영하는 실제실행이다. 반복적으로 이미 통과한 nested envelope 테스트만 추가하지 말고 기존 trigger/selector→세션→transport 흐름을 연결·검증한다. 실제live인증만 외부조건으로 명시한다.

F의 현재핀은 맞지만 DR본문은 여전히 verified_restore_source→run_all인 이전검사설명이다. 원B/F 서비스·설정·백업hash·성공/실패·구버전상태호환성 또는 검증된복구절차를 현재후보에 맞춰 준비한다. 운영전환승인과 준비작업을 구분한다.

## 직접 검사와 기존로그

- 별도복사본의 GJC/assembled-session **20tests passed/19.97s**, 이 중 GJC14·session6. 원본 `jarvis-focused.log`.
- 직접 RuffEXIT0, tscEXIT0. revoked_keys타입0errors/2warnings/EXIT1(완전통과아님).
- 설치 standard/work/maintenance **3게이트 모두EXIT0**, 실제 source_commit2782f1b의 harness와 설치물을 사용, 전체inventory불변.
- Grok전체 `/var/tmp/sb-full-pytest-2782f1b.log`: **1834passed/2skipped/631.93s/EXIT0**, SHA256 `1878dc160b3e1458e5d8b38633a6071caa402e04973266335b52ce7ea52e98dd`. 기존로그를 읽은 것이며 Codex직접전체회귀 수치가 아니다. 동일SB제품바이트 전체를 재반복하지 않았다.

이전 M6writer강제중단후 실제업무커밋·키보존, scopedrestore·브라우저복구·한정된검색/MCP성능 통과는 해당고정트리/경로로 보존한다. 원A–F/R1–R7/V1–V5/M1–M14 의미 유지. M14임의구현 없음. M1/M2/M5/M8 native/사용자입력, 운영drain 등 진짜외부조건은 오전보고에 모은다. 최종완료/운영전환/인증복사/사용자삭제/push승인 없음.

## 다음 행동

현재 승인된 Grok native목표에 남은 **N1 negative후정정 + M12cold/scoped전체계약 + V1실제compaction경로 + F복구준비**를 체크리스트로 유지한다. N1한건을 고친 뒤 곧바로 candidate/goal완료로 끝내지 말고 나머지실행가능단계를 계속한다. 미변경SB 전체검사를 단지새문서커밋 때문에 반복하기보다 변경영향검사와 아직미완료인 통합경로에 시간을 쓴다. 모든실행가능항목의 근거 또는 구체적외부입력만 남았을 때 하나의일관된후보를 제출한다. 30분감시 유지.
