# Grok 통합 구현 인계 — Codex는 최종 후보 독립 검증 담당

## 1. 사용자 결정과 역할

사용자는 개별 수정 → Codex 재검토 → 개별 수정의 반복을 끝내고, **Grok이 통합 구현·자체 검증·후보 준비를 맡고 Codex가 최종 검증을 맡는 방식**을 요청했다. 이 문서는 그 실행 기준이다.

- **Grok:** 전체 코드 경로 분석, 설계/ADR, 구현, 회귀 추가, 격리 통합·설치·실제 클라이언트 검증, 증거 정리와 최종 제출을 책임진다. 개별 수정 커밋마다 Codex의 허락이나 재검토를 기다리지 않는다.
- **Codex:** 이 인계 이후 제품 코드를 병행 수정하지 않는다. Grok이 제출한 고정 소스와 설치 후보를 독립 검증하고, 판정을 통과/미충족 항목으로 한 번에 정리한다. 제출 후보 변경 시 영향 범위를 기준으로 재검증한다. 결함이 남으면 검증을 생략하거나 완료로 승인하지 않는다.
- **사용자:** 실제 운영 중단/전환·사용자 데이터 처분 등에 아직 없는 허가와 필요한 인증/업무 입력을 제공한다. 그 판단은 준비된 절차·대상·복구안을 대상으로 한다. 이미 허가된 행위는 다시 묻지 않는다.

최종 목표는 **세컨드브레인을 JARVIS와 여러 에이전트의 공통 기억 저장소로 완성하는 것**이다. 아래 두 가지 현재 결함만 고치는 것으로 범위를 줄이지 않는다. 제품 준비 완료와 실제 운영 완료는 구분한다.

## 2. 작업공간과 시작 자료

제품 작업공간: `/home/jm/orca/projects/second-brain-app`. 현재 구현 기준 `6fb150b9261f209202931a0d997cb1c75c6c1cd7`, 브랜치 `codex/shared-memory-completion-20260907`. Orca 터미널의 컨텍스트가 `/home/jm/orca/workspaces/second-brain-app`로 보여도 제품 경로를 혼동하지 않는다. 시작 시 실제 HEAD와 상태를 재확인한다.

현재 미커밋 자료는 Codex의 추가 검토와 재현 증거다. 읽고 인계에 포함하되 이전 실패 증거를 새 성공 결과로 덮어쓰지 않는다:

- `CODEX-6FB150B-RECHECK-2026-09-11.md` / `.json`
- `scripts/w0-w9-review-probe.py`의 관리형 compile·Unicode 사례 확장
- `IMPLEMENTATION-STATUS.md` 상단의 최신 검토 링크
- 이 통합 인계서 및 전달 기록

기준 문서는 다음 순서로 읽는다. 서로 충돌하는 상태 설명에는 최신 검토를 적용하고 원래 완료 요구는 유지한다.

1. 이 문서와 `CODEX-6FB150B-RECHECK-2026-09-11.md`.
2. `CODEX-W0-W9-REVIEW-2026-09-11.md`, `CODEX-W0-W9-REPLY-2026-09-10.md`.
3. `CODEX-FOLLOWUP-REVIEW-2026-09-10.md`의 W0–W9 상세 지시와 `CURSOR-HANDOFF-2026-09-10.md`의 M1–M14.
4. `OSS-ABSORPTION-INTEGRATION-PLAN-2026-09-07.md`, JARVIS의 `/home/jm/orca/projects/Orca-JARVIS/docs/second-brain-oss-absorption-handoff-2026-09-07.md`.
5. 리포 `AGENTS.md`, `../dev-wiki/README.md` 및 관련 ADR. JARVIS 수정은 해당 리포 규칙과 현재 담당 작업을 확인한다.

보존 대상: `2n`, `phone-history/`, `sb/compile.py.bak-20260906-214804`, `sb/llm.py.bak-20260906-214804`. 이 자료를 커밋·삭제·정리하지 않는다. 의도한 파일만 선택해 커밋하고 원격 push는 하지 않는다.

## 3. 현재 사실 — 재해석하거나 재시작하지 말 것

