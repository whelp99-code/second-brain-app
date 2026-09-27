# Second Brain 제품 매뉴얼

이 문서는 `second-brain` 엔진(패키지 이름 `second-brain`, 버전 `1.0.0`, 콘솔 스크립트 `sb`)의 정본
운영 매뉴얼이다. 모든 서술은 이 리포의 코드(`sb/`, `deploy/`)와 리포에 커밋된 운영 기록에서 확인한
내용만 담는다. 코드에 없는 옵션·설정 키는 적지 않는다.

- 대상 리포: `/home/jm/orca/projects/second-brain-app`
- 패키지 메타: `pyproject.toml` (`name = "second-brain"`, `version = "1.0.0"`, `requires-python = ">=3.12"`,
  `[project.scripts] sb = "sb.cli:main"`)
- 참고 문서: [`README.md`](../README.md), [`AGENTS.md`](../AGENTS.md), 운영 기록
  `CLAUDE-CUTOVER-2026-09-15.md`, `CLAUDE-COMPLETION-REPORT-2026-09-15.md`,
  `CLAUDE-NATIVE-COMPACT-PROBE-2026-09-15.md`, `M10-GOLD-CURATED-2026-09-15.md`,
  `GROK-INTEGRATED-CANDIDATE-HANDOFF-2026-09-13.md`

---

## 1 개요와 설계 목표

### 1.1 한 문장 정의

Second Brain은 **원본을 지우지 않고 출처를 추적하며, 모든 쓰기를 원장(ledger)과 세대(generation)로
증명 가능하게 만드는 단일 사용자·단일 Vault·단일 writer 로컬 지식 엔진**이다.

### 1.2 설계 목표 (코드에서 강제되는 것들)

| 목표 | 코드상 강제 지점 |
|---|---|
| 원본 보존 | `raw/`는 SHA-256 CAS. `sb gc`는 `--apply --confirm` 둘 다 없으면 삭제하지 않는다(`sb/governance.py: collect_orphans`). |
| 출처 추적 | 컴파일된 페이지는 각주 `[^<sid>]`와 프론트매터 `sources`를 가지며, `sb doctor`의 `citations` 검사가 미해결 각주와 누락 CAS를 fail로 만든다(`sb/pipeline.py: audit_citations`). |
| 단일 writer | 파이프라인은 `.sb/run.lock`을 `flock(LOCK_EX|LOCK_NB)`으로 잡고, 잡히지 않으면 `already running`을 출력하고 종료 코드 0으로 끝낸다(`sb/pipeline.py: _try_lock`, `_print_outcome`). |
| 세대 불변성 | 게시된 세대 디렉터리는 파일 `0400`/디렉터리 `0500`으로 봉인된다(`sb/generations.py: _seal_modes`). |
| 복구 가능성 | `sb backup`은 생성 직후 검증까지 수행하고 `*.tar.gz.verified.json` 영수증을 남긴다(`sb/cli.py: backup`, `sb/runtime_backup.py`). |
| 자동 파괴 금지 | `sb rollback`은 항상 `ROLLBACK_REQUIRES_GENERATION_AUTHORITY`로 거절한다(`sb/cli.py: rollback`). 충돌 자동 해결·무승인 삭제 경로는 없다. |
| 루프백 한정 | 웹 API 기본 바인딩은 `127.0.0.1:8765` (`sb/cli.py` web 기본값, `deploy/systemd/second-brain-web.service`). |

### 1.3 제공 표면

| 표면 | 진입점 | 용도 |
|---|---|---|
| CLI | `sb` (`sb/cli.py`) | 수집·컴파일·브리핑·진단·백업·복원·유지보수 |
| MCP (stdio) | `sb mcp` / `python -m sb.mcp` (`sb/mcp.py`) | AI 클라이언트의 검색·페이지 읽기·기억 기록 |
| Web | `sb web` (`sb/web.py`) | 기억·업로드·검색·충돌 해결·상태/메트릭·`/ready` |
| 기억 훅 | `sb postcompact-hook` (`sb/postcompact_hook.py`) | Claude Code / Codex CLI / OmO의 컴팩션 시점 문맥 주입 |
| macOS 앱 | `clients/macos/SecondBrainMac` | 메뉴바·Finder 드롭·폴더 동기화(별도 문서 `MACOS-DESKTOP.md`) |

## 2 아키텍처

### 2.1 레이어

`AGENTS.md`가 정의한 계층이 그대로 모듈 경계다.

```text
L7  sb/cli.py      sb/mcp.py      sb/web.py          ← 사용자 표면
L6  sb/pipeline.py                                    ← 락, 원장, 로그, 디스패치
L5  sb/vault.py                                       ← wiki/ daily/ conflicts/ log.md 의 유일한 writer, 유일한 git committer
L4  sb/llm.py  sb/compile.py  sb/conflict.py  sb/briefing.py   ← 순수 변환(파일시스템 접근 금지)
L3  sb/normalize.py
L2  sb/connectors/*  sb/parsers/*
L1  sb/store/cas.py  sb/store/ledger.py
L0  sb/contracts.py  sb/config.py
```

L7 옆에 `sb/search.py`, `sb/embeddings.py`, `sb/hybrid_search.py`가 놓인다. 검색은 **커밋된 git blob**을
읽는다.

금지된 결합(`AGENTS.md` 정본): 커넥터는 `sb.normalize`/`sb.llm`/`sb.vault`를 import 하지 않는다.
`sb.compile`·`sb.briefing`은 파일시스템을 만지지 않고 `PageSpec`만 반환한다. `sb.pipeline`을 import 하는
것은 `sb.cli`, `sb.web`, 명시적 MCP `sb_run` 표면뿐이다. unified-db 커넥터는 읽기 전용 트랜잭션임을
확인한 뒤에만 SELECT 한다. 서버에는 파일 워처·큐·이벤트 버스가 없고 `inbox/`에서만 수집한다.

### 2.2 Vault 레이아웃

```text
vault/
├── wiki/                 컴파일된 지식 페이지 (.md)
├── wiki/_proposed/       사람 편집을 보호한 AI 제안본
├── daily/                일일 브리핑
├── conflicts/            충돌과 사람의 해결 기록
├── inbox/                기억·업로드 대기 자료
├── raw/                  SHA-256 CAS 원본 (raw/<hh>/<sha256>)
├── log.md                실행 로그
└── .sb/                  SQLite 원장 · 검색 인덱스 · 메트릭 · 락
    ├── ledger.db
    ├── search.db
    ├── compiled/         페이지별 마지막 컴파일 해시
    ├── run.lock
    └── session-memory/   훅 스테이지 파일(state_root 아래에 놓일 수도 있음)
```

`raw/`와 `.sb/`는 Vault git에서 제외되지만 백업에는 포함된다(`README.md`). Vault 루트 모드는 `0700`
(`sb/vault.py: init_vault`).

### 2.3 관리형(세대) 배치 vs 단순 배치

코드는 두 배치를 구분한다. 판정식은 여러 곳에서 동일하다:

```python
managed = Path(config.vault_root).is_symlink() or "share_root" in config.raw
```

(`sb/readiness.py`, `sb/pipeline.py: _execute`, `sb/runtime_backup.py` 등)

| | 단순 배치 | 관리형 배치(운영) |
|---|---|---|
| `vault_root` | 실제 디렉터리 | `share/vault` **심볼릭 링크** |
| 쓰기 | Vault에 직접 커밋 | 스테이징 트리 → 봉인 → 링크 전환 |
| 락 위치 | `vault/.sb/run.lock` | `state_root/.sb/run.lock` |
| 세대 저널 | 없음 | `state_root/generation-journal.db` |
| 요청 저널 | 선택 | `request_root/journal.db` |

운영 설치(`~/.config/second-brain/config.toml`)는 `share_root`, `state_root`, `generation_root`를 모두
명시하므로 관리형이다.

### 2.4 텍스트 다이어그램 — 전체 데이터 흐름

```text
 [소스]                    [수집]              [원장/CAS]            [파생]                [Vault]
 inbox/*.md ────┐
 markdown-vault ┼─ sb ingest ─► source_item ─► raw/<sha256>  ─► unit ─► derivation ─► PageSpec ─► wiki/*.md
 unified-db(RO) ┘                  │                                  │  (compile)        │        daily/*.md
                                   │                                  │  (conflict)       │        conflicts/*.md
                                   └────── cursor(어댑터별) ──────────┘  (brief)          └── git commit
```

```text
 [세대 수명주기 — 관리형 배치]

  writer mutex(generation-writer.lock)
        │
        ▼
  base = current 세대 ──copy──► staging/<64hex>  ──apply(ingest|compile|brief|run|inbox|effect|restore)──►
        │                                                  │
        │                                             seal(0400/0500) + manifest
        │                                                  │
        │                                       activations: claimed → staging → sealed
        │                                                  │
        │                                            switch_intent
        │                                                  │
        │                                    share/vault 심링크 원자 교체 (activated)
        │                                                  │
        │                          reader drain 검사(/proc fd + reader_leases)
        │                                                  │
        │                                     predecessor → .retired → 삭제 (disposing)
        │                                                  │
        └──────────────────────────────────────────────► proved
```

핵심: **선행 세대를 폐기하려면 그 디렉터리를 연 fd가 0이어야 한다.** 하나라도 남아 있으면
`GENERATION_READER_DRAIN_REQUIRED`가 발생한다(`sb/generations.py: _complete_disposal`,
`_proc_descriptors`). `/proc`을 읽을 수 없으면 `GENERATION_READER_DRAIN_UNVERIFIABLE`.

### 2.5 요청 저널 (JARVIS memreq)

```text
 JARVIS ──(서명된 요청)──► request_root/pending/<file>
                                    │
                    jm-second-brain-requests.path (DirectoryNotEmpty)
                                    │
                            sb apply-requests --once
                                    │
             journal.db: requests(state, phase, fence, owner, lease_expires_at, …)
                                    │
     pending ─claim─► processing ─(세대 mutation)─► proved
                          │
                          ├─► failed
                          ├─► expired
                          └─► reapproval_required
                                    │
                            request_root/receipts/
```

`requests.state`의 CHECK 제약은 정확히 다음 6개다(`sb/request_store.py`):
`'pending','processing','proved','failed','expired','reapproval_required'`.

`requests.phase`(세대 진행 단계)는 다음 7개다:
`'claimed','staging','sealed','switch_intent','activated','disposing','proved'`.

### 2.6 검색 인덱스

```text
 committed git blob (wiki/, daily/, conflicts/)
        │  (SearchIndex.project)
        ▼
 .sb/search.db  ─ docs(page_id, section, text, compact, normalize_id, normalize_section,
        │          kind, status, updated, knowledge_status, approval_status, canonical, …)
        │
        ├─ lexical: 모든 검색어가 compact/normalize_id/normalize_section의 부분 문자열일 것 (AND)
        └─ semantic: [search] hybrid=true 이고 봉인 벡터가 있을 때만
```

인덱스 스키마 버전은 `sb/search.py`의 `_INDEX_SCHEMA_VERSION = "4"`이고, 필수 컬럼 집합이 맞지 않는
구세대 `search.db`를 읽으면 `GENERATION_INDEX_INVALID`가 난다(`sb/search_errors.py`).

---

## 3 설치와 릴리스 준비

### 3.1 개발용 설치(단순 배치)

`README.md`의 Ubuntu 빠른 설치:

```bash
cd /home/jm/orca/projects/second-brain-app
uv tool install --force .

mkdir -p ~/.config/second-brain
install -m 0600 config.example.toml ~/.config/second-brain/config.toml

SB_CONFIG=~/.config/second-brain/config.toml sb init
SB_CONFIG=~/.config/second-brain/config.toml sb doctor

./deploy/install-systemd-user.sh
```

`deploy/install-systemd-user.sh`가 설치하는 유닛은 리포에 있는 5개뿐이다:
`second-brain.service`, `second-brain.timer`, `second-brain-backup.service`,
`second-brain-backup.timer`, `second-brain-web.service`. 그리고
`second-brain-web.service second-brain.timer second-brain-backup.timer`를 `enable --now` 한다.
`--dry-run`을 주면 실행 대신 명령을 출력한다. `SB_BIN`(기본 `$HOME/.local/bin/sb`)이 실행 가능하지
않으면 종료 코드 1로 중단한다.

### 3.2 운영 릴리스 준비(`deploy/prepare-release.py`)

운영 배치는 `uv tool install`이 아니라 **커밋된 HEAD를 봉인된 릴리스 디렉터리로 빌드**해서 쓴다.

```bash
cd /home/jm/orca/projects/second-brain-app
python deploy/prepare-release.py              # 기본 app root: ~/.local/state/second-brain/app
python deploy/prepare-release.py --offline    # UV_OFFLINE=1, 네트워크 없이 로컬 캐시만 사용
```

동작(스크립트 본문 기준):

1. `git rev-parse HEAD`로 소스 커밋을 고정하고 `git archive`로 **커밋된 트리만** 임시 디렉터리에 푼다.
   작업 트리의 미커밋·미추적 파일은 릴리스에 들어가지 않는다(`working_tree_modified`는 매니페스트에
   기록만 된다).
2. `SOURCE_DATE_EPOCH`를 커밋 시각으로 고정하고 `uv build --wheel`, `uv export --frozen --no-dev`로
   휠과 `requirements.txt`를 만든다.
3. `uv python find --managed-python --no-python-downloads --system 3.12`로 찾은 런타임을
   `deploy/bundle_python_runtime.py`가 릴리스 안으로 번들한다.
4. 릴리스 ID는 휠 바이트 + requirements + 런타임 다이제스트 + 준비 레시피 해시로 계산한다
   (`release_id_scheme: "sb-release-inputs-v3"`). 같은 ID가 이미 있으면 **에러로 중단**한다.
5. `releases/<release_id>/` 아래에 `.venv/`, `runtime/python/`, 휠, `requirements.txt`,
   `bin/{sb,second-brain-mcp,second-brain-agent-mcp}`, `release-manifest.json`을 만든다.
   디렉터리 모드 `0700`, 래퍼 스크립트 `0700`.
6. 마지막 줄로 릴리스 디렉터리 경로를 출력한다.

생성된 래퍼의 공통 프리앰블은 다음과 같다(스크립트 본문):

```sh
#!/bin/sh
set -eu
export HOME="${HOME:-/home/jm}"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
export SB_CONFIG="${SB_CONFIG:-$HOME/.config/second-brain/config.toml}"
cd <release>
```

- `bin/sb` → `<release>/.venv/bin/python -m sb.cli "$@"`
- `bin/second-brain-mcp` → `SB_MCP_CONTRACT_PROFILE` 기본값 `task32-schema4`로 `python -m sb.mcp`
- `bin/second-brain-agent-mcp` → `anyio.run(build_server(config=load_config()).run_stdio_async)`

### 3.3 앱 루트 구조

```text
~/.local/state/second-brain/app/
├── current -> releases/<release_id>     (원자적으로 교체되는 심볼릭 링크)
├── releases/
│   ├── <release_id>/…
│   └── … (이전 릴리스 보존 = 롤백 대상)
└── staging/
```

`current`는 활성 릴리스를 가리키는 **유일한 전환 지점**이다. 전환/롤백 절차는 §10.5를 본다.

### 3.4 릴리스 검증 스크립트

