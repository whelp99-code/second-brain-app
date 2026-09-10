# Codex 회신서 — Cursor 인계 수행 결과와 남은 결정

작성일: 2026-09-10, Asia/Seoul. 대상: [Cursor 인계 지시서](CURSOR-HANDOFF-2026-09-10.md)를 쓴 Codex 세션.

인계서의 8-A(전체 검증 갱신), 8-B(설치 후보 paired 인수), 8-C(실제 업무·에이전트 간 기억 공유 인수)를 수행했다. **개발 완료나 운영 배포 선언이 아니다.** 승인 없이 도달 가능한 끝까지 진행했고, 남은 항목은 전부 사용자 결정이라 목표를 blocked로 두었다.

## 1. 시작·종료 지점

- 작업공간 `/home/jm/orca/projects/second-brain-app`, 브랜치 `codex/shared-memory-completion-20260907` — 인계서 그대로다.
- 시작 HEAD `d4cbdda`(인계 문서 커밋), 종료 HEAD **`9d08398`**. 커밋 16개.
- 원격 push 없음. 운영 `current`·운영 DB·운영 서비스 전환 없음. 인계서가 지정한 미추적 자료 4개(`2n`, `phone-history/`, `sb/*.bak-20260906-214804`)는 그대로 두었다.

```
9d08398 docs: record that key revocation does not survive a config restore
8c3e082 test: show a resumed client session returns the memory from its local copy
be5c888 docs: inventory the native client copies M5 has to dispose of
3d2d362 test: hold sb_search to the same scope no-leak bar as sb_read_page
832bc6b docs: re-verify the deletion lifecycle at the current HEAD
d1d06e2 test: prove a failed or unevidenced result cannot become a success memory
4068a37 test: reproduce the write-cost and interrupt defects, correcting one attribution
a951e40 docs: record the JARVIS lineage acceptance carrying real work content
4aa7111 fix: stop the readback reporting fixture content limits for a real work item
daed44b fix: let the context readback query follow the work item it verified
21e45cf feat: carry a real verified work item through the JARVIS memory lineage
8d53c90 docs: confirm the proposed-diversion defect is already fixed in the candidate
4db866f docs: record correction sharing and three operational defects
110b474 fix: dedupe footnote definitions annotated with a comma before span
7c14cdb docs: record real work memory shared across two agent products
1c203ed docs: refresh full regression and paired installed acceptance at d4cbdda
```

## 2. 8-A 전체 검증 — 갱신 완료

| 시점 | 결과 |
|---|---|
| `d4cbdda` | 1,785 passed / 2 skipped / 569.06초 / exit 0 |
| `110b474`(각주 수정 후) | 1,793 passed / 2 skipped / 593.22초 / exit 0 |
| **현재 트리**(`3d2d362` 이후) | **1,793 passed / 2 skipped / 503.77초 / exit 0** |

`ruff check --no-cache sb tests` exit 0, `basedpyright sb/pipeline.py sb/connectors/sessions_opencode.py` 0 errors 0 warnings. `tests/test_embeddings.py`는 지침대로 제외.

**인계서의 "13cab77 기준 1,767 passed"는 이제 최신이 아니다.** 과거 보고서에 그대로 보존했고 IMPLEMENTATION-STATUS 진입점만 갱신했다.

## 3. 8-B 설치 후보 — 두 번 갱신

| 후보 | 소스 | wheel SHA-256 | 결과 |
|---|---|---|---|
| `25d49b4367945c8fa01ea71f2d83932d8da934d8` | `d4cbdda` | `aa6fad5f…86dcf` | 연동·유지보수 exit 0 |
| `c04dee1a11ff0833b634c30796924d1ea19f8a6a` | `4aa7111` | **동일** | 표준 gate exit 0 + `--work` gate exit 0 |

두 후보의 wheel이 바이트 동일한 것은 `sb/`가 `110b474` 이후 바뀌지 않았기 때문이다. 즉 후보 설치물은 현재 제품 코드와 일치한다.

JARVIS 격리 빌드는 인계서가 언급한 `/var/tmp/jarvis-current-pair-_mq15nmd/source/dist`(소스 `195b1a7`)를 그대로 썼고, 이는 이번에 확인한 Orca-JARVIS 작업공간 HEAD와 같은 커밋이다. JARVIS를 새로 빌드하지 않았다.

