# SB 운영 전환 기록 — 2026-09-15 (JARVIS 미전환)

실행: Claude Fable 5.1, 사용자 승인. 2026-09-15T02:02:43.415353+00:00. 원본 `/var/tmp/claude-night-e53dd66-GBr0la/cutover-2026-09-15.json`, gates/.

- 릴리스: `~/.local/state/second-brain/app/releases/2ccf0267…` (source b9039d2, sb/ = 8d1f8cc 183파일 일치, wheel 60d66ad6…). 이전 current 41f0751 릴리스 디렉터리 보존.
- 사전 점검: pending 큐 비어 있음, active cursor 0, SB writer lock 미보유, DB 핸들은 jm-jarvis 유닛뿐, 백업 존재, 디스크 여유. 미해결 lease 1건은 실행 중인 jm-jarvis.service 소유(JARVIS 미전환이라 해당 없음).
- 백업: `second-brain-20260915T100736+0900.tar.gz` sha256 검증.
- 절차: SB 유닛만 정지 → current 원자 교체 → 유닛 재시작(web 200, apply-requests NO_PENDING_REQUEST) → 검색 `GENERATION_INDEX_INVALID` 발견(구 세대 search.db 스키마가 새 질의 계획 열 없음) → `doctor --rebuild-ledger`는 done→running 전이 오류로 실패(활성화 없음) → `jm-second-brain-refresh.service`(sb run)로 새 세대 `sbgen:v1:c58f6026…` 게시(3m40s) → 검색/web/doctor(ledger 5/5) 정상 → 타이머 재가동.
- 잔여: 구 릴리스 경로의 `sb mcp` 프로세스 18개(클라이언트 세션 재시작 시 교체), last_run `capped`(LLM 상한), doctor `scheduler-assets` warn, JARVIS는 a3cbbbe 그대로(scoped v4·postcompact consumer·N1 휴면).
- rollback: 링크를 41f0751로 되돌리고 web 재시작(구 릴리스는 전환 전 세대 febe7de2…를 읽음).

## 후속: compile `capped` 처리 (11:19–11:29 KST)
- 원인: SB 아님. 서비스가 쓰는 `/usr/bin/codex`(0.144.6)가 사용자의 `~/.codex/config.toml`(model `gpt-6-astra`, `openai_base_url=http://127.0.0.1:10100/v1` 로컬 프록시)을 읽어 모든 compile LLM 호출이 실패("LLM unavailable after 2 attempts" ×40). 격리 `CODEX_HOME`(빈 config, `auth.json`은 `~/.codex/auth.json` 심볼릭)에서는 CLI 기본 모델로 `codex exec`가 정상 동작함을 두 바이너리에서 확인.
- 조치: `/home/jm/.local/state/second-brain/codex-home` 생성(0700). `~/.config/second-brain/jarvis-provider.toml`(refresh 경로)과 `config.toml`의 `llm.argv_template` 앞에 `env CODEX_HOME=<그 경로>` 추가. 원본은 `*.bak-20260915T111901`로 보존. 사용자 `~/.codex` 설정은 변경하지 않음.
- 결과: refresh.service 재실행 → compile 40 pages(설정 cap `max_llm_calls_compile=40`), brief 1 page, run `762c5f43…` **ok**, compile 실패 0. 남은 실패는 brief 5건(`daily/2026-09-05: unresolved [^uncited]`, `BRIEF_REPLAY_INPUTS_UNAVAILABLE` 보류; 전환 전부터 존재).

## brief 실패 5건 판정
`daily/2026-09-05` 시간별 실행 5회(2026-09-05 10:26–14:36 UTC)의 brief 검증 실패(`unresolved [^uncited]`) 기록이다. 같은 날 이후 실행이 성공해 `daily/2026-09-05.md`는 존재한다. 제품은 역사적 brief 재시도를 의도적으로 보류하고 실패 행과 attempts를 보존한다(`sb/ops.py` `BRIEF_REPLAY_INPUTS_UNAVAILABLE`). 원장 직접 편집은 세대 무결성 설계에 어긋나므로 하지 않는다. doctor/readiness는 이를 결함으로 보지 않으며 운영 영향 없음 → **감사 기록으로 유지, 조치 없음**.