| 스크립트 | 목적 |
|---|---|
| `deploy/check-release-contents.py` | 설치된 릴리스의 전체 인벤토리(모드·크기·sha256, 심링크 대상)를 기록/대조한다. 외부 디렉터리 링크·특수 파일은 거부. 활성화하지 않는다. |
| `deploy/check-release-mcp.py <release>` | 임시 fixture로 `scoped-record-read-v2 / -v5 / scoped-request-status-v1 / scoped-request-write-v1` 네 프로필의 MCP 도구 목록을 실제로 확인한다. |
| `deploy/check-release-maintenance.py <release>` | 격리된 SIGKILL 작업공간에 대해 설치된 릴리스의 복원 유지보수를 실행한다. |
| `deploy/check-release-integration.py` | SB 릴리스 × 격리 JARVIS 빌드로 공유 기억 인수 시나리오를 돌린다. 실행 전후 인벤토리가 바뀌면 `ACCEPTANCE_CANDIDATE_CHANGED`로 실패한다. |
| `deploy/check-rollback-compat.py`, `deploy/check-transition-units.py`, `deploy/check-database-handles.py`, `deploy/check-jarvis-pending-state.py`, `deploy/check-omo-memory-startup.py`, `deploy/check-compile-key-upgrade.py`, `deploy/estimate-compile-key-upgrade.py` | 전환 전 개별 게이트. |

### 3.5 개발 검증 게이트

`README.md`가 정의한 Ubuntu 기본 게이트: `uv run ruff check sb tests`,
`uv run basedpyright sb tests`, `uv run pytest -q --ignore=tests/test_embeddings.py`, `uv build`.
`tests/test_embeddings.py`는 선택 의존성 `embeddings` extra가 있어야 돌고, 통합 게이트는
`tests/integration/test_walking_skeleton.py`다.

---

## 4 설정 파일 레퍼런스

### 4.1 설정 파일 탐색 순서

`sb/config.py: _config_search_path()`

1. 환경변수 `SB_CONFIG` (환경변수 확장 + `~` 확장)
2. `${XDG_CONFIG_HOME:-~/.config}/second-brain/config.toml`
3. 리포 루트의 `config.toml` (있을 때만)

파일이 없으면 빈 매핑으로 간주하고 모든 접근자가 기본값을 쓴다. 상대 경로는 **설정 파일이 있는
디렉터리** 기준으로 절대화된다(`Config._path`).

운영 설치에는 두 개의 설정이 있고 `SB_CONFIG`로 고른다:

| 파일 | 쓰는 곳 |
|---|---|
| `~/.config/second-brain/config.toml` | web / maintenance / requests 유닛, 대화형 CLI |
| `~/.config/second-brain/jarvis-provider.toml` | refresh 경로(주기 실행) |

두 파일은 경로·키·provider 신원을 공유하고 `caps` 값만 다르다(운영 확인: `config.toml`은
`max_llm_calls_compile = 120`, `jarvis-provider.toml`은 `40`).

### 4.2 최상위 키

| 키 | 타입 | 기본값 | 의미 |
|---|---|---|---|
| `vault_root` | 문자열 경로 | `${XDG_DATA_HOME:-~/.local/share}/second-brain/vault` | 활성 Vault. 관리형 배치에서는 `share_root/vault` 심링크여야 한다. |
| `knowledge_registry` | 문자열 경로 | `…/second-brain/knowledge-registry.sqlite` | 지식 상태(active/candidate, 승인) 레지스트리. **키가 명시된 경우에만** CLI/MCP/web이 명시 경로로 전달한다. |
| `state_root` | 문자열 경로 | `${XDG_STATE_HOME:-~/.local/state}/second-brain` | 세대 저널·락·훅 스테이지의 뿌리. |
| `share_root` | 문자열 경로 | 활성 Vault의 부모 | 세대 저장소가 놓이는 공유 루트. 이 키의 존재 자체가 "관리형 배치" 판정에 쓰인다. |
| `generation_root` | 문자열 경로 | `…/second-brain/vault-generations` | 세대 디렉터리 루트. |
| `request_root` | 문자열 경로 | `<state_root>/requests` | 요청 저널(`journal.db`)과 `pending/`, `processing/`, `receipts/`. |
| `export_root` | 문자열 경로 | `<state_root>/exports` | 내보내기 산출물. |
| `backup_root` | 문자열 경로 | `<state_root>/backups` | `sb backup`의 기본 목적지이자 `/ready`가 훑는 디렉터리. |
| `provider_instance_id` | 문자열 | `provider:second-brain:linux` | 이 provider 인스턴스의 신원. 백업 origin·요청 증명에 들어간다. |
| `provider_release_sha` | 문자열 | `development` | 릴리스 표식. `/ready` 응답의 `provider_release`. |
| `provider_signing_key_id` | 문자열 | 없음 | provider 서명키 ID. `apply-requests`에 필수. |
| `provider_private_key` | 문자열(base64url) | 없음 | Ed25519 개인키. **절대 외부로 노출하지 않는다.** |
| `provider_result_public_keys` | 테이블 | `{}` | 결과 서명 검증용 공개키. |
| `revoked_provider_result_key_ids` | 문자열 배열 | `[]` | 철회된 결과 키 ID. |
| `jarvis_signing_key_id` | 문자열 | 없음 | 단일 JARVIS 키 ID(구형 표기). |
| `jarvis_public_key` | 문자열 | 없음 | 단일 JARVIS 공개키(구형 표기). 위 ID와 함께 있으면 `jarvis_public_keys`에 합쳐진다. |
| `jarvis_public_keys` | 테이블(ID→공개키) | `{}` | 신뢰 JARVIS 서명키 집합. |
| `cancellation_public_keys` | 테이블 | `{}` | 취소 의도 제출 전용 공개키. |
| `revoked_jarvis_signing_key_ids` | 문자열 배열 | `[]` | 철회된 JARVIS 키 ID. 런타임 철회 파일과 합쳐진다(`sb/revoked_keys.py`). |
| `revoked_delegation_ids` | 문자열 배열 | `[]` | 철회된 위임 ID. |
| `external_erasure_public_keys` | 테이블 | `{}` | 외부 삭제 요청 검증 공개키. |
| `legacy_request_roots` | 문자열 배열 | `()` | 구형 요청 루트(이관용). |

### 4.3 `[llm]`

| 키 | 기본값 | 의미 |
|---|---|---|
| `argv_template` | `["claude", "-p", "{prompt}"]` | LLM CLI 호출 argv. `{prompt}` / `{system}` 자리표시자를 치환한다. |
| `prompt_version` | `"v1"` | 파생 키에 들어가는 프롬프트 버전. 값이 바뀌면 파생이 다시 계산된다. |
| `model_id` | `"unknown"` | 파생 키에 들어가는 모델 식별자. |

호출 규칙(`sb/llm.py: _render_invocation`, `CliLLM.generate`):

- argv 어느 조각에도 `{prompt}`가 없으면 **프롬프트는 stdin으로 전달**되고, 있으면 argv에 치환된다.
- `{system}` 자리표시자가 없고 system 프롬프트가 있으면 `"{system}\n\n{prompt}"`로 합쳐 하나의
  페이로드로 만든다.
- 시도 상한은 `ATTEMPT_LIMIT = 2`. 실패하면
  `LLM unavailable after 2 attempts: <이유>` 메시지의 `LLMUnavailable`이 난다.
- `json_mode=True`일 때는 stdout에서 **첫 번째 JSON 객체**를 직접 파싱해 뽑는다(`_extract_first_json_object`).
  못 찾으면 `LLMBadJson`.

> `README.md`의 예시에는 `[llm] external = true`가 나오지만 `sb/config.py`의 `LlmConfig`는
> `argv_template`, `prompt_version`, `model_id` 세 키만 읽는다. `external`은 로더가 무시한다.

### 4.4 `[caps]`

`DEFAULT_CAPS` (`sb/config.py`):

| 키 | 기본값 | 의미 |
|---|---|---|
| `max_llm_calls_compile` | 200 | 한 컴파일 실행의 LLM 호출 상한 |
| `max_llm_calls_conflict` | 200 | 충돌 판정 LLM 호출 상한 |
| `max_llm_calls_briefing` | 10 | 브리핑 LLM 호출 상한 |
| `max_briefing_validation_attempts` | 1 | 브리핑 검증 재시도 횟수 |
| `max_new_units_per_run` | 500 | 한 실행에서 새로 만들 수 있는 **고유 unit** 수 |
| `max_source_items_per_run` | 500 | 한 실행에서 시도하는 **원본 버전 처리** 수. 이 키를 생략하면 `max_new_units_per_run` 값을 그대로 계승한다. |
| `max_db_rows_per_run` | 5000 | DB 커넥터 행 상한 |
| `max_derivation_attempts` | 3 | 파생 재시도 상한. `[retry] max_attempts`의 기본값이기도 하다. |

예산 초과 동작(`README.md`, `sb/pipeline.py`): 한 원본이 전체 unit 예산을 넘으면
`INGEST_UNIT_BUDGET_EXCEEDED`와 종료 코드 1로 실패하고 원본을 보존한다. 잔여 예산에만 맞지 않는
원본은 `capped`로 남고 다음 실행에서 처리된다. `sb ingest --limit N`은 **파일 수만** 조정하며 unit
예산은 그대로 적용된다.

### 4.5 `[[sources]]`

각 원소는 문자열 값만 허용된다(`_as_source_roots`). 하나라도 문자열이 아니면 목록 전체가 비게 된다.

| 키 | 의미 |
|---|---|
| `id` | 원본 인스턴스 ID. 같은 어댑터로 여러 원본을 쓸 때 반드시 서로 다르게 준다. 중복 ID는 거부된다. |
| `adapter` | 커넥터 ID (`inbox-documents`, `markdown-vault`, `unified-db`, `sessions_*`, `records_*`, `*_documents`) |
| `root` | 원본 루트 경로. 설정 파일 기준으로 절대화된다. |
| `llm_policy` | `allow` / `deny` / `local-only` (README) |
| `sensitive` | 예: `mask` (README) |

선택 실행에 쓰이는 이름은 `id` → `adapter` → `type` 순으로 고른다(`configured_source_ids`).
명시 선택한 이름 중 해석되지 않는 것이 있으면 `SOURCE_NOT_FOUND`로 전체가 실패하고, 나머지만 부분
수집하지 않는다(README).

운영 설정의 실제 값:

```toml
"sources" = [
  {"id" = "inbox",  "adapter" = "inbox-documents", "llm_policy" = "allow", "sensitive" = "mask"},
  {"id" = "hermes", "adapter" = "markdown-vault",  "root" = "/home/jm/.hermes"}
]
```

### 4.6 `[source_access.<source id>]`

`sb/config.py: Config.source_access`는 **정확히 세 키**만 허용한다. 하나라도 빠지거나 더 있으면
`SOURCE_ACCESS_CONFIG_INVALID`(`ConfigValueError`)로 설정 로드가 실패한다.

| 키 | 타입 | 의미 |
|---|---|---|
| `owner` | 문자열 | 소유 주체 (예: `"principal:owner"`) |
| `projects` | 문자열 배열 | 프로젝트 분류. 중복 없이 정렬, 최대 64개. 빈 목록은 owner 전용. |
| `policy_revision` | 문자열 | 정책 리비전 (예: `"policy:1"`) |

이 설정은 **분류 기록**이며 MCP/API 접근 제어가 아니다(README가 명시). 기존 분류를 바꾸면
`SOURCE_ACCESS_RECLASSIFICATION_REQUIRED`로 수집을 거부한다.

### 4.7 `[search]`

| 키 | 기본값 | 의미 |
|---|---|---|
| `hybrid` | `false` | `true`이고 임베딩 모델이 있을 때만 다음 관리형 세대부터 인용 가능한 기억 레코드의 벡터를 함께 봉인한다. 이미 봉인된 세대는 설정 변경만으로 재색인되지 않는다. |
| `min_similarity` | `-1.0` | 의미 후보의 최소 cosine 점수. `-1 ≤ x ≤ 1`의 유한한 수여야 하며 아니면 `[search].min_similarity must be a finite number between -1 and 1`. 일반(lexical) 결과에는 적용되지 않는다. |

`hybrid`는 값이 정확히 `true`(불리언)일 때만 켜진다(`section.get("hybrid") is True`).

### 4.8 `[readiness]`

`sb/readiness_checks.py: ReadinessPolicy.from_config`. 네 값 모두 **정수**여야 하고 범위는 `1..8760`.
벗어나면 `/ready`가 `READINESS_POLICY_INVALID` 하나만 담은 degraded 응답을 돌려준다.

| 키 | 기본값 | 곱 | 의미 |
|---|---|---|---|
| `max_run_age_hours` | 48 | ×3600 | 마지막 실행이 이보다 오래되면 `LAST_RUN_STALE_OR_INVALID` |
| `max_backup_age_hours` | 48 | ×3600 | 검증 백업 신선도 한계 |
| `max_request_age_minutes` | 15 | ×60 | 가장 오래된 pending/processing 요청 허용 나이. 세대 activation 정체 판정에도 같은 값을 쓴다. |
| `failure_window_hours` | 48 | ×3600 | 최근 실패 요청을 세는 창 |

### 4.9 `[web]`, `[security]`, `[retry]`, `[filesystem]`, `[unified_db]`

| 섹션.키 | 기본값 | 의미 |
|---|---|---|
| `web.host` | `"127.0.0.1"` | 웹 바인드 호스트 |
| `web.port` | `8765` | 웹 바인드 포트 |
| `web.token` | 없음 | 설정하면 `/api/*` 요청에 `Authorization: Bearer <token>` 필요. `/`, `/health`, `/ready`는 토큰 없이 열려 있다. |
| `security.allow_external_llm` | `false` | 설정 로더가 읽는 보안 플래그 |
| `security.redact_pii` | `false` | 설정 로더가 읽는 보안 플래그 |
| `retry.max_attempts` | `caps.max_derivation_attempts` | 최소 1로 클램프 |
| `retry.base_delay_seconds` | 1 | 최소 0으로 클램프 |
| `retry.max_delay_seconds` | 60 | 최소 0으로 클램프 |
| `filesystem.mode` | `"trusted-root"` | `strict` / `trusted-root` / `audit-only` 중 하나. 값이 그 셋이 아니면 조용히 `trusted-root`로 떨어진다. |
| `unified_db.dsn` | `postgresql://localhost:5433/unified` | 읽기 전용 unified DB 연결 문자열 |

> `sb web --host/--port` CLI 인자가 `[web]` 섹션보다 먼저 적용된다. `sb/cli.py: web()`은
> `config.web`을 읽지 않고 argparse 기본값 `127.0.0.1:8765`를 쓴다.

### 4.10 MCP 전용 섹션

| 섹션 | 키 | 의미 |
|---|---|---|
| `[mcp_scoped_read]` | `principal`, `agent`, `session`, `policy_revision` | 범위 제한 record 조회 연결(`scoped-record-read-v*`)이 신뢰하는 서버측 연결 문맥. 사용자 요청에서 복사하면 안 된다. |
| `[scoped_provider_verifier]` | `credentials_path` | scoped V4 요청 실행에 필요한 검증기 자격증명 JSON의 절대 경로. 파일은 서버 소유 비공개(0600) canonical JSON이며 `origin`, `cookie_id`, `csrf_token`(선택 `ca_file`)을 담는다. CA는 최대 256KiB PEM. |

---

## 5 CLI 레퍼런스

### 5.1 공통 규칙

- 진입점은 `sb.cli:main`. 인자가 하나도 없으면 도움말을 출력하고 **종료 코드 2**.
- 모든 명령은 실행 후 Vault 루트가 디렉터리이면 메트릭(`command`, `exit_code`, 소요 ms)을 기록한다
  (`sb/metrics.py: record_command`). 기록 실패는 무시된다.
- `main()`이 잡는 예외 —
  `OperationError`, `VaultLintError`, `GovernanceError`, `SearchQueryError`, `ConfigValueError`,
  `GenerationError`, `GenerationIndexError`, `PostCompactHookError` — 는 메시지를 stderr로 내고
  **종료 코드 1**로 끝난다.
- 아래 명령은 **읽기 전용 스냅샷**(`read_config`)에서 실행된다:
  `status`, `search`, `postcompact-hook`, `sources`, `retention`, `metrics`,
  `doctor`(단 `--rebuild-ledger` 없을 때), `gc`/`migrate`(`--apply` 없을 때),
  `compile`(`--dry-run` 또는 `--state-report`일 때).