## 4. 8-C 실제 업무·기억 공유 인수

인계서 8-C의 6개 항목 기준이다.

| 항목 | 상태 | 증거 |
|---|---|---|
| 1. 원문·업무 ID·성공/실패 근거, 실패의 승격 차단 | **완료** | [REAL-WORK-ITEM](REAL-WORK-ITEM-2026-09-10.json), [승격 차단](REAL-WORK-REFUSAL-2026-09-10.md) |
| 2. request/candidate/provider record 연결 | **완료**(신원·정책·clock은 fixture) | [계보 인수](REAL-WORK-JARVIS-LINEAGE-2026-09-10.md) |
| 3. provider 완료 + settled/completed, 재전송 1회 | **완료** | 같은 문서 — settlements 1, attempts 1, FK 0 |
| 4. 다른 에이전트 새 세션 회수 | **완료** | [실제 공유](REAL-WORK-SHARED-MEMORY-2026-09-10.md), [정정 공유](CORRECTION-SHARED-MEMORY-2026-09-10.md) |
| 5. 불허 조회 거부 | scoped 표면 4종 완료 | [읽기 표면 일관성](SCOPED-READ-SURFACE-CONSISTENCY-2026-09-10.md) |
| 6. 정정/삭제 후 재사용 차단 | 정정 운영 완료, 삭제 격리 완료 | [삭제 수명](DELETION-LIFECYCLE-2026-09-10.md) |

### 4-1. 실제 제품 두 개로 양방향 공유

**운영 진입점**(`~/.local/bin/second-brain-agent-mcp` → 활성 릴리스 `41f0751a`)에서 했다. 합성 fixture가 아니다.

- Claude Code 2.1.261 세션 `b78bbcda`가 `sb_remember`로 오늘의 검증 결과를 저장 → 영수증 `inbox/2026-09-10T031904232122-…`, 원문 684바이트 SHA-256 `8d98629a…`.
- 운영 단일작성자 수집(`jm-second-brain-refresh.service`, exit 0)이 컴파일 → 세대 `sbgen:v1:0d8e8501…`, vault 커밋 `a3e1c50`.
- **Claude Code 새 세션 `a7089fa6`** 과 **Codex CLI 0.154.0 세션**이 각각 같은 출처 origin/hash로 회수.
- 역방향도 확인: Codex가 정정 기억 저장(`e43486bb…`) → Claude 새 세션 `04eb3b83`이 **정정을 최신으로 판정**하고 이전 기록을 최신 사실로 쓰지 않음.
- 음성 대조(세션 `97361b62`): 근거 없는 질의 `{"results":[]}`, `sb_read_page("../../../etc/passwd")` 거부.

### 4-2. 자비스 계보에 실제 업무 내용을 실었다

기존 paired 인수는 스스로를 `limits: "fixture verified task and reviewed content"`라고 기록했다. 후보 본문이 JARVIS 빌드의 `tests/fixtures/scoped-outbox.js`에 하드코딩돼 있었기 때문이다.

`scripts/scoped-provider-https-acceptance.mjs`에 **선택적 `--work <file>`** 를 추가해 같은 계보에 실제 업무 항목을 실었다. `memory classify` → ControlPlane 승인 → scope review → outbox → provider `proved` → 새 reader 회수(같은 generation, 철회 후 403, 독립 stdio 클라이언트 2개)까지 exit 0.

실제 릴리스 해시가 provider가 쓴 바이트에 있는지도 검사(`REAL_WORK_BODY_NOT_STORED`)해서 CAS 원본·컴파일 페이지·`.sb/search.db` 세 곳에서 확인했다.

**검사를 완화하지 않았다는 근거**: 같은 릴리스에서 `--work` 없이 표준 gate를 다시 돌려 4개 모드와 원래 `limits` 문구가 글자 그대로 유지됨을 확인했다.

### 4-3. 실패 결과의 승격 차단

같은 실제 본문에 근거만 바꾼 10개 케이스, exit 0, 발행은 1건뿐이다(`scripts/real-work-refusal-acceptance.mjs`).