| 항목 | 확인된 상태 |
|---|---|
| 6fb150b 관련 회귀 | Codex가 97 passed / 18.42s, Ruff 통과 확인. 전체 회귀 결과 아님 |
| 기존 직접 Vault 손편집 사례 | 보존 성공. 하지만 아래 관리형 compile에서는 유실 |
| W2 동시 철회·정적 symlink | 스레드/독립 프로세스 두 키 보존, symlink 정책 거부 확인. 전체 M3 수명 완료 아님 |
| 기존 W6 3사례 | newline/ASCII case/짧은 한글 일치. Unicode 전체 일치 아님 |
| 새 운영 후보 | 아직 없음. `0eefce7`에는 6fb150b의 수정이 포함되지 않음 |
| 이전 후보 | `0eefce70378a2b0051ee0d8c159a542d1fd9f554`, wheel `dc705e8a058565fc6f98cc8d3a6ca9a62c47119b1ad8c51f9bdc7f2c6bbbb3dd`, 비교 자료로 보존 |
| 운영 기준 | SB `41f0751…`, JARVIS authority `a3cbbbe…`는 마지막 관측값. 현재값은 전환 직전에 확인 |
| JARVIS 격리 페어 | 소스 `195b1a7`의 기존 dist. 새 운영 dependency artifact를 대신하지 않음 |
| 삭제/철회·native 사본 | 일부 격리 검증 존재. rollback·복원·클라이언트 재개 전체 인수는 남음 |

LightRAG, TencentDB-Agent-Memory, code-brain, memory-bank의 장점만 선별 흡수한다. 세컨드브레인 교체, 네 제품 동시 설치, 에이전트별 별도 기억 DB, 근거 없는 전역 Proxy/queue/authority 도입으로 방향을 바꾸지 않는다.

## 4. 반복을 막는 구현 방식

1. **수정 전에 전체 호출 경로와 불변조건을 고정한다.** 함수 단독 성공 대신 원본 → staging → 작성/정책/검색 → 봉인 → 재시작/회수까지 추적한다. 아래 인수표를 구현 체크리스트로 사용한다.
2. **원인의 종류를 제거한다.** 보고된 문자열·공백 몇 개를 하드코딩하거나 특정 fixture만 맞추지 않는다. 예시는 실패한 계약의 증거다.
3. **긍정·부정·복구 경로를 함께 검사한다.** 모두 거부되면 권한 검사가 완성된 것이 아니다. 원본을 전부 제안으로 돌리면 정정 복구가 완성된 것도 아니다.
4. **자체 검증에서 발견한 문제를 스스로 통합 해결한다.** 다른 경로에서 같은 불변조건이 깨지는지 조사하고 최종 제출 전에 수정한다. 중간 커밋·문서 추가를 인수 완료로 올리지 않는다.
5. **중간 진행은 저장소에 기록한다.** 사용자의 상태 질문에는 응답하되 Codex 검토를 매번 작업 의존성으로 만들지 않는다. 진짜 외부 입력이 필요하면 구체적으로 요청하면서 독립 작업을 계속한다.

## 5. 필수 통합 인수표

### A. 원본·사용자 편집·정정 보존 — W1, M2/M4/M6

현재 남은 원인: `GenerationMutationService`가 원본을 staging으로 복사한 뒤 `init_vault`로 초기 커밋을 만든다. 따라서 `_committed_bytes_match`가 보는 staging HEAD에는 손편집도 포함된다. 마지막 컴파일 근거가 아니다.

**실제 해결 기준:** staging 생성 이전의 신뢰 가능한 마지막 컴파일 근거와 원본 상태가 올바르게 연결되어야 한다. frontmatter 존재나 staging HEAD 일치만으로 덮어쓰기를 허용하지 않는다. 마지막 컴파일 근거를 복구할 수 없는 페이지는 보존한다. 근거가 있는 무수정 페이지는 정상 정정이 가능해야 한다.

인수 조합:

- legacy 최초 전이와 managed 후속 전이.
- marker 존재/부재/유효하지 않은 값, 원문/CAS·기존 세대 근거 부재.
- 무수정 compiled 페이지, 미커밋 수동 편집, 커밋된 수동 편집, 사람 작성 페이지.
- 직접 Vault API, 실제 `run_compile`, 별도 CLI 프로세스.
- 정상 정정, 같은 요청 반복, 쓰기 중단 후 재시작, marker 승계.