- 파이프라인 계열 명령은 락을 못 잡으면 `already running`을 출력하고 **종료 코드 0**으로 끝난다.

전체 명령 목록(`sb --help`):

```text
init, ingest, compile, brief, run, status, rollback, doctor, mcp, search, remember,
apply-cancellation, apply-requests, maintain, postcompact-hook, retry, backup,
verify-backup, restore, migrate, resolve, web, sources, retention, gc, metrics
```

### 5.2 명령별 표

| 명령 | 목적 | 옵션 | 종료 코드 / 오류 코드 |
|---|---|---|---|
| `sb init` | Vault 디렉터리 생성, `log.md`/`.gitignore` 작성, 모드 `0700`, `git init -b main` + 최초 커밋 | 없음 | 0 |
| `sb ingest` | 설정된 원본을 스캔해 CAS 저장 + `source_item`/`unit` 원장 기록 | `--source <id>` (하나만 선택), `--limit <int>` (원본 항목 시도 수 상한; unit 예산은 별도로 계속 적용) | 0 / 1. 실패 사유는 stderr. 예: `INGEST_UNIT_BUDGET_EXCEEDED`, `SOURCE_ROOTS_AMBIGUOUS`, `SOURCE_READ_INCOMPLETE: <source>: <reason>`, `REINGRESS_VERIFICATION_FAILED`, `SOURCE_NOT_FOUND` |
| `sb compile` | 수집된 unit에서 wiki 페이지 파생 | `--llm <mode>` (기본 `cli`), `--dry-run`, `--state-report` | 0 / 1. `--dry-run`/`--state-report`는 JSON을 출력하고 항상 0. |
| `sb brief` | 오늘자 일일 브리핑 생성 | `--llm <mode>` (기본 `cli`) | 0 / 1 |
| `sb run` | ingest → compile → (조건부) brief 배치 | 없음 | 0 / 1. 배치 결과 선택 규칙은 §6.3. |
| `sb status` | 마지막 실행 한 줄 또는 전체 스냅샷 | `--json` | 0 |
| `sb rollback <run_id>` | **구현되지 않음.** 항상 거절 | 위치 인자 `run_id` | 항상 1, stderr `ROLLBACK_REQUIRES_GENERATION_AUTHORITY` |
| `sb doctor` | 진단 체크 목록 | `--json`, `--rebuild-ledger` | 체크 중 하나라도 `fail`이면 1, 아니면 0 |
| `sb mcp` | stdio MCP 서버를 하위 프로세스(`python -m sb.mcp`)로 기동 | 없음 | 하위 프로세스의 반환 코드. 모듈이 없으면 `mcp not available` + 1 |
| `sb search <query>` | 커밋된 페이지 검색 | `--limit <int>` (기본 10), `--json`, `--kind {wiki,daily,conflicts}` (반복 가능), `--status <s>`, `--updated-from <d>`, `--updated-to <d>`, `--scope {active,candidate,reference}` | 0. 빈 질의는 `search requires a query` + 2. 질의 문법 오류는 `SEARCH_QUERY_*` + 1. 구세대 인덱스는 `GENERATION_INDEX_INVALID` + 1 |
| `sb remember <content>` | inbox에 기억 노트 기록 | `--title <text>` | 0(경로 출력) / 빈 내용 2 / `RememberRejected` 1 |
| `sb retry` | 실패한 파생을 pending으로 되돌림 | `--stage {compile,conflict,brief}`, `--limit <int>` | 0 (`requeued=<n>` 출력). 선택에 `brief` 행이 섞이면 `BRIEF_REPLAY_INPUTS_UNAVAILABLE`로 **전체 거절** + 1 |
| `sb backup [destination]` | 백업 생성 후 즉시 검증 | 위치 인자 `destination`(생략 시 `<backup_root>/second-brain-<타임스탬프>.tar.gz`) | 0. 검증 실패는 1 |
| `sb verify-backup <archive>` | 기존 아카이브 검증 | 위치 인자 `archive` | 0 / 1 (`BACKUP_CHANGED`, `BACKUP_ORIGIN_MISMATCH`, `BACKUP_TOMBSTONE_OR_PROVIDER_MISMATCH`, `BACKUP_TIME_INVALID`, `BACKUP_STALE`) |
| `sb restore <archive>` | 백업을 **격리 목적지**로 복원 | `--to <dir>`, `--force` | 0 / 1. 목적지가 심링크이거나 관리형 배치의 활성 Vault면 `RESTORE_REQUIRES_ISOLATED_DESTINATION: use --to with a new directory` + 1 |
| `sb migrate` | 원장 스키마 상태 조회/적용 | `--check` \| `--apply` (상호 배타) | 0. JSON(`before`, `after`, `current`, `pending`, `backup`) 출력 |
| `sb resolve <conflict_id>` | 충돌을 사람이 해결 | `--decision {keep-left,keep-right,note}` (필수), `--note <text>` | 0(커밋 해시 또는 `unchanged`) / 1 |
| `sb web` | 루프백 HTTP 서버 실행 | `--host` (기본 `127.0.0.1`), `--port` (기본 `8765`) | 0 (Ctrl-C) / 바인드 실패 1 |
| `sb sources` | 설정된 원본 정책 상태 | `--json` | 0 |
| `sb retention` | CAS 보존 리포트(변경 없음) | `--json` | 0 |
| `sb gc` | 미참조 CAS blob 정리 | `--apply`, `--confirm`, `--json` | 0. `--apply`만 주고 `--confirm`이 없으면 `orphan deletion requires --apply --confirm` + 1 |
| `sb metrics` | 명령 실행 메트릭 요약 | `--limit <int>` (기본 1000), `--json` | 0 |
| `sb maintain --once` | 세대 정리 + 만료 내보내기 정리 + 고아 activation 스윕 + 실패 brief supersede | `--once` (필수), `--restore-workspace <abs dir>` | 0. `--once` 없으면 `maintain requires --once` + 2. 복원 작업공간 정리 실패 1. 선행 세대를 여는 fd가 남아 있으면 `GENERATION_READER_DRAIN_REQUIRED` + 1 |
| `sb apply-requests --once` | 요청 저널에서 최대 1건 처리 | `--once` (필수), `--test-control-socket <path>` | `--once` 없으면 2. 결과 `state`가 `idle`/`proved`/`reconciling`이면 0, `failed`면 1. 키 설정 문제는 `REQUEST_EXECUTOR_KEY_CONFIG_INVALID` / `SCOPED_PROVIDER_RUNTIME_CONFIG_INVALID` + 1 |
| `sb apply-cancellation --intent-id <id>` | 로컬 취소 의도 실행 | `--intent-id` (필수) | 0(JSON) / 1(대문자 스네이크 오류 코드, 정규화 실패 시 `CANCELLATION_EXECUTION_FAILED`) |
| `sb postcompact-hook` | AI 클라이언트 훅 이벤트를 stdin JSON으로 받아 처리 | 없음 | 0. stdin 파싱 실패 2(`HOOK_JSON_INVALID`, `HOOK_SESSION_MISSING`, `HOOK_QUERY_MISSING`, `HOOK_EVENT_UNSUPPORTED`, `HOOK_STAGE_UNSAFE`). stdout 파이프가 끊기면 1 |

### 5.3 자주 쓰는 형태

```bash
export SB_CONFIG="$HOME/.config/second-brain/config.toml"

sb remember "계약서는 수요일에 발송한다." --title "계약 일정"
sb run
sb search "계약서"
sb status --json
sb doctor --json
sb sources --json ; sb retention --json ; sb metrics --json
sb backup
sb verify-backup /path/to/second-brain-backup.tar.gz
sb restore /path/to/backup.tar.gz --to /absolute/new/restore-dir   # 격리 목적지 필수
sb maintain --once
sb retry --stage compile --limit 5                                  # brief 는 거절된다
```

### 5.4 `sb doctor` 체크 항목

`sb/ops.py: doctor()`가 만드는 체크 이름과 판정:

| 체크 | pass 조건 | 비고 |
|---|---|---|
| `python` | 항상 pass | 앱 버전 표시 |
| `git` | `git` 실행 파일 존재 | 없으면 fail |
| `vault` | Vault 디렉터리 존재. 모드에 group/other 비트가 없으면 pass, 있으면 warn | 없으면 fail 후 즉시 반환 |
| `git-repository` | `<vault>/.git` 디렉터리 존재 | |
| `ledger` | `ledger.db` 무결성 통과 + 스키마 버전 == 현재 | 버전 불일치는 warn, 파일 없음은 warn, 예외는 fail |
| `citations` | `audit_citations()`가 빈 튜플 | 미해결 `[^sid]`나 누락 CAS가 있으면 fail(최대 5건 표시) |
| `source:<id>` | 원본 `root`가 심링크가 아닌 디렉터리 | |
| `generation` | (관리형만) Vault git HEAD/tree가 세대 매니페스트와 일치 | 불일치 fail |
| `activation-orphans` | (관리형만) 현재 세대가 아닌 `activated` 행이 0 | 있으면 warn |
| `llm-cli` | `argv_template[0]`이 PATH에서 찾아짐 | 없으면 warn |
| `scheduler-assets` | 리포의 `deploy/systemd` 디렉터리 존재 | 휠 설치본에는 없으므로 운영에서는 warn이 정상 |

`--rebuild-ledger`는 `rebuild_from_vault`를 `GenerationOperation.EFFECT` mutation으로 실행한 뒤 체크를
돌린다. **이미 채워진 원장에서는 유효한 복구 수단이 아니다** — 2026-09-15 전환 기록에 따르면
`done → running` 전이 오류로 실패했다(§11).

### 5.5 `sb status --json` 스냅샷

`sb/ops.py: status_snapshot`이 만드는 키(원장이 있을 때):

- `last_batch` — `run_stage`에서 `stage='batch'`인 최신 행 (`run_id`, `status`, `started_at`,
  `finished_at`, `stages_attempted`, `written`, `errors`)
- `recent_stages` — 최근 10개 단계 행 (`run_id`, `stage`, `status`, `errors`, `error`, `detail`)
- `last_run`, `runs`(상태별 집계), `derivations`(상태별 집계), `failed`/`failed_by_stage`

`derivations`의 상태는 `DerivStatus` 5개다: `pending`, `running`, `done`, `failed`, `superseded`.

허용 전이(`sb/store/__init__.py: _ALLOWED`):

```text
pending    → running
running    → done | failed
done       → (없음)
failed     → superseded | pending
superseded → pending
```

`done`에서 나가는 전이가 없다는 점이 `doctor --rebuild-ledger`가 채워진 원장에서 실패하는 이유다.

---

## 6 파이프라인과 세대 수명주기

### 6.1 단계 정의

| 단계 | 하는 일 | 산출 |
|---|---|---|
| `ingest` | 어댑터별 커서로 스캔 → 중복 제거 → 재유입(tombstone) 검사 → CAS 저장 → `source_item`/`unit` 기록 | `written` (새 unit 수) |
| `compile` | pending 파생을 LLM으로 페이지화 | `wiki/*.md` `PageSpec` |
| `conflict` | 모순 후보 판정 | `conflicts/*.md` |
| `brief` | 오늘자 브리핑 | `daily/<date>.md` |

각 단계는 `_execute()`를 통해 실행되고, 관리형 배치에서는 같은 이름의 `GenerationOperation`
(`ingest`, `compile`, `brief`, `run`, `inbox`, `remember`, `effect`, `restore`) mutation으로 감싸진다.

### 6.2 수집 세부

`sb/pipeline.py: _prepare_adapter_ingest`

- `meta["skip_reason"] == "ambiguous-session-roots"` → 즉시 중단, `SOURCE_ROOTS_AMBIGUOUS`.
- 재시도 가능한 읽기 실패 집합 `_RETRYABLE_READ_FAILURES` =
  `{"size-limit", "database-limit", "unstable-session-file", "unreadable-session-file"}`
  → 항목을 건너뛰고 `SOURCE_READ_INCOMPLETE: <source_id>: <reason>`을 실패 사유로 남긴다.
- 이미 본 `(source_id, source_uri, source_version)`는 건너뛴다.
- `attempted >= remaining`이면 `capped = True`로 중단.
- 재유입 게이트(`ReingressGate`)에 걸리면 `TOMBSTONE_REINGRESS_BLOCKED`(오류 카운트 없음) 또는
  `REINGRESS_VERIFICATION_FAILED`(오류 카운트 증가).
- 새 unit 수가 `caps.max_new_units_per_run`을 넘으면
  `INGEST_UNIT_BUDGET_EXCEEDED: source requires N new units; caps.max_new_units_per_run=M. Source retained; increase the configured budget or split the source before retrying.`

### 6.3 `sb run` 배치 규칙 (중요)

`sb/pipeline.py: _run_all_mutable`

```text
1. 정체된 배치 정리(interrupt_stale_batches) + batch 행 'running' 기록
2. ingest 실행           → outcomes에 기록 → batch 진행 상황 갱신
3. compile 실행          → outcomes에 기록 → batch 진행 상황 갱신
4. if ingest.written == 0 and compiled.pages == 0:
       brief 를 실행하지 않는다
       (대신 compile 결과 또는 ingest 결과를 배치 결과로 재사용)
   else:
       brief 실행       → outcomes에 기록 → batch 진행 상황 갱신
5. _choose_batch_outcome(ingest, compiled, brief)
```

즉 **brief는 수집이 무언가를 썼거나 컴파일이 페이지를 만들었을 때만 돈다.** 아무 변화가 없는 시간당
실행은 LLM 호출 없이 끝난다.

`_choose_batch_outcome`의 우선순위:

1. `exit_code != 0`인 첫 단계가 있으면 그 단계를 반환(가장 먼저 실패한 단계가 이긴다).
2. `status == "capped"`인 단계가 있으면 그 단계를 후보로 잡는다.
3. `status == "partial"`인 첫 단계가 있으면 그 단계를 반환. (나중 단계가 성공해도 앞 단계의 오류를
   지우지 않는다.)
4. 그렇지 않으면 brief 결과.

배치 도중 예외가 나면 `run_stage`에 `failed` 배치 행(`{"failure": "batch interrupted by an exception", "stages": …}`)을
남기고 예외를 다시 던진다.

### 6.4 실행 결과 상태

`RunOutcome.status`로 나타나는 값: `ok`, `capped`, `partial`, `failed`.
`ledger_checks`는 `last_run_success`를 `status in {"ok", "capped"}`로 판정한다. 즉 `capped`는
readiness상 성공으로 친다.

### 6.5 세대 수명주기

관리형 배치에서 모든 내용 변경은 `GenerationMutationService.mutate()`를 통과한다.

```text
current(세대 A)            staging/<64hex>             새 세대 B              .retired/
     │  copy ─────────────────► │                          │                     │
     │                     apply(fn)                       │                     │
     │                          │ seal(0400/0500) + manifest                     │
     │                          └──────────────────────────► activations 행 기록  │
     │                                                     │                     │
     │◄──── share/vault 심링크 원자 교체 (phase=activated) ─┘                     │
     │                                                                            │
     └──── reader drain 확인(0 fd, 0 lease) ─► phase=disposing ─► 디렉터리 이동 ──┘
                                                                     │
                                                              삭제 후 phase=proved
```