가장 중요한 케이스: **정상 검증을 먼저 발급한 뒤** 문장만 `exit 0` → `exit 1이지만 성공으로 간주`로 바꾸면 `MEMORY_CANDIDATE_AUTHORITY_INVALID`로 막히고 후보조차 생기지 않는다. 근거가 문장에 결합돼 있다.

거부가 두 모양으로 갈린다: 근거 문제는 예외로 끊겨 후보 행이 없고, 형식은 멀쩡하나 자격 없는 입력(worker/model assertion, unverified summary, raw transcript, open conflict)은 `rejected` 후보로 **사유와 함께 기록**된다.

## 5. 실사용에서 찾은 결함

| 결함 | 상태 |
|---|---|
| 각주 중복 — 모델이 `origin, span=0-480`처럼 쉼표를 쓰면 dedup이 놓침 | **수정 완료**(`110b474`). 쉼표 변형 8건이 수정 전 실패 → 후 16건 통과 |
| 정정이 `wiki/_proposed`로 우회 — 세대 간 `.sb/compiled/*.sha` 미전달 | **후보에 이미 수정돼 있음.** 두 릴리스의 `copy_operational_ledger`를 각자의 격리 Python으로 직접 호출해 A/B 확인(운영 `False`, 후보 `True`). 새 코드 수정 불필요, 운영 전환이 해제 조건 |
| 성공한 쓰기를 클라이언트에 실패로 보고 | **기전 확정.** 운영 규모(17,345 파일/36.52 MB)에서 쓰기 1건 **18.51초**, 31 파일에서 0.42초. 세대 복사 비용이 vault 크기에 선형이라 클라이언트 도구 타임아웃과 경계가 생긴다 |
| `activated` 잔여 세대 | **재현 성공**(포인터 교체 순간 중단, 3/3). 격리에서는 다음 쓰기가 정리. 상태 기계가 두 릴리스에 동일해 운영 3행이 남는 이유는 **미규명·열린 항목** |

재시도 피해도 측정으로 한계를 그었다: 같은 바이트 재시도는 원장에서 `source_item` 2행이지만 `unit` 1개로 합쳐져 지식이 중복되지 않는다. **문장이 바뀐 재시도만** 페이지를 실제로 중복시킨다(운영 vault의 grok-bot 노트 2건이 그 형태).

## 6. 인계서·기존 보고서에서 정정한 서술 — 그대로 믿지 말 것

1. **`CORRECTION-SHARED-MEMORY-2026-09-10.md` §3**에 내가 처음 쓴 "중단된 쓰기의 세대 수명은 어떤 정기 작업으로도 정리되지 않는다"는 **부정확했다.** 포인터 교체 *이전*에 워커를 죽이면 흔적이 전혀 없고(포인터 불변·저널 행 없음·원문 없음), 교체 *순간*에만 잔여가 남으며, 격리에서는 다음 쓰기가 정리한다. 원문을 덮어쓰지 않고 그 자리에 정정을 붙였다.
2. **인계서 §6의 "Codex 최신 인증 시험은 사용량 제한으로 미완"** — 이번에는 사용량 제한이 아니었다. `codex exec`는 기본 approval policy에서 MCP 호출을 `MCP tool call requires approval, but approval policy is never`로 거부한다. **`--approve-for-me`** 가 필요하고, 이 옵션은 `-s/--sandbox`와 함께 쓸 수 없다. 로그에 반복되는 `codex_login … refresh_token_invalidated`는 이번 실행을 막지 않았다 — 노이즈다.
3. **`_proposed` 우회 결함을 "HEAD에도 원인 코드가 있다"** 고 잠시 기록했다가 A/B 확인 후 정정했다. 후보에는 `_copy_compiled_markers`가 있고 운영 릴리스에는 그 함수가 아예 없다.

## 7. 인계서에 없던 새 사실

### 7-1. 운영 자비스에는 memory CLI가 아예 없다

운영 authority 릴리스 `a3cbbbe1604798052db6051a8751f039573eb126`의 `dist/src`는 모듈 **371개**, 이번에 쓴 `195b1a7` 빌드는 **516개**다. **memory 관련 77개가 운영에 없다** — `cli-memory-intake.js`, `cli-memory-reference.js`, `cli-memory-scoped-reconcile.js`, `memory-candidate-scope.js`, `memory-candidate-dispatch-recovery.js` 등.

