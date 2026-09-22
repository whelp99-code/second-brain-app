# Codex 야간 독립 검토 — b9fc3d4

**미통과. 새 테스트2개는 통과하지만 원 M13 GUI 삭제 수명과 M11 동시 정정 인수를 검증하지 않는다.** 작성자는 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`이며 원래 Codex의 직접 실행으로 표기하지 않는다. 제품 준비/운영 인수는 미완료. `2026-09-12T11:05:38.322966+00:00`.

## 고정 후보와 직접 결과

제출 `b9fc3d40c5e156883e89bf2927a5623dda44483a`, source `034804ecfd8bb7d7aaa44bb56817cd5b83e0c3d1`, 후보 `/var/tmp/sb-candidate-034804e/releases/7d2fdedd9d4934b809c674cc5ed6c88c068b9726`, wheel `c940cf6b936bb45f9d9c7b0220c03cf3d192c824e3c3b720843aa57080cb389f`. JARVIS `1672626c5f2b0b06f7fb93c900cf8771536b58cd`, dist `/var/tmp/jarvis-artifact-1672626/source/dist`, inventory `e9751dfaf955bab6a1ea15792733e0af576f7bac540ca5efeb0b69d9bccbf9cd`/34768. SB182 Python파일은 source/wheel/installed 바이트 일치, JARVIS inventory도 전후 일치. 이전 e3148bf 대비 제품 sb/와 scripts/ 변경이 없고 새2테스트/문서만 변경됐다. `identity.json`, `changed-files.json`에 정확한 manifest/runtime/변경 범위를 보존했다.

직접 `pytest` 추가2테스트 **2 passed(5.42s)/EXIT0**, Ruff **EXIT0**, 새 후보 설치 standard 게이트 **EXIT0**. 정확한 argv/cwd/env와 원본은 `/var/tmp/codex-night-b9fc3d4-vhasiswh/run.py`, `new-tests.log`, `ruff.log`, `installed-standard.log`. `TMPDIR=/var/tmp`, frozen archive/PYTHONPATH, 제품venv Python. 관측용 pytest plugin은 원 함수를 그대로 호출하면서 시작/종료·호출 표면만 기록했다. 결과 대역/인위적 sleep은 없다.

변경 테스트2파일 타입 검사 **5errors/122warnings/EXIT1**. 이전 e3148bf의 동일2파일을 같은 조건으로 대조하면 **5errors/106warnings/EXIT1**이며 5개 오류 위치도 동일(기존 test_web46,495–498행)이다. 새 제품 오류로 세지 않는다. 추가 테스트 관련 경고16개가 늘었고 타입 통과라고 쓰지 않는다. 제품 모듈의 이전0errors/0warnings 검사와 구분한다.

이전 실제 복원/만료fence거부/종료후fresh2scopes/원장재전송/cold1pass/실제UI/JARVIS8tests·tsc는 같은 제품·harness바이트 범위로 보존하고 재실행·중복 합산하지 않았다. 이전 전체회귀1837passed/1failed/2skipped를 이번2pass로 전체통과라 바꾸지 않는다. 새 제품회귀가 확인된 것이 아니라 미충족 인수 범위가 남은 판정이다.

## P2 — M13: HTTP 조회가 GUI 삭제 수명을 증명하지 않음

`tests/test_web.py:528`의 새 테스트는 `_request`로 Python HTTP9건을 실행한다. remember POST2건, pages GET1건, conflict resolve POST2건, retention GET1건, changes GET1건, search GET2건이다. 삭제 요청/실제브라우저조작은 없다. retention GET은 보존 현황 조회이며 삭제 효과/영수증/부활방지를 검사하지 않는다. `test-observation.json`에 실제9호출을 보존했다.

원 요구는 `CURSOR-HANDOFF-2026-09-10.md:156`의 GUI 정정/삭제·원문/영수증·실패복구다. 패키지55행도 삭제 컨트롤이 없다고 명시한다. 이전 Codex 실제Chrome 기억400→201/충돌400→200 및 inbox/git 통과는 유지하되 전체 수명으로 확대하지 않는다.

**완료 기준:** 원 M13에 필요한 최소 삭제 컨트롤/연결이 없다면 이미 승인된 구현 범위에서 기존 제품 요청·실행·영수증 계약으로 연결하고 합성 fixture의 실제브라우저에서 검증한다. 이는 원 요구를 채우는 구현이며 무관한 새UI/기능 추가가 아니다. 실패 원인 표시→입력정정→같은 경로 재실행, 원문/영수증과 실제 정정·삭제 결과/검색·범위조회 반영을 함께 끝낸다. 기존 실패 이력을 지우지 않는다. 실제사용자삭제/운영timer/native로그인은 허가·외부입력 없이 수행하지 않는다.

## P2 — M11: 두 조회 묶음에 정정/갱신이 없음

`tests/test_scoped_search.py:97–114`는 첫 `list(pool.map(allowed,...))`가 끝나야 다음 `list(pool.map(denied,...))`를 실행한다. 직접 관측 결과 allowed4건 모두종료 후 denied4건 시작이다. 같은허용범위 안의 병렬조회는 있지만 허용/거부가 함께 열린 동시성은 검증하지 않는다. `search_scoped_records` helper 직접호출이며 실제MCP·writer·정정·세대갱신은 없다. 새웹테스트도 같은TERM에 변경 없이 두번검색할 뿐이다.

**완료 기준:** 합성자료와 실제MCP 클라이언트, 제품이 수락한 정정/갱신을 사용해 읽기 중 쓰기커밋을 결정적 동기화로 재현한다. 정정 전후 세대/버전/본문과 오래된 버전 제외, 서로 다른scope의 불허정보노출0을 함께 확인한다. 운영corpus/실사용자질문이 없어도 가능한 원 M11의 격리 범위다. 기존helper통과는 그대로 보존한다. 테스트명을 동시갱신으로 바꾸거나 같은결과 재조회로 대신하지 않는다.

## P2 — F: 로그·소스·측정값 결합 불일치

고정JARVISdist 사용과 fixture root명 정리는 개선됐다. 그러나 JSON18행의 gate log는 `sb-gates-32e58fe.log`인데 harness_commit을034804e로 바꿨다. MD84–86행은 qku1N6의값이라고2092/9740/48ms를 쓰지만 직접 읽은 원본은 **1958/9418/46ms**다. `reported-rto-comparison.json` 참조. 재개상태 파일도 여전히32e58fe다.

**완료 기준:** 고정 source/test/harness/runtime/build/artifact·명령·로그·정확한 가용성 단계별 시간과 상태를 한 진입점에서 정합하게 연결한다. 같은바이트의 이전게이트를 보존할 수 있으나 과거실행 source를 새 source로 다시 이름붙이지 않는다. 이번 직접 검증도 정확한 한계와 함께 인용한다. 운영절차 준비는 실제 전환과 구별한다. 추가 테스트 타입 경고와 기존오류도 통과로 숨기지 말고 새경고는 해당변경에서 정리한다.

## 재개와 외부 조건

이 통합 검토 하나로 기존 Grok의 현재 승인된 목표를 재개한다. 반복 중단의 이번 원인은 잔여 계약을 테스트 이름/작은HTTP·helper검사로 대체한 뒤 완료처리한 것이다. native상태만 running으로 바꾸지 말고 위 원요구가 실제 충족됐는지 완료audit에 포함한다. Codex나 사용자의 추가 답변이 필요하다는 새게이트를 만들지 않는다.

운영 current41f0751/production_activated=false는 제출정보이며 새 운영health 확인은 하지 않았다. 실인증·native사본/compaction경로·실사용자업무/한글정답집·운영corpus/백업/전환허가와 timer가 정확한 외부조건이다. M11/M13의 위 격리 작업은 외부조건이 아니다. 기존 A–F/M1–M14, R1–R7/V1–V5의 통과·미완료 범위는 유지한다. Codex 제품소스수정·운영전환·auth복사·push·실사용자삭제 없음. 기존30분감시는 계속 유지한다.
