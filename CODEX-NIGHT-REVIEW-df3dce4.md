# 야간 독립 검토 — df3dce4 미통과

작성자: 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e` (야간 독립 검증 위임). 원래 Codex 직접 실행 아님. 2026-09-11T19:05:03.308945+00:00. 제품 준비 및 운영 최종 인수 아님.

## 고정 후보 및 직접 바이트 확인

제출 `df3dce40e63452059101862b39a3753fb3112877`, SB source `537ec9be03320e941b699c9655da406a3556bddb`, release `0ecdb5617a1fe95697e55366f631ee4373f407b1`, wheel `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57`. 후보 `/var/tmp/sb-candidate-537ec9b/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1`. SB182 Python파일 archive/휠/설치물 동일. 이전26b06eb 대비 제품 sb 바이트 변화 없음, 새 테스트/문서만 추가됐다.

JARVIS `a935751`, `/var/tmp/jarvis-artifact-a935751/source/dist`. Git 제품 tracked1137파일 동일, 직접 tsc EXIT0, 재빌드1109JS가 제출 dist와 동일. 설치 게이트의 전후 inventory `e0e5c22adbdca1b7a7b44a08068a46f35d90c0359b06599924402c2314c4a0a9`/34780도 제출값과 일치. 각 게이트는 실제 source_commit537ec9b의 harness를 추출해 설치물을 실행했다.

모든 독립 증거: `/var/tmp/codex-night-df3dce4-hmjxkqph`. 종료 시 SB HEAD 고정 제출과 동일. Codex는 제품 소스/테스트/운영 상태를 변경하지 않았다.

## N1: 전송 시도별 결과와 응답 유실 복구 미완성 (P2)

**개선 보존:** 첫 전송에서 합성 remote가 접수를 기록한 뒤 child exit99이면 재시작 sends0, remote접수1, `unknown_accepted`로 남는다 (`dispatch-accepted-crash.json`). 살아있는 worker +61초 경합도 sends1이다. 명시적 거절 뒤 정정, 권한거부 뒤 정정, 잘못된 스키마/철회 fence는 각 기존 제한 경로에서 유지된다. transport에 진입한 후 아직 전송하지 않고 child를 끝낸 경우도 현재는 unknown으로 남는다; 전송 여부를 관측할 수 없는 경계 자체를 자동 재전송 요구로 해석하지 않는다. 전송 시작 전 예약의 dead-worker 회수는 제품 focused test로 통과했다.

그러나 실제 public handler/SQLite/제출 dist에 다음 재현이 남는다.

1. **명시적 실패 → 재시도에서 remote접수 후 exit99 → 다시 재시작**: remote접수2회/retry sends1 (`dispatch-fail-accepted-crash.mjs/.json`). `gjc-intent-store.ts:107`의 과거 어느 `model_send_failed`라도 존재하면 다음 시도의 미확정 접수까지 재전송 가능하게 한다. 실패 이벤트가 현재 attempt/fence에 귀속되지 않는다.
2. **remote접수 → 응답 유실 예외 → 재시도**: 합성 remoteAccepted2건/sends2 (`dispatch-accepted-timeout.mjs/.json`). `cli-gjc-commands.ts:123`은 모든 예외를 명확한 `model_send_failed`로 기록한다. 일반 throw는 원격 미접수 증명이 아니다.

두 재현 모두 합성 transport이며 실제 사용자 데이터나 운영 모델 요청을 사용하지 않았다. 임의 remote에 대한 무조건 exactly-once 요구가 아니다. 검증된 미전송/명시적 거절과 불명확 접수 결과를 구분하고, **시도별 durable 상태 + transport delivery identity/가능한 reconciliation**으로 기존 응답 유실 복구 계약을 끝낸다. 실패 이력 뒤 성공·미확정, timeout, 프로세스 중단, 정정, 동시요청을 함께 검증하고 한 fixture만 고치는 반복을 피한다.

## N1: remote reconciliation 성공이 원장에 정착하지 않음 (P2)

`dispatch-reconcile-accepted.mjs/.json`: 접수 후 child exit99, 새 프로세스가 DB를 열고 합성 transport의 `reconcile`이 accepted:true를 반환한다. 응답은 `recovered: remote_accepted`지만 **model_dispatched=false**, lease_owner는 죽은 child다. `cli-gjc-commands.ts:105`에서 호출하는 `recordGjcModelDispatched`는 `gjc-intent-store.ts:63`의 owner 검사로 아무 기록 없이 반환한다.

owner/fence 안전성을 없애지 말고, 정당한 복구 주체가 실제 receipt를 원자적으로 기록하고 난 뒤 성공을 반환하게 한다. 초기 transport에도 같은 delivery identity가 결합되는지 확인하고, 재실행/재시작에서도 접수 확인이 한 번 정착함을 검증한다. 현재 reconcile callback 추가만으로 복구 완료를 주장할 수 없다.

## M12: archive 검증 뒤 별도의 빈 vault 쓰기는 실제 복원 후 쓰기가 아님 (P2)

새 테스트의 독립 복사본은 **출력 경로만 변경**했다. 직접 `1 passed/12.55s`, 원본 journal이 없으면 RESTORE_SOURCE_ANCHOR_MISSING, 기존 신뢰 journal로 digest 검증, 제품run_all ok/commit `cdafe2c68bbb19cac941ecc7bb40ec0d3c7ae733`, post 검색을 확인했다. 기록된8.9989초는 이 한 fixture의 검증+새vault생성+쓰기 시간이다.

하지만 `tests/test_restore_journal_loss.py:32`는 기존 store에 archive 검증만 하고, :34부터 **init_vault(tmp_path/writable)**로 새 vault를 만든다. archive를 이 대상에 복원하지 않고 cfg에 share_root도 없다. 따라서 원본 업무/세대/원장/요청 journal 및 삭제high-water가 복원되어 새 쓰기가 가능한지는 검증하지 않았다. 백업시각 하나는 별도 SB/JARVIS RPO가 아니다. 테스트 자체 실행 오류가 아니라 인수 경로 미연결이다.

기존 통합5E/CURSOR9 요구 유지: 신뢰된 복구자료와 anchor를 명시한 합성 shared runtime에서 원본/control journal 소실→실제 restore→fresh scoped 허용/거부·보존/삭제기억·high-water/재유입차단→**동일 복원 시스템의 새 제품 쓰기**→별도SB/JARVIS RPO/전체 사용가능RTO. 원본 anchor 없는 안전거부는 우회하지 않는다. 기존 runtimebackup/JARVIS restore harness를 확장하고, 검증함수와 빈vault쓰기 두 조각을 연결된 DR로 제출하지 않는다.

## 통과한 범위와 남은 원 요구

직접 JARVIS focused **10tests passed**, 전체10.11s/테스트6.45s. RuffEXIT0. tscEXIT0. SB revoked_keys 타입 **0errors/2warnings/EXIT1**, 완전 타입검사 통과로 표시하지 않는다. 설치 standard/work/maintenance **3게이트 EXIT0**. 각 원본은 `jarvis-focused.log`, `ruff.log`, `python-types.log`, `jarvis-tsc.log`, `installed-*.log`.

Grok 전체 원본 `/var/tmp/sb-full-pytest-537ec9b.log`을 읽어 **1833passed/2skipped/649.28s/EXIT0** 확인(SHA256 `ed061a2a0c07b305fc87c916b94dcd80667b1fdc86c177f34913d580551f1659`). 이것은 기존 로그 관찰이며 Codex 직접 전체회귀 수치가 아니다. 같은 SB 제품 바이트에 전체 검사를 반복하지 않았다. 이전 M6 SIGKILL후 업무commit/key보존, legacy복원, 브라우저 실패→정정→동일UI성공, 제한된MCP성능/검색 및 이전 shared-runtime restore의 통과는 해당 고정 트리/정확한 경로로 보존한다.

V1/M9는 `personal-context-persistence.ts:58`의 `session:${now}`가 여전히 선택 task.session_id가 아닌 구조이고, 새 런북의 nested dispatch/extra keys/unknown 안내는 새세션·compaction·최종transport 인수가 아니다. 이 영역 제품 변경은 없었다. auth없이 가능한 실제 제품 경로를 완성하고 native/live 인증만 외부조건으로 구분한다. 런북은 현재 핀/게이트를 적었지만 기존 B/F의 실제 상태 호환성 또는 검증된 복구 절차, 서비스·설정·백업hash·성공실패조건까지 갖추지 않았다.

A–F/R1–R7/V1–V5 및 원 M1–M14 의미 유지. 원 M14는 연기/미구현으로 보존하며 새 기능을 임의 추가하지 않는다. M1/M2/M5/M8 native/사용자 입력과 운영drain 등 진짜 외부조건은 오전 보고로 모으고 승인 우회하지 않는다.

## 다음 행동

현재 승인된 기존 Grok native 목표에서 위 **delivery 시도/receipt 복구 + 동일 shared runtime의 DR + 실제 세션/최종핀 복구 준비**를 한 체크리스트로 마친다. 변경마다 작은 후보로 되돌려 보내지 말고 관련 정상/실패/복구 계약과 근거를 함께 제출한다. 이 보고서는 최종 인수/운영 전환을 승인하지 않는다. 30분 감시 유지.