필수 증거: `USER_EDIT_KEEP_THIS`가 관리형 compile 후에도 보존됨. 동시에 근거가 있는 무수정 페이지의 정정이 최신 조회에 나타남. `_proposed`를 일괄 승격/삭제하거나 임의 hash를 심어 통과시키지 않는다.

### B. 철회 정본·권한·복원 — W2/W4, M1/M3/M5/M7

현재 flock/고유 tmp/정적 symlink 거부 개선은 유지한다. 새 `revoked-jarvis-signing-key-ids` 파일의 **정본·초기화·유실·복구 계약**을 완성한다. 관련 ADR이 필요하면 구현 전에 구체화한다.

인수 조합:

- 두 개 이상 독립 프로세스의 서로 다른/중복 철회, read/merge/publish 중단, 재시작 후 집합 보존.
- 최초 초기화와 기존 store의 유실·파손·권한 오류·잘못된 파일 형식·symlink를 구분. 파일 검사와 열기 사이의 경합도 검토.
- 철회 직후 조회, 조회 없이 설정 복원, 기발급 claim, 열린 세션, 새 프로세스, 과거 config 및 백업 복원.
- 철회된 키는 거부, 새 유효 키의 fresh claim/fence는 정상 읽기·쓰기. 다른 principal/project/session은 거부.
- read/remember/request executor/cancellation 등 서명 키를 소비하는 기존 표면을 대조해 적용 범위를 명시. 일부 경로만 durable store를 읽는 상태를 공통 권한 완성으로 표시하지 않음.
- `tests/restore_scoped_mcp.py`의 옛 키 거부를 유지하면서, 새 키로 **복원 뒤 fresh stdio 서버 두 개에서 정상 회수**하는 긍정 경로를 복구.

구버전 `41f0751`에는 이 store를 읽는 경로와 `sb.scoped_read_policy` 자체가 없다. 새 파일을 남기는 것만으로 rollback 안전성을 주장하지 않는다. 새 후보가 만든 실제 세대·원장·철회 상태로 격리 왕복 검증하고, 불가능하면 자동 rollback 조건을 제거하고 검증된 복구 절차를 명시한다.

### C. 하나의 검색 계약·품질·실제 본문 전달 — W6, M7/M9/M10

SQL의 일부 공백 제거+`lower()`와 Python의 전체 `isspace()`+`casefold()`는 다르다. 공통 정규화 계약을 선택하고 mutable index·sealed index·scoped record 경로에 동일하게 적용한다. 읽기 전용 봉인 보장과 쿼리 제한을 유지한다.

인수 조합:

- ASCII space/tab/LF/CRLF/form-feed/vertical-tab, NBSP(U+00A0), 전각 공백(U+3000), Unicode `isspace()`의 나머지 범주.
- ASCII 대소문자, `Straße`/`STRASSE` 같은 Unicode casefold, 긴/짧은 한글, 영문/숫자 혼합, 따옴표 구문, 다중 term, 빈/과대/잘못된 질의.
- 실제 SQL 결과와 record 결과의 동등성, CLI/MCP/웹/scoped 표면의 지원 범위, 제목·snippet·score·원문 누출 0.
- FTS 제외로 순위가 사라지는 변화와 normalization의 비용을 측정. 특정 18문에서 Recall 상승만으로 전체 품질을 승인하지 않음.
- 고정 synthetic 기준선과 미사용 검증 질문, 실제 사용자 질문 100–300개를 구분. `user_curated` 근거 없는 이름 변경 금지. 정정/옛 결정/no_answer/의역/자연어와 지연을 비교.

JARVIS `context-assembler*`부터 **실제 모델 요청 payload**까지 연결한다. 본문·출처·버전·예산을 확인하고, provider의 untrusted 기억을 검증된 실행 결과로 승격하지 않는다. 새 세션/compaction 후 필요한 기억을 재선택하되 철회·만료·삭제된 기억은 재공급하지 않는다. 기존 snapshot 공백 probe의 exit 0은 완료가 아니다.

### D. 실제 공유 기억의 수명 — W4/W5, M1/M2/M4/M5/M8

