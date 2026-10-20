> ENGINEERING-MAP-START: 작업을 시작하면 `/home/jm/orca/engineering-vault/index.json`에서 이 디렉터리의 프로젝트 기록을 읽고 relations와 depends_on을 따라간다. 측정하지 않은 배포는 unknown이다. 이 문장은 기존 규칙을 바꾸지 않는다.

> 리포 간 결정·관례·라우팅 규칙은 [`../dev-wiki`](../dev-wiki/README.md) 를 정본으로 본다. 이 파일은 이 리포 내부 규칙만 담는다.

# Agent notes

Use the selected app repository root: Ubuntu `/home/jm/orca/projects/second-brain-app`; the historical Mac path is `/Volumes/DevSpace/second-brain-app` and must be verified before use. The vault at `/Volumes/DevSpace/second-brain` is a different repo. Do not push either, and leave `/Volumes/DevSpace/me-wiki` and `/Volumes/DevSpace/orca/Wiki-spike` untouched.

## Module boundaries

Ledger-centric batch library plus a thin CLI. Layers, top to bottom:

| Layer | Owns | May import |
| --- | --- | --- |
| L0 | `sb/contracts.py`, `sb/config.py` | stdlib only in contracts |
| L1 | `sb/store/cas.py`, `sb/store/ledger.py` | L0 |
| L2 | `sb/connectors/*`, `sb/parsers/*` | L0, L1, `fs_safety` |
| L3 | `sb/normalize.py` | L0, L1 |
| L4 | `sb/llm.py`, `sb/compile.py`, `sb/conflict.py`, `sb/briefing.py` | L0, L1, prompts |
| L5 | `sb/vault.py` | L0. Sole writer of `wiki/`, `daily/`, `conflicts/`, `log.md`, and the only git committer. |
| L6 | `sb/pipeline.py` | stages above. Lock, logs, briefing I/O, dispatch. |
| L7 | `sb/cli.py`, `sb/mcp.py`, `sb/web.py` | config, explicit pipeline run surfaces, search, vault reads, inbox/upload writes |

`sb/search.py`, `sb/embeddings.py`, and `sb/hybrid_search.py` sit beside L7. Search reads committed git blobs. Hybrid is off unless `[search] hybrid` is true.

File ownership stays one module per concern. Later connectors add a new file. They do not edit `sb/connectors/__init__.py`.

## Forbidden couplings

From plan Scope. Do not add these.

- Connectors must not import `sb.normalize`, `sb.llm`, or `sb.vault`.
- `sb.compile` and `sb.briefing` must not touch the filesystem. They take frozen inputs and return `PageSpec`s.
- Only `sb.cli`, `sb.web`, and the explicit MCP `sb_run` surface import `sb.pipeline`.
- MCP shares no mutable pipeline state. Writes are `sb_remember` into `inbox/` and the explicit `sb_run`, which delegates to the normal single-writer pipeline lock.
- No writes to unified-db. The connector asserts `default_transaction_read_only` and `transaction_read_only` are `on` before SELECTs. No INSERT/UPDATE/DELETE/DDL.
- The server has no file watcher, queue, or event bus. The native macOS client may watch user-selected local folders and upload changed files through the bounded desktop API; the server still ingests only from `inbox/`.
- No signing, consent, authority, or dual-approval machinery. Single scoped exception (owner decision, 대표-결정 C0C9YHNUHUN:1792502949): the company internal-automation policy receipt signer (`principal:company-internal-automation`, `sb/company_auto_*`) may sign and verify its own policy receipts. It must stay separate from every other signing identity and must not gate the default path.
- No vault git remote. `raw/` and `.sb/` stay gitignored. Vault root stays mode `0700`.
- No human-approval gate on the default path. There is no `--review` flag.
- Secret redaction is credential regexes only (AWS keys, `ghp_`/`gho_`, `sk-`, PEM, `password=`/`token=`). Contact emails and phones stay.

## Tests

From the app root. The whole suite runs on a plain `uv sync`; `sqlite-vec` sits in the `dev`
group so `tests/test_embeddings.py` needs no extra. The `embeddings` extra is the product's
optional feature, not a test dependency -- those tests encode with a fake model.

```bash
cd /Volumes/DevSpace/second-brain-app
uv run pytest -q
```

```bash
cd /Volumes/DevSpace/second-brain-app
uv run ruff check sb tests
```

Focused modules follow the same pattern: `uv run pytest -q tests/test_<area>.py`. Integration gate is `tests/integration/test_walking_skeleton.py`. Tests must be deterministic. No sleeps.

## Add a connector (5 steps)

1. Add `sb/connectors/<name>.py` whose filename is `sessions_*`, `records_*`, `*_documents`, `markdown_vault`, or `unified_db`. Auto-discovery loads those names only. Leave `__init__.py` alone.
2. Export `ADAPTER_ID: str` and `create(config) -> SourceAdapter`. Keep `ADAPTER_ID` unique.
3. Implement `source_id`, `scan(cursor) -> Iterator[tuple[SourceRef, bytes, ItemMeta]]`, and `next_cursor()`. Use `ItemMeta.skip_reason` for quarantined or absent items. Do not raise on a missing root.
4. Add a `[[sources]]` row to the vault `config.toml` (`id`, `adapter`, optional `root`). Aliases belong in the module's accepted-adapter set, not in the registry.
5. Add `tests/test_connectors_<name>.py` covering parse, skip, and unchanged-cursor resume. Run `uv run pytest -q tests/test_connectors_<name>.py`.


<!-- github-development-management:v1:start -->
## GitHub 기반 개발 작업 관리 (사용자 지정 기본 흐름)
개발·수정·개선·고도화 요청을 받으면 `~/ops/github-development-management/WORKFLOW.md`를 읽고 자동 적용한다. 이 섹션은 같은 작업을 Linear/별도 보드에 중복 관리하라는 기존 안내보다 우선한다. 모델·권한·전문 검증 지침은 바꾸지 않는다.
- 실제 remote/registry로 대상 확인 → 기존 Issue/PR 검색·재사용(없을 때만 생성) → 목표·범위·인수 조건 기록 → 통합 Project 연결 → 구현·검증 → 근거 기록 → GitHub 재조회.
- 해당 작업의 Issue/Project 등록·상태·검증 댓글 갱신은 사용자 상시 승인 범위다. commit/push/PR/merge/deploy/삭제/권한 변경은 별도 기존 승인 범위를 따른다. 원격이 미확정이면 임의 저장소에 쓰지 않는다.
- 시작/종료 보고에 Issue URL을 남긴다. 등록 실패는 로컬 pending으로 보존하고 미등록이라고 밝힌다. 단순 질문·번역·읽기 전용 조사에는 생성하지 않는다.
- 상태 Backlog → In Progress → Verify → Done. 실제 인수 근거 없이 Done 처리하지 않는다. 코드 존재·테스트·배포·실사용을 구분한다. HANDOFF draft/사람 ready 규칙을 유지한다.
- 상세 원본: `~/ops/github-development-management/WORKFLOW.md`; 연결표: `~/ops/github-development-management/registry.json`; 도구: `python3 ~/ops/github-development-management/manage.py`.
<!-- github-development-management:v1:end -->
