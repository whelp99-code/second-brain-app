# 야간 독립 검토 — f0a1044 미통과

작성자: 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e` (야간 독립 검증 위임). 원래 Codex가 직접 실행한 검토가 아니다. 작성 시각 2026-09-11T22:07:33.168721+00:00. 제품 준비/운영 인수는 미완료다.

## 고정 후보와 무결성

제출 `f0a1044db1422f0ab9d1263786e004a980d26862`, SB source `c6949e0bb02c5860ab4b42edaf705a76495cbb54`, release `0ecdb5617a1fe95697e55366f631ee4373f407b1`, wheel `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57`. 후보 `/var/tmp/sb-candidate-c6949e0/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1`. JARVIS `10858a4f80769473123d67147dd55c9c8ae79f1b`, dist `/var/tmp/jarvis-artifact-10858a4/source/dist`.

SB 182 Python 파일은 Git archive/휠/설치물의 바이트가 같다. JARVIS 제품 tracked 1137파일은 Git와 같고, tsc EXIT0 및 재빌드 1109 JS 파일이 제출 dist와 같다. 전체 inventory `cc77dfcb768ca376da107dc153c075ab2afabd4c1dce0aef9af4abce666e964f` / 34768항목은 제출값 및 검사 전후 동일하다. 증거는 `/var/tmp/codex-night-f0a1044-z74_5p00`. Vitest는 독립 전체 복사본에서 실행했고, 직접 재현은 제출 dist를 사용했다. 제품 소스/테스트/운영 상태는 수정하지 않았다.

## 통과한 변화

이전 미호출 reselectAndDeliver는 제거됐다. 실제 `executeGjcCommand`의 gjc.dispatch가 generation_status→search→read_page→generation_status를 호출하고 현재 기억을 선택하여 주입한 transport로 보낸다. caller의 memories/evidence를 빈 배열로 둔 독립 재현에서도 본문을 전달했다. 이전 '제품 호출처 없음' 결함은 이 명시적 dispatch 경로에서 해소됐다.

`dispatch-current-reader.json`: 정상 1건은 session s / 411bytes, no_data는 223bytes / memories[]로 전달. 이미 만료된 record는 MEMORY_REFERENCE_PROVIDER_UNAVAILABLE/send0으로 안전 거부. 총예산32bytes는 PERSONAL_CONTRACT_INVALID/send0 (`dispatch-tiny-budget.json`). 새 세션은 합법적인 fixture configureGjc 후 s→fresh-session 각각 새 provider 조회 4회와 전송 1회를 확인했다 (`dispatch-newsession-generation.json`). 최초 harness의 단순 session_id 교체는 GJC_DISPATCH_NOT_AUTHORIZED로 거부됐으며, 이를 제품 결함으로 세지 않는다.

N1 물리 전송 복구: 독립 자식 프로세스에서 첫 negative→두 번째 접수 후 exit99→새 프로세스 재시도는 remote_accept_count=1/retry_sends=0/unknown_accepted를 유지했다 (`dispatch-inner-negative-crash.json`). 새 reader/fence fixture를 연결한 재현이다. 보편적인 exactly-once/운영 결과로 확대하지 않는다.

## V1-A: 여러 기억의 증거 바인딩과 출처·수명 보존 (P2)

`src/cli-gjc-commands.ts:314` 부근은 모든 evidence의 memory_ref에 `snapshot.payload.included_memory_refs[0]`을 사용한다. 서로 다른 유효한 2개 record를 반환한 직접 재현에서 **PERSONAL_CONTEXT_MEMORY_EVIDENCE_CONFLICT / send0**가 발생한다. 새 record의 본문·record digest는 정본 canonical 규칙으로 계산했다. 1개짜리 fixture 통과만으로 다중 기억 경로가 검증되지 않았다.

같은 파일 `assemblerFromReference` (251–289)는 읽기 결과의 source_ref/source_version/observed_at/fresh_until을 보존하지 않고 source_id를 항상 inbox로, observed_at을 now로, fresh_until을 now+1h로, trust를 user_confirmed로 바꾼다. 본문도 예산과 별개로 줄바꿈을 치환하고 96자에 자른다. `long_text`에서는 남은 예산이 3986bytes인데도 본문 뒤 END_CRITICAL_SOURCE_DETAIL이 사라졌다. excerpt가 가능한 계약이더라도 원 출처/버전·허용된 예산/신뢰·만료를 임의 재작성해서는 안 된다. `memory-reference-context.ts:91`의 reader 결과는 이 정보를 이미 제공한다.

완료 기준: 여러 selected record 각각의 고유한 ref/evidence를 연결하고, 원 출처/버전/수명·신뢰 제한을 보존한 변환 계약을 구현한다. 0/1/여러 건, 서로 다른 출처, 긴 Unicode/줄바꿈 본문, 부분 예산, 만료 경계를 같은 제품 dispatch 경로에서 검증한다. 고정 inbox/첫 ref/임의 확인 상태나 fixture에 맞춘 잘라내기로 통과시키지 않는다.

## V1-B: 선택 이후 실제 전송/재시도에서 세대·철회·만료 재확인 누락 (P1)

새 dispatch는 reader.read 결과를 추출한 뒤 reader.submit/submitInSession의 검증을 사용하지 않고 별도 AssembledModelSession으로 보낸다. `cli-gjc-commands.ts:298–340`, `assembled-model-session.ts:41–55`. 현재 send 재시도는 로컬 권한 함수만 호출하며 provider generation/선택된 record의 수명·privacy를 다시 확인하지 않는다.

직접 `negative_generation_changed`: 첫 send가 명시적 negative를 반환하는 순간 provider generation_id를 바꿨다. 재시도까지 provider 호출은 최초 4회 그대로이며 **동일 이전 기억을 두 번째 send에 전송하고 성공**한다. `dispatch-newsession-generation.json`에 두 capture와 호출 목록이 있다. 이는 최초 조회 시 안전성으로 실제 전달 시점까지 안전하다고 보장할 수 없음을 재현한다. 새로운 reader 자체의 `submitChecked`는 generation/expiry/privacy를 검사하므로 그 보장을 우회하지 않아야 한다.

완료 기준: 첫 전송 및 실제 재시도 경계마다 현재 세대/철회/수명을 확인하고 stale 결과를 보내지 않는다. generation 변경·삭제·권한 철회·만료·negative 재시도와 N1의 unknown/accepted-crash 중복 방지를 함께 검증한다. 외부 승인이 없는 운영/native 인증을 우회할 필요는 없다.

## V1 남은 세션 범위

이번 통과는 **명시적 gjc.dispatch와 합법적으로 구성한 새 세션**의 제품 함수 경로 및 injected transport에 한정한다. 실제 문맥 compaction 이벤트가 이 경로를 일으키는 증거는 아직 제출되지 않았고 정본에서 session/context compaction 진입점 호출을 확인하지 못했다. 자료삭제 compactor나 이름 변경으로 이 요구를 대체하지 않는다. 실제 기존 세션 trigger에 연결하거나, 제품별 필요한 외부 세션 기능/입력과 준비된 경로를 정확하게 분리한다. 단순 RecordingModelTransport를 운영 모델 연결로 표시하지 않는다.

## M12 / B / F

정본 `scripts/jarvis-restore-acceptance.mjs`는 interpreter 경로만 바꾼 독립 실행에서 **EXIT0**. `/var/tmp/sb-jarvis-restore-DZHAm9`: 신뢰 backup의 journal2개 소실/복구, JARVIS 삭제→SB 복원, 삭제0/보존1, 서로 다른 scoped client2개의 동일 세대/본문과 독립 철회2, 같은 runtime의 새 accepted request proved, 후속 삭제 highwater2 및 재복원0을 유지했다. 원본 로그 `paired-restore.log`, 결과 `paired-restore-result.json`. 실제 운영/native 인수나 모든 저장소 소실 복구로 확대하지 않는다.

새 `rto_restore_to_readable_ms=15102`는 이름만 바뀌었다. `restoreStarted`는 여전히 backup 직전에 시작하여 journal 복구, 두 번 삭제/복원, client 검사와 새 쓰기까지 포함한다. 업무 불가 시작/복구 후 사용 가능 시점으로 경계를 정의하지 않았다. `rpo_loss`의 deleted_records=1은 의도적 철회 건수이고 keep_records_at_backup=1은 fixture 개수이며 실제 손실 측정/각 SB·JARVIS RPO가 아니다. 각 시스템의 복구 시점·마지막 내구 기록·손실량/시간을 근거로 계산하고, 장애→사용 가능 RTO를 구분해야 한다. 테스트 전체 소요 시간은 별도 지표로 유지할 수 있다.

런북 현재 핀은 c6949e0/10858a4와 맞는다. 그러나 원 B/F 서비스/설정·백업 hash·성공/실패 조건·구버전 상태 호환성 또는 검증된 복구 준비는 여전히 미충족이다. 원본 anchor 없는 복원은 RESTORE_SOURCE_ANCHOR_MISSING 안전 거부를 유지한다. 운영 허가 부재는 문서/격리 복구 준비의 차단 사유가 아니다.

## 검사 수치와 다음 작업

직접 실행: GJC16 + assembled-session6 **22passed / 18.72s** (테스트14.50s), RuffEXIT0, tscEXIT0, 설치 standard/work/maintenance **3게이트EXIT0**. revoked_keys 타입은 0errors/2warnings/EXIT1로 완전 통과가 아니다. Grok 복구 집중 로그의 13passed/EXIT0는 기존 로그 관찰이며 직접13검사 수치가 아니다 (`/var/tmp/sb-focused-restore-c6949e0.log`, SHA256 `263235f52cce9317085ab1ab445b2f34be11de50b623b23b4eb19c5b9445e975`). 동일 SB 제품 전체 회귀는 반복하지 않았다. 기존 V2/V3/V4/V5·M6 등은 이전 고정 후보와 정확한 경로의 결과로 보존하며 이번 수치에 합산하지 않는다. M1–M14/A–F/R1–R7 원 의미를 유지한다.

기존 Grok의 현재 승인 목표에서 V1의 여러 건/원계보/수명/실제 전송 경계를 하나의 계약으로 끝내고, 실제 compaction 연결 및 M12 측정/B·F 복구 준비를 함께 완료한다. 부분 패치 후 중간 후보로 반복 종료하지 않는다. 제품/native 인증·운영 drain 등 실제 외부 조건은 오전 보고에 모은다. 운영 current=41f0751은 제출된 상태로서 이번에 운영을 바꾸거나 새로 검증하지 않았다. 운영 전환/사용자 삭제/인증 복사/push 승인 없음. 30분 감시는 유지한다.
