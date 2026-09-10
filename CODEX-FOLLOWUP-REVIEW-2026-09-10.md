# 그록 후속 회신 검토 및 작업 지시서

검토 대상: 시작 시 미커밋이던 `CODEX-FOLLOWUP-REPLY-2026-09-10.md`, 코드 HEAD `0033c22`. 시작 `a6b3620` 이후 구현/문서 커밋은 12개다. 검토 도중 회신서만 추가하는 `4173b2e` 커밋이 관측됐으며 제품 코드·테스트 차이는 없다. 이 검토에서 해당 커밋을 만들거나 원본 회신을 수정하지 않았다. 운영 전환·기억 삭제·journal 수정도 수행하지 않았다. 아래 작업 지시서는 후속 실행용이며 아직 수행한 결과가 아니다.

## 판정

주요 정정과 수행 범위는 코드·증거에 부합한다. 다만 “승인 없이 도달 가능한 끝”을 모든 남은 개발이 막혔다는 뜻으로 받아들이지는 않는다. M3·M5는 설계/제한된 테스트, M9–M12는 측정 단계다. 실제 사용자 신원 종단 인수와 메인 기억 저장소 전체 완성은 아직 아니다.

## 직접 확인한 결과

| 검증 | 결과 |
|---|---|
| 변경 테스트 4개 파일 | `tests/test_activated_orphan_rows.py`, `test_managed_copy_disposal.py`, `test_web.py`, `test_korean_search_hard_draft.py`: **29 passed / 41.90s** |
| 관련 기존 회귀 2개 파일 | `tests/test_ops.py`, `test_korean_search_evaluation.py`: **43 passed / 2.57s** |
| 정적 검사 | `uv run ruff check --no-cache sb tests` 및 `git diff --check a6b3620..0033c22` 통과 |
| 문맥 probe | 운영 authority와 페어 빌드 양쪽에서 `boundary_gaps_reproduced`, exit 0, `delivery_acceptance=false`. 3B/3600B 본문 모두 snapshot 1967B 재현 |
| 실제 후보 wheel | `c04dee1` 안의 wheel 바이트 SHA-256은 `ac8fcd1655356124ec0c51b56b9e23cc4b9054ede9283649fd2fecb4703502ca` |
| 현재 릴리스 링크 | SB `41f0751aca8906d612961e704bc60dd0855fdabd`, JARVIS authority `a3cbbbe1604798052db6051a8751f039573eb126` |

pytest 명령에는 `TMPDIR=/var/tmp`를 사용했다. 전체 회귀는 이번에도 실행하지 않았으며, 예전 전체 회귀 결과를 새 HEAD의 전체 통과로 표시하지 않는다. 라이브 링크의 현재 값 확인은 과거 구간에 변경이 전혀 없었다는 이력 증명과 구분한다.

## 정정 3건의 타당성과 범위

1. **운영 memory 모듈은 존재한다.** 실제 `dist/src/*.js` 파일 수는 운영 369 / 페어 513, 페어에만 있는 파일 144개로 일치한다. 다만 `cli-memory-intake.js`, `cli-memory-reference.js`, `cli-memory-scoped-reconcile.js`, `memory-outbox-production.js`는 운영에 없고 페어에 있다. 기본 memory 코드와 새 scoped/production 명령 경로를 구분해야 한다. 따라서 종전의 “memory 관련 77개가 없다”와 “memory 코드 전체가 없다”를 같은 주장으로 취급하지 않는다.
2. **DR verify 정정은 타당하다.** 커밋 JSON에는 tiny 설정을 쓴 검증의 mismatch와 복사본 아카이브 검증 7.4197s 성공이 모두 있다. `sb/backup_verification.py`도 expected generation 불일치 시 해당 오류를 낸다. 아카이브 무결성 성공이 운영 신원·삭제 상태를 포함한 복원 성공을 대신하지 않는다. 이번에는 DR를 재실행하지 않았다.
3. **고아 journal의 잔존 이유는 코드와 일치한다.** 읽기 전용 조회에서 동일한 activated 3행이 남고, 대응 세대 디렉터리는 active/retired 모두 없다. 현재 세대는 proved다. 운영 wheel에는 prior pointer switch 마무리 호출이 없고 후보에는 있지만 현재 parent만 대상으로 한다. 이로써 다음 쓰기가 왜 옛 3행을 정리하지 않는지는 설명된다. 최초 행 생성과 디렉터리 소실의 전체 사건 순서까지 입증한 것은 아니다.