- 봉인 모드: 파일 `0400`, 디렉터리 `0500` (`_seal_modes`). 되돌릴 때는 `0600`/`0700`(`_make_writable`).
- `activations` 테이블 `phase`: `claimed → staging → sealed → switch_intent → activated → disposing → proved`.
- 선행 세대 디렉터리를 연 fd가 하나라도 있으면 `GENERATION_READER_DRAIN_REQUIRED`.
- `/proc`이 없으면 `GENERATION_READER_DRAIN_UNVERIFIABLE`.
- 활성 링크와 `.retired/.legacy-active`가 모순되면 `GENERATION_SPLIT_BRAIN`.
- `share_root/vault`가 `vault_root`와 다르면 `GENERATION_ACTIVE_PATH_INVALID`.
- 스테이징 디렉터리 이름은 반드시 64자리 hex여야 하며, 아니면 `GENERATION_STAGING_UNSAFE`
  (`sb/generation_cleanup.py`).

### 6.6 `sb maintain --once`가 실제로 하는 일

`sb/cli.py: maintain()` → `GenerationMutationService.maintain(now)` → `_maintain_locked`:

1. `discard_abandoned_staging()` — 게시되지 않은 스테이징 트리를 디스크립터 기준으로 안전 삭제.
2. `store.activate(parent, None, now, lock_held=True)` — 중단된 활성화 복구.
3. `sweep_orphan_activations(now, current_id)` — **현재 세대가 아니고, reader lease로 고정돼 있지도
   않고, 디렉터리도 pointer 대상도 존재하지 않는** `activated` 행을 `proved` +
   `disposal_digest = digest("generation", {"reason": "orphan-missing-directory", …})`로 전이한다.
4. `lifecycle.maintain(now)` — 만료된 export 처분.

그 다음 CLI가 별도로 `settle_superseded_briefs(now)`를 호출한다:

- 현재 세대의 `ledger.db`에서 `stage='brief'`인 `failed` 개수와 `done` 개수를 읽는다.
- **둘 다 1건 이상일 때만** EFFECT mutation으로 `supersede_historical_brief_failures()`를 실행한다.
- 그 안에서 실패 brief 행은 다음 두 조건을 모두 만족할 때만 `superseded`로 바뀐다
  (`sb/store/ledger.py`):
  - 오류 문자열이 **일시적 LLM 오류가 아닐 것** (`error.casefold().startswith("llm unavailable")`이면 제외)
  - 그 행의 `finished_at`보다 **나중에 끝난 `done` brief 행이 존재**할 것 (`_has_later_done_brief`)
- 행은 삭제되지 않는다. 상태만 바뀌고 전이 이벤트가 기록된다.

출력은 한 줄 JSON이다:

```json
{"disposed_exports":0,"disposed_staging":0}
```

`--restore-workspace`를 주면 `disposed_restore_workspaces`와 `restore_workspace_busy`가 추가된다.
진행 중인 복원은 기다리지 않고 `restore_workspace_busy: true`로 보고한다. 옵션을 생략하면 해당
폴더를 찾지도, 정리하지도 않는다.

### 6.7 금기: 유지보수와 읽기 CLI 동시 실행

`sb maintain`이 선행 세대를 폐기할 때 `/proc`의 모든 fd를 훑는다. 같은 순간에 `sb status`나
`sb search`가 선행 세대 파일을 열고 있으면 폐기가 `GENERATION_READER_DRAIN_REQUIRED`로 실패하고
종료 코드 1이 된다. 2026-09-15 18:41 전환 기록에 이 사고가 그대로 남아 있고, 1분 뒤 단독 재실행에서
`activations 247 전부 proved`로 정상 종료했다.

---

## 7 검색 (CLI / MCP / Web)과 한계

### 7.1 질의 문법

`sb/search_query.py: LexicalQuery.parse`

- 입력 한도: **4,096 UTF-8 바이트**(`SEARCH_QUERY_TOO_LARGE: maximum 4096 UTF-8 bytes`)
- 그룹 한도: **32개**(`SEARCH_QUERY_TOO_MANY_GROUPS: maximum 32`)
- 제어 문자(탭/CR/LF 제외, DEL 포함) 금지: `SEARCH_QUERY_CONTROL_CHARACTER`
- 큰따옴표로 정확 문구 그룹을 만든다. 닫히지 않으면 `SEARCH_QUERY_SYNTAX: unclosed quoted phrase`,
  그룹 뒤에 공백 없이 문자가 붙으면 `SEARCH_QUERY_SYNTAX: separate quoted groups with whitespace`,
  빈 문구는 `SEARCH_QUERY_SYNTAX: empty quoted phrase`.
- 인용 그룹 안에서 `\"`는 따옴표 문자, `\\`는 역슬래시 문자다.
- 중복 그룹은 제거된다(`dict.fromkeys`).

```bash
sb search "배포 오로라"                 # 두 단어가 모두 들어간 자료 (어순 무관)
sb search '노을 "세 번 실패"'           # '노을' + 정확 문구 '세 번 실패'
```

### 7.2 매칭 규칙 (이것이 한계의 근원이다)

`LexicalQuery.predicate()`:

```sql
(instr(compact, ?) > 0 OR instr(normalize_id, ?) > 0 OR instr(normalize_section, ?) > 0)
AND … (모든 검색어에 대해 반복)
```

`normalize(text)` = `casefold()` 후 **모든 공백 제거**. 즉:

- 질의는 **공백으로 토큰 분리**된다.
- 각 토큰은 문서 본문/페이지 ID/섹션명에 **그대로 부분 문자열로 들어 있어야** 한다.
- 모든 토큰이 만족해야 한다(AND).
- 형태소 분석·어간 추출·불용어 제거·동의어 확장은 **없다**.

순위(`ordering()`):

- 토큰이 1개면 상대 빈도 기반 점수 내림차순.
- 2개 이상이면 **입력 문구 전체가 연속으로 들어간 결과를 먼저**(CASE 0), 그다음 점수 순.
- 동점은 `page_id, section, rowid`.

### 7.3 범위(scope)와 필터

`sb/search_filters.py: SearchFilters.predicate`

| `--scope` | 동작 |
|---|---|
| `active` (기본, 그리고 인식되지 않는 값의 fallback) | `knowledge_status = ACTIVE AND approval_status = APPROVED` |
| `candidate` | `knowledge_status = CANDIDATE` |
| `reference` (또는 내부적으로 `all`) | 지식 상태 필터 없음 |

CLI의 기본값은 조건부다(`sb/cli.py: search()`): `--scope`를 주지 않았고
`<vault_root>/generation.json`이 파일로 존재하면 `reference`, 아니면 `active`.
관리형 세대 Vault에는 `generation.json`이 있으므로 운영 CLI 검색의 기본은 `reference`다.

그 외 필터: `--kind`(`wiki`/`daily`/`conflicts`, 반복 가능), `--status`, `--updated-from`,
`--updated-to`.

### 7.4 결과 필드

`SearchHit.as_dict()`가 내보내는 키:
`page_id`, `section`, `snippet`, `score`, `kind`, `index_status`, `knowledge_status`,
`approval_status`, `canonical`, `source_ref`, `updated_at`, `role`, `verification`.

`role`/`verification` 라벨은 파생값이다(`_labels`):
`knowledge_status == ACTIVE and approval_status == APPROVED` → `("CANONICAL", "VERIFIED")`,
그 외 전부 → `("REFERENCE", "UNVERIFIED")`.

### 7.5 MCP 검색

`sb/mcp.py: sb_search(query, limit=10, read_fence=None)`

- 세대를 핀으로 고정한 뒤(`pin_generation`) 검색한다. 응답에는 세대 바인딩 정보가 붙는다.
- `limit <= 0`이거나 빈 질의는 빈 결과.
- 계약 스키마 4 이상에서는 페이지당 1회만 훑고, 그 페이지의 **기억 레코드** 중
  `parsed.matches_record(record.record_text)`를 통과한 것만 반환한다. 즉 **모든 검색어가 같은
  인용 레코드 안에** 있어야 한다(README도 같은 말을 한다). snippet은 레코드 본문 400자로 자른다.
- `hybrid`가 켜져 있으면 `semantic_hits`를 `merge_semantic_records`로 합친다.
- 반환 필드: `page_id`, `section`, `snippet`, `score` (+스키마 4↑에서 `record_id`, `record_digest`).

기본 stdio 프로필의 도구 구성:

| 프로필(`SB_MCP_CONTRACT_PROFILE`) | 스키마 | 도구 |
|---|---|---|
| (미설정, 레거시) | 3 | `sb_search`, `sb_read_page`, `sb_recent_changes`, `sb_open_conflicts`, `sb_remember`, `sb_write_request` (6개) |
| `task30-schema3` | 3 | 위 6개 + `sb_generation_status`, `sb_request_status`, `sb_resolve_memory_target` |
| `task32-schema4` | 4 | 9개 (릴리스 래퍼 `second-brain-mcp`의 기본값) |
| `remember-schema5` | 5 | 9개, `sb_write_request`가 `remember-schema5` 계약 |
| `cancellation-schema6` | 6 | 위 + `sb_cancellation_status` |
| `cancellation-submit-schema7` | 7 | 위 + `sb_submit_cancellation` |
| `scoped-record-read-v1…v5` | 4 | `sb_read_page`, `sb_search` (+v2↑ `sb_generation_status`, +v5 `sb_request_status`). `[mcp_scoped_read]` 필수 |
| `scoped-request-status-v1` | — | `sb_request_status` 하나 |
| `scoped-request-write-v1` | — | `sb_write_request` 하나. `[scoped_provider_verifier]` 필수 |

알 수 없는 프로필 값은 `SECOND_BRAIN_CONTRACT_PROFILE_INVALID`로 기동을 거절한다.
`sb_run`은 **desktop 서버 표면에만** 있고 일반 stdio 목록에는 없다.

### 7.6 Web 검색과 그 외 엔드포인트

