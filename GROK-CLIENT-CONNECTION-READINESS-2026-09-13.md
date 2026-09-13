# 클라이언트 연결 준비 (읽기 전용, 2026-09-13)

**착수:** 원 M8/F의 실사용 연동 1건을 실행하기 *전* 공개 문서·설치 예시·실행 파일 버전만 대조한다. native 세션/모델 호출/로그인/계정 토큰/개인 세션 본문 열람·복사는 하지 않았다. 운영 current `41f0751` / `production_activated=false`를 바꾸지 않았다.

Codex `CODEX-NIGHT-REVIEW-20eff3c.md`가 이미 존재한다. 일반 후속 두 항목(1fc3d7a)은 그 검토에서 한정 완료로 기록됐다. 일반 기능만 계속한 것은 **Codex 조정 보류**이지 사용자 원 A–F/M1–M14 축소가 아니다. 사용자는 보안/삭제 개선을 금지하지 않았다. 이번 산출물은 그 보류 분기를 재실행하지 않는다.

핀: 아카이브 `e13cd3b` · 실행 제품 wheel `f7c1945`/`1847b599…`/`d9c6825b…` · JARVIS `1672626`. 게이트 로그 `/var/tmp/sb-gates-f7c1945.log`는 실행 핀이며 새 실행으로 바꾸지 않는다.

관측 등급: **observed** = 이번 명령 출력. **documented** = 리포 공개 파일. **unconfirmed** = 실행하지 않음.

## 1. 설치된 클라이언트 (실행 파일·공개 버전만)

| 이름 | 경로 | 관측 | 등급 |
|---|---|---|---|
| Codex CLI | `/home/jm/.nvm/versions/node/v24.19.0/bin/codex` | `codex --version` → `codex-cli 0.154.0` | observed |
| Claude Code | `/home/jm/.local/bin/claude` | `claude --version` → `2.1.261 (Claude Code)` | observed |
| OmO | `/home/jm/.local/bin/omo` | `omo --version` → `omo 5.0.0-0.beta.53 (engine: senpi 2026.9.10-2)` | observed |
| orca CLI | `/home/jm/.local/bin/orca` | `orca --version` → `1.4.197` (Linux bare `orca`는 화면 읽기 도구일 수 있음) | observed |
| Orca IDE | `/home/jm/.local/bin/orca-ide` | `orca-ide status --json` → `ok`, `appVersion` `1.4.197`, `runtime.state` `ready` | observed |
| Cursor | `/home/jm/.local/bin/cursor` | `--version`/`-v`/`version` 모두 EXIT 1: Cursor IDE 미설치 | observed |
| OpenCode | PATH 없음 | | observed |
| Gemini CLI | PATH 없음 | | observed |

native 세션·실모델 호출은 **unconfirmed**.

## 2. 제품별 연결표

근거: `sb/connectors/*.py` `ADAPTER_ID`, `sb/connectors/__init__.py` 자동 발견 규칙, `config.example.toml`, `README.md`, `sb/cli.py` (`sb mcp`/`search`/`remember`/`run`/`web`).

### 수집 adapter (코드에 존재)

| adapter id | 모듈 | 자동 발견 | 설정 예시 | 상태 |
|---|---|---|---|---|
| `markdown-vault` | `markdown_vault.py` | yes (`_DISCOVERABLE_EXACT`) | `config.example.toml` 주석 `[[sources]]` | documented; 이번 운영 수집 **unconfirmed** |
| `inbox-documents` | `inbox_documents.py` | yes (`*_documents`) | 동일 예시 | documented |
| `claude-sessions` | `sessions_claude.py` | yes (`sessions_*`) | 예시 소스 블록 없음 | 코드 있음. 실세션 수집 **unconfirmed** (세션 본문 열람 안 함) |
| `codex-sessions` | `sessions_codex.py` | yes | 예시 없음 | 동일 |
| `omo-sessions` | `sessions_omo.py` | yes | 예시 없음 | 동일 |
| `opencode-sessions` | `sessions_opencode.py` | yes | PATH에 opencode 없음 | 미설치 |
| `gjc-sessions` | `sessions_gjc.py` | yes | 예시 없음 | **unconfirmed** |
| `orca-records` | `records_orca.py` | yes (`records_*`) | 예시 없음 | **unconfirmed** |
| `project-records` | `records_project.py` | yes | 예시 없음 | **unconfirmed** |
| `unified-db` | `unified_db.py` | yes | 예시 없음 | **unconfirmed** |

`claude_native.py`는 발견 규칙에 없어 registry 자동 수집 대상이 아니다 (documented).

### 조회·쓰기 entrypoint (제품 공개 표면)

| 표면 | 명령/경로 | 읽기 | 쓰기 | 자동주입 | 상태 |
|---|---|---|---|---|---|
| CLI | `sb search` / `sb remember` / `sb run` / `sb ingest` / `sb compile` | yes | remember·run | 없음 | documented. 운영 실행 **unconfirmed** |
| MCP stdio | `sb mcp` (`Command.MCP`) | `sb_search` 등 | `sb_remember`; scoped write는 별도 프로필 | 클라이언트가 도구를 부를 때만. 모델 문맥 자동주입 **unconfirmed** | documented |
| Web | `127.0.0.1:8765` (`second-brain-web.service`) | search/pages | remember/run/conflict | 없음 | documented. 운영 서비스 상태 이번 미조회 |
| JARVIS | dist `/var/tmp/jarvis-artifact-1672626/source/dist` | GJC/scoped 경로 | 요청/outbox (V3 문서) | **unconfirmed** | artifact 경로 documented; 이번 프로세스 호출 없음 |