## 운영 unit 재설치 판정
`deploy/install-systemd-user.sh --dry-run` 대조: 설치된 second-brain.timer / backup.service / backup.timer / web.service는 리포와 동일, `second-brain.service`만 4줄 차이이며 이 유닛은 inactive(운영 실행은 JARVIS deploy의 `jm-second-brain-refresh.service`). `jm-second-brain-requests.*`는 JARVIS deploy 소유 유닛으로 SB 리포 설치 대상이 아님. doctor `scheduler-assets` warn은 wheel에 `deploy/systemd`가 포함되지 않아 생기는 안내로 기능 영향 없음. → **재설치하지 않음(변경 이유 없음)**.

## 2차 SB 전환 (13:34 KST) — 보류 분기 H1–H4 반영
- 릴리스 `~/.local/state/second-brain/app/releases/8ea65a7d…`(source b239c0b, sb/ = 83a7aba 183파일 일치, wheel 6bc94e22…), 전체 회귀 1924 passed / 3 skipped / EXIT0 후 relink.
- 절차: SB 유닛 정지(pending 0, writer 없음) → current 교체 → 유닛 재시작 → web 200, 검색 정상, doctor pass(scheduler-assets warn만). 파생 인덱스 스키마 불변이라 세대 재생성 불필요. JARVIS 미변경.

## JARVIS 페어 전환 (14:24– KST) — 진행 기록
- 사전: JARVIS HEAD 65bfd64(lint/typecheck 0, 전체 verify 1578 passed + 사전 존재 2건은 65bfd64로 해소), worktree clean. 타이머 정지 → 백업 `backups/jarvis-20260915T052439257Z-231c6a07801da415.sqlite`(integrity ok, migrations 58) + `/var/tmp/jarvis-precutover-20260915T052439Z.sqlite`.
- control-center 부트스트랩 릴리스 `artifact-3b439dfc…`(source 65bfd64; 의존성은 HEAD lock으로 `npm ci --omit=dev` + `npm rebuild better-sqlite3 --build-from-source`) 발행·활성화 → authority 릴리스 `49f0680c…` 발행·활성화(publisher가 CC current의 node_modules를 hardlink).
- 서비스 재시작: jm-jarvis `db.migrate ok`(schema_migrations 58→81), lease fence 242230·pid 일치, `service status ok`, backup.service 성공.
- **장애**: jm-jarvis-dashboard가 기동 직후 core-dump(`better_sqlite3.node` `Statement::~Statement` → `RemoveEnvironmentCleanupHook` assertion). phone-gateway는 dashboard 의존으로 미기동. 원인 격리: 새 dist + 구 릴리스의 prebuilt `better_sqlite3.node`(45cb92a1…)로 dashboard HTTP 200 → **소스 재빌드한 native 모듈이 문제**. 조치: `npm ci --omit=dev`만(prebuilt) 의존성으로 CC/authority 릴리스 재발행 예정. 그동안 dashboard 재시작 루프 정지, authority 서비스는 정상.
- **복구·완료 (14:30–14:32 KST)**: deps2(`npm ci --omit=dev`만, prebuilt `better_sqlite3.node` sha 45cb92a1… = 구 릴리스와 동일)로 control-center `artifact-7e8ddde9…` 발행·활성화, authority `387c7c95…` 재발행·활성화(둘 다 source 65bfd64). 서비스 재시작(lease 만료 55s 대기 후): jm-jarvis `db.migrate ok`, dashboard 200, phone-gateway healthz/readyz 200, journal assert/abort 0, 타이머 재가동. 실패 릴리스 `artifact-3b439dfc…`/`49f0680c…`는 디렉터리 보존(current 아님).
- 운영 핀(최종): SB current `8ea65a7d…`(83a7aba) / JARVIS authority current `387c7c95…`(65bfd64) / control-center current `artifact-7e8ddde9…`(65bfd64). 이전: a3cbbbe / artifact-4146a192 보존. rollback은 Step-5 백업 복원 + 두 current 동시 복귀(runbook).
- **전환 후 SB↔JARVIS 게이트 (14:33 KST)**: 라이브 authority 릴리스 387c7c95의 dist를 artifact 배치(`/var/tmp/jarvis-ops-gate-387c7c95/dist`, node_modules는 동일 lock의 작업 트리 복사)로 두고 `check-release-integration.py` (SB current 8ea65a7 × JARVIS 387c7c95) **EXIT0**, `--work REAL-WORK-ITEM-2026-09-15.json`(오늘 운영 전환 검증 결과, 실제 콘텐츠) **EXIT0**, provider_state proved·jarvis_settled true. 로그 `/var/tmp/claude-night-e53dd66-GBr0la/gates/{integration,work}-ops-387c7c95.log`.
- **구 릴리스 MCP 서버 정리**: 41f0751/2ccf0267 경로의 `sb mcp` 프로세스 12개 SIGTERM → 0개. 현재 릴리스 프로세스 10개 유지(클라이언트가 필요 시 재생성).
- **M2/M4 운영 경로 판단**: 신 JARVIS CLI에도 실사용 업무를 직접 제출하는 명령은 없고 기억 계보는 gjc 검증 레코드에서 시작한다(`service status` connected:false, 코디네이터 미구성). 운영 DB에 검증 레코드를 임의 삽입하지 않는다. 실사용 종단은 실제 검증 태스크가 생기면 동일 경로로 이어진다.