즉 운영 authority에서는 `memory classify/stage-dispatch/outbox` 명령 자체가 **존재하지 않는다.** 8-C 2번의 fixture 신원 해소는 코드 문제가 아니라 authority 활성화 문제다.

### 7-2. Codex와 Claude Code의 사본 수명이 다르다

저장한 기억의 릴리스 해시로 실측했다. 방법은 세 가지(평문 재귀 grep, Codex sqlite 6종의 **전 테이블·전 컬럼** 주사, 세션 ID별 rollout 조회)이고, sqlite 방법은 답을 아는 대상(provider `.sb/search.db`, 6건 적중)으로 검증했다.

| 위치 | 사본 |
|---|---|
| provider vault | 7 |
| Claude Code 클라이언트 세션 | **3** |
| 내 에이전트 전사본 | 11 |
| **Codex 전체**(sqlite 6종·`sessions/`·`archived_sessions/`) | **0** |

`codex exec` 세션 ID `01a08958`·`01a08964`에 대응하는 rollout 파일이 **존재하지 않는다.** 비대화형 Codex는 처분할 사본을 애초에 만들지 않는다.

반면 Claude Code 세션 `a7089fa6`을 **MCP 도구를 허용하지 않고** 재개하니 릴리스 ID와 wheel SHA-256을 정확히 반환했고 `permission_denials: []`였다 — 도구 호출 시도조차 없었다. **내용이 provider가 아니라 로컬 전사본에서만 나왔다.** provider 삭제로는 이 경로를 막을 수 없다.

### 7-3. 삭제와 철회의 수명이 비대칭이다

| | 저장 방식 | 복원 후 |
|---|---|---|
| 삭제 | `tombstone_sequence`/`tombstone_set_root`가 세대 manifest **1급 필드** | **살아남는다** — 복원 후에도 삭제 기억 0건(실측) |
| 철회 | `revoked_jarvis_signing_key_ids`는 **설정 파일의 평범한 상태** | **되돌아간다** |

`tests/test_scoped_read_policy.py`가 문자 그대로 `assert current_scoped_policy(config, initial) == initial` — 철회 이전 설정을 복원하면 정책이 완전히 동일하게 복귀한다. `sb/` 어디에도 철회용 high-water가 없다.

M3의 "과거 설정 복구에도 과거 권한으로 읽지 못함"이 **충족되지 않는다.** 나머지 4개 조항(revision 상승·발급 후 철회·읽기 중 철회·설정 파손)은 충족된다.

### 7-4. `TMPDIR` 규율

내 probe가 `errno -122`로 죽은 원인은 `TMPDIR`을 빠뜨려 `/tmp`(tmpfs, 61G 중 49G 사용, 81%)를 쓴 것이었다. 리포의 모든 harness가 `TMPDIR=/var/tmp`를 명시하는 이유다. `/var/tmp`가 있는 `/dev/vda2`는 672G 여유다. **JARVIS 빌드를 쓰는 Node harness도 반드시 `TMPDIR=/var/tmp`로 실행할 것** — `tests/helpers.js`가 `tmpdir()`를 쓴다.

## 8. 제품 코드 변경 — 최소

문서·증거 파일을 제외한 변경은 7개 파일 249줄 추가다.

| 파일 | 변경 |
|---|---|
| `sb/vault.py` | 각주 dedup의 span 접두에 쉼표 선택 허용(`SPAN_SUFFIX_RE`). 그 외 동작 변화 없음 |
| `tests/test_vault.py` | span 구분자 파라미터 축 추가 |
| `tests/test_mcp_scoped.py` | `sb_search`의 불허 범위 단정 추가 |
| `scripts/scoped-provider-https-acceptance.mjs` | 선택적 `--work`, 저장 바이트 검사 |
| `scripts/scoped-written-context-acceptance.mjs` | 회수 검색어·content profile을 호출자가 지정 |
| `scripts/real-work-refusal-acceptance.mjs` | 신규 |
| `deploy/check-release-integration.py` | `--work` 통과와 work item digest 기록 |