## 인계에 반드시 덧붙일 점

- **doctor 개선은 고정 후보에 없다.** `git diff 4aa7111..0033c22 -- sb`는 `sb/ops.py` 29줄 추가이며, 설치된 `c04dee1`의 `ops.py`에는 `activation-orphans`가 없다. 기존 검증 후보를 유지할 수는 있지만 새 doctor 개선까지 배포된다고 쓰면 안 된다. 포함하려면 새 후보 생성·설치 인수를 별도 수행한다.
- **운영 수치는 스냅샷이다.** 이번 읽기에서 proved는 89가 아닌 94이며 current generation은 `cef0c87b…`다. activated 3행은 동일하다. 실제 설정의 vault는 `/home/jm/.local/share/second-brain/vault`다. 전환 전에는 설정에서 경로와 current를 다시 읽고 lease/DB 핸들/backup도 함께 재확인한다.
- **memory 개수의 집계식을 명시해야 한다.** 문서의 “memory-* 또는 second-brain*”를 파일명 접두로 적용하면 운영 124 / 페어 197이다. 문서의 125 / 198은 그 정의로 재현되지 않았다. substring 전체 검색은 128 / 213으로 또 다르다. 모듈 부재 판정은 숫자만으로 하지 말고 정확한 파일 목록과 import/명령 진입점을 고정한다.
- **웹 검증은 실제 재처리의 종단 시험이 아니다.** 새 `test_web_run_does_not_clear_held_brief_failures`는 `sb.web.run_all`을 실패 응답으로 대체한다. 실제 HTTP 응답과 실패 원장 보존을 확인하지만 실제 pipeline 재실행·브라우저 조작·복구 성공까지 입증하지 않는다.
- **품질·성능은 여전히 개선 전이다.** 한글 fixture SHA와 기존 실행 evidence를 대조했다. 정답 있는 합성 15문 Recall@5 73.3%, 붙여쓰기·자연어·의역은 해당 사례에서 미회수다. 문맥 전달 공백도 양쪽 빌드에서 재현됐다. 쓰기 21.36s/그중 fsync 15.35s는 기존 격리 측정이며 이번에는 성능을 재측정하지 않았다.

5.2의 운영 전환은 이번 “확인” 요청으로 실행하지 않는다. 그와 별개로 새 dependency artifact 준비, compiled marker 복구 절차의 격리 검증, M3 구현 대안/ADR, 검색·문맥·쓰기 성능 개선은 계속 준비할 수 있다. 실제 중단 판단은 해당 준비가 구체화된 전환 절차를 대상으로 한다.

## 후속 작업 지시서 — Cursor·Claude·Grok·Codex 공통

### 1. 목표와 적용 범위

세컨드브레인을 기반으로 유지하며 **JARVIS와 여러 에이전트가 같은 기억을 권한·출처·정정·삭제 수명까지 일관되게 쓰게 하는 것**이 목표다. 보고서 추가나 테스트 개수 증가만으로 완료 처리하지 않는다. 아래 W0–W9는 원래 M1–M14를 실행 순서로 묶은 것이며, 기존 요구를 삭제하거나 완화하지 않는다.

작업공간은 `/home/jm/orca/projects/second-brain-app`이다. [기존 인계서](/home/jm/orca/projects/second-brain-app/CURSOR-HANDOFF-2026-09-10.md), [OSS 통합 계획](/home/jm/orca/projects/second-brain-app/OSS-ABSORPTION-INTEGRATION-PLAN-2026-09-07.md), [운영 준비서](/home/jm/orca/projects/second-brain-app/OPERATIONAL-CUTOVER-PREP-2026-09-10.md)를 함께 읽는다. 이 문서의 정정은 과거 상태 설명에 우선한다. 새 사용자 지시와 저장소 규칙은 계속 우선한다.

