# M8 클라이언트 인수 — 2026-09-27

Claude가 아닌 실제 클라이언트(Codex CLI, OmO)가 격리 vault의 Second Brain MCP에서 fixture를 읽고 새 사실을 기억하는지 측정했다. 코드·`IMPLEMENTATION-STATUS.md`는 고치지 않았고 커밋하지 않았다.

## 판정

| 항목 | 결과 |
|---|---|
| 격리 vault + `task32-schema4` MCP | PASS |
| Codex 읽기 (`sb_search` / `sb_read_page`) | PASS |
| Codex 쓰기 (`sb_remember` → inbox) | PASS |
| Codex 자동 문맥 주입 | 미지원. 공개 compact 이벤트 없음 |
| OmO 호출당 MCP 등록 | PASS. 프로젝트 `mcp.json` + `--approve` |
| OmO 읽기 | FAIL. 도구는 보였으나 `query`/`id`가 빈 인자로 빠짐 |
| OmO 쓰기 | PASS. inbox에 별도 토큰이 남음 |
| OmO 자동 문맥 주입 | 미지원. 공개 이벤트 미확인, 이번에도 관측 없음 |
| 독립 읽기 재확인 | PASS. MCP와 `sb search`가 fixture 레코드를 반환 |
| 프로덕션 vault/config | 디렉터리 mtime 불변. Codex `config.toml` 불변 |

## 무엇을 띄웠나

설치된 릴리스 `68eee51e09981d81d210ac4154532f0cf7229417` (`source_commit` `2e9f2cd288511ec4f30f882763fbed9fa666b103`, 프로필 `task32-schema4`)의 `bin/second-brain-mcp`를 래퍼로 실행했다. 래퍼가 `SB_CONFIG`를 격리 파일로 고정한다. 보고 시각의 작업 트리 HEAD는 `99b496694556022b71d7b2b86932d6cafab10e29`이며 이 작업의 커밋이 아니다.

격리 루트는 `/var/tmp/sb-m8-ef5f878d`였다. `.test-vault` 복사본은 빈 디렉터리라 검색할 레코드가 없었다. 매뉴얼대로 그 루트에만 가리키는 config로 `sb init`한 뒤, 인용 페이지 `wiki/m8-fixture`를 커밋했다. 모든 경로(`vault_root`, `share_root`, `state_root`, `request_root`, `export_root`, `backup_root`, `knowledge_registry`)는 그 루트 안이다. MCP 세대 경로 검사는 `share_root/vault == vault_root`를 요구해서 `share_root`를 루트 자신으로 뒀다.

fixture 토큰은 `M8FIXTURE9f3a2c1b`다. 독립 MCP 읽기가 돌려준 레코드는 `sbrecord:v1:226c5c2a47c932654d69dc151f49325a25b480309216da4a90b7b64e095146bf`, 본문은 `The isolated M8 fixture fact token is M8FIXTURE9f3a2c1b.`이다.

## Codex CLI 0.157.0

등록은 호출당 `-c mcp_servers.sb_m8.command=...`뿐이다. `--ignore-user-config`로 `~/.codex/config.toml`의 기존 `mcp_servers.second-brain`은 로드하지 않았다. 그 파일의 mtime/size는 전과 같다. `--ephemeral`이라 해당 thread id 이름의 세션 파일은 `~/.codex`에서 찾지 못했다.

모델 호출은 2회다.

1. `gpt-5.4`, 종료 코드 1. ChatGPT 계정이 이 모델을 거절했다. 도구 호출 0. 외부 차단이며 SB 결함으로 세지 않는다. 전사: `c6/codex-exec.jsonl`.
2. `gpt-6-astra`, 종료 코드 0. thread `01a0e299-2c8e-7913-b5f1-414743ea3226`. 카탈로그상 이 모델은 `tool_mode=code_mode_only`지만 MCP 도구 호출은 됐다.

관측된 호출은 모두 서버 `sb_m8`이다.

- `sb_search` `query=M8FIXTURE9f3a2c1b` completed. snippet과 record_id가 fixture와 일치.
- `sb_read_page` `id=wiki/m8-fixture` completed. 같은 record_id.
- `sb_remember` title `M8 isolated remember`, content `M8NEWFACT7c4e8d0a isolated write landed` completed. `inbox_path=inbox/2026-09-27T112134781156-m8-isolated-remember.md`.

읽기 OK, 쓰기 OK. 자동 주입은 하지 않았다. 준비 문서(2026-09-14)가 Codex에 공개 compact 이벤트가 없다고 고정한 상태와 같다. 이번에도 compaction 이벤트는 없었다.

