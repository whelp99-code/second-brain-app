# Codex 야간 독립 검토 — e68d5e5

**미통과.** 고정 제출 재현 파일 누락, 마지막 복원 이후의 성공 수치 불일치, 통합 인계/GUI 잔여와 cold 복원 테스트의 비결정적 실패가 있다. 작성자는 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`이며 원래 Codex가 직접 실행한 것으로 쓰지 않는다. 작성 시각 `2026-09-12T10:18:41.293669+00:00`. 제품 준비 인수/운영 인수 모두 미완료.

## 고정 대상과 직접 검증

제출 `e68d5e5aab6f4bed6d84af8922179179feb8a4ac`, SB source `a4b228f326c275cf0aeb05b6ce01d9f224697a2f`, release `7d2fdedd9d4934b809c674cc5ed6c88c068b9726`, wheel SHA256 `c940cf6b936bb45f9d9c7b0220c03cf3d192c824e3c3b720843aa57080cb389f`. 후보 `/var/tmp/sb-candidate-a4b228f/releases/7d2fdedd9d4934b809c674cc5ed6c88c068b9726`. JARVIS `1672626c5f2b0b06f7fb93c900cf8771536b58cd`, dist `/var/tmp/jarvis-artifact-1672626/source/dist`, 전체 inventory `e9751dfaf955bab6a1ea15792733e0af576f7bac540ca5efeb0b69d9bccbf9cd` /34768항목. 정확한 manifest/runtime/build 정보는 `sb-identity.json`과 제출 JSON에 보존했다.

- SB Python182파일 source/wheel/installed 실제 바이트 일치. JARVIS 전체 inventory도 검증 전후 동일.
- 이번 Codex 직접 전체 회귀: **1 failed, 1837 passed, 2 skipped in 607.24s (0:10:07)**. 변경된 공통 MCP/desktop 읽기 경로의 영향을 확인하기 위해 한 번 실행했다. embeddings 선택 의존성 테스트만 정본대로 제외.
- Ruff EXIT0. 변경 모듈 `sb/mcp.py`·`sb/runtime_access.py` 타입 검사0errors/0warnings/EXIT0.
- 설치 표준·`--work`·유지보수3게이트 직접 EXIT0. 초기 archive 디렉터리에는 git metadata가 없어 표준/업무 게이트가 실패했지만, 실제 repo의 동일 커밋 harness로 정정 후 통과했다. 초기 타입환경 오류도 명시적 `--pythonpath`로 정정했다. 검토 환경 오류를 제품 결함으로 세지 않는다.
- 동일 JARVIS의 이전 직접8backup tests/tsc는 보존하며 이번 실행 수에 합산하지 않는다.
- 누락 fixture를 별도 진단 복사본에만 보충하면 paired 흐름 EXIT0, 실제 서로 다른 recover-a/b/retry와 같은 digest/seq3이 확인된다. 필수 `recoveredFence`만 유효 서명된 만료 시각으로 바꾼 대조군은 `TOMBSTONE_FENCE_REQUIRED`/EXIT1. 보충 파일은 제출물에 포함되지 않으므로 이 통과는 고정 제출 재현 통과가 아니다.

명령/환경: `TMPDIR=/var/tmp`, `PYTHONDONTWRITEBYTECODE=1`, frozen source의 `PYTHONPATH`, 제품 venv Python으로 `-m pytest -q --ignore=tests/test_embeddings.py`. `run-checks.py`, `correct-checks.py`, `run-diagnostics.py`에 정확한 argv/cwd가 있다. 원본 `/var/tmp/codex-night-e68d5e5-1wan26x9`. 운영 authority/config/auth를 테스트 fixture에 복사하지 않았다.

## P2 — 제출 커밋에 필수 scoped seed가 없음

`source/scripts/jarvis-restore-acceptance.mjs:264`가 `scripts/seed-scoped-v4.py`를 호출하지만 source커밋/제출 git archive에 그 파일이 없다. 고정 소스에서 Python경로만 검토 환경에 맞춘 직접 실행은 Python status2/outer EXIT1로 실패한다. 작업공간의 해당 파일은 untracked다. `paired-restore.log`가 원본이며, 보충 진단 파일의 출처/hash는 `diagnostic-seed-provenance.json`에 있다.

완료 기준: 필수 fixture/harness 자료를 모두 로컬 커밋하고, 깨끗한 git archive와 고정 설치물/JARVIS로 정상·실패·복구를 재현한다. 작업공간의 미추적 파일이 있어야 실행되는 제출은 인수할 수 없다. 이는 제품 소스 결함이 아닌 제출 재현성 결함이다.

## P2 — 마지막 복원 뒤에도 기록1건이라는 결과가 실제와 다름

새 classified write와 recover-a/b/retry 검사는275–285행이다. 이후286행 `restoredAgain`이 더 오래된 archive를 실제로 활성화한다. 그런데319행 `second_restore_records` 등은 그 이전의 성공값을 사용한다.

Codex가 별도 보충 진단에서 **모든 제출 동작을 마친 직후** 새 reader로 조회했다. root `/var/tmp/sb-jarvis-restore-ZyYLVt`에서 reported second_restore_records=1이나 실제 `첫 결정`=0, KeepBeta=0, ExtraLost=0이었다. 이어 실제2독립 scoped MCP 세션 모두 `MEMORY_SCOPED_READ_DENIED`로 실패했다. 원본 `final-state.log`의 `CODEX_FINAL_STATE`, `final-state-scopes.json/.log`, 각 fixture MCP stderr. `post-recovery-scopes.json`의 추가 fresh fence/restore도 통과했으나 이후 새 기억은 없었다.

오래된 archive에 없는 새 기억이 사라지고 읽기가 거부되는 것 자체를 새 권한 버그로 단정하지 않는다. 문제는 최종복구 뒤의 업무가능성을 증명하지 않고 복구 전 카운터로 통과를 보고한 것이다. 필수 restore와 만료 fence 거부를 유지하면서, 필요한 복구를 끝낸 뒤 새 classified write/원장 재시도/두독립 scope 철회·회복을 실행하고 종료 후 fresh 프로세스에서도 결과를 확인해야 한다. 의도된 RPO손실이면 정확히 손실로 기록하고 이후 실제 회복을 증명한다.

## P2 — 통합 인계 정합성과 남은 GUI 수명

제출 `isolated-browser-correct-receipt.py:44–53`은 Python `_request` POST로 저장/정정을 수행한다. Chrome은 전후 `dump-dom`만 한다. 직접 실행 EXIT0과 HTTP/파일결과는 보존하되 실제 UI조작 인수로 치환하지 않는다.

**이번 Codex의 추가 실제 UI 통과:** 별도 `actual-ui.py/.mjs`에서 Chrome의 실제 버튼/입력으로 기억 빈내용400→내용정정→동일버튼201, 충돌 없는ID400→ID정정→동일해결버튼200을 실행했다. inbox파일존재와 정정파일/git `e47bc81ba3668f2c650acd1d2e2ef1dd0108e09d` 확인. `actual-ui-result.json`, `actual-ui.log`, 실패/성공PNG·HTML에 보존했다. Python POST나 숨은 URL명령 없이 수행했다. 이 한정된 기존 UI흐름은 새 통과범위로 보존하고 불필요하게 다시 실행하지 않는다. 기억의 최종 컴파일/전체삭제/native/운영timer까지 통과한 것은 아니다.

패키지56행은 GUI삭제컨트롤 부재,116행은 남은 M7/M13/미커밋 및 명시요청 대기를 남긴다.71행에는 구핀12db06e 게이트가 있고 `GROK-RESUME-STATUS`도 과거핀이다. 새버전표와 모순되며 로컬커밋은 이미 승인된 구현 범위다. 기존 실제 UI 통과와 HTTP증거를 구분해 연결하고, 원 A–F/M1–M14의 실행 가능한 잔여를 끝낸 뒤 정확한 현재핀·원본로그·runtime/build·재현/복구 절차의 단일 진입점으로 정합화해야 한다. GUI 미구현을 운영허가만의 문제로 바꾸거나 기존 요구를 줄이지 않는다. 임의 새기능은 추가하지 않는다.

## P2 — cold 복원 회귀 테스트가 외부 브리핑 결과에 의존

`tests/test_cold_restore_write.py:46–47`의 첫 `run_all`이 백업 전 실패했다. 원본 fixture의 ledger를 읽어 확인하니 ingest/compile은 ok, brief derivation이 `unresolved [^uncited]`3건으로 failed였다. `cold-failure-ledger.json`에 원본 오류를 보존했다. 기본 cap10으로 CLI를 부르는 테스트이며 이 테스트와 pipeline/briefing은 c0b4fce 대비 변경이 없어 새 제품 소스 회귀로 단정하지 않는다.

별도 검토 복사본에서 설정 `max_llm_calls_briefing=0`과 증거 출력 경로만 바꿨다. 실제 `run_all`·백업·fixture DB3개 유실·복원·새 쓰기·검색·철회 키 보존 검사는 모두 유지했다. 직접 PASS, 복원 뒤 새 커밋 `20f38036262903f705edcb3457f9db528366f320`, pre/post 검색 각각1건, revoked key `key:test` 보존. 해당 작은 fixture의 백업 시작→복원/첫 검색까지0.0524초이며 운영RTO가 아니다. `cold-local.log/.json`(정확한 JSON 이름 `cold-local-result.json`)과 `cold-diagnostic-source.py` 참조. 제품 코드는 수정하지 않았다.

완료 기준: 기존 cold DR 테스트를 명시적 로컬 설정 또는 결정적 provider fixture로 고쳐 외부 생성 결과에 의존하지 않게 하고 기존 제품 경로/복구 검사를 유지한다. 원래 전체 회귀는 **실패1건**이며 이 한정 진단 통과로 전체 통과라고 바꾸지 않는다. 수정 후 해당 집중 회귀를 실행하고 필요한 영향 범위만 넓힌다.

## 유지되는 경계와 다음 행동

기존 R1–R7/V1–V5의 통과와 미완료 범위를 유지한다. fixture/helper/실제 제품 진입점/native운영을 구별한다. 운영 로그인/자동주입/compaction사본수명, 실사용자 업무원문/한글정답집, 운영 corpus/백업/전환허가 등 정확한 외부입력은 따로 남는다. 운영 current41f0751/production_activated=false는 제출정보이며 이번에 운영health를 새로 검사한 결과가 아니다.

Codex는 제품 소스/테스트를 수정하지 않았다. 검토 복사본/harness/보고서/조정기록만 작성했고 push·운영전환·인증복사·실사용자삭제 없음. 이 통합 검토 하나를 기존 Grok에 전달하여 승인된 목표를 공식 재개한다. 새 고정후보에서 관련 정상/실패/복구와 원통합 인계를 함께 확인한다. 기존30분감시는 사용자중단 또는 검증된 최종완료 전까지 유지한다.