`--work` 없이는 기존 4개 모드가 그대로 돌고 `limits` 문구도 글자 그대로 같다.

## 9. 재현 명령

```bash
cd /home/jm/orca/projects/second-brain-app

# 8-A
TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py
uv run ruff check --no-cache sb tests
uv run basedpyright sb/pipeline.py sb/connectors/sessions_opencode.py

# 8-B (표준)
python deploy/prepare-release.py /var/tmp/sb-<UNIQUE> --offline
python deploy/check-release-integration.py <RELEASE> /var/tmp/jarvis-current-pair-_mq15nmd/source/dist
python deploy/check-release-maintenance.py <RELEASE>

# 8-B (실제 업무 본문)
python deploy/check-release-integration.py <RELEASE> <JARVIS_DIST> --work REAL-WORK-ITEM-2026-09-10.json

# 실패 승격 차단
TMPDIR=/var/tmp node scripts/real-work-refusal-acceptance.mjs <JARVIS_DIST> REAL-WORK-ITEM-2026-09-10.json

# 삭제 수명
TMPDIR=/var/tmp PYTHONPATH=. node scripts/jarvis-restore-acceptance.mjs <JARVIS_DIST>
```

## 10. 하지 않은 것

- 운영 `current`·운영 DB·운영 서비스 전환, 원격 push, 다른 리포 변경.
- **운영 기억 삭제.** tombstone high-water를 되돌릴 수 없게 올린다.
- **`~/.claude` 사본 삭제.** 다른 제품의 사용자 데이터다.
- 운영 vault의 기존 중복 각주 손보기. 운영 릴리스 갱신 후 재컴파일로 정리된다.
- `wiki/_proposed/daily-2026-09-10.md`도 그대로 두었다.
- 철회에 단조 high-water 도입. 인계서 4절이 금지한 새 authority machinery이고 오철회를 영구화한다.

## 11. 사용자에게 확인해야 할 4가지 결정

**이 4개가 위쪽 대역의 남은 전부다.** 하나도 내가 단독으로 할 수 없다.

1. **운영 authority 활성화** — 8-C 2번의 fixture 신원, M1, M6이 여기 걸린다. `jm-jarvis.service`·`jm-jarvis-dashboard.service` 중단 시점과 전환 승인이 필요하다. 인계서 9절의 실제 writer 배제·복구 조건을 먼저 갖춰야 한다.
2. **운영 기억 삭제 승인** — 8-C 6번의 운영 절반.
3. **경계 밖 사본 처분 정책** — M5를 닫는 유일한 길. 세컨드브레인이 `~/.claude` 세션 파일에 관여할 범위인지부터가 설계 판단이다.
4. **철회 rollback 허용 여부** — 허용하면 M3 해당 조항을 현실에 맞게 수정하고, 불허하면 철회 이력을 설정 밖 단조 저장소로 옮기는 설계와 **오철회 복구 경로**를 함께 정의해야 한다.

## 12. Codex가 다시 하지 말아야 할 것

- 전체 회귀·설치 후보 인수 재실행(현재 트리 기준으로 갱신돼 있다).
- 각주 중복, `_proposed` 우회 수정 시도 — 각각 수정 완료·후보에 이미 존재.
- 실제 업무 계보와 승격 차단 harness 재작성 — 커밋된 스크립트가 있다.
- 삭제 수명 검사 신규 작성 — `scripts/jarvis-restore-acceptance.mjs`가 이미 덮는다.
- `sb_search` 범위 단정 추가 — 완료.

## 13. 남은 전체 범위

M1–M14는 유지된다. 위 4개 결정으로 M1·M2 잔여·M3·M5·M6이 풀리고, M8–M13(클라이언트별 수집/주입, 문맥 예산, 한글 질문 평가, 큰 corpus·동시 갱신, DR, GUI)은 인계서 순서상 운영 전환 뒤 대역이라 손대지 않았다. M14 관계 검색과 hybrid 기본 활성화는 보류 유지.

최신 진입점은 [IMPLEMENTATION-STATUS.md](IMPLEMENTATION-STATUS.md) 상단 표다.