- LightRAG, TencentDB-Agent-Memory, code-brain, memory-bank의 장점은 기존 코드와 대조해 필요한 부분만 흡수한다. 네 제품 동시 설치·별도 기억 DB·정본 교체를 시작하지 않는다.
- SB는 기억 provider, JARVIS는 실행·소비자, dev-wiki/Git은 개발 결정의 정본이라는 경계를 유지한다. JARVIS 코드 변경은 그 리포의 `AGENTS.md`와 현행 작업을 확인하고 기존 담당 작업과 중복되지 않게 조율한다.
- 기존 미추적 `2n`, `phone-history/`, `sb/compile.py.bak-20260906-214804`, `sb/llm.py.bak-20260906-214804`를 포함하거나 정리하지 않는다. `git add .` 대신 의도한 파일만 선택한다. 원격 push는 하지 않는다.
- 현재 문서 작성 요청은 운영 중단·전환·사용자 기록 삭제의 새 허가가 아니다. 반대로 문서에 “승인 대기”가 있다는 이유만으로 격리 개발과 검증까지 멈추지 않는다. 기존 세션에 해당 행위의 명시적 허가가 있으면 다시 묻지 않는다.

### 2. 실행 순서와 완료 기준

| 순서 | 우선순위 / 연결 요구 | 수행할 작업 | 완료 기준 |
|---|---|---|---|
| W0 | P0 / 공통 | 코드·후보·운영 스냅샷 정합성 고정 | 아래 세 기준을 구분한 manifest와 최신 지원표 |
| W1 | P0 / M6 | compiled marker 유실 상태의 업그레이드 복구 | 과거 페이지를 보존하면서 정정이 정상 반영되고 재시도도 중복 없음 |
| W2 | P0 / M3·M7 | 철회 뒤 설정 복원으로 권한이 부활하는 결함 해결 | 복원·재시작·기발급 claim·열린 연결에서 철회된 접근과 누출 0 |
| W3 | P0 / M1·M2·M4·M6 | 새 배포 후보와 JARVIS 의존성 준비 | 같은 고정 소스의 설치물로 표준/실제 업무/유지보수 인수 통과 |
| W4 | P0 / M1·M2·M4·M7 | 전환 창의 실제 사용자 종단 인수 | 실제 신원과 동일 업무 계보로 발행 1회·새 세션 회수·범위 거부 |
| W5 | P0 / M5·M8 | native 사본·삭제·재개 수명 | 지원 제품별 격리 실험과 사본 처분 또는 명시적 미지원 경계 |
| W6 | P1 / M9·M10 | 실제 본문 전달과 한글 검색 개선 | 전달 payload 근거 및 고정 평가셋 전후 수치, 철회·삭제 재공급 없음 |
| W7 | P1 / M11·M6 | 쓰기 지연·재시도·고아 journal 처리 | 실제 MCP 비용 개선, 중단 복구와 권한·내구성 회귀 유지 |
| W8 | P1 / M12·M13 | DR와 실제 GUI 실패 복구 | 복구된 저장소의 조회·삭제 억제와 브라우저 복구 증거 |
| W9 | P2 / M14 | 관계 검색의 추가 가치 평가 | 기준선 대비 유효성이 확인될 때만 제한 채택 |

W0 다음 W1–W3의 배포 준비를 우선한다. W4가 전환 창을 기다리는 동안 W2·W5–W8의 격리 작업을 계속한다. W9는 핵심 연동을 대신하는 선행 작업이 아니다.

### 3. W0 — 세 가지 기준과 상태 문서 고정

1. 시작 시 `git status --short`, HEAD, 제품·테스트 diff를 기록한다. 테스트 도중 다른 작업이 코드를 바꾸면 해당 결과의 기준을 다시 판정한다. 다른 사람의 변경을 되돌리지 않는다.
2. **검토 코드:** `0033c22`의 제품 코드, 문서 추가 HEAD `4173b2e`. **설치 기준 후보:** `c04dee1` / 소스 `4aa7111` / wheel `ac8fcd16…`. **운영 릴리스:** SB `41f0751…`, authority `a3cbbbe…`는 과거 관측값이므로 현재 링크를 읽어 갱신한다.
3. 이번 doctor 변경을 포함해 배포하려면 검증한 최종 소스로 새 후보를 만든다. 기존 `c04dee1`을 비교 기준으로 보존하고, 새 후보가 통과하기 전에는 전환 대상을 덮어쓰지 않는다. doctor를 제외하고 기존 후보를 택한다면 제외 사실과 후속 배포 항목을 명시한다.
4. authority 모듈 목록을 정렬된 상대 경로+SHA-256으로 저장한다. `*.js`와 memory 접두/부분 문자열 규칙을 각각 명시한다. 총 개수와 함께 필요한 CLI 진입점·정적 import·격리 실행을 확인한다.
5. `IMPLEMENTATION-STATUS.md`와 지원표에 실제 업무 본문/fixture 신원, 소스/설치/운영 검증, 모델 회수/자동 주입의 차이를 유지한다. 기록 시각 없는 PID·세대 ID·백업 시각을 현재값처럼 쓰지 않는다.