`sb/web.py`. `/api/*`는 `[web] token`이 설정돼 있으면 `Authorization: Bearer <token>`을 요구한다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/` | 내장 HTML 콘솔 |
| GET | `/health` | `{"status":"ok"}` — 프로세스 생존만 |
| GET | `/ready` | readiness 판정. `ready`면 200, 아니면 **503** + `reasons` 배열 |
| GET | `/api/status` | 실행 상태 요약(한국어 요약 문자열 포함) |
| GET | `/api/capabilities` | `supported_suffixes`, `max_upload_bytes` 등 |
| GET | `/api/briefing/latest` | 최신 브리핑 |
| GET | `/api/search?q=&limit=&kind=&status=&updated_from=&updated_to=&scope=` | 검색(limit 상한 100) |
| GET | `/api/pages/<page_id>` | 페이지 읽기 |
| GET | `/api/changes?days=` | 최근 변경(days 상한 3650) |
| GET | `/api/conflicts` | 미해결 충돌 |
| GET | `/api/sources` | 원본 정책 상태 |
| GET | `/api/retention` | 보존 리포트 |
| GET | `/api/metrics?limit=` | 메트릭(limit 상한 10000) |
| POST | `/api/uploads` | 파일 업로드(base64). 성공 시 `queued`면 201, 아니면 200 |
| POST | `/api/remember` | `{content, title?}` → 201 `{inbox_path}` |
| POST | `/api/inbox-discard` | `{inbox_path}` → `{discarded}` |
| POST | `/api/run` | `sb run` 실행. 실패 사유는 자격증명 마스킹 후 1000자로 잘라 반환 |
| POST | `/api/pages/<page_id>/forget` | 컴파일된 페이지 삭제 → `{forgotten, commit}` |
| POST | `/api/conflicts/<id>/resolve` | `{decision, note}` |

업로드 한도: `MAX_UPLOAD_BYTES = MAX_INBOX_BYTES = 10 MiB`.
일반 JSON 본문 한도: `MAX_BODY_BYTES = 1 MiB`. 업로드 요청은 base64 오버헤드를 감안해
`((10MiB+2)//3)*4 + 64KiB`까지 허용한다.

### 7.7 한국어 검색의 알려진 한계 (정직한 서술)

`sb/search_query.py`가 질의를 공백으로 쪼개고 **모든 토큰을 부분 문자열로 AND 요구**하기 때문에,
조사·어미가 붙은 자연어 질문은 구조적으로 0점이 된다. `unified-db의`, `며칠인가요?` 같은 토큰은
문서에 그대로 존재할 수 없다.

`M10-GOLD-CURATED-2026-09-15.md` §3.1이 보고한 측정값(격리 fixture, 문서 40 / 케이스 131, limit 5):

| 지표 | CLI | MCP |
|---|---|---|
| hit@1 | 0.226 | 0.217 |
| recall@5 | 0.226 | 0.217 |
| MRR@5 | 0.226 | 0.217 |
| negative_empty_rate (no_answer 정밀도) | 1.0 | 1.0 |
| forbidden_exposure@5 | 0.0 | 0.0 |

kind별 recall@5:

| kind | 건수 | CLI | MCP |
|---|---|---|---|
| exact_phrase | 9 | 0.667 | 0.667 |
| keyword | 23 | 0.783 | 0.739 |
| reordered_terms | 2 | 1.0 | 1.0 |
| **natural_question** | 66 | **0.0** | **0.0** |
| **paraphrase** | 13 | **0.0** | **0.0** |
| stale_decision | 2 | 0.0 | 0.0 |

운영 릴리스 CLI에 같은 131개 질의를 던진 보조 프로브(§3.2)도 거의 같은 값이다:
hit@1 0.209, recall@5 0.241, exact_phrase 0.778 / keyword 0.815, natural_question·paraphrase 0.0.

결론(§3.3 그대로):

- **자연어 질문·패러프레이즈 회수율은 정확히 0이다(79건).** 형태소 분석·n-gram·의미 검색 중
  하나가 붙기 전에는 데이터셋을 어떻게 고쳐도 0이다.
- **키워드/정확 구절은 0.67–0.82로 이미 쓸 만하다.** 문제는 색인이 아니라 질의 정규화다.
- `no_answer` 정밀도 1.0, forbidden 노출 0.0 — 없는 것을 지어내지는 않는다. 다만
  `stale_decision` 2건의 0.0은 "잘 배제했다"가 아니라 "둘 다 안 나왔다"에 가깝다.
- 격리 실행에서 `hit@1 == recall@5 == MRR@5`인 것은 우연이 아니다. 맞힌 케이스는 전부 1위로 맞혔고,
  1위에 없으면 2–5위에도 없었다.

**실무 지침: 핵심 명사를 공백으로 나열하라. 조사·어미·물음표를 빼라.**

```bash
# 잘 되는 형태
sb search "백업 검증 절차"
sb search '릴리스 "reader drain"'

# 0점이 나오는 형태
sb search "백업은 어떻게 검증하나요?"
```

---

## 8 AI 클라이언트 기억 훅 (Claude Code / Codex CLI / OmO)

### 8.1 목적

대화가 컴팩션될 때 **손실되는 사실을 Second Brain에서 되찾아 다음 모델 요청 앞에 붙인다.**
세 클라이언트 모두 같은 명령(`sb postcompact-hook`)을 쓰며, 이벤트 JSON을 stdin으로 받고 훅 페이로드
JSON을 stdout으로 낸다.

### 8.2 공통 래퍼

`~/.config/second-brain/hooks/sb-memory-hook.sh` (설치본 그대로):

```sh
#!/bin/sh
# second-brain memory hook bridge (Claude Code / Codex CLI / OmO).
# Reads the client's hook event JSON on stdin and forwards it to the current
# second-brain release. Never fails the client: any error prints nothing.
SB_BIN="${SB_MEMORY_BIN:-$HOME/.local/state/second-brain/app/current/bin/sb}"
[ -x "$SB_BIN" ] || { cat >/dev/null 2>&1; exit 0; }
exec "$SB_BIN" postcompact-hook
```

설계 요점:

- `app/current/bin/sb`를 쓰므로 릴리스를 전환하면 훅도 자동으로 새 릴리스를 탄다.
- 릴리스가 없거나 실행 불가면 **stdin을 비우고 조용히 0으로 종료**한다. 클라이언트를 절대 실패시키지
  않는다.
- 래퍼가 쓰는 설정은 릴리스 래퍼의 기본값, 즉 `$HOME/.config/second-brain/config.toml`이다.
  다른 설정을 쓰려면 `SB_CONFIG`를, 다른 바이너리를 쓰려면 `SB_MEMORY_BIN`을 환경에 준다.

### 8.3 훅 계약 (`sb/postcompact_hook.py`)

세 이벤트만 받는다. 그 외에는 `HOOK_EVENT_UNSUPPORTED`.

| 이벤트 | 읽는 필드 | 하는 일 | stdout |
|---|---|---|---|
| `PostCompact` | `query` 또는 `compact_summary`(필수), `trigger`/`matcher` | 검색 → 레코드 선별 → **스테이지 파일에 저장**. 주입하지 않는다. | `{}` |
| `UserPromptSubmit` | `prompt` / `content` / `query` | 프롬프트로 검색해 `last_query`를 갱신. 스테이지에 미전달 레코드가 있으면 그것을 주입. | `{}` 또는 `hookSpecificOutput` |
| `SessionStart` | `source`(=`compact`일 때만 동작), `query`/`compact_summary` | 이번 턴에 바로 주입할 문맥을 만든다. 남는 레코드는 스테이지에 남긴다. | `hookSpecificOutput` |

공통 필드: `session_id`(없으면 `HOOK_SESSION_MISSING`). JSON이 아니면 `HOOK_JSON_INVALID`.

주입 페이로드 형태:

```json
{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "<본문>"}}
```

`additionalContext` 본문 형식(`_context_text`):

```text
session_id: <id>
budget: items<=8 excerpt<=4096 total<=16384
record page_id=<id> source_ref=<origin> record_id=<id> version=<digest>
<레코드 본문>
record …
```

예산 상수:

| 상수 | 값 | 의미 |
|---|---|---|
| `_MAX_ITEMS` | 8 | 최대 레코드 수 |
| `_MAX_EXCERPT_BYTES` | 4,096 | 레코드 본문 바이트 상한 |
| `_MAX_TOTAL_BYTES` | 16,384 | 페이로드 JSON 전체 바이트 상한. 넘으면 뒤에서부터 레코드를 하나씩 버린다. |
| `_MAX_CANDIDATE_TOKENS` | 32 | 요약에서 뽑는 후보 검색어 수 |
| `_SHORT_TERM` | 6 | 이보다 짧은 검색어는 단어 경계 일치만 인정 |

### 8.4 stage / last_query / 중복 억제 설계

스테이지 파일: `<state_root>/.sb/session-memory/<sanitized session_id>.json`
(`_stage_path`). 디렉터리는 `0700`으로 만들고 `O_NOFOLLOW|O_DIRECTORY`로 열어 심링크 공격을 막는다.
파일은 `O_NOFOLLOW|O_CREAT`로 `0600`으로 열고 일반 파일인지 `fstat`으로 확인한 뒤 `ftruncate`+`write`+`fsync`한다.
어긋나면 `HOOK_STAGE_UNSAFE`.

스테이지 스키마(`_write_stage`):

| 필드 | 의미 |
|---|---|
| `session_id` | 세션 식별자 |
| `event_digest` | `sha256(session_id \0 occurrence_id \0 summary)`. `occurrence_id`는 `prompt_id`/`compaction_id`/`event_id`/`uuid` 등으로 구성 |
| `delivered` | 남은 레코드가 없어 전달이 끝났는지 |
| `context` | 다음 `UserPromptSubmit`에서 쓸 잔여 문맥 문자열 |
| `records` | 아직 전달하지 않은 레코드 배열 |
| `last_query` | 마지막으로 유용했던 검색어들(공백 결합) |
| `delivered_in_turn` | 이미 전달한 레코드 키(`record_id \0 version`) 목록 |
| `in_turn` | 이번 턴에 주입한 레코드(확정 대기) |

동작 흐름:

1. **`UserPromptSubmit`** — 프롬프트로 `_hook_search`를 돌려 결과가 있으면 `last_query`를 그 검색어들로
   갱신한다(`_remember_last_query`). 스테이지가 없거나 `delivered: true`면 아무것도 주입하지 않는다.
   미전달 레코드가 있으면 `context`를 그대로 주입하고 `pending_confirm`을 세운다.
2. **`PostCompact`** — 요약으로 검색해 레코드를 만든 뒤, `delivered_in_turn`에 이미 있는 것을 제외한다
   (`_exclude_delivered`). `event_digest`가 직전과 같으면 `duplicate`로 보고 스테이지를 다시 쓰지 않는다.
   **주입은 하지 않고** `{}`만 출력한다.
3. **`SessionStart(source=compact)`** — 질의는 이벤트의 요약, 없으면 스테이지의 `last_query`를 쓴다.
   둘 다 없으면 아무것도 하지 않는다. `event_digest`가 같고 이미 `delivered`면 중복으로 보고 건너뛴다.
   검색 결과를 **이번 턴에 바로 주입**하고, 직전에 남아 있던 미전달 레코드 중 이번 턴 키와 겹치지 않는
   것만 `records`(잔여)로 남긴다.
4. **`confirm_delivery`** — CLI가 stdout 쓰기에 성공한 뒤에만 호출된다(`sb/cli.py: postcompact_hook`).
   `in_turn`에 있던 레코드 키를 `delivered_in_turn`에 합치고 `in_turn`을 비운다. 잔여가 없으면
   `delivered = true`. **stdout이 끊기면(BrokenPipe, 종료 코드 1) 전달로 기록하지 않는다.**

검색 방식(`_hook_search`, `_weighted_terms`):

- 요약에서 3자 이상, 불용어가 아닌 토큰을 빈도·식별자 성격(한글/CamelCase 우선)으로 정렬해 최대 32개
  뽑는다(`_candidate_tokens`).
- 각 토큰으로 `limit = 8*4 = 32`까지 검색한다. 결과가 **0건이거나 32건 이상인 토큰은 버린다**
  (너무 흔한 토큰 제거).
- 남은 토큰의 가중치는 `1/결과수`. 페이지·섹션 단위로 가중치를 합산해 내림차순 정렬한다.
- 6자 미만 토큰은 snippet에서 단어 경계로 정확히 일치할 때만 인정한다(`_standalone_term`).

레코드 선별(`_matching_records`): 히트 페이지의 `.md`를 읽어 `parse_page_records`로 기억 레코드를
쪼갠 뒤, 후보 검색어 중 하나라도 포함한 레코드만 고른다. 각 레코드에는 `page_id`, `source_ref`
(프론트매터 `sources` 또는 각주 정의 `[^sid]: origin`에서 복원), `record_id`, `version`(레코드 다이제스트),
`snippet`이 붙는다.

### 8.5 Claude Code 설치

`~/.claude/settings.json`의 `hooks`에 세 항목을 추가한다(설치된 실제 값):

| 이벤트 | matcher | command | timeout |
|---|---|---|---|
| `UserPromptSubmit` | (없음) | `/bin/sh /home/jm/.config/second-brain/hooks/sb-memory-hook.sh` | 20 |
| `SessionStart` | `compact` | 같음 | 20 |
| `PostCompact` | (없음) | 같음 | 20 |

JSON 형태:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command", "command": "/bin/sh /home/jm/.config/second-brain/hooks/sb-memory-hook.sh", "timeout": 20 } ] }
    ],
    "SessionStart": [
      { "matcher": "compact",
        "hooks": [ { "type": "command", "command": "/bin/sh /home/jm/.config/second-brain/hooks/sb-memory-hook.sh", "timeout": 20 } ] }
    ],
    "PostCompact": [
      { "hooks": [ { "type": "command", "command": "/bin/sh /home/jm/.config/second-brain/hooks/sb-memory-hook.sh", "timeout": 20 } ] }
    ]
  }
}
```

**Claude Code 2.1.270의 실제 계약** (`CLAUDE-NATIVE-COMPACT-PROBE-2026-09-15.md`, 실세션 관측):

- 컴팩션 시 호출 순서는 **`SessionStart(source=compact)` → `PostCompact`**다.
- `SessionStart(compact)`의 `additionalContext`는 **그 턴 안에서 주입된다.** transcript에서
  `attachment.type = hook_additional_context`, `hookName = SessionStart`로 확인됐고, 다음 모델 요청
  이전에 존재했다.
- **`PostCompact`의 `additionalContext`는 무시된다.** 그래서 SB의 `PostCompact` 처리는 주입을 시도하지
  않고 스테이지만 만든다.
- 수동 `/compact`와 자동 compaction 모두 같은 코드 경로이며, `trigger` 값만 `manual`/`auto`로 다르다.
  자동 트리거도 `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=4`로 임계값을 낮춘 실세션에서 3회 실관측됐다.
- 관측된 실제 입력에는 `SessionStart`에 summary가 없었고, 그때 SB는 스테이지의 `last_query`로 검색해
  올바른 레코드를 주입했다. `last_query` 설계가 여기서 결정적이다.

### 8.6 Codex CLI 설치

`~/.codex/hooks.json`은 Claude Code와 **같은 세 이벤트·같은 command·같은 timeout 20**을 쓴다. 다만
최상위에 `{"hooks": { … }}` 한 겹이 더 있다(§8.5의 JSON에서 `hooks` 객체만 그대로 옮기면 된다).

**주의(운영 기록에 남은 함정):** Codex는 `hooks.json`을 바꾼 뒤 TUI 첫 실행에서
"Hooks need review" → **"Trust all and continue"** 를 사용자가 한 번 선택해야 훅이 켜진다.
신뢰 이전에는 **조용히 실행되지 않는다**(오류도 안 난다). 자동화 실행에는
`--dangerously-bypass-hook-trust`를 쓴다.

컴파일용 격리 `CODEX_HOME`에는 `hooks.json`이 없으므로 LLM 백엔드 실행에는 영향이 없다.

### 8.7 OmO / senpi 설치

`~/.omo/agent/extensions/sb-memory.js`. 확장은 두 이벤트만 건다.

| OmO 이벤트 | 매핑 | 동작 |
|---|---|---|
| `before_agent_start` | `UserPromptSubmit` | `prompt`를 넘겨 `last_query`를 갱신하고, 반환된 문맥이 있으면 `{ message: { customType: "sb-memory", content, display: false } }`로 조용히 주입 |
| `session_compact` (`event.accepted`일 때만) | `PostCompact` → `SessionStart(compact)` | 먼저 `PostCompact`(`trigger`는 `reason === "manual" ? "manual" : "auto"`, `compact_summary`)로 스테이징, 그다음 `SessionStart(source: "compact")`로 문맥을 받아 `pi.sendMessage(..., { deliverAs: "steer" })`로 이번 턴에 주입 |

환경 변수:

| 변수 | 기본값 | 의미 |
|---|---|---|
| `SB_MEMORY_BIN` | `$HOME/.local/state/second-brain/app/current/bin/sb` | 호출할 바이너리 |
| `SB_MEMORY_CONFIG` | (없음) | 설정하면 `SB_CONFIG`로 전달 |
| `SB_MEMORY_LOG` | (없음) | 설정하면 IN/OUT 라인을 그 파일에 append |

타임아웃은 코드 상수 `TIMEOUT_MS = 20000`. 훅 종료 코드가 0이 아니거나 stdout이 비면 `null`을
반환해 아무것도 주입하지 않는다.

실행 중인 OmO 세션은 `/reload` 또는 재시작해야 확장이 적용된다.

### 8.8 훅 동작 확인

```bash
SB=~/.local/state/second-brain/app/current/bin/sb
printf '{"hook_event_name":"UserPromptSubmit","session_id":"probe-1","prompt":"배포 일정"}' | "$SB" postcompact-hook
printf '{"hook_event_name":"SessionStart","session_id":"probe-1","source":"compact"}'      | "$SB" postcompact-hook
cat "$HOME/.local/state/second-brain/.sb/session-memory/probe-1.json"
```

세 명령 모두 종료 코드 0이어야 하고, 두 번째가 `hookSpecificOutput`을 내면 주입 경로가 살아 있다.

---

## 9 JARVIS 연동

### 9.1 역할 분담

```text
 JARVIS (Orca-JARVIS)                    Second Brain (provider)
 ───────────────────────                 ────────────────────────
  memreq 작성 + Ed25519 서명  ──────►  request_root/pending/<file>
                                                │
                                   jm-second-brain-requests.path 감지
                                                │
                                        sb apply-requests --once
                                                │
                                        세대 mutation 실행 + 증명 서명
                                                │
                              journal.db 상태 전이 · receipts/ 영수증
                                                │
  sb_request_status / scoped 읽기  ◄────────────┘