동일 실제 업무에서 조회 → 검증 결과 → candidate → outbox → provider record → proved → settlement/completed → 다른 제품 새 세션 회수까지 하나의 계보로 묶는다. 실패·미확정·변조 결과가 성공 경험으로 저장되지 않아야 한다. 재전송에도 발행/완료는 1회다.

제품별 버전·프로필·수집·쓰기·조회·자동 주입·보존 사본을 명시한다. 허용된 격리 프로필에서 native 저장/회수/정정/provider 삭제/재개/compaction/재색인/백업 복원을 확인한다. 빈 인증 프로필의 미실행을 제품의 미지원 판정으로 바꾸지 않는다. 실제 필요한 인증 입력이 없으면 무엇이 필요한지 구체적으로 요청한다.

운영 `~/.claude`/`~/.codex`를 실험장으로 삼지 않는다. SB 관리 사본과 클라이언트 소유 사본의 처분 방법·한계를 분리하고, 한계가 남으면 전체 M5 미완료를 유지한다. 운영 기억 삭제 대상은 허가와 사본 처리 범위를 구체화한 뒤 수행한다.

### E. 가용성·복구·GUI — W7/W8, M6/M11/M12/M13

- 작은/중간/운영 규모 고정 corpus, 실제 MCP에서 p50/p95/최대 지연·RSS·단계 시간을 측정한다. 쓰기 약 21초를 timeout 목표 달성으로 쓰지 않는다. 클라이언트 timeout 기준과 여유를 수치로 정한다.
- 완료 후 응답 유실, 재시도, 동시 읽기/정정/갱신, 원문 보존과 idempotency를 기존 영수증·요청 ID로 검증한다. fsync를 일괄 제거해 숫자만 낮추지 않는다.
- 고아 journal은 참조·reader·disposal 근거로 다룬다. 디렉터리 부재만으로 proved로 바꾸거나 운영 3행을 수동 UPDATE하지 않는다.
- DR는 archive 무결성 → 신뢰된 원장/세대 결합 → 복원 → 조회·범위 거부·삭제 high-water → 새 쓰기까지 검사한다. archive extract 시간은 전체 RTO가 아니다. SB/JARVIS 백업의 실제 RPO를 따로 산정한다.
- GUI는 `run_all` 대역 없이 격리 실제 서버/브라우저에서 실패 생성 → 원인 표시 → 입력 복구 → 재실행 성공을 확인한다. 과거 실패를 임의 삭제/성공 처리하지 않는다.

### F. 배포 재료와 운영 절차 — W0/W3/W4, M6

- SB의 최종 제품 소스·테스트·harness를 고정한 뒤 새 후보를 만든다. `0eefce7`·`14a6ed7`·`c04dee1`을 새 후보 이름으로 재사용하지 않는다.
- JARVIS source/lockfile에 맞는 새 dependency artifact를 준비한다. 기존 `195b1a7` 페어 dist나 운영 CC 의존성 혼합으로 대신하지 않는다. JARVIS 담당 작업과 변경 소유권을 조율하고 미해결 의존성을 남기지 않는다.
- 같은 최종 조합에서 전체 회귀, 표준 paired, `--work`, 유지보수, cold start/새 stdio, 실제 제품별 지원 인수를 수행한다. 변경된 소스와 다른 wheel의 성공을 합산하지 않는다.
- 전환/복구 런북은 정확한 명령·서비스·경로·writer/lease 배제·설정·백업 hash·성공/실패 조건을 포함한다. 큐 0과 writer 배제를 구분한다. 전환 직전 스냅샷은 새로 읽는다.
- 필요한 운영 허가가 없으면 실제 중단·전환은 남겨두되, 위 준비와 격리 호환성 검증을 전부 끝낸 상태에서 판단을 요청한다. 실사용자 종단 검증이 없으면 제품 후보 준비 완료까지만 선언한다.

M14 관계 검색은 핵심 인수를 대신하지 않는다. 기준선 대비 추가 가치·비용·삭제 일관성을 측정하고, 효과가 없으면 보류 이유를 명시한다.

## 6. 제출 전 자체 검증 규칙