### 4. W1 — marker가 이미 없는 운영 상태에서 정정 복구

대조 대상: `sb/generation_staging.py::_copy_compiled_markers`, `sb/pipeline.py`, `sb/vault.py`, `tests/test_generation_runtime.py`, 기존 정정·각주 보고서.

- 격리 vault에 기존 컴파일 페이지와 ledger를 만들고 marker가 없는 상태를 재현한다. 단순히 복사 함수가 존재한다는 테스트로 끝내지 않는다.
- 후보에서 동일 기억의 정정을 수행해 최초 전이와 두 번째 전이를 관측한다. 기존 페이지·원문·출처 보존, 최신 정정 회수, 정당한 사용자 수동 편집 보호, marker 승계를 함께 검사한다.
- 복구 방법은 현재 ledger/페이지의 검증 가능한 근거에서 결정한다. 임의 SHA 작성, `_proposed` 일괄 이동·삭제, 사용자 편집 덮어쓰기로 통과시키지 않는다.
- 완료 산출물은 재현 입력·실제 CLI 결과·전후 페이지/marker digest·재시도 결과다. 이 증거가 있는 절차만 전환 런북의 첫 compile에 반영한다.

### 5. W2 — M3 철회·복원 결함 수정

대조 대상: `sb/scoped_read_policy.py`, `sb/config.py`, `tests/test_scoped_read_policy.py`, `tests/test_mcp_scoped.py`, JARVIS의 기존 issuer/정책/키 회전 경로와 [M3 초안](/home/jm/orca/projects/second-brain-app/M3-RESTORE-DESIGN-2026-09-10.md).

- 먼저 회귀를 만든다: claim 발급 → 키 철회 → 같은 claim 거부 → 철회 이전 설정 복원 → 같은 claim 재조회. 현재의 정책 객체 복귀 단정만으로 실제 데이터 접근 시험을 대신하지 않는다.
- 복원 시 유지되는 기존 정책 정본·키 회전·철회 병합 경로가 있는지 코드로 확인한다. 이전 설정과 함께 롤백되는 revision만 추가해 해결했다고 하지 않는다.
- 기존 경계에서 해결 가능하면 그 경로를 구현한다. 새 정본이나 계약 변경이 필요한 경우 코드 전에 dev-wiki 규칙에 맞는 ADR에 소유자·재시작·백업 복원·실수 철회 복구를 구체화한다. ADR 작성 자체를 운영 실행 승인으로 취급하지 않는다.
- 완료 조건: 같은 프로세스/새 프로세스, 열린 MCP 연결, 기발급 claim, 올바른 새 키, 파손·누락 설정, 과거 설정 복원을 함께 검사한다. 철회된 접근은 제목·snippet·score·원문까지 노출 0이고 정상 권한은 유지돼야 한다.

### 6. W3·W4 — 후보 준비와 실제 운영 종단 연결

**전환 전에 실행할 준비:**

