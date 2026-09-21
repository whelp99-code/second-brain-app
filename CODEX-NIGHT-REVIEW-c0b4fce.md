# Codex 야간 독립 검토 — c0b4fce

**미통과.** 직전 두 결함의 핵심 재현은 해결됐으나 복구 후 실제2scope 인수와 기존 통합 최종 인계는 미완료다. 제품 준비/운영 인수 아님. 작성: 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`; 원래 Codex의 직접 실행으로 표시하지 않는다. 2026-09-12T03:38:32.765234+00:00.

고정 제출 `c0b4fcece90208fe983bfde6e1479608252a6ec1`; SB source `12db06edc6760f8478e2d7c866b10a8d06430eb3`; release `0ecdb5617a1fe95697e55366f631ee4373f407b1`; JARVIS `1672626c5f2b0b06f7fb93c900cf8771536b58cd`. wheel SHA256 `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57`. 후보 `/var/tmp/sb-candidate-12db06e/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1`; dist `/var/tmp/jarvis-artifact-1672626/source/dist`; 전체 inventory `e9751dfaf955bab6a1ea15792733e0af576f7bac540ca5efeb0b69d9bccbf9cd` /34768항목. 바이트 대조 후 변경된 복구 harness를 검증했다.

## 해결 확인과 직접 검증

- SB182 source/wheel/installed bytes identical and manifest/source/wheel hash valid
- JARVIS source unchanged1672626 and full34768inventory identical to previous direct identity/tsc/tests; no new8test run or Ruff/type/tsc/fullsuite repetition
- Changed harness node --check EXIT0; standard/work/maintenance3installed gates directly EXIT0
- Normal paired harness EXIT0; current trusted high-water snapshot restores3 after measured old-backup rollback3→1; extra ID recovered; deleted content0 and general PostRecoveryWrite1
- Mandatory recovery fence deliberately signed expired in review copy now yields TOMBSTONE_FENCE_REQUIRED and harness EXIT1; previous false-success fixed
- After harness exit actual general reads KeepBeta0/ExtraLost0/PostRecoveryWrite1; new fresh fence3 and same-root restore3 EXIT0
- New post-fresh-restore legacy remember through existing request executor proved; actual scoped denial diagnosed as missing classified input, not denied product regression

현재 SB/JARVIS 제품 바이트는 직전 검토와 같다. 직전 Codex 직접8backup tests/Ruff/tsc 결과를 새 실행 수로 말하지 않는다. 이전 revoked_keys 타입은0errors/2warnings/EXIT1이며 완전 통과가 아니다. 이번에는 변경 harness 정상·실패·fresh 프로세스·설치3게이트를 실행했고 같은 전체 회귀를 반복하지 않았다.

필수 성공 restore의 `recoveredFence` 발급 시각만120초 전으로 바꾼 복사본은 정상 서명된 만료 fence로 TOMBSTONE_FENCE_REQUIRED/EXIT1을 반환한다. 이전 catch-all false success 수정 확인이며 제품 소스는 변경하지 않았다. 정상 직접 paired root `/var/tmp/sb-jarvis-restore-nxqDT4`. 첫 복구 RTO는 restore→read2177ms, failure→read7728ms, failure→업무가능10330ms, 첫 JARVIS unlink→reopen48ms, 전체28380ms이며 마지막 장애부터 최종 업무가능까지의 RTO가 아니다.

## P2 — 복구 후 두 scoped 세션의 증거가 아님

`jarvis-restore-acceptance.mjs`의 `const recoveredPeer = recoveredScoped`는 두 번째 세션을 실행하지 않는다. recoveredScoped도 실제 scoped client 결과가 아니라 일반 reference reader의3질의 건수다. 앞부분의 실제2scope 시험은 마지막 JARVIS 장애/복원 이전이므로 이후 가용성의 대체 증거가 아니다.

Codex는 harness 종료 후 보존된 authority를 사용하여 fresh fence3→같은ROOT restore3을 실제 새 프로세스에서 통과시켰다. 이어 같은 `seed-extra-lost.py` 요청 surface로 구별되는 `CodexPostFreshRestore`를 저장해 proved를 확인하고, 두 실제 `scoped-record-read-v3` 세션(`agent:codex-recovery-a/b`, 서로 다른 session/config/policy)에서 같은 페이지를 읽었다. 둘 다 MEMORY_SCOPED_READ_UNAVAILABLE이며 transport는 SECOND_BRAIN_TOOL_ERROR였다.

원인은 이 probe가 기존 generic schema1 request를 사용하여 source_access를 제공하지 않는다는 점이다. `request_executor.py:277`의 기본 None은 schema4 scoped 경로에서만 accepted preparation으로 채워지고 `remember_page.py:36`은 None인 경우 접근 분류를 결합하지 않는다. **이것은 올바른 미분류 데이터 거부다. 검토 harness 입력 문제를 제품 결함으로 세지 않는다.** 제출 PostRecoveryWrite 또한 같은 legacy 생성기를 쓰므로 이 결과를 두 scoped client의 정상 공유 인수로 확대할 수 없다.

완료 기준: 최종 JARVIS 복구 이후 실제 accepted scoped/classified 쓰기 경로로 새 기록을 만들고2독립 scoped MCP 프로세스에서 같은 원계보/본문digest를 읽는다. 각 scope 철회가 서로 독립적으로 거부/회복됨과 정상 새write/재시도를 실행한다. 직접 ledger에 권한을 넣거나 결과 객체를 복사하지 않는다. 일반 reader 통과는 별도로 보존한다. 원본 `post-recovery-scopes.mjs/.json/.log`, `post-recovery-diagnostic.mjs/.json/.log`, `after-harness-fresh-fence.log`, `after-harness-fresh-restore.log`.

## P2 — 원래 요구한 통합 인계가 아직 미완료

정본 `GROK-INTEGRATED-COMPLETION-HANDOFF-2026-09-11.md`7절은 정확한버전, A–F/M1–M14 상태/증거, 명령/환경/원본로그, 핵심수명, 재현, 운영/외부조건을 한 패키지 진입점으로 요구한다. 현재 패키지는 최신 DR 패치와 핀만 짧게 제시한다. IMPLEMENTATION-STATUS의 M7은 모든 프로필/벡터/원문 경로 미완, M13은 GUI 전체미검증으로 남아 있으며 광범위한 외부 표기만으로 승인 범위의 격리 작업까지 끝났다고 볼 수 없다.

기존 검증을 다시 실행해 시간을 채우라는 요구가 아니다. 원 A–F/M1–M14에 현재핀의 실제 로그/명령/보고서와 검증 경로를 연결하고, 구현·미검증·외부입력을 구분한다. M7읽기정책 표면/M13GUI수명 등 남은 승인된 격리 작업을 구체적으로 열거하여 실행가능한 것은 이어간다. 운영 로그인/전환 없이 불가능한 것은 정확한 제품/버전/필요입력/준비절차로 정리한다. 새기능·요구축소·재승인대기·고정트리전체반복을 만들지 않는다. 이 기존 전체 인계를 복구후2scope와 함께 한 후보에 통합한다.

## 경계와 다음 행동

기존 R1–R7 및 원 A–F/M1–M14, V1–V5 통과/미완료 범위를 유지한다. 실제 native 인증/자동주입·전체읽기·compaction·사본수명·실사용 정답집/운영성능·전체GUI/운영 인수는 fixture나 helper 성공과 다르다. M14는 효과/비용 근거에 따른 보류를 유지하며 새 임의 기능을 요청하지 않는다.

운영 current41f0751/production_activated=false는 제출 정보이며 새 운영 health 확인이 아니다. 운영 전환/인증 복사/실사용자 삭제/push 없음. Codex 제품 소스·테스트 수정 없음. 검토 복사본/harness/보고서/조정 기록만 작성했다. 기존 Grok의 현재 승인 목표에 이 통합 검토를 전달하고 새 고정후보를 확인한다. 기존30분감시는 최종 검증 인수 또는 사용자중단 전까지 유지한다.

모든 원본 `/var/tmp/codex-night-c0b4fce-2zudy5aj`. `sb-identity.json`, `jarvis-inventory-before.json`, `jarvis-inventory-after-proof.json`, `prior-product-checks-retained.json`, `installed-*.log`, `changed-harness-syntax.log`, `paired-restore.log/-result.json`, `paired-expired-fence-control.log`. 전송접수·실제착수·지속은 control에 구분하여 기록한다.