## 15:00 정기 실행 실패 — 원인: Codex 계정 사용량 한도
15:00 refresh 실행에서 compile 2건·brief 1건 실패("LLM unavailable"). 격리 CODEX_HOME으로 `codex exec` 직접 재현: **"You've hit your usage limit … try again at Sep 19th, 2026 5:11 PM"** (ChatGPT 계정 Codex 한도 소진). 11:19 조치(격리 CODEX_HOME)는 유효하며 12:00–14:00 실행은 정상이었다. 사용자 프록시(ocx, gpt-6-astra)는 상위 토큰 만료로 별도 불가. → LLM compile은 9/19 17:11 KST까지 계정 한도 외부 조건. 실패 compile 행은 `retry_hold_reason` 없음이라 한도 회복 후 `sb retry --stage compile`로 정상 재시도 가능. 대안(사용자 결정): `llm.argv_template`를 `claude -p`(예: Haiku)로 전환 — 비용·데이터 제공자 변경이므로 승인 필요.

## M13 실사용자 처분 — 운영 GUI에서 실제 페이지 삭제 (15:2x KST)
사용자 위임에 따라 운영 콘솔(127.0.0.1:8765)에서 실제 중복 페이지를 처분했다: `wiki/inbox-2026-09-09t130927692351-grok-bot-운영-10점-계약-7c4748df`(같은 주제의 6분 뒤 페이지 `…f8c074a8`가 존재). GUI "페이지 삭제" → `{"forgotten": …, "commit": "853ae3cb…"}`, 새 세대 `sbgen:v1:d55ac3ac…` 게시. 검증: `sb search "grok-bot 운영 10점 계약"` 구 페이지 0건 / 신 페이지 2건, 세대 wiki에 파일 없음. 삭제 전 백업(14:56 `second-brain-20260915T145651+0900.tar.gz`) 보존. 아울러 실제 운영 기록 노트("2026-09-15 운영 전환 기록")를 GUI로 기억(영수증 `inbox/2026-09-15T060017028950-…`)했으나 compile은 Codex 계정 한도(9/19)로 대기 중.