1. 변경한 코드의 관련 회귀를 통과시킨 뒤 최종 소스를 고정하고 전체 회귀를 한 번 수행한다. 새 코드 변경·실패·미해결 우려가 없으면 전체 회귀를 반복하지 않는다.
2. 명시적인 새 `/var/tmp` app root에 후보를 만든다. SB 소스/테스트/harness commit, wheel/requirements/runtime/recipe digest를 기록한다. 개발 소스가 설치물 import를 대신하지 않는지 검사한다.
3. JARVIS 측에서 고정한 source와 lockfile에 맞는 새 dependency artifact를 준비한다. 운영 control-center에 다른 버전 dist를 섞지 않는다. 기존 `/var/tmp` 페어 빌드는 receipt를 검증한 경우에만 비교 기준으로 사용한다.
4. 같은 후보로 표준 paired gate, `--work` gate, 유지보수 gate를 수행한다. `REAL-WORK-ITEM-2026-09-10.json`은 이전 후보 검증이라는 실제 업무 내용이므로 본문의 옛 해시를 새 실행 후보 해시로 몰래 바꾸지 않는다. 새 업무를 쓰면 근거를 먼저 검증한다.
5. 전환 직전 실행 명령, 서비스 집합, writer/lease 배제, 새 artifact 경로, 설정 변경, 백업, 실패 시 복귀 조건을 한 런북에 작성한다. 새 쓰기 이후의 rollback은 바이너리 링크 복원만으로 충분한지 스키마·세대 호환성을 격리에서 검증한다.

**전환 창에서만 수행할 항목:**

- 기존 허가 여부를 먼저 확인하고, 없으면 준비된 런북을 대상으로 중단/전환 판단을 받는다. 해당 판단 전에 의존성 준비·격리 검증·복구 문안을 끝낸다.
- 큐 0과 writer 배제를 구분한다. 정지 후 실제 DB/WAL/SHM 핸들과 SB lock을 다시 확인하고 현재 유효 lease를 처리한다. 오래된 PID를 재사용하지 않는다.
- 실제 principal/agent/session으로 조회 → 검증 결과 → candidate → outbox → provider record → proved → settlement/completed를 같은 업무 ID로 연결한다. 재전송에 완료/발행 1회, 실패·미확정 결과는 성공 기억으로 승격되지 않아야 한다.
- 서로 다른 실제 에이전트의 새 세션에서 동일 record의 출처·버전을 회수한다. 불허 프로젝트/종료 세션/철회된 claim의 내용 노출은 0이어야 한다. 정정·삭제 시험의 대상과 사본 처리 범위는 W5에 따라 구체화한다.
- activation 성공, 서비스 active, fixture gate 성공만으로 M1–M7을 일괄 완료하지 않는다.

### 7. W5 — 제품별 native 사본 수명

대조 대상: `tests/test_managed_copy_disposal.py`, 기존 삭제/restore 계약, [M5 초안](/home/jm/orca/projects/second-brain-app/M5-COPY-POLICY-2026-09-10.md), 에이전트 지원표.

- 실제 바이너리의 지원 옵션으로 격리 프로필/클라이언트 저장 경로를 지정한다. 일반 사용자 홈이나 `CODEX_HOME`을 실험용 변수로 덮어쓰거나 운영 인증 자료를 통째로 복사하지 않는다.
- 제품·버전·실행 모드·수집/쓰기/조회/주입 여부를 고정한다. 기억 저장 → 다른 새 세션 회수 → 정정 → provider 삭제 → 재개/compaction/재색인/백업 복원을 테스트한다.
- 기억 원문만 찾지 말고 도구 응답, 세션 로그, 요약, SQLite/WAL, export/backup 사본을 각 형식에 맞게 조사한다. 검색 0건은 조사 경로에서 미검출이라는 뜻이다.
- SB 관리 사본과 클라이언트 소유 사본을 구분해 처분 경로를 검증한다. 클라이언트 기능으로 삭제 수명을 보장할 수 없으면 해당 조합을 미지원/제한으로 명시하고 M5 미충족을 유지한다. 사용자 요구를 조용히 줄이지 않는다.
- 완료 증거에는 사본별 전후 digest, 실제 사용한 클라이언트 명령, 재개 시 도구 호출 여부, 삭제 후 반환 내용 여부를 포함한다. 현재의 합성 `session.jsonl` 보존 테스트는 native 인수를 대신하지 않는다.

### 8. W6 — 문맥 전달과 한글 회수 품질 개선

JARVIS 대상: `src/context-assembler*.ts`, `src/second-brain-adapter*.ts`, 실제 모델 요청 조립 경계. SB 대상: `sb/search.py`, `sb/hybrid_search.py`, `scripts/korean_search_evaluation.py`, 한글 fixture와 scoped 검색 회귀.