변경별 의미 있는 회귀를 먼저 추가하고 실행한다. 테스트는 실제 계약을 검증해야 하며, 기존 실패를 테스트 삭제/전체 거부로 바꾸어 통과시키지 않는다. deterministic 테스트에 sleep을 넣지 않는다.

최종 코드가 고정되면 다음을 실행한다. 코드가 바뀌면 영향 있는 회귀를 다시 확인한다. 전체 검사를 불필요하게 반복하지 않는다.

```bash
cd /home/jm/orca/projects/second-brain-app
TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py
uv run ruff check --no-cache sb tests
git diff --check
```

변경한 모듈의 타입 검사를 포함하고, embeddings/hybrid를 바꿨으면 optional 환경도 검증한다. 프로브 출력은 회귀 테스트와 인수 증거를 보조하며 그 exit 0만으로 완료 처리하지 않는다.

배포할 코드는 커밋한 후 명시적 `/var/tmp` app root로 `deploy/prepare-release.py --offline`을 실행한다. 설치물로 `deploy/check-release-integration.py`의 표준/`--work`, `deploy/check-release-maintenance.py`를 통과시킨다. 실제 인자는 확인한 절대 경로를 사용하고 운영 app root 기본값은 사용하지 않는다.

## 7. 최종 제출물 — 이것이 갖춰진 뒤 Codex에 검증 요청

`GROK-FINAL-ACCEPTANCE-PACKAGE.md`와 `GROK-FINAL-ACCEPTANCE-PACKAGE.json`을 작성한다. 이것이 중간 회신서 여러 개를 대신하는 단일 진입점이다.

필수 내용:

1. **정확한 버전:** source commit/tree, test/harness commit, SB release ID/wheel SHA-256, Python/runtime/requirements/recipe, JARVIS source/build/dependency artifact와 digest.
2. **요구별 상태:** 위 A–F 및 M1–M14에 `verified`, `implemented_unverified`, `blocked_external`, `not_implemented` 중 하나와 증거 링크. 차단 사유는 필요한 외부 입력과 준비 완료 범위를 적는다.
3. **테스트 증거:** 명령·환경·exit code·시간·원본 로그·기계 판독 JSON. fixture/native, source/installed/operational을 구분하고 중복 합산하지 않는다.
4. **핵심 수명 증거:** 관리형 편집 보호/정상 정정, 철회/새 키/복원/rollback, 검색 경로 동등성, 업무 계보/재전송, native 사본/compaction, 성능/DR/브라우저.
5. **재현 명령:** 새 세션에서 같은 후보를 검증할 수 있는 명령과 자료 경로. 원문/비밀정보는 필요한 최소 범위만 남긴다.
6. **운영 상태:** 전환 유무, 실제 신원 종단 유무, 보류 항목, 구체적인 전환/복구 런북. 미전환을 운영 완료로 표현하지 않는다.

파일을 만드는 것만으로 제출 자격이 생기지 않는다. 자체 검증에서 실패한 핵심 항목은 해결하거나 진짜 외부 입력 조건을 명시한다. 정상/부정/복구 경로가 준비되지 않은 채 “Grok은 완료, Codex가 나머지 테스트”로 넘기지 않는다.

## 8. Codex 최종 검증 범위

Grok이 제출하면 Codex는 고정 후보에 대해 다음을 수행한다:

- 제출 manifest와 실제 파일/commit/hash 대조.
- 기존 실패 사례뿐 아니라 A–F의 독립 경계 사례로 불변조건 검사.
- source 회귀와 installed/paired gate를 제출 버전 기준으로 재현.
- 자료·권한 보존, 새 키의 정상 회수, 실제 모델 전달/공유 기억, 성능·복구 증거 검토.
- 한 보고서에 통과 항목과 미충족 항목·재현·영향 범위를 함께 정리.

제품 후보 인수와 운영 인수는 별도 판정한다. 운영 허가/인증 같은 외부 조건이 남아 제품 후보만 인수한 경우 전체 메인 기억 저장소 완료로 선언하지 않는다. 반대로 외부 조건을 이유로 실행 가능한 구현/격리 검증을 생략하는 것도 허용하지 않는다.

**이번 인계 이후 Grok이 구현 책임을 갖고 끝까지 진행한다. Codex는 중간 패치의 반복 검토자가 아니라 최종 후보의 독립 검증자다.**