전사: `.omo/evidence/ulw/mass-20260927/c6/codex-exec-2.jsonl`.

## OmO 5.0.1 (senpi 2026.9.27)

호출당 MCP는 된다. `omo --help`의 `OMO_CODING_AGENT_DIR`과 senpi 문서의 프로젝트 `mcp.json`이 그 표면이다. 브랜드 configDir는 `.omo`다. 사용자 `~/.omo/agent/mcp.json`은 만들지 않았다. 격리 cwd의 `.omo/mcp.json`(같은 내용을 `.senpi`, `.pi`에도 둠)을 `--approve`로 그 실행만 신뢰했다. help 전사: `c6/client-help.txt`.

모델 호출은 2회다. 그 전에 `--no-omo-task`는 파서가 `Unknown option`으로 거절했고, 모델은 호출되지 않았다. 재시도에서는 `--omo-senpi-task-disabled`를 썼다.

1. `--provider anthropic --model claude-opus-5-5`, 종료 코드 0이지만 SB 도구 0. Anthropic이 `Third-party apps now draw from your extra usage, not your plan limits`로 400을 냈다. 폴백 `cursor-cli-oauth/claude-opus-5`는 Cursor 플러그인 네임스페이스만 보여 줬다. `sbm8`은 senpi 로그에 등록됐으나 그 모델 카탈로그에는 없었다. 읽기/쓰기 모두 실패. 로그인 부재가 아니라 사용량 정책 차단이다.
2. `--provider xai --model grok-4.7 --no-model-fallback`, 종료 코드 0. xAI OAuth는 `omo auth check`에서 ready였다.

두 번째 실행에서 보인 도구는 `mcp_sbm8_sb_search`, `mcp_sbm8_sb_read_page`, `mcp_sbm8_sb_remember`를 포함한 9개다. 그러나 검색·읽기는 인자가 `{}`로 나갔다. 서버는 `query`/`id` Field required로 거절했다. 모델은 공개 스키마에 파라미터가 없어 인자가 버려졌다고 했다. 같은 서버를 독립 SDK로 `list_tools`하면 `query`와 `id`가 required다. 그래서 OmO 읽기는 FAIL이고, 서버 읽기 능력의 실패는 아니다. 같은 턴의 `sb_remember`는 성공했다. inbox `2026-09-27T112659158395-m8-omo-remember.md`에 `M8OMOFACT3b1e6a9c isolated omo write landed`가 있다.

자동 주입은 준비 문서대로 미지원이다. 이번 전사에도 주입 이벤트는 없다.

전사: `c6/omo-exec.json`, `c6/omo-exec-2.json`.

## 독립 확인

클라이언트 전후에 격리 `SB_CONFIG`로 `sb search M8FIXTURE9f3a2c1b --json --scope reference`와 stdio MCP `sb_search`/`sb_read_page`를 호출했다. 둘 다 fixture 페이지와 위 record_id를 반환했다. 종료 코드 0.

쓰기는 컴파일 인덱스가 아니라 inbox에 남는다. 새 토큰으로 `sb search`하면 빈 배열이다. `requests/pending`에는 파일이 없다. Codex 쓰기 이후 vault는 `share_root/vault` → `vault-generations/sbgen:v1:...` 심볼릭 링크가 되었고, 두 inbox 파일 모두 그 세대 inbox에 있다.

증거: `c6/independent-after-codex.txt`, `c6/independent-readback.txt`, `c6/independent-mcp-readback.json`.

## 격리 한계

- `~/.codex/config.toml`, `~/.config/second-brain/config.toml`, `~/.omo/omo.jsonc`, `~/.local/share/second-brain`, `~/.local/state/second-brain` 디렉터리 mtime은 작업 전후 같다.
- OmO 프로세스가 `~/.omo/agent/settings.json` 크기를 7612에서 7610으로 바꿨다. 손으로 고친 것이 아니고, 원본을 저장하지 않아 되돌리지 않았다. `credential-pool-state.json` mtime도 첫 Anthropic 시도 구간에 움직였다. MCP 서버 목록 파일은 추가하지 않았다.
- 격리 검색 전에 `SB_CONFIG` 없이 `sb search`를 한 번 호출했다. 결과는 `[]`이고, 프로덕션 `vault/.sb/search.db` mtime은 움직이지 않았다.

임시 루트는 삭제했다. 세대 트리가 0555라 `chmod -R u+w` 뒤에 `rm -rf`했다. `pgrep -af sb-m8` 잔여 0. 영수증은 `c6/cleanup.txt`다.
