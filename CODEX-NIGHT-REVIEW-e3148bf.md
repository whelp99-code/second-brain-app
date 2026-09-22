# Codex 야간 독립 검토 — e3148bf

**미통과: 직전 복원 결함3건은 해결됐으나 원래 실행 가능한 통합 인수가 남았다.** 작성자는 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`; 원래 Codex의 직접 실행으로 쓰지 않는다. 제품 준비/운영 인수 모두 미완료. `2026-09-12T10:36:56.769971+00:00`.

## 고정 대상과 검증 출처

최종 제출 `e3148bf85f04e74b6474be90aae7b22821b053b6`, source `32e58fe3031649221a8694ef967d036c2d2ece50`, 후보 `/var/tmp/sb-candidate-32e58fe/releases/7d2fdedd9d4934b809c674cc5ed6c88c068b9726`, wheel `c940cf6b936bb45f9d9c7b0220c03cf3d192c824e3c3b720843aa57080cb389f`. JARVIS `1672626c5f2b0b06f7fb93c900cf8771536b58cd` / `/var/tmp/jarvis-artifact-1672626/source/dist` / inventory `e9751dfaf955bab6a1ea15792733e0af576f7bac540ca5efeb0b69d9bccbf9cd`(34768). manifest/runtime 정보는 `/var/tmp/codex-night-1bf7210-qoro55_0/identity.json`.

처음 `1bf7210` archive로32e58fe 소스/검증을 고정한 동안 Grok가 마지막 런북 수정 `e3148bf`를 제출했다. 두 제출 간 변경은 `GROK-PIN-RECOVERY-RUNBOOK.md` 하나뿐임을 git diff로 확인하고 최종 문서를 별도 보존·검토했다. **제품·테스트·harness·후보는 동일**하며 바뀐 소스에 과거 검증을 붙인 것이 아니다. `submission-final.json`에 이력을 기록했다. 이 검토의 통합 판정 대상은 e3148bf 하나다.

## 직접 통과한 범위

- SB182 Python파일 source/wheel/installed 바이트 일치. JARVIS34768항목 inventory 전후 일치. 필요한 scoped seed는 이번 git archive에 포함됐다.
- 깨끗한 제출 archive의 paired harness **EXIT0**. Python 실행 파일 경로만 검토 환경에 맞췄고 빠진 fixture를 보충하지 않았다. 필수 복원을 마친 뒤 classified write→recover-a/b/retry 순서가 실행됐다. 새 기록1건과 seq3 확인.
- 필수 recoveredFence만 유효 서명된 만료 시각으로 바꾼 별도 대조군은 **TOMBSTONE_FENCE_REQUIRED/EXIT1**. 정상 복원 실패를 삼키지 않는다.
- **harness 종료 후 새 프로세스의 실제2scoped MCP 세션**이 같은 새 기억/digest/활성세대를 회수했다. A철회 시 A거부/B조회, B철회 시 B거부/A조회, 각 정책 복구와 응답 직후 철회 검사가 통과했다. `final-state-scopes.json`의 independentRevocations=2. 단순 파일 스캔 helper를 제품 조회로 대체하지 않았다.
- 별도 프로세스에서 같은 schema4 요청을 다시 accept하고 실제 RequestExecutor를 실행했다. 상태/영수증/세대 불변, proved7→7, idle/NO_PENDING_REQUEST. **세 번째 read인 recovered_retry와 원장 재전송을 구분**한다. `retry-result.json`, `retry-corrected.log`.
- 수정한 cold 복원 집중 pytest **1 passed(3.94s)**. 브리핑 cap0은 제출된 수정이며, 검토 복사본은 과거 전역 증거 덮어쓰기를 막기 위해 증거 출력 경로만 바꿨다. 원래 제품 run_all/백업/DB유실/복원/새쓰기/검색/철회키 assertion 모두 유지했다.
- Ruff EXIT0, 설치 표준/work/maintenance3게이트 직접 EXIT0.

직전 전체 회귀 **1837 passed/1 failed/2 skipped**는 그대로 보존하며 새 전체 통과로 바꾸지 않는다. 제품 바이트가 동일하고 변경된 실패 테스트를 집중 확인했으므로 전체 회귀를 반복하지 않았다. 직전 변경 타입0errors/0warnings, 실제 Chrome 기억/정정 실패→성공 및 inbox/git, 동일 JARVIS8backup tests/tsc도 보존하고 새 실행 수에 합산하지 않는다.

처음 별도 retry 검토 harness가 반환값을 None으로 잘못 예상했다. 실제 계약은 idle/NO_PENDING_REQUEST이며 상태/증거/세대와 건수는 그대로였다. 검토 assertion 정정 후 통과했고 원본 `retry.log`는 보존했다. 제품 결함으로 세지 않는다.

## P2 — 원래 실행 가능한 통합 인수 잔여

`GROK-FINAL-ACCEPTANCE-PACKAGE.md:55`는 전체 GUI 삭제 경로가 미구현이라고 명시한다.117행은 M7/M13의 다음 격리 작업을 남기지만 worker는 완료했다. 원 M13은 `CURSOR-HANDOFF-2026-09-10.md:156`의 GUI 정정/삭제·원문/영수증·실패 복구다. 운영 timer 허가 부재가 로컬 합성 fixture의 삭제/원문/영수증 수명 검증까지 막지는 않는다. 기존 기억/정정 버튼 성공은 위와 같이 보존하며 전체 수명 인수로 확대하지 않는다.

M11의 동시 조회/정정은 패키지53행에서 운영 자료 입력으로 묶여 있다. 운영 corpus 측정은 외부 조건이나, 원 통합 인계115–119행의 합성 자료에서 가능한 동시 갱신/정정·최신값·권한 불변은 실행 가능한 범위다. 이미 충족된 항목은 해당 고정 바이트/원본 증거를 연결하고 다시 실행하지 않는다. 기존 M7 통과도 같은 방식으로 유지한다.

**완료 기준:** 원 요구의 실행 가능한 GUI/동시 정정·읽기 잔여를 제품 진입점과 실제 결과로 끝내고 정상/실패/정정/삭제/복구의 관련 계약을 함께 검증한다. 외부 로그인·실사용자 원문/정답집·운영 데이터/전환처럼 정확한 입력이 필요한 부분만 별도 보류한다. 새로운 기능이나 UI로 핵심 연동을 대신하지 않는다. 잠든 사용자/원래 Codex/다음30분 입력을 기다리는 부분 제출을 반복하지 않는다.

## P2 — 최종 진입점의 증거·재현 정합성

메인 패키지63행은 qku1N6/harness36이지만69·82–86행은 이전 kJ4UcY와 시간값이다.117행에는 이미 끝낸 미커밋 harness/게이트를 명시 요청 시 하겠다는 문구가 남아 있다.97행 재현은 고정 artifact가 아닌 작업공간 JARVIS dist를 사용한다. 마지막 e3148bf 런북 핀 수정은 확인했으나 메인 진입점의 모순은 남았다.

**완료 기준:** 최신 고정 source/test/harness·runtime/build/requirements·wheel/dist와 원본 로그, 측정 시점/가용성 구간, 새 세션 재현 명령을 단일 진입점에 정확히 연결한다. 과거 로그는 과거로 표시하고 반복 승인대기를 제거한다. 운영 전환을 실행하지 않고도 준비할 수 있는 서비스/경로/설정·백업hash/작성자배제/복구 조건을 원 정본 수준으로 연결한다. 제3 read를 원장 retry로 표시하지 않는다.

## 증거와 다음 행동

원본 `/var/tmp/codex-night-1bf7210-qoro55_0`: `run.py`, `identity.json`, `paired.log/result`, `expired.log`, `cold.log`, `cold-result.json`, `installed-*.log`, `ruff.log`, `final-state-scopes.mjs/.json/.log`, `retry*.py/.log`, 최종 문서와 provenance. `TMPDIR=/var/tmp`, synthetic fixtures. seed의 authority callback과 fixture키는 native인증 인수가 아니다. 제출의 final_fresh helper는 모든 세대 파일을 찾으므로 그 자체를 활성세대 조회로 인수하지 않고 위의 실제 fresh2scope 검증으로 확인했다.

기존 A–F/M1–M14와 R1–R7/V1–V5의 범위 제한을 유지한다. 제품 source 수정/운영전환/auth복사/push/실사용자삭제 없음. 운영 current41f0751과 production_activated=false는 제출정보이며 새 운영health 확인이 아니다. 이 통합 검토 하나를 기존 Grok에 전달하고 현재 승인된 native 구현 목표를 재개한다. 기존30분 감시는 유지한다.
