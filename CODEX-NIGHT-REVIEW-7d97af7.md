# 야간 독립 검토 — 7d97af7 미통과

작성자: 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`에 위임된 야간 독립 검증자. 원래 Codex가 직접 실행한 검토가 아니다. **제품 준비 인수 미통과, 운영 인수/전환 승인 아님.** 제품 소스/테스트를 수정하지 않았고 고정 복사본·검토 harness·보고서만 작성했다.

## 고정 대상

- 제출 `7d97af74f3f75efad4d73a4ad9df88fc4e85ad0a`.
- SB source `55a2dfd85d59efa4fba5f3ac78c2a1d90d369877`; 별도 선언된 MCP harness `7bf4fa3`는 제출 archive에서 읽었다. 제품 Python 변경과 harness 변경을 구분했다.
- 후보 `/var/tmp/sb-candidate-55a2dfd/releases/8a85e133340baf66e58cedc517108d4529d44ba8`.
- wheel `7f591736d7b17384eb6fc0f88700f33e136688cf539d6b5f07429d890e6a9e7b`.
- JARVIS `e3ca9355d8db6383d2df9bd5d5a65102f70e80bf`, `/var/tmp/jarvis-artifact-e3ca935/source/dist`; inventory `b4d80e7c81b1a63c14c6368a0a32f5dee2fdb969a8bab24a95594fcce6331fd1` /34778.
- 독립 증거 `/var/tmp/codex-night-7d97af7-20yx1iji`; 고정 archive `source/`. 검토 종료 확인에서 두 HEAD는 위 값과 같았다.

SB Python182개 archive/wheel/설치물 동일. JARVIS 추적 src/tests1133개 git 소스 동일, 별도 재컴파일 JS585개 dist 동일. 설치 gate의 실제 inventory도 일치했다.

## 직접 통과한 검사와 한계

변경 철회 및 관련 scoped/rollback 회귀 **22 passed /14.22s**, Ruff EXIT0, Python 변경 모듈 타입 **0 errors/2 warnings/EXIT1**, JARVIS tsc EXIT0. 설치 표준/work/유지보수 각각 EXIT0. `focused.log`, `ruff.log`, `python-types.log`, `jarvis-tsc.log`, `installed-*.log`가 원본이다.

Grok 전체 회귀 **1828 passed, 2 skipped /605.57s**는 `/var/tmp/sb-full-pytest-55a2dfd.log`를 읽은 수치다. 이번 검증자가 전체를 재실행한 수치가 아니며 SHA/tail은 `grok-full-log-observation.json`에 있다. 결정적인 결함이 남아 동일 트리 전체 회귀를 반복하지 않았다.

N1 factory 직접 경로의 정상, false→성공, false2회 거부, throw disconnect→성공, 초기 fence 거부 send0, no_data 빈 본문 전송, 만료 evidence 거부는 통과했다 (`factory-session.json`). N3의 빈/부분/완전한 기록 유실, legacy marker 거부, marker 갱신 중단 후 단일 reader 복구와 record 재시도도 통과했다 (`marker-lifecycle.json`, `partial-truncation.json`). 기존 cap 혼합/재시도·marker symlink·N2 길이/경로 순위도 `extended-result.json`에서 유지됐다.

## N1 / V1 / R4 — 새 dispatch 연결의 계약 결함 (P1)

`src/cli-gjc-commands.ts:91-92`는 `assembleDispatchContext`로 **전송을 먼저** 하고 `createGjcDispatchFromTask`로 작업을 나중에 검사한다. `src/gjc-configuration-store.ts:146`의 exact-key 스키마는 `assemble_context`와 `memory_evidence`를 허용하지 않는다. 따라서 현재 제안된 새 필드를 그대로 넣은 task는 원래 dispatch 검사를 통과할 수 없다.

실제 제출 dist의 CLI `execute(['gjc','dispatch',fixtureTask,...], dependencies)`로 독립 실행했다. context/evidence가 유효하더라도 dispatch 입력이 불완전한 경우 **model sends1 이후 GJC_DISPATCH_SCHEMA_INVALID**, result 없음이었다 (`dispatch-boundaries.mjs/.json`). 외부 모델 호출은 하지 않았고 주입 transport의 호출을 센 것이다. 동적 재현과 exact-key 코드가 함께 새 진입점의 정상/거부 계약 미완료를 보여 준다.

또한 `assembleDispatchContext`는 `context.dependencies.memoryReferenceOptions`가 없으면 조용히 생략한다. 일반 `src/cli.ts:25`는 `execute(argv)`로 호출하며 이 옵션을 공급하는 설정 경로가 없다. 새 단위검사 5개는 직접 factory/session helper만 사용하고 실제 새 dispatch 성공을 검증하지 않는다. 읽기 전용 `memory.context`에 무조건 전송 부작용을 추가하라는 요구는 아니다.

**완료 기준:** 기존 권한·lease·정확한 schema 계약을 유지하는 검증된 세션 입력/문맥 envelope를 정하고, 요청 유효성/권한 확인을 모든 외부 전송보다 먼저 수행한다. 기본 제품 진입점의 실제 옵션/transport 연결과 정상 dispatch 성공·잘못된/무권한 입력 send0·중복 요청·실패/복구를 함께 검증한다. 새 필드를 받기 위해 exact-key/권한 검사를 우회하거나 불명확한 필드를 무조건 제거하지 않는다. 실제 task/session 식별자와 model 요청 수명도 연결한다.

## N1 / V1 / M3·M9 — 재시도 직전 권한을 재확인하지 않음 (P1)

`src/assembled-model-session.ts:26-32`는 authorize를 최초 한 번만 호출한다. 독립 `retry_revoked` fixture에서 첫 send가 실패하면서 현재 read fence를 revoked로 바꿨다. 이후 두 번째 send는 **sends2, read-fence calls1, revoked=true, delivered=true**였다. 기존 reader의 응답 후 권한 재확인과 같은 수명 경계가 재시도에 전달되지 않았다.

완료 기준: 각 실제 전송/재전송 직전에 현재 시각의 위임·철회·세대/수명 조건을 확인한다. 최초 문자열 now를 그대로 재사용해 시간 경과를 숨기지 않는다. 최초 허용→전송 실패→철회/만료/세대 변경→재시도 거부(send 추가0)와 권한 유지→재시도 성공을 함께 검증한다. 무조건 모든 예외를 재시도하지 않는다. 이 재현은 합성 policy/transport 경계이며 실제 사용자 데이터 유출을 주장하지 않는다.

## N3 / R2 / M3 — journal 복구의 동시 reader 실패 (P2)

`sb/revoked_keys.py:54-72`의 `_recover_journal`은 read 경로에서 writer lock 없이 marker를 쓰고 journal을 제거한다. 같은 pending journal을 두 reader가 읽으면 한 reader의 제거 뒤 다른 reader가 `journal.unlink()`에서 FileNotFoundError로 실패한다.

`journal-concurrent.py/.json`은 sleep 없이 barrier/event로 두 reader가 같은 journal을 읽은 시점만 조정했다. marker 쓰기 및 load는 실제 제품 함수를 실행했다. **reader0 keys=[key:a,key:b], reader1 FileNotFoundError**, 마지막 store의 키는 정상 보존됐다. 철회 부활은 아니며 정상 동시 조회 하나가 예외로 실패하는 가용성/복구 결함이다.

완료 기준: read/write/recovery 간 소유권과 원자성을 일관되게 처리하고 반복 복구를 idempotent하게 만든다. 단순 이번 FileNotFoundError 한 줄만 삼키지 말고 공유 `.tmp` marker 경합, writer 진행 중 read, 중단 뒤 동시 재시작·새 철회/새 유효 키까지 검사한다. 정상 legacy store는 fail-closed로 거부되므로 승인 범위의 신뢰 가능한 마이그레이션/복구 절차도 제출한다. 손상된 현재 파일에 맞춰 marker를 덮어쓰는 복구는 하지 않는다.

## M11 — 직접 실제 MCP 측정 및 기존 페이지 정정

제출 harness를 독립 복사본으로 실행했고 후보 launcher를 exec하는 검토 wrapper로 해당 MCP 프로세스 PID를 기록하여 `/proc/<pid>/status`를 읽었다. 제품/설치 launcher는 수정하지 않았다. `mcp-corpus.py`, `mcp-launcher`, `mcp-corpus.log`, `mcp-corpus-result.json`이 재현 자료다.

| 페이지 | p50 초 | p95/max 초 | MCP RSS KiB |
|---:|---:|---:|---:|
| 30 | 0.0559 | 0.0995 | 81972 |
| 100 | 0.0824 | 0.0901 | 83268 |
| 300 | 0.1620 | 0.1956 | 84288 |

각 11회, 첫 표본 포함, p95 nearest-rank. RSS는 서버 시작 후와 각 query 완료 시 표본의 최대이며 OS 전체 생애 peak가 아니다. 이번에는 세 규모 모두 같은 page_id의 새 본문 query가 회수되고 옛 needle query 결과0이 확인됐다. 이전 ‘새 페이지 추가’ 증거 결손은 이 범위에서 해소됐다.

한계: correction은 generation library mutation callback에서 기존 wiki 본문을 수정한 격리 재현이다. 실제 사용자 정정 진입점·원업무 계보·동시 정정/조회 전체 인수는 아니다. 300개를 운영 규모라 부를 근거, 실제 timeout 여유/단계 시간, 완료 후 응답 유실·idempotency 증거는 여전히 구분해야 한다. 제출의 null RSS를 이제 해결 불가능한 외부 조건으로 취급할 이유는 없다.

## M12 — 추가 직접 실행한 격리 복원 통과

제출 source의 `scripts/jarvis-restore-acceptance.mjs` 및 연관 harness를 검토 디렉터리에 복사하고 경로/검증 Python만 고정 archive에 맞췄다. SB 프로세스는 **고정 source**를 실행하며, 그 제품 Python 바이트는 위 wheel/설치물과 일치한다. JARVIS는 제출 dist다. 실제 운영 authority/config/auth를 복사하지 않았다.

`restore-integration.log/.json`: 실제 JARVIS fixture 삭제 체인→백업/복원→권한별 조회, 삭제 high-water1 유지, 살아남은 기억1개, 서로 다른 두 agent/session의 동시 조회와 독립 철회2회, 복원 후 재삭제 high-water2→두 번째 복원 후 삭제 기억0 모두 EXIT0. model calls0, 실제 native/운영 인수 아님. M12를 단순 과거 sealed 조회1로만 보고하지 말고 이 증거를 보존한다.

한계: 이 harness는 모든 live control journal/원본이 사라진 cold disaster의 재구성과 전체 RPO/RTO를 검증한 것은 아니다. 복원 후 삭제 mutation은 검증했지만 새 일반 업무 쓰기/조회까지 전 범위를 완료한 것으로 확대하지 않는다. M6의 writer/lease 배제·rollback 진입점 강제 적용도 단위검사 포함만으로 전체 통과가 되지 않는다. 기존 적합한 고정 후보 증거를 연결하거나 승인 범위 격리 검증을 끝낸다.

## 원 요구와 후속 실행

A–F/R1–R7 및 원래 M1 신원/권한, M2 업무 공유 계보, M3 철회, M4 검증 원계보, M5 native 사본 수명, M6 단일작성자/전환복구, M7 전체 읽기, M8 제품 연결, M9 문맥/compaction, M10 검색품질, M11 성능, M12 DR, M13 GUI, M14 관계검색의 의미를 유지한다. N2와 a7df330의 정상 UI 복구 N4 한정 통과도 보존한다. UI 관련 제품 소스가 바뀌지 않아 같은 검사를 이번에 반복하지 않았다.

Grok는 새 dispatch의 정상·거부·수명/재시도와 journal 동시 복구를 **한 통합 작업**으로 처리한다. 이후 M6/M12 및 전체 요구별 상태/증거 표까지 갖춘 고정 후보를 제출한다. 작은 wrapper/한 줄 수정 뒤 ready를 반복하지 않는다. 현재 native 구현 목표만 공식 기능으로 재개하며 옛 W4 운영 blocked 목표로 돌아가지 않는다.

외부 조건은 실제 로그인, 업무/공유 프로젝트, native 세션/사본 범위, 사용자 질문, 운영 drain 허가다. 위 독립 구현/검증의 차단 사유로 확대하지 않는다. 야간 반복 승인을 묻지 않는다. 운영 current 보고값41f0751, 직접 gate production_activated=false. 운영 전환·인증 복사·사용자 기록 삭제·push는 수행/승인하지 않았다. 기존 30분 감시를 유지한다.