## 3차 SB 전환 — 2026-09-15 18:41 KST (H5/H6 readiness 종결, 제품 45f5b72)
- 릴리스 `~/.local/state/second-brain/app/releases/62ffbc9d…`(source a5c4159, 제품 45f5b72; Grok 격리 후보 id와 동일). 검증: `CLAUDE-NIGHT-REVIEW-45f5b72.md`.
- 백업 `second-brain-20260915T184120+0900.tar.gz`(checksum c23aa3b1…). 사전: pending 요청 0, refresh.service failed(18:01, Codex 한도) → reset-failed.
- 18:41:44 stop requests.path/refresh.timer/maintenance.timer/web → relink current → start → web 200, doctor PASS, search 정상. JARVIS 무관.
- 18:41:56 maintenance 1회: journal activated 3(고아)→proved, brief failed 5→superseded(6). 단, 종료 시 `GENERATION_READER_DRAIN_REQUIRED` exit 1 — 동시에 실행한 내 `sb status --json` 읽기가 선행 세대 fd를 잡고 있던 탓(재현 시 fd 0). 18:43:29 재실행 → Finished, activations 247 전부 proved, 세대 디렉터리 4개.
- 결과 `/ready`: `GENERATION_CLEANUP_STALLED` 해소. 잔여 `LAST_RUN_UNSUCCESSFUL` + `DERIVATIONS_FAILED`(compile 2행, "LLM unavailable … OpenAI Codex v0.144.6" = ChatGPT Codex 한도, 2026-09-19 17:11 KST 해제 예정). 한도 복구 후 `sb retry --stage compile` + refresh 1회로 정상화 예상. 이전 current 8ea65a7d 보존(롤백: relink + 동일 절차).
- 교훈: maintenance 실행 중 `sb status`/`search` 등 읽기 CLI를 병행하지 말 것(선행 세대 폐기의 reader drain 검사에 걸림).

## 클라이언트 기억 훅 설치(M8) — 18:39 KST
- 공통 래퍼 `~/.config/second-brain/hooks/sb-memory-hook.sh` → `app/current/bin/sb postcompact-hook`(운영 config 기본).
- Claude Code `~/.claude/settings.json`(백업 `.bak-sb-20260915T1840`): UserPromptSubmit / SessionStart(matcher compact) / PostCompact 추가.
- Codex CLI `~/.codex/hooks.json`(백업 `.bak-sb-20260915T1840`): 동일 3이벤트. 격리 CODEX_HOME 프로브에서 UserPromptSubmit 훅 실행·SB 응답 확인, SessionStart(source=compact)로 in-turn 컨텍스트 반환 확인(합성 이벤트). **주의: Codex는 hooks.json 변경 후 TUI 첫 실행 시 "Hooks need review" → "Trust all and continue"를 사용자가 1회 선택해야 훅이 켜진다**(신뢰 전에는 조용히 실행 안 됨). 컴파일용 격리 CODEX_HOME에는 hooks.json이 없어 영향 없음.
- OmO(senpi 2026.9.13) `~/.omo/agent/extensions/sb-memory.js`: `before_agent_start`→UserPromptSubmit(last_query 기억, 잔여 주입), `session_compact`(accepted)→PostCompact 스테이징 + SessionStart(compact) 조회 → `pi.sendMessage(steer)`로 in-turn 주입. fake-pi 하네스(주입/중복억제/거부 이벤트 무시) + 실제 `omo -p -e` 로드 확인. 실행 중인 Grok OmO 세션은 `/reload` 또는 재시작 후 적용.

## LLM 백엔드 교체 — 2026-09-15 18:55 KST (사용자 지시: Codex 한도 → Grok)
- `~/.config/second-brain/llm/omo-grok.sh`(OmO print 모드, `xai/grok-4.6`, thinking low, 최소 system prompt, stdin 프롬프트)로 `config.toml`·`jarvis-provider.toml`의 `llm.argv_template` 교체(백업 `*.bak-20260915T1855`). `sb retry --stage compile` requeued=2 → 19:52 refresh에서 compile 2행 done(Grok, 행당 ~10초).
- 같은 refresh에서 brief 단계 failed(20ms, 무메시지): 45f5b72 H6가 오늘 15:00 실패행(일시 장애)까지 superseded로 만들어 `mark_running` 전이 불가. → H7 지시(`CLAUDE-DIRECTIVE-H7-BRIEF-SUPERSEDE-2026-09-15.md`).

## 4차 SB 전환 — 2026-09-15 20:11 KST (H7, 제품 7cab61b)
- 릴리스 `releases/13688d66…`(source 7cab61b). 검증 `CLAUDE-NIGHT-REVIEW-7cab61b.md`(1933 passed). 백업 `second-brain-20260915T201138+0900.tar.gz`.
- 20:11:53 stop → relink → start, web 200, doctor PASS 8. 20:11:56 refresh 1회 → **last_run ok**, `/ready` = **ready, reasons []**. 이전 current 62ffbc9d 보존.