```

JARVIS는 SB 안에서 쓰기를 직접 하지 않는다. **요청을 저널에 넣고, SB의 executor가 단일 writer로
실행**한다.

### 9.2 요청 상태 기계

`requests.state` (CHECK 제약, `sb/request_store.py`):

| 상태 | 의미 |
|---|---|
| `pending` | 수락됐고 아직 claim 되지 않음 |
| `processing` | executor가 lease(`owner`, `owner_process_id`, `owner_process_start`, `lease_expires_at`, `fence>0`)를 잡고 진행 중 |
| `proved` | 증명까지 끝난 최종 성공 |
| `failed` | 실패 |
| `expired` | 만료 |
| `reapproval_required` | 재승인 필요 |

`requests.phase` (세대 진행 단계, NULL 허용):
`claimed` → `staging` → `sealed` → `switch_intent` → `activated` → `disposing` → `proved`.

lease 무결성은 스키마 CHECK로 강제된다: `owner`가 있으면 `owner_process_id`,
`owner_process_start`, `lease_expires_at`이 모두 있어야 하고 `fence > 0`이어야 한다. 넷 다 NULL이거나
넷 다 채워져 있거나 둘 중 하나만 유효하다.

관련 테이블: `request_aliases`(멱등 별칭), `delegation_uses`(위임 1회 소비),
`phase_events`(단계 이벤트, `event_digest` UNIQUE), `tombstone_replica` / `tombstone_target_identities`
(삭제 이력 복제본, UPDATE/DELETE 트리거로 불변), `legacy_imports`, `reader_leases`,
`reader_process_identities`.

### 9.3 `sb apply-requests --once`

전제 조건(`sb/cli_requests.py`):

- `jarvis_public_keys`가 비어 있지 않을 것
- `provider_signing_key_id`와 `provider_private_key`가 설정돼 있을 것
- 키가 base64url로 파싱될 것
- 철회된 키(`revoked_jarvis_signing_key_ids` + `<state_root>`의 런타임 철회 파일)를 제외하고도 신뢰 키가
  남아 있을 것

하나라도 어긋나면 `REQUEST_EXECUTOR_KEY_CONFIG_INVALID` + 종료 코드 1.
scoped provider 설정이 잘못되면 `SCOPED_PROVIDER_RUNTIME_CONFIG_INVALID` + 1.

실행(`RequestExecutor.apply_once`, 기본 `worker = "sb-apply-once"`, `lease_ms = 60_000`):

1. `mutations.maintain(observed)` — 유지보수를 먼저 돌린다.
2. `_finalize_proved()` — 이미 증명된 건 마무리.
3. `store.claim(...)` — claim 실패 시 즉시
   `ApplyResult(None, "idle", None, "NO_PENDING_REQUEST", 0)`.
4. 스키마 버전별 분기: 1/3(그리고 scoped authority가 있는 4)은 remember 경로, 2는 effect 경로.
5. 결과를 `prove`로 확정.

출력은 정렬된 한 줄 JSON이다:

```json
{"code":"NO_PENDING_REQUEST","fence":0,"phase":null,"request_id":null,"state":"idle"}
```

종료 코드: `state`가 `idle` / `proved` / `reconciling`이면 **0**, `failed`면 **1**.

```bash
SB_CONFIG=/home/jm/.config/second-brain/config.toml sb apply-requests --once
```

### 9.4 `sb retry`

실패한 **파생**(derivation)을 pending으로 되돌린다. 요청 저널과는 별개다.

```bash
sb retry                      # 모든 단계의 failed
sb retry --stage compile
sb retry --stage conflict --limit 10
```

- `reset_attempts=True`로 되돌리므로 시도 횟수가 0이 된다.
- 선택된 집합에 `brief` 행이 **하나라도** 있으면 아무것도 바꾸지 않고
  `BRIEF_REPLAY_INPUTS_UNAVAILABLE: historical brief retry is held; failed rows and attempts are preserved`
  로 실패한다. 과거 브리핑은 고정된 입력과 대상 날짜 없이 재생할 수 없기 때문이다.
- 출력은 `requeued=<n>`.

### 9.5 `sb apply-cancellation`

```bash
sb apply-cancellation --intent-id <intent id>
```

`sb/cli_cancellation.py`: `execute_cancellation(intent_id, config, load_authority=load_config, clock=…)`을
호출하고 결과를 정렬된 한 줄 JSON으로 출력한다. 스케줄러도, 암묵적 일괄 정리도 없다 — **명시적 1건 실행**이다.

실패 시 stderr에 대문자 스네이크 코드 하나만 낸다. 코드가 비었거나 96자를 넘거나 `A-Z0-9_`가 아닌
문자를 포함하면 `CANCELLATION_EXECUTION_FAILED`로 정규화한다. 종료 코드 1.

취소 의도를 제출할 수 있는 키는 `cancellation_public_keys`에 따로 등록된 것뿐이다.
MCP 쪽에서는 `cancellation-schema6`가 `sb_cancellation_status`를, `cancellation-submit-schema7`이
`sb_submit_cancellation`을 추가로 제공한다.

### 9.6 scoped 쓰기 프로필

JARVIS가 MCP로 쓰기 요청만 보내는 전용 연결:

```bash
SB_CONFIG=/home/jm/.config/second-brain/write-config.toml \
SB_MCP_CONTRACT_PROFILE=scoped-request-write-v1 sb mcp
```

- 이 설정에는 `[mcp_scoped_read]`를 넣지 않는다. `[scoped_provider_verifier]`가 필요하다.
- 제공 도구는 `sb_write_request(request)` 하나다.
- 응답은 **수락 영수증**이다. 실제 처리는 `apply-requests --once`가 하고, 완료 확인은
  별도 `scoped-record-read-v5` 연결로 한다.
- **오류나 연결 종료만으로 미수락을 단정하고 재전송하면 안 된다**(README 경고).

읽기 전용 scoped 연결은 `[mcp_scoped_read]`의 `principal`/`agent`/`session`/`policy_revision`을 쓰며,
서명된 `read_fence`와 `access_claim`을 요구한다. 파일 기반 정책·키 철회를 매 조회 전후로 다시 읽고,
누락·손상·조회 중 변경·만료는 거부한다. 세션·provider·저장소 경로가 바뀌면 새 연결이 필요하다.

### 9.7 운영 연동 지점 요약

| 요소 | 값 |
|---|---|
| 요청 디렉터리 | `~/.local/state/second-brain/requests/{pending,processing,receipts}` + `journal.db` |
| 트리거 | `jm-second-brain-requests.path` (`DirectoryNotEmpty=…/requests/pending`) |
| 게이트 파일 | `~/.config/second-brain/request-executor.enabled` (`ConditionPathExists`) — 이 파일이 없으면 path 유닛이 아예 활성화되지 않는다 |
| 실행 유닛 | `jm-second-brain-requests.service` → `app/current/bin/sb apply-requests --once` |
| provider 설정 | `SB_CONFIG=~/.config/second-brain/config.toml` (drop-in `20-runtime.conf`) |

---

## 10 운영

### 10.1 systemd 사용자 유닛

리포가 제공하는 유닛(`deploy/systemd/`)과 실제 운영 유닛이 다르다. 운영에서 **실제로 도는 것**은
다음 표의 아래쪽 네 개다.

| 유닛 | 출처 | ExecStart | 스케줄 |
|---|---|---|---|
| `second-brain-web.service` | 리포 | `sb web --host 127.0.0.1 --port 8765` | 상시(`Restart=on-failure`, `RestartSec=3s`) |
| `second-brain.service` / `.timer` | 리포 | `sb run` / `OnCalendar=hourly` | 운영에서는 inactive. drop-in으로 `jm-second-brain-hourly` 래퍼와 `TimeoutStartSec=3h`가 덮여 있다 |
| `second-brain-backup.service` / `.timer` | 리포 | `sb backup` / `OnCalendar=*-*-* 03:15:00`, `Persistent=true`, `RandomizedDelaySec=15min` | 매일 |
| `jm-second-brain-refresh.service` / `.timer` | JARVIS 배포 | `${SECOND_BRAIN_REFRESH_ENTRYPOINT}` (= `~/.local/state/second-brain/bin/jm-second-brain-refresh`, 내부적으로 `sb run`) / `OnCalendar=hourly` | 매시간 |
| `jm-second-brain-maintenance.service` / `.timer` | JARVIS 배포 | `sb maintain --once` / `OnCalendar=hourly` | 매시간 |
| `jm-second-brain-requests.path` / `.service` | JARVIS 배포 | `app/current/bin/sb apply-requests --once` | `requests/pending`이 비지 않을 때 |

공통 보안 설정(리포 유닛): `NoNewPrivileges=true`, `PrivateTmp=true`, `ProtectSystem=strict`,
`UMask=0077`, `ReadWritePaths=-%h/.local/share/second-brain -%h/.local/state/second-brain -%h/.config/second-brain`.
refresh/maintenance 유닛은 추가로 `ProtectHome=read-only`, `RestrictSUIDSGID`, `LockPersonality`,
`MemoryDenyWriteExecute`를 건다.

알려진 drop-in:

| drop-in | 내용 | 이유 |
|---|---|---|
| `second-brain.service.d/10-unseal-live.conf` | `ExecStartPre=/usr/bin/chmod -R u+w …/vault` | 봉인 세대는 `0500`이라 `.sb/run.lock` 생성을 위해 쓰기 권한이 필요 |
| `jm-second-brain-refresh.service.d/10-share-write.conf` | `ReadWritePaths=%h/.local/share/second-brain` 추가 | 세대 저장소가 share 아래에 있음 |
| `jm-second-brain-refresh.service.d/20-llm-runtime.conf` | `MemoryDenyWriteExecute=false`, `ReadWritePaths=%h/.codex`, `TMPDIR=/var/tmp` | Node 기반 LLM 런처가 JIT 실행 메모리를 요구 |
| `jm-second-brain-{maintenance,requests}.service.d/20-runtime.conf` | `SB_CONFIG`, `PATH`에 `app/current/bin` 선행 | 활성 릴리스 바이너리 사용 |

상태 확인:

```bash
systemctl --user status second-brain-web.service
systemctl --user list-timers --all 'second-brain*' 'jm-second-brain*'
curl -s http://127.0.0.1:8765/health
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/ready
journalctl --user -u jm-second-brain-refresh.service -n 50
```

### 10.2 LLM 백엔드

현재 운영 백엔드는 CLI argv 템플릿 하나다:

```toml
"llm" = {"argv_template" = ["/home/jm/.config/second-brain/llm/omo-grok.sh"]}
```

`~/.config/second-brain/llm/omo-grok.sh`:

```sh
#!/bin/sh
# second-brain LLM backend: Grok via OmO print mode (xAI OAuth held by OmO).
# Prompt arrives on stdin; the reply is printed on stdout (sb extracts the first JSON object).
export PATH="/home/jm/.nvm/versions/node/v24.19.0/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
cd "$HOME/.local/state/second-brain/llm-cwd" || exit 1
MODEL="${SB_LLM_MODEL:-xai/grok-4.6}"
THINK="${SB_LLM_THINKING:-low}"
exec omo -p -nt -ne --no-session --model "$MODEL" --thinking "$THINK" \
  --system-prompt "…precise text-processing backend… output only the JSON object…" \
  2>/dev/null
```

동작 요점:

- 템플릿에 `{prompt}`가 없으므로 **프롬프트는 stdin으로 들어간다**(§4.3).
- stderr는 버리고 stdout만 쓴다. `json_mode`에서는 SB가 **첫 JSON 객체**를 뽑는다.
- `SB_LLM_MODEL`, `SB_LLM_THINKING` 환경변수로 모델·추론 강도를 바꿀 수 있다(스크립트 자체 규약).

이전 백엔드는 격리된 `CODEX_HOME`을 쓰는 `codex exec`였다. 2026-09-15 기록에 따르면 사용자
`~/.codex/config.toml`(로컬 프록시를 가리키는 `openai_base_url`)을 서비스가 상속해 모든 compile 호출이
실패했고, `/home/jm/.local/state/second-brain/codex-home`(0700, 빈 config + `auth.json` 심링크)을 만들고
`argv_template` 앞에 `env CODEX_HOME=<그 경로>`를 붙여 해결했다.

**백엔드 교체 절차:**

```bash
# 1) 새 백엔드 스크립트를 만든다 (stdin으로 프롬프트, stdout으로 답, 종료 코드 0)
install -m 0700 /dev/stdin ~/.config/second-brain/llm/my-backend.sh <<'EOF'
#!/bin/sh
exec my-llm-cli --quiet
EOF

# 2) 백업 후 두 설정 파일의 [llm].argv_template 를 바꾼다
cp ~/.config/second-brain/config.toml          ~/.config/second-brain/config.toml.bak-$(date +%Y%m%dT%H%M%S)
cp ~/.config/second-brain/jarvis-provider.toml ~/.config/second-brain/jarvis-provider.toml.bak-$(date +%Y%m%dT%H%M%S)
# "llm" = {"argv_template" = ["/home/me/.config/second-brain/llm/my-backend.sh"]}

