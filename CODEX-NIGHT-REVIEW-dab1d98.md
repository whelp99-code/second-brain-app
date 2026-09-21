# 야간 독립 검토 — dab1d98 미통과

작성자: 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`, 야간 독립 검증 위임. 원래 Codex 직접 실행 아님. 2026-09-11T22:35:55.337471+00:00. 제품 준비 및 운영 인수는 미완료다.

## 고정 후보 / 검사 무결성

제출 `dab1d983d86babc3305716a507bde66a152a560c`, SB source `f191a8e24066c3e865036265efd998f2802f52a4`, release `0ecdb5617a1fe95697e55366f631ee4373f407b1`, wheel `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57`. 후보 `/var/tmp/sb-candidate-f191a8e/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1` × JARVIS `4332390d9ae01b76ceb490c644ac6d9b19b0c470` / `/var/tmp/jarvis-artifact-4332390/source/dist`.

SB 182 Python 파일의 archive/휠/설치물 바이트가 같다. JARVIS 제품 tracked1137파일은 Git와 같고, tscEXIT0 / 재빌드1109JS가 제출 dist와 같다. 전체 inventory `a2f1a336209b8edbe3809527a3b2cca0fe6779bc2599b97e786f1eca79f8702e` /34768은 제출값 및 검사 전후 동일하다. 독립 증거 `/var/tmp/codex-night-dab1d98-9kedr5f5`. Vitest는 별도 전체 복사본에서, 재현은 제출 dist에서 실행했다. 제품 소스/테스트/운영 상태 수정 없음.

## 이전 결함 해소 및 통과 범위

정상 1건은 실제 reader 조회와 전송 직전 status 재검증 후 session s에 336bytes로 전달됐다. 서로 다른 유효한 2건은 개별 memory_ref/source로 497bytes 전송하여 기존 증거 충돌이 해소됐다. 긴 본문 후반부와 줄바꿈을 보존하고 고정 inbox/96자 잘라내기를 제거했다. 다만 아래 예산·저장 일치 결함이 생겼으므로 변환 계약 전체 통과는 아니다.

명시적 dispatch의 no_data는166bytes/빈 memories, 만료된 record는 send0으로 안전 거부. 합법적으로 구성한 s→fresh-session은 각5회 provider 호출/전송1회다. 실제 문맥 compaction/native 이벤트 인수로 확대하지 않는다. `dispatch-current-reader.json`, `dispatch-newsession-generation.json`.

첫 전송의 known-negative 후 provider 세대 변경은 이번에는 **MEMORY_REFERENCE_GENERATION_CHANGED/send1**로 재전송을 막는다. 이전 V1-B 재현은 해결됐다. 실제 자식 프로세스의 inner negative→accepted 후 exit99→재시도는 remote_accept_count1/retry_sends0/unknown_accepted를 유지했다 (`dispatch-inner-negative-crash.json`).

## V1-C: 직렬화 총예산 및 항목 예산 회귀 (P2)

`src/cli-gjc-commands.ts:287–337` captureFromReference는 max_excerpt_bytes를 적용하지 않으며, 총예산도 query+본문 길이만 계산한다. JSON 메타데이터가 더해진 최종 요청 크기를 제한하지 않는다.

직접 `dispatch-final-budget-2048.json`: **max_total_bytes=2048인데 최종 JSON/capture.bytes=2180, send1/ok=true**. max_excerpt_bytes=128인데 한 기억 본문1876bytes를 보낸다. 일반 long_text도 128한도에236bytes다. 1024 총예산 사례는 앞단의 빈 context persistence가 CONTEXT_ASSEMBLER_BUDGET_IMPOSSIBLE로 거부하여 전송되지 않았다. 이 거부를 최종 예산 구현으로 오인하지 않았고, 유효하게 전송되는2048사례로 재현했다.

완료 기준: 원 내용·출처·버전을 보존하면서 문서화된 excerpt/omission 규칙을 적용하고, 최종 UTF-8 JSON bytes를 정확히 제한한다. query, source/version, omitted metadata, Unicode/줄바꿈까지 포함한 최종 budget을 검증한다. 고정96자 슬라이스로 되돌아가지 않는다.

## V1-D: 보낸 기억과 영속 문맥/증거 불일치 (P2)

`persistAssembleInput`은 memories/observations/pending_authority_refs를 전부 빈 배열로 만든다. `assembleDispatchContext`는 그것을 session.prepare에 저장한 후, 별도로 만든 다른 capture를 보낸다. 따라서 기존 증거 바인딩 오류가 영속 바인딩을 비우는 방식으로 회피됐다.

직접 `dispatch-persisted-lineage.json`: transport에는 두 기억/497bytes가 전달됐지만, 실제 SQLite personal_context_snapshots는 **payload_state=insufficient, memory_count=0, evidence_count=0**, personal_context_memory_evidence 행도0이다. lastAssembledModelCapture는 no_data=true/223bytes/빈 memories로 실제 전송과 다르다. SQLite 행을 직접 읽었으므로 메모리 내 표시 차이만의 문제는 아니다.

완료 기준: 선택·저장·실제 전송이 동일한 문맥/원계보를 가리키도록 고유 ref와 증거를 정상 바인딩한다. 전달된 항목과 omission/버전/출처를 재구성할 수 있어야 한다. 새 세션 재조회와 재시도에서도 이 관계를 검증하고, 빈 문맥 저장을 실제 전달 증거로 쓰지 않는다. 원 A–F/M4/M9의 계보·문맥 보존 범위다.

## V1-E / N1: 물리 전송 전 거부를 unknown 접수로 남김 (P2)

`cli-gjc-commands.ts:373` 부근의 recordGjcSendStarted가 새 beforeSend 재검증보다 먼저 호출된다. 검증이 거부되어 실제 transport를 한 번도 호출하지 않아도 불명확 접수로 남을 수 있다.

`dispatch-before-send-generation.json`: 마지막 사전 재검증 때 generation을 바꾸면 첫 호출 MEMORY_REFERENCE_GENERATION_CHANGED/**send0**. provider를 정상으로 정정하고 동일 요청을 재시도하면 새 읽기/전송 없이 **ok=true/recovered=unknown_accepted**, 총 send0이다. 실제 접수 후 unknown 보존과 전송 전 안전 거부를 구분하지 못해 정상 정정으로 작업을 이어갈 수 없다.

완료 기준: 물리 전송 직전 검증의 known-unsent 실패는 정상 정정·재조회 후 재개 가능해야 한다. accepted/unknown crash는 계속 중복 방지하고, negative→검증 실패→정정과 최초 검증 실패→정정을 함께 완료한다. 실제 전송 시작/결과와 사전 준비의 상태를 구분한다.

## M12 / B·F / 세션 외부 조건

정본 paired restore harness는 interpreter 경로만 검토 환경에 맞춰 직접 실행했고 EXIT0이다. `/var/tmp/sb-jarvis-restore-YP1YWe`: backup에서 journal2개 복구, JARVIS 삭제→SB복원, 삭제0/보존1, scoped2client/독립철회2/동일세대·본문, 동일runtime 새 accepted request proved, 후속highwater2/재복원0을 유지했다. `paired-restore.log`/`paired-restore-result.json`.

측정 경계 개선은 인정한다. restore 시작→첫 KeepBeta 읽기는 **1830ms**, journal 소실 시나리오 시작→해당 읽기는 **7446ms**, 전체 시나리오는 별도 **17955ms**다. 이 값은 해당 synthetic 규모/실행에 한정하며 운영 RTO가 아니다. 후자의 끝은 scoped client2개의 복구·새 accepted write보다 앞이므로 완전한 업무 복구 시간으로 이름을 확대하면 안 된다.

SB의 backup 후 장애 전 쓰기0/손실0은 이 fixture에서 성립한다. rpo_jarvis는 여전히 tombstone sequence/읽기 여부이며 JARVIS 자체의 마지막 내구 기록·장애 시점·복구 손실량/시간이 아니다. 각각의 RPO, 전체 업무 가능 판정과 B/F의 서비스·설정·백업hash·구버전 상태 호환 또는 검증된 복구 준비가 남는다. 런북의 성공/실패 조건과 anchor 안전 거부 명시는 보존한다. 준비 작업을 운영 허가 대기와 혼동하지 않는다.

Grok는 JARVIS 자체에 모델 세션 문맥 compaction 이벤트가 없으며 native/Orca 세션에서 dispatch 호출을 연결해야 한다고 명시했다. 따라서 실제 compaction은 **미구현/외부 세션 연결 미검증**으로 보존한다. 어떤 기존 제품 진입점·소유자·필요 입력이 남는지 정리하되, 이 항목으로 독립 실행 가능한 위 결함 수정을 차단하지 않는다. 자료삭제 compactor를 모델 문맥 compaction으로 대체하지 않는다.

## 직접 검사와 후속 조치

직접 GJC19+session6 **25passed /23.23s**(tests17.84s), RuffEXIT0, tscEXIT0, 설치 standard/work/maintenance **3게이트EXIT0**. revoked_keys 타입검사는 기존0errors/2warnings/EXIT1이며 완전 통과가 아니다. 제출서의 복구집중13passed는 이번 실행에서 직접 검증하거나 로그를 확인한 수치가 아니므로 별도 주장으로 남긴다. 같은 SB 제품 전체 회귀는 반복하지 않았다. 이전 V2/V3/V4/V5/M6 등 결과는 각각의 고정후보/검증 경로에 한정해 보존한다.

기존 Grok의 현재 승인 목표에서 **최종 예산·영속 계보·전송 전 실패 복구**를 단일 전달 계약으로 함께 마무리하고, M12/B·F의 독립 준비를 끝낸다. 새 worker/새 기능을 만들지 않는다. 운영/native 인증 및 compaction 연결에 필요한 구체적 외부 입력은 오전 보고에 모은다. A–F/R1–R7/V1–V5/M1–M14 원 범위 유지. 운영 current41f0751은 제출된 상태이며 이번에 운영 확인/변경하지 않았다. 사용자삭제/인증복사/운영전환/push 승인 없음. 30분 감시 유지, 최종 인수 없음.