자동주입: README는 MCP를 클라이언트가 호출하는 도구 목록으로 적는다. `sb_remember`는 inbox 접수이며 검색 반영은 `ingest`/`compile` 또는 배치. **자동 문맥 주입은 확인하지 않음** (원 M8 `blocked_external` 유지).

## 3. 다음 실사용 연동 1건 — 실행 전 준비

대상 (공개 예시만으로 준비 가능): **격리 프로필에서 Codex CLI → `sb mcp` stdio** (README `mcpServers.second-brain` 형태, SSH/운영 `~/.config/second-brain` 대신 격리 경로).

실행하지 않음. 운영 설정·심볼릭 링크 변경 없음.

### 정확한 경로

| 항목 | 값 |
|---|---|
| 아카이브 | `/var/tmp/sb-candidate-e13cd3b/releases/d9c6825b9a94cf6637ba01416562e4eb777db7a2` |
| 동일 wheel 실행 핀 | `/var/tmp/sb-candidate-f7c1945/releases/d9c6825b9a94cf6637ba01416562e4eb777db7a2` |
| 소스 예시 설정 | `/home/jm/orca/projects/second-brain-app/config.example.toml` |
| 격리 설정 (아직 만들지 않음) | `/var/tmp/sb-client-readiness/config.toml` |
| 격리 vault (아직 만들지 않음) | `/var/tmp/sb-client-readiness/vault` |
| MCP 엔트리 (절대 경로) | `/var/tmp/sb-candidate-e13cd3b/releases/d9c6825b9a94cf6637ba01416562e4eb777db7a2/bin/sb` (동일 wheel: `.../sb-candidate-f7c1945/releases/d9c6825b9a94cf6637ba01416562e4eb777db7a2/bin/sb`). PATH의 bare `sb`를 후보라고 보장하지 않음 |
| JARVIS dist | `/var/tmp/jarvis-artifact-1672626/source/dist` |
| Codex CLI | `/home/jm/.nvm/versions/node/v24.19.0/bin/codex` (`codex-cli 0.154.0`) |
| Codex 설정 형식 | `~/.codex/config.toml` (TOML). `codex mcp add --help` observed 2026-09-13: `codex mcp add <NAME> -- <COMMAND>...` + `--env KEY=VALUE`. README `mcpServers` JSON은 일반/SSH 예시이며 Codex 0.154.0 설정이 아님 |
| SB_CONFIG | `sb/config.py` 185행 documented 지원 |

### 실행 전 명령 (아직 돌리지 않음. native 등록/운영 설정 변경 없음)

```bash
CAND=/var/tmp/sb-candidate-e13cd3b/releases/d9c6825b9a94cf6637ba01416562e4eb777db7a2
mkdir -p /var/tmp/sb-client-readiness/vault
install -m 0600 /home/jm/orca/projects/second-brain-app/config.example.toml \
  /var/tmp/sb-client-readiness/config.toml
# config.toml vault_root → 격리 vault 후:
SB_CONFIG=/var/tmp/sb-client-readiness/config.toml "$CAND/bin/sb" init
SB_CONFIG=/var/tmp/sb-client-readiness/config.toml "$CAND/bin/sb" doctor
# 등록은 실행하지 않음. 공개 CLI 예시만:
# codex mcp add second-brain --env SB_CONFIG=/var/tmp/sb-client-readiness/config.toml -- \
#   $CAND/bin/sb mcp
```

Claude Code 등 `mcpServers` JSON은 README SSH 예시와 구분한다. 운영 `~/.config/second-brain/config.toml`은 쓰지 않는다.

### 필수 입력 (이름만)

공개 예시로 준비 가능: 격리 디렉터리, `config.example.toml`, 후보 `bin/sb mcp`, Codex `mcp add` TOML CLI.

비밀 대신 항목 이름:
- Codex **로그인 프로필** (현재 로그인 여부는 미확인)
- compile 시 `argv_template` **Claude CLI 프로필**
- 제안 업무 원문(아직 기억/native로 보내지 않음): 사용자가 지정한 `/home/jm/orca/projects/Orca-JARVIS/docs/second-brain-oss-absorption-handoff-2026-09-07.md` 및 “세컨드브레인·자비스 연동 완료 요청” 맥락. 제안 ≠ native 종단 성공.

### 운영 공개 스냅샷 (서비스 변경 없음)

인용: `/var/tmp/codex-completion-20260913-u7qerm73/operational-readonly-snapshot.json` (`observed_at` 2026-09-13T12:15:12+09:00, read_only).
- SB current → `41f0751aca8906d612961e704bc60dd0855fdabd`
- JARVIS authority current → `a3cbbbe1604798052db6051a8751f039573eb126`
- `jm-jarvis.service` / dashboard / phone-gateway: active running
- `jm-second-brain-requests.service`: oneshot, inactive/dead, 마지막 성공 2026-09-03 23:53:58 KST
- 같은 이름 timer: LoadState not-found. 단독 장애나 timer 필요로 단정하지 않음.

### 이 준비가 완료로 치환하지 않는 것

운영 전환, 원 M5/M9/M13 보류 수명, native 자동주입, 실사용 질의 성공, 보안/삭제경합 분기.

## 근거 파일

- `README.md` (일반 mcpServers JSON·SSH 예시 — Codex TOML과 구분)
- `config.example.toml`, `sb/config.py:185` SB_CONFIG
- `sb/cli.py` `Command.MCP`
- `codex mcp add --help` (observed)
- `CODEX-NIGHT-REVIEW-20eff3c.md`