- 기존 `context-boundary-audit.mjs`는 공백 재현용으로 보존한다. 구현 후 별도의 전달 인수에서 허용된 본문·출처·버전이 실제 모델 요청 payload에 포함되는지 확인한다. snapshot ID만 남긴 것을 전달 완료로 취급하지 않는다.
- 여러 줄 본문을 식별자 필드에 넣지 않는다. provider의 `untrusted`를 실행 성공/검증 완료로 자동 승격하지 않고, 기록된 자료로 구분해 사용한다. 기억 조회에 가짜 live observation을 채우지 않는다.
- 최종 payload의 토큰/바이트 예산과 잘림 기준을 정하고 출처를 보존한다. 새 session/compaction 뒤 필요한 기억을 다시 선택하며 만료·철회·삭제 record는 재공급하지 않는다.
- 한글 검색은 현재 정확 일치·정정·no_answer 기준선을 보존하면서 붙여쓰기/자연어/의역 실패를 분류해 구현한다. 특정 질문 문자열을 하드코딩하거나 정답 페이지를 미리 선택하지 않는다.
- synthetic 18문 결과와 기존 평가셋, 별도의 미사용 검증 질문에서 전후 Recall@5/MRR/no_answer/오래된 결정 노출/지연을 비교한다. 사용자 질문 100–300문은 허용된 자료와 근거를 확보해 별도 `user_curated`로 관리한다. 초안 18문을 이름만 바꾸지 않는다.
- hybrid/관계 검색은 필요할 때만 평가하며 기존 기본 비활성 정책과 범위 검사·삭제 억제를 유지한다. 품질 개선 완료는 실제 전후 수치로 판정한다.

### 9. W7 — 쓰기 지연·재시도·고아 저널

대조 대상: `sb/generations.py::_fsync_tree`, `sb/generation_runtime.py`, `sb/inbox.py`, `sb/ops.py`, `tests/test_activated_orphan_rows.py`, `tests/test_inbox_ack_recovery.py`, 세대·중단 회귀.

- 현재 21.36s/15.35s는 단일 격리 표본이다. 작은/중간/운영 규모의 고정 corpus에서 warm/cold 조건과 반복 수를 기록하고 실제 MCP의 p50/p95·최대값·RSS·각 단계 시간을 측정한다. 중첩된 cProfile 누적 시간을 합산하지 않는다.
- 내구성 보장에 필요한 fsync를 통째로 제거하지 않는다. 변경되지 않은 파일의 반복 작업 축소 등 기존 세대 구조에서 가능한 최적화를 검토하고, 새 저장 구조가 필요하면 ADR을 먼저 작성한다. reflink/hardlink는 지원 환경·쓰기 격리 증거 없이 채택하지 않는다.
- 완료 후 응답 유실/클라이언트 timeout/같은 요청 재전송을 재현한다. 기존 영수증·요청 ID로 결과를 확인할 수 있는지 연결하고, 새 idempotency 계약이 필요하면 명시적으로 설계한다. 바이트 dedup을 요청 1회 실행 보장과 혼동하지 않는다.
- 고아 행은 현행 경고를 유지한다. 자동 정리를 추가하려면 current 여부·세대 존재·reader/요청 참조·disposal 근거를 구분한다. 디렉터리가 없다는 이유만으로 `proved`를 쓰지 않는다. 근거가 부족한 행은 미해결 상태로 남기고 비파괴 보고를 유지한다.
- 개선 완료 조건: 측정된 클라이언트 timeout보다 충분히 낮은 지연 목표를 명시하고 전후 결과로 입증한다. 동시에 단일 작성자, 원문 보존, 세대 봉인, 중단 재시작, 반복 maintenance, 권한 불변 회귀를 통과해야 한다.

### 10. W8·W9 — DR·GUI·관계 검색