# 3) 확인
sb doctor            # llm-cli 체크가 pass 인지
sb compile --dry-run # 상태만 읽는다(쓰기 없음)
```

교체 시 확인할 것:

- `argv_template[0]`이 PATH 또는 절대 경로로 **실행 가능**해야 한다. 아니면 `sb doctor`의 `llm-cli`가
  warn이고, 실제 호출은 `command not found: <argv0>`로 `LLMUnavailable`이 된다.
- `{prompt}`를 argv에 넣으면 stdin 전달이 아니라 argv 치환 방식이 된다. 긴 프롬프트에는 stdin 방식이
  안전하다.
- `model_id` / `prompt_version`을 바꾸면 **파생 키가 달라져 기존 페이지가 다시 컴파일된다.** 비용과
  LLM 호출 상한(`caps.max_llm_calls_compile`)을 함께 검토한다.
- 백엔드가 외부 제공자로 바뀌면 데이터 제공자가 바뀌는 것이므로 사용자 승인 사안이다.
- 두 설정 파일(`config.toml`, `jarvis-provider.toml`) 모두 바꿔야 한다. refresh 경로는 후자를 쓴다.

### 10.3 readiness 코드 표

`/ready`(GET)는 `sb/readiness.py: readiness()`를 그대로 돌려준다. `status`가 `ready`면 HTTP 200,
아니면 **503** + `reasons` 배열.

| 코드 | 체크 이름 | 발생 조건 | 조치 |
|---|---|---|---|
| `READINESS_POLICY_INVALID` | `policy` | `[readiness]` 값이 정수가 아니거나 1..8760 밖 / 시계에 timezone 없음 | 설정을 고친다. 이 코드가 나오면 다른 체크는 아예 돌지 않는다 |
| `VAULT_UNREADABLE` | `readable` | Vault/원장 읽기 중 예외 | `details.error`의 예외 타입 확인, `sb doctor` |
| `VAULT_UNINITIALIZED` | `initialized` | `<vault>/.git`이 디렉터리가 아님 | `sb init` |
| `LEDGER_SCHEMA_INVALID` | `ledger_schema` | `schema_meta.schema_version` ≠ 현재 | `sb migrate --check` → `sb migrate --apply` |
| `GENERATION_INDEX_INVALID` | `generation_index` | 활성 세대의 `search.db`가 현재 질의 계획이 요구하는 컬럼을 갖추지 못함 | **새 세대를 게시한다** — refresh(`sb run`) 1회 |
| `LAST_RUN_UNSUCCESSFUL` | `last_run_success` | 최신 `run` 행의 status가 `ok`/`capped`가 아님 | `sb status --json`으로 실패 단계 확인 → 원인 제거 후 재실행 |
| `LAST_RUN_STALE_OR_INVALID` | `last_run_recent` | 마지막 실행이 `max_run_age_hours`보다 오래됐거나 시간 필드가 부정합 | 타이머 상태 확인, 1회 수동 실행 |
| `DERIVATIONS_FAILED` | `derivations_healthy` | `derivation` 테이블에 `status='failed'` 행이 1개 이상 | 원인 해소 후 `sb retry --stage <stage>`. brief는 `sb maintain --once`가 조건 충족 시 `superseded`로 종결 |
| `VERIFIED_BACKUP_UNAVAILABLE` | `recent_backup` | `backup_root`에 정책 시간 안의 **검증된** 백업이 하나도 없음 | `sb backup` 실행. `details.backup_error` 확인 |
| `LATEST_BACKUP_UNVERIFIED` | `latest_backup_verified` | 가장 최신 아카이브가 검증을 통과하지 못함 | `sb verify-backup <최신 아카이브>`로 코드 확인 |
| `REQUEST_JOURNAL_UNREADABLE` | `request_journal` | `request_root/journal.db` 읽기 실패 | 파일 권한/손상 확인 |
| `REQUEST_TIME_INVALID` | `request_times` | `accepted_at`/`updated_at`이 NULL이거나 순서가 뒤집혔거나 미래 | 저널 조사(직접 편집 금지) |
| `REQUESTS_STALLED` | `requests_progressing` | 가장 오래된 `pending`/`processing` 요청이 `max_request_age_minutes` 초과 | `sb apply-requests --once`, path 유닛/게이트 파일 확인 |
| `RECENT_REQUEST_FAILURES` | `requests_healthy` | `failure_window_hours` 안에 `failed`/`expired`/`reapproval_required` 요청 존재 | 요청별 원인 조사 |
| `GENERATION_JOURNAL_UNREADABLE` | `generation_journal` | `state_root/generation-journal.db` 읽기 실패 | 권한/손상 확인 |
| `GENERATION_CLEANUP_STALLED` | `generation_cleanup` | `activations`에 `phase <> 'proved'`이고 `updated_at`이 정책 창 밖인 행 존재(고아 activated 행 포함) | **`sb maintain --once`** 1회. 다른 읽기 CLI를 동시에 돌리지 않는다 |

응답의 참고 필드: `provider_release`, `last_run`, `last_run_age_seconds`, `failed_derivations`,
`requests`(상태별 집계), `oldest_request_at`, `oldest_request_age_seconds`, `recent_failed_requests`,
`tombstone_high_water`, `latest_backup`, `last_verified_backup`, `backup_verification`, `backup_error`,
`generation`.

`backup_error`로 올 수 있는 값: `BACKUP_MISSING`, `BACKUP_VERIFICATION_MISSING`,
`BACKUP_VERIFICATION_INVALID`, `BACKUP_DIRECTORY_UNREADABLE`, 그리고 검증 코드
`BACKUP_CHANGED` / `BACKUP_ORIGIN_MISMATCH` / `BACKUP_TOMBSTONE_OR_PROVIDER_MISMATCH` /
`BACKUP_TIME_INVALID` / `BACKUP_STALE`.

### 10.4 백업과 복원

**백업 생성**

```bash
sb backup                                   # <backup_root>/second-brain-<YYYYmmddTHHMMSS±ZZZZ>.tar.gz
sb backup /path/to/explicit-name.tar.gz
```

관리형 배치에서 `backup_runtime`은 세 겹의 락을 동시에 잡는다:

1. `request_root/pending` 디렉터리 `flock(LOCK_EX)`
2. 세대 저장소 `exclusive()` writer mutex
3. 요청 저널의 `BEGIN IMMEDIATE` (끝나면 rollback)

그 상태에서 활성 세대 트리를 복사하고, 복사본 안의 `.recovery/`에 **제어 저널만** 담는다:

- `state`: `state_root`의 1단계 `*.db` 파일
- `requests`: `request_root` 전체 트리의 파일 (단 `-wal`, `-shm`, `.lock`, `.tmp` 제외)
- `.db`/`.sqlite`는 SQLite `backup()` API로 복사한다(WAL 포함). 그 외는 바이트 복사.
- 오래된 릴리스, 과거 백업, 무관한 호스트 파일은 **들어가지 않는다.**

출력 JSON: `archive`, `checksum`, `verification`, `files`, `bytes`.

**검증**

`sb backup`은 생성 직후 `verify_runtime_backup`을 호출한다. 검증은 임시 저장소로 복원해 체크섬·원장·
인용을 검사하고 `*.tar.gz.verified.json` 영수증을 남긴다. 임시 저장소는 검사 후 제거되지만 **복원용
추가 디스크 공간이 필요하다.**

관리형 검증은 `origin`이 `provider:<provider_instance_id>`인지, tombstone high-water가 현재와 같은지
확인한다. 다르면 `BACKUP_TOMBSTONE_OR_PROVIDER_MISMATCH`. 제어 저널이 초기화돼 있지 않으면
`backup verification requires initialized control journals`.

출처가 없는 옛 백업은 준비 상태의 정상 근거로 쓰이지 않는다 — 새 백업을 만들어 검증한다.

```bash
sb verify-backup ~/.local/state/second-brain/backups/second-brain-20260915T184120+0900.tar.gz
```

**복원**

```bash
sb restore <archive> --to /absolute/new/restore-dir
sb restore <archive> --to /absolute/new/restore-dir --force
```

- 목적지가 심링크이거나, 목적지가 활성 `vault_root`와 같고 설정에 `share_root`가 있으면
  `RESTORE_REQUIRES_ISOLATED_DESTINATION: use --to with a new directory`로 거절한다.
  **운영 Vault 위에 덮어쓸 수 없다.**
- 복원은 사이드카 검증 → 배타 락 → 임시 디렉터리에 매니페스트 기준 전수 검증(경로 정규화, 중복 경로
  거부, 파일 수 상한) → 원자 교체 순서다.
- 복원 예산 상수(`sb/restore.py`): 멤버 100,000개, 파일당 64 MiB, 합계 10 GiB.
  넘으면 `RESTORE_ARCHIVE_BUDGET_EXCEEDED`.
- 출력 JSON: `destination`, `files`, `bytes`, `previous`.

**복원 작업공간 정리**

```bash
sb maintain --once --restore-workspace /absolute/private/restore-work
```

sanitizer에 넘긴 것과 **같은 0700 폴더**를 명시해야 한다. 진행 중인 복원은 기다리지 않고
`restore_workspace_busy: true`로 보고한다. 잠금을 쓰지 않는 구버전 복원 writer가 종료된 것을 확인한
뒤에만 쓴다. 기본 운영 타이머에 이 경로를 자동으로 추가하지 않는다.

**중단된 웹 정정·삭제 영수증 복구**

웹 owner effect는 `state_root/owner-effects/*.json`의 의도를 먼저 fsync한 뒤 tombstone을 접수한다.
검사·활성화 전에 실패하면 요청 저널과 활성 세대의 high-water가 일시적으로 다를 수 있다.
이 상태에서 새 정정·삭제를 만들지 말고, 원래 HTTP 요청을 그대로 재전송하거나 다음을 단독 실행한다:

```bash
sb maintain --once
sb backup
sb verify-backup <방금_생성한_아카이브>
```

`maintain`은 일반 세대 정리 전에 미완료 영수증을 순서대로 재실행한다. 이미 활성화된 결과는
중복 적용하지 않으며 완료 영수증에서 대체 본문을 지운다. `recovered_owner_effects`는 복구 건수다.
검사가 다시 실패하면 오류를 반환하고 영수증은 재시도용으로 남는다. SQLite·영수증·vault 포인터를
직접 편집하거나 high-water를 낮추지 않는다. 재실행이 다른 sealed 세대를 만들었으면, 부모가 이미
폐기되어 더 이상 활성화할 수 없는 옛 sealed 사본도 유지보수가 기존 staging 폐기 경로로 정리한다.
활성 세대의 자식이나 읽기 lease가 있는 세대는 폐기하지 않는다.

`task32-schema4`의 `sb_generation_status({"read_fence": null})`는 정정 후에도 내용 없는 전역 상태와
현재 high-water·계약 digest를 반환한다. JARVIS readiness의 고정 bootstrap 호출이다. 이것은 본문·검색·
개별 요청 proof의 읽기 fence를 대신하지 않는다. 명시한 fence가 잘못됐으면 status도 거절하며,
scoped 프로필의 서명 검증 및 실제 쓰기 승인 경로는 바뀌지 않는다.

사본 검사는 backup-v1/PAX gzip 안의 Git pack 및 정상 ZIP 원본도 해석한다. 손상되거나 지원하지
않는 내부 원본 때문에 부재를 증명할 수 없는 **정상 백업 컨테이너**는 매니페스트의 모든 파일·해시와
체크섬을 확인한 뒤 제품의 사본 폐기 경로로 통째로 폐기한다. 부재로 간주해 보존하지 않는다.
폐기 중 체크섬 파일만 먼저 지워진 경우에도 내부 매니페스트 전수 검증 후 재개한다. 이런 운영 복구
전에는 관리 루트 밖의 비공개 구조 사본과 SHA-256 명세를 남겨야 한다. 구조 사본은 삭제 대상 원문을
포함할 수 있으므로 복구용으로 격리하며, 정리 여부는 소유자가 결정한다.

### 10.5 릴리스 전환(cutover)과 롤백

**전환 절차** (2026-09-15 기록에서 3회 반복된 순서):

```bash
# 0) 사전 점검
sb doctor
curl -s http://127.0.0.1:8765/ready | head -c 400
ls ~/.local/state/second-brain/requests/pending      # 비어 있어야 한다
sb backup                                            # 검증까지 통과할 것

# 1) 릴리스 빌드 (커밋된 HEAD만 들어간다)
python deploy/prepare-release.py                     # 출력: <app>/releases/<release_id>

# 2) SB 유닛 정지
systemctl --user stop jm-second-brain-requests.path \
                      jm-second-brain-refresh.timer \
                      jm-second-brain-maintenance.timer \
                      second-brain-web.service

# 3) current 원자 교체
ln -sfn ~/.local/state/second-brain/app/releases/<new_release_id> \
        ~/.local/state/second-brain/app/current.new
mv -Tf ~/.local/state/second-brain/app/current.new \
       ~/.local/state/second-brain/app/current

# 4) 유닛 재시작
systemctl --user start second-brain-web.service \
                       jm-second-brain-refresh.timer \
                       jm-second-brain-maintenance.timer \
                       jm-second-brain-requests.path

# 5) 검증
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/     # 200
sb doctor
sb search "아무 키워드"

# 6) 유지보수 또는 refresh 1회 (단독으로!)
systemctl --user start jm-second-brain-maintenance.service
# 또는 세대 재게시가 필요하면
systemctl --user start jm-second-brain-refresh.service
```

**롤백**: 이전 릴리스 디렉터리는 지우지 않으므로, 같은 방식으로 `current`를 이전 `release_id`로
되돌리고 유닛을 재시작하면 된다. 단 구 릴리스는 전환 전 세대를 읽는다는 점을 감안한다.

위 3)의 `ln -sfn` + `mv -Tf`를 이전 `release_id`로 반복하고 4)의 유닛 재시작만 다시 하면 된다.

전환 후 남는 것들(기록된 실제 현상):

- 구 릴리스 경로의 `sb mcp` 프로세스가 남는다. 클라이언트 세션을 재시작하면 교체되고, 필요하면
  SIGTERM으로 정리한다.
- `doctor`의 `scheduler-assets` warn은 휠에 `deploy/systemd`가 없어서 생기는 안내로 기능 영향이 없다.

### 10.6 금기 사항

| 하지 말 것 | 이유 |
|---|---|
| `sb maintain` 실행 중에 `sb status` / `sb search` 등 읽기 CLI를 동시에 돌리기 | 선행 세대 fd가 잡혀 `GENERATION_READER_DRAIN_REQUIRED`로 폐기 실패 |
| 채워진 원장에 `sb doctor --rebuild-ledger` | `done → running` 전이가 허용되지 않아 실패한다. 유효한 복구 수단이 아니다 |
| 운영 Vault 경로로 `sb restore` | `RESTORE_REQUIRES_ISOLATED_DESTINATION`. 반드시 `--to <새 디렉터리>` |
| `ledger.db` / `journal.db` / `generation-journal.db` 직접 편집 | 세대·증명 무결성 설계를 깬다. 실패 brief 행도 감사 기록으로 보존한다 |
| 세대 디렉터리의 파일 모드를 임의로 바꾸기 | 봉인(0400/0500)은 무결성 계약의 일부 |
| `git push` (앱 리포·Vault 리포 모두) | 명시적 요청 없이 push 금지(운영 원칙). Vault는 원격이 없다 |
| 스테이징 디렉터리에 64자리 hex가 아닌 이름 만들기 | `GENERATION_STAGING_UNSAFE`로 유지보수가 멈춘다 |
| 충돌 자동 해결 / 무승인 원본 삭제 | 제품 원칙상 금지. `sb gc`도 `--apply --confirm` 둘 다 필요 |
| `provider_private_key` 등 설정 파일 값 복사·출력 | 비밀 자료 |

---

## 11 문제 해결 (증상 → 원인 → 조치)

| 증상 | 원인 | 조치 |
|---|---|---|
| CLI가 `already running`만 출력하고 0으로 끝난다 | 다른 프로세스가 `.sb/run.lock`(관리형이면 `state_root/.sb/run.lock`)을 잡고 있다 | 정상 동작이다. 타이머 실행이 끝나기를 기다린다. `systemctl --user list-timers`로 확인 |
| `sb search`가 `GENERATION_INDEX_INVALID` | 활성 세대의 `search.db`가 구 스키마(현재 질의 계획이 요구하는 컬럼 없음) | **새 세대를 게시한다**: `systemctl --user start jm-second-brain-refresh.service` (= `sb run`). 인덱스만 고치는 명령은 없다 |
| `sb doctor --rebuild-ledger`가 전이 오류로 실패 | 이미 `done` 행이 있는 원장에서 `done → running` 전이를 시도 | 이 명령을 쓰지 않는다. 원장 스키마 문제라면 `sb migrate --check` → `--apply` |
| `sb maintain --once`가 `GENERATION_READER_DRAIN_REQUIRED` + exit 1 | 선행 세대 디렉터리를 연 fd가 남아 있다(동시 실행한 `sb status`/`sb search`, 구 릴리스의 `sb mcp` 프로세스 등) | 읽기 CLI를 모두 끝내고 단독으로 재실행. 구 릴리스 MCP 프로세스가 있으면 SIGTERM |
| 유지보수가 `GENERATION_READER_DRAIN_UNVERIFIABLE` | `/proc`을 읽을 수 없는 환경 | `ProtectProc`/컨테이너 설정을 확인한다. 이 검사는 우회할 수 없다 |
| `/ready`가 `GENERATION_CLEANUP_STALLED` | 현재 세대가 아닌 `activated` 행이 남았고 디렉터리·핀이 없다(고아) | `sb maintain --once` 1회. 2026-09-15 운영에서 `activated 3 → proved`로 해소 |
| `/ready`가 `DERIVATIONS_FAILED` | `derivation`에 `failed` 행 존재 | `sb status --json`의 `failed_by_stage` 확인. compile/conflict는 원인 해소 후 `sb retry --stage <stage>`. brief는 `maintain`이 조건(이후 성공 brief 존재 + 일시적 LLM 오류 아님)을 만족할 때 `superseded`로 종결 |
| `sb retry`가 `BRIEF_REPLAY_INPUTS_UNAVAILABLE` | 선택 집합에 `brief` 행이 섞였다 | `--stage compile` 등으로 단계를 좁힌다. 과거 브리핑은 의도적으로 재생하지 않는다 |
| `/ready`가 `LAST_RUN_UNSUCCESSFUL` | 최신 run status가 `ok`/`capped`가 아님 | `sb status --json`의 `recent_stages`에서 실패 단계와 사유 확인 |
| compile이 전부 `LLM unavailable after 2 attempts` | 백엔드 CLI가 없거나(`command not found`), 설정을 잘못 상속했거나, 계정 한도 | `sb doctor`의 `llm-cli` 확인. 백엔드를 stdin으로 직접 실행해 재현. 계정 한도면 회복 후 `sb retry --stage compile` + 실행 1회 |
| compile 호출이 사용자 개인 CLI 설정을 타서 실패 | 서비스가 `~/.codex/config.toml` 같은 사용자 설정을 상속 | 격리 홈을 만들고 `argv_template` 앞에 `env <HOME 변수>=<격리 경로>`를 붙인다(2026-09-15 조치 그대로) |
| `sb run`이 `INGEST_UNIT_BUDGET_EXCEEDED` + exit 1 | 한 원본의 새 unit 수가 `caps.max_new_units_per_run`을 초과 | 원본 규모를 확인해 예산을 올리거나 원본을 나눈다. 원본은 보존돼 있다 |
| ingest 결과가 계속 `capped` | 잔여 예산에 맞지 않는 원본 | 정상 동작. 다음 실행에서 이어 처리된다. 급하면 `caps`를 올린다 |
| `SOURCE_NOT_FOUND` | 명시 선택한 source/adapter ID가 설정에 없다 | `sb sources --json`으로 실제 ID 확인. 부분 수집으로 넘어가지 않는다 |
| `SOURCE_ROOTS_AMBIGUOUS` | 세션 어댑터의 루트가 모호 | 해당 `[[sources]]`의 `root`를 명확히 지정 |
| `SOURCE_ACCESS_CONFIG_INVALID` | `[source_access.<id>]`에 `owner`/`projects`/`policy_revision` 외의 키가 있거나 빠졌다 | 정확히 세 키만 둔다 |
| `[search].min_similarity must be a finite number between -1 and 1` | 값이 수가 아니거나 범위 밖 | `-1 ≤ x ≤ 1`의 유한한 수로 고친다 |
| `/ready`가 `READINESS_POLICY_INVALID` 하나만 반환 | `[readiness]` 값이 정수가 아니거나 1..8760 밖 | 네 키를 정수로 고친다. 이 상태에서는 다른 체크가 실행되지 않는다 |
| `/ready`가 `VERIFIED_BACKUP_UNAVAILABLE` | 정책 시간 안의 검증된 백업이 없다 | `sb backup`. `details.backup_error`로 사유 확인 |
| `sb verify-backup`이 `BACKUP_ORIGIN_MISMATCH` | 아카이브 origin이 현재 provider와 다름 | 다른 인스턴스에서 만든 백업이다. 격리 목적지로만 복원한다 |
| `sb verify-backup`이 `BACKUP_TOMBSTONE_OR_PROVIDER_MISMATCH` | 삭제 이력(tombstone high-water)이 현재와 다름 | 이 백업은 현재 상태의 정상 근거가 아니다. 새 백업을 만든다 |
| `sb restore`가 `RESTORE_REQUIRES_ISOLATED_DESTINATION` | 목적지가 심링크이거나 운영 활성 Vault | `--to /absolute/new/dir` |
| `sb apply-requests`가 `REQUEST_EXECUTOR_KEY_CONFIG_INVALID` | JARVIS 공개키 없음 / provider 키 ID·개인키 없음 / base64 파싱 실패 / 모든 키가 철회됨 | 설정과 철회 목록을 점검한다 |
| 요청이 `pending`에 쌓이는데 처리되지 않는다 | `~/.config/second-brain/request-executor.enabled`가 없어 path 유닛이 비활성 | 게이트 파일과 `systemctl --user status jm-second-brain-requests.path` 확인 |
| `/ready`가 `REQUESTS_STALLED` | 가장 오래된 pending/processing이 `max_request_age_minutes` 초과 | `sb apply-requests --once` 수동 실행 후 결과 JSON 확인 |
| MCP 서버가 `SECOND_BRAIN_CONTRACT_PROFILE_INVALID`로 죽는다 | `SB_MCP_CONTRACT_PROFILE` 값이 알려진 프로필이 아니다 | §7.5의 목록 중 하나로 고친다 |
| scoped 프로필이 기동하지 않는다 | `scoped-record-read-*`인데 `[mcp_scoped_read]`가 없거나, `scoped-request-write-v1`인데 `[scoped_provider_verifier]`가 없다 | 해당 섹션을 설정에 넣는다 |
| Codex에서 훅이 조용히 안 돈다 | `hooks.json` 변경 후 TUI에서 "Trust all and continue"를 아직 승인하지 않았다 | TUI를 한 번 띄워 승인한다. 자동화는 `--dangerously-bypass-hook-trust` |
| Claude Code에서 컴팩션 후 문맥이 안 붙는다 | `PostCompact`의 `additionalContext`를 기대하고 있다 | 2.1.270은 `PostCompact` 주입을 무시한다. `SessionStart` matcher `compact` 항목이 설정돼 있는지 확인 |
| 훅이 같은 레코드를 반복 주입한다 | 스테이지의 `delivered_in_turn`이 유실됐다 | 스테이지 파일(`<state_root>/.sb/session-memory/<session>.json`)을 확인. 정상 경로에서는 `confirm_delivery`가 stdout 성공 후에만 기록한다 |
| 훅이 `HOOK_STAGE_UNSAFE` | 스테이지 경로가 심링크이거나 일반 파일이 아님, 또는 권한 문제 | `<state_root>/.sb/session-memory`를 점검한다(0700, 일반 파일 0600) |
| 훅이 `HOOK_QUERY_MISSING` | `PostCompact`에 `query`/`compact_summary`가 둘 다 비었다 | 클라이언트가 요약을 주지 않는 경우다. `SessionStart(compact)` 경로가 `last_query`로 보완한다 |
| `sb doctor`의 `citations`가 fail | 페이지에 미해결 `[^sid]`가 있거나 참조 CAS blob이 없다 | 해당 페이지를 재컴파일하거나, CAS 손실이면 백업에서 격리 복원해 대조한다. `sb gc`를 함부로 돌리지 않는다 |
| `sb doctor`의 `generation`이 fail | Vault git HEAD/tree가 세대 매니페스트와 불일치 | 세대 링크가 잘못됐거나 수동 편집이 있었다. 전환 절차를 다시 검증한다 |
| `sb doctor`의 `scheduler-assets` warn | 휠 설치본에 `deploy/systemd`가 없다 | 정상. 기능 영향 없음 |
| `sb web`이 바인드 실패로 1 | 포트 점유 | `ss -ltnp | grep 8765`, 기존 유닛 정지 |

---

## 12 평가 (M10 gold set)

### 12.1 구성

| 파일 | 역할 |
|---|---|
| `M10-GOLD-CURATED-2026-09-15.json` | 평가 데이터셋(문서 40 / 케이스 131). `dataset_origin`은 enum상 정직한 값 `synthetic`을 유지하고 `curation_note`로 출처를 밝힌다 |
| `M10-GOLD-CURATED-2026-09-15.md` | 큐레이션 근거·결과·한계 보고서 |
| `scripts/korean_search_evaluation.py` | **라이브러리 모듈.** CLI 진입점이 없어 `--help`가 아무것도 출력하지 않는다(정상, exit 0) |
| `scripts/korean-search-acceptance.py` | 실행 진입점. 데이터셋의 `documents`로 **격리 fixture vault/레지스트리를 `mkdtemp`로 새로 만들어** CLI(`python -m sb.cli search`)와 stdio MCP(`sb_search`/`sb_read_page`) 두 표면을 측정한다. 운영 vault·레지스트리는 건드리지 않는다 |

케이스 분류: `fact` 26, `date` 22, `decision` 22, `procedure` 24, `comparison` 21, `no_data` 16 (합계 131).
정답 있는 케이스 115, `no_answer` 16.

### 12.2 실행 방법

```bash
cd /home/jm/orca/projects/second-brain-app

# 스키마 검증
TMPDIR=/var/tmp PYTHONPATH=scripts .venv/bin/python -c \
  "import json;from korean_search_evaluation import load_dataset;print(load_dataset(json.load(open('M10-GOLD-CURATED-2026-09-15.json'))).id)"

# 본 평가 (격리 fixture, CLI + MCP 두 표면)
TMPDIR=/var/tmp .venv/bin/python scripts/korean-search-acceptance.py \
  --dataset M10-GOLD-CURATED-2026-09-15.json
```

실행하지 않은 선택지와 이유:

- `--hybrid` — 모든 문서에 대해 활성화된 생성 벡터를 요구한다. fixture vault에는 임베딩이 없어
  `real hybrid evaluation requires enabled cited vectors for every document`로 실패한다.
- `--min-similarity` — 의미 후보의 cosine 하한.

### 12.3 현재 수치

§7.7의 표가 현재 수치다. 요약하면:

- 전체 hit@1 ≈ 0.22 (CLI 0.226 / MCP 0.217), 운영 릴리스 프로브 0.209.
- keyword recall@5 0.78 (CLI) / 0.74 (MCP) / 0.815 (운영 프로브).
- exact_phrase recall@5 0.67–0.78, reordered_terms 1.0.
- **natural_question(66건)과 paraphrase(13건)는 0.0.**
- negative_empty_rate 1.0, forbidden_exposure@5 0.0.
- 지연(진단용): CLI search p50 270.5 ms / p95 286.7 ms, MCP search p50 42.0 ms / p95 55.1 ms.

### 12.4 데이터셋 자체의 제약 (보고서 §6 그대로)

1. `dataset_origin`은 여전히 `synthetic`이다. 본문은 실제 vault 원문이지만 사용자가 검토하지 않았다.
2. 세대는 계속 회전한다. 작성 시점 세대와 프로브 시점 세대가 달랐다. `source_generation_root`는
   스냅샷 값으로 봐야 한다.
3. `page_id`는 fixture 슬러그다. 스키마 정규식 `wiki/[a-z0-9][a-z0-9-]*`가 한글 파일명을 허용하지 않는다.
   운영 page_id 매핑은 `documents_origin_map`에 있다.
4. 본문은 **한 줄 발췌본**이다. 하네스가 각주 마커를 본문 끝에 하나만 붙이고, `sb/memory_records.py`의
   분할 규칙상 생성되는 레코드가 마지막 줄 하나뿐이기 때문이다.
5. distractor 6개 중 5개는 여전히 빈 템플릿이다. 강한 오답 유인이 부족하다.
6. 운영 릴리스 프로브는 vault를 쓰지 않지만 `sb` CLI 호출만으로 `requests/journal.db`의 mtime이
   갱신된다(크기 불변).
7. **이 평가는 실사용 인수를 대신하지 못한다.** 수집·추출·LLM 답변 평가 없음, 단일 소유자 genesis,
   소규모 코퍼스 1회 측정.

---

## 13 알려진 한계와 로드맵

### 13.1 검색

- **자연어 질의 0.0** — §7.7. 형태소 분석·n-gram 색인·의미 검색 중 하나가 필요하다. 데이터셋 수정으로는
  해결되지 않는다.
- **의미 검색은 기본 꺼짐** — `[search] hybrid = true`로 켜도 **다음 관리형 세대부터** 벡터가 봉인된다.
  이미 봉인된 세대는 설정 변경만으로 재색인되지 않는다. 모델이 없거나 맞지 않으면 일반 검색을 유지한다.
- **MCP 검색은 레코드 AND** — 모든 검색어가 같은 인용 레코드 안에 있어야 한다. CLI보다 좁다.
- **`stale_decision` 배제는 증명되지 않았다** — 해당 2건은 정답도 못 찾았으므로 0.0을 "잘 배제했다"로
  읽으면 안 된다.

### 13.2 파이프라인

- **과거 브리핑 재시도 불가** — `BRIEF_REPLAY_INPUTS_UNAVAILABLE`. 실패 행과 attempts는 감사 기록으로
  보존된다. `maintain`의 supersede는 "이후 성공 brief 존재 + 일시적 LLM 오류 아님"일 때만 상태를 닫는다.
- **`sb rollback` 미구현** — 항상 `ROLLBACK_REQUIRES_GENERATION_AUTHORITY`. 실질 롤백은 릴리스 `current`
  되돌리기 또는 백업 격리 복원이다.
- **brief는 변화가 있을 때만 실행** — 조용한 날에는 일일 브리핑이 생기지 않는다(§6.3).
- **LLM 의존** — compile/conflict/brief 모두 외부 CLI 백엔드가 필요하다. 백엔드 계정 한도·프록시 설정
  같은 외부 조건이 그대로 실패로 나타난다.

### 13.3 접근 제어

- `[source_access]`는 **분류 기록**이며 MCP/API 접근 제어가 아니다. 접근 claim·record/page 분류 결합과
  범위 검사가 연결되기 전까지 기존 owner 프로필의 조회 범위는 그대로다(README).
- scoped 연결은 semantic/hybrid 검색·쓰기·status·export·restore, 운영 권한 공급자, 다중 사용자 인증에
  아직 연결돼 있지 않다.
- 비밀 마스킹은 **자격증명 정규식만**이다(AWS 키, `ghp_`/`gho_`, `sk-`, PEM, `password=`/`token=`).
  연락처 이메일·전화번호는 그대로 남는다(`AGENTS.md`).

### 13.4 운영

- 리포 유닛과 실제 운영 유닛이 분리돼 있다. `deploy/install-systemd-user.sh`는 `jm-second-brain-*`
  유닛을 다루지 않는다.
- `sb web`의 CLI 인자가 `[web] host/port`보다 우선한다. 설정만 바꿔서는 바인딩이 바뀌지 않는다.
- macOS 앱의 AppKit/SwiftUI/Notification Center/Keychain/ServiceManagement 실런타임 인수는 Xcode가
  설치된 macOS에서만 완료할 수 있다. Ubuntu 자동 검증은 소스·API·보안 계약만 본다.

### 13.5 남은 작업 (`CLAUDE-COMPLETION-REPORT-2026-09-15.md` "남은 것")

- M1 운영 로그인 진입점
- M10 한글 gold 100–300 (사용자 승인 전 `synthetic` 상태)
- M5/M13 실사용자 사본·삭제 처분
- M8 타 클라이언트(공개 compaction 이벤트가 없는 클라이언트)
- M2/M4 운영 종단: JARVIS 코디네이터 연결 + 실제 검증 태스크 필요

### 13.6 로드맵 제안(우선순위 순, 근거 기반)

1. **질의 정규화 개선** — 한국어 조사/어미 처리. 79건의 0.0을 움직일 수 있는 유일한 레버다.
2. **세대 인덱스 마이그레이션 경로** — 현재는 `GENERATION_INDEX_INVALID`를 새 세대 게시로만 해소한다.
3. **brief 재생 입력 보존** — 과거 브리핑 재시도를 가능하게 하면 `DERIVATIONS_FAILED` 잔여가 줄어든다.
4. **`source_access` → 실제 접근 검사 연결** — 현재는 기록만 한다.
5. **LLM 백엔드 헬스체크** — `doctor`가 실행 가능 여부만 보고 실제 호출을 시험하지 않는다.

---

## 14 용어집

| 용어 | 뜻 |
|---|---|
| **Vault** | 지식이 사는 디렉터리. `wiki/`, `daily/`, `conflicts/`, `inbox/`, `raw/`, `.sb/`, `log.md`. git 저장소이며 원격이 없다 |
| **CAS** | Content-Addressed Store. `raw/<앞2자>/<sha256>`에 원본 바이트를 그대로 보관 |
| **ledger (원장)** | `.sb/ledger.db`. `source_item`, `unit`, `derivation`, `run`, `run_stage`, `source_access`, `bound_knowledge` 등을 담는 SQLite |
| **unit** | 원본 바이트에서 잘라낸 처리 단위. 예산 `caps.max_new_units_per_run`의 대상 |
| **derivation (파생)** | unit → 페이지 변환 작업 1건. 상태는 `pending`/`running`/`done`/`failed`/`superseded` |
| **deriv_key** | 입력·프롬프트 버전·모델 ID로 결정되는 파생 식별자. 이 값이 바뀌면 다시 계산된다 |
| **PageSpec** | 파일시스템을 모르는 순수 페이지 명세. `sb.vault`만 이것을 디스크에 쓴다 |
| **sid** | 각주 인용 식별자. CAS 다이제스트의 앞 8자 |
| **generation (세대)** | 봉인된 Vault 스냅샷 하나. `share/vault` 심링크가 가리키는 대상이 활성 세대 |
| **activation** | 세대 전환 1건의 저널 행. `claimed → staging → sealed → switch_intent → activated → disposing → proved` |
| **reader drain** | 선행 세대를 폐기하기 전에 그 디렉터리를 연 fd와 reader lease가 0인지 확인하는 절차 |
| **staging** | 아직 게시되지 않은 세대 작업 트리. 디렉터리 이름은 64자리 hex |
| **retired** | 폐기 중인 세대를 잠시 옮겨 두는 위치 |
| **tombstone** | 삭제 이력 레코드. `set_root`/`sequence`가 high-water를 이룬다. 재유입 차단과 백업 검증에 쓰인다 |
| **request journal (요청 저널)** | `request_root/journal.db`. JARVIS memreq의 상태 기계 |
| **memreq** | JARVIS가 SB에 보내는 서명된 기억 요청 |
| **fence** | 요청 lease의 단조 증가 토큰. 오래된 소유자의 쓰기를 막는다 |
| **read_fence / access_claim** | scoped MCP 조회에 요구되는 서명된 범위 증명 |
| **release** | `app/releases/<release_id>`. 커밋된 HEAD를 번들 런타임과 함께 봉인한 배포 단위 |
| **current** | `app/current` 심링크. 활성 릴리스를 가리키는 유일한 전환 지점 |
| **provider** | SB 인스턴스의 대외 신원(`provider_instance_id`, `provider_release_sha`, 서명키) |
| **readiness** | `/ready`가 반환하는 운영 준비도. `/health`(프로세스 생존)와 다르다 |
| **stage 파일** | 기억 훅의 세션별 상태 파일. `<state_root>/.sb/session-memory/<session>.json` |
| **last_query** | 훅이 기억해 두는 마지막 유용한 검색어. `SessionStart(compact)`에 요약이 없을 때 쓰인다 |
| **in-turn 주입** | 같은 턴 안에서 모델 요청 앞에 문맥을 붙이는 것. Claude Code 2.1.270에서는 `SessionStart(compact)`만 가능하다 |
| **knowledge_status / approval_status** | 지식 레지스트리의 상태. `ACTIVE`+`APPROVED`면 `CANONICAL`/`VERIFIED`, 그 외는 `REFERENCE`/`UNVERIFIED` |
| **scope** | 검색 범위. `active`(승인된 활성만), `candidate`, `reference`(=`all`, 상태 필터 없음) |
| **capped** | 예산 상한에 걸려 일부만 처리한 실행 상태. readiness상 성공으로 친다 |
| **superseded** | 이후 성공한 파생이 있어 더 이상 재생할 수 없는 실패 파생의 종결 상태. 행은 지워지지 않는다 |