- DR: archive 검증 → 신뢰된 세대/원장 근거 결합 → 복원 → 검색 재구축 → 허용 조회/불허 거부 → 삭제 high-water 유지 → 새 쓰기까지 격리에서 수행한다. journal 소실을 안전하게 거부하는 것과 복구 성공을 구분한다. 복구 근거가 없으면 자동 anchor 생성을 추가하지 않는다.
- 실제 RPO는 SB와 JARVIS 각각의 마지막 검증 백업·스케줄·실패 이력으로 산정한다. RTO는 압축 해제뿐 아니라 검증·재결합·서비스 준비까지 측정한다. 운영 timer 복구가 필요하면 원인과 변경 문안을 먼저 구체화한다.
- GUI: `run_all` 대역 없이 실제 pipeline을 실행하는 격리 서버에서 실패 생성 → 실패 원인 표시 → 입력 복구 → 재실행 → 성공을 실제 브라우저로 확인한다. 과거 실패 23행이 임의로 성공 처리되지 않는지, 다른 기존 기억이 보존되는지도 검사한다.
- 관계 검색은 W6의 기준선 이후 고정 질문에서 추가 근거 회수와 비용을 비교한다. 이점이 없으면 채택 보류와 수치를 남긴다. 그래프 구축 자체를 M14 완료라고 하지 않는다.

### 11. 검증 명령과 산출물

다음은 후속 실행 명령이다. 이 문서에 적혔다는 이유로 실행 완료로 집계하지 않는다.

```bash
cd /home/jm/orca/projects/second-brain-app
git status --short
git rev-parse HEAD
TMPDIR=/var/tmp uv run pytest -q tests/test_activated_orphan_rows.py tests/test_managed_copy_disposal.py tests/test_web.py tests/test_korean_search_hard_draft.py tests/test_ops.py tests/test_korean_search_evaluation.py
uv run ruff check --no-cache sb tests
uv run basedpyright sb/ops.py sb/pipeline.py sb/connectors/sessions_opencode.py
git diff --check
```

추가 구현 후에는 그 변경을 검증하는 회귀를 함께 실행한다. 최종 제품 코드를 고정한 뒤 전체 검사:

```bash
TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py
```

embeddings/hybrid를 실제 변경했다면 필요한 optional extra와 모델을 갖춘 별도 환경에서 해당 테스트도 실행하고 환경·결과를 따로 기록한다. 기본 검사에서 제외했다는 사실을 숨기지 않는다.

후보 생성은 **배포할 변경을 커밋한 뒤** 실행한다. 아래 대문자 경로는 placeholder이므로 실제 고유 절대 경로로 바꾼다. 운영 app root 기본값을 사용하지 않는다.

```bash
TMPDIR=/var/tmp python deploy/prepare-release.py /var/tmp/SB_UNIQUE_CANDIDATE_ROOT --offline
TMPDIR=/var/tmp python deploy/check-release-integration.py /ABSOLUTE/RELEASE_PATH /ABSOLUTE/VERIFIED_JARVIS_DIST
TMPDIR=/var/tmp python deploy/check-release-integration.py /ABSOLUTE/RELEASE_PATH /ABSOLUTE/VERIFIED_JARVIS_DIST --work /home/jm/orca/projects/second-brain-app/REAL-WORK-ITEM-2026-09-10.json
TMPDIR=/var/tmp python deploy/check-release-maintenance.py /ABSOLUTE/RELEASE_PATH
```

오프라인 의존성이 없으면 부족한 artifact를 특정해 준비한다. 실패한 빌드를 설치 성공으로 처리하거나 운영 의존성 디렉터리를 덮어쓰지 않는다. 준비 스크립트가 committed HEAD만 사용하는 점을 유지한다.

작업 묶음마다 다음을 보고한다:

1. W/M 항목, 시작/종료 커밋, 실제 변경 파일, 해결한 결함과 남은 조건.
2. 명령·환경·시간·exit code·원본 로그·JSON 경로. 테스트 수는 중복 합산하지 않는다.
3. 소스/harness/설치물/운영 중 무엇을 검증했는지와 실제 모델/fixture 여부.
4. 원문·기억·세대·영수증의 연결 및 변경 전후 digest. 비밀키·토큰·불필요한 사용자 원문은 보고서에 넣지 않는다.
5. 운영 변경 유무, 실패 시 보존된 상태, 다음 작업과 구체적인 의존 조건.

최종 보고는 **완료 / 구현됐으나 운영 미검증 / 미구현 / 명시적 제한 또는 결정 필요**를 구분한다. M1–M14 전체가 끝나지 않았다면 “메인 기억 저장소 완성”이라고 쓰지 않는다.
