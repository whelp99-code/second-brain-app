# Second Brain Terminal Work Memory 단계별 개발계획서

- 문서 상태: **SUPERSEDED — 독립 실행 금지**
- 기준 프로젝트: `second-brain-app`
- 기준 제품 버전: `1.0.0`
- 목표 버전: `1.4.0`
- 작성 기준일: 2026-08-29
- 권위 있는 데이터 서버: `jm-cloud` Ubuntu
- 클라이언트 환경: macOS 및 `jm-cloud`
- 대상 에이전트: OMP/Luna, Claude Code, Codex 및 MCP 호환 에이전트
- 문서 목적: 각 터미널을 독립적인 작업 세션으로 식별하고 프로젝트·에이전트·명령·결과·실패·해결·개선점·다음 작업을 추적 가능한 공용 기억으로 남기는 기능을 단계적으로 구현·검증·운영한다.

> 이 문서의 독립형 구현 순서는 2026-08-29 JARVIS 실제 계획 분석 후 폐기됐다. 최신 실행 기준은 [`ORCA-JARVIS-SECOND-BRAIN-JOINT-DEVELOPMENT-PLAN.md`](ORCA-JARVIS-SECOND-BRAIN-JOINT-DEVELOPMENT-PLAN.md)이다. ORCA의 실행 사실과 terminal operational state는 JARVIS가 소유하고, 검증된 장기기억만 Second Brain에 정착시킨다.

---

## 1. 확장 기능 정의

### 1.1 고정 정의

Terminal Work Memory는 Mac과 `jm-cloud`에서 열리는 각 터미널을 독립적인 작업 세션으로 식별하고, 터미널에서 수행한 작업의 **사실**과 에이전트가 이해한 **의미**를 분리해 수집한 뒤 하나의 Second Brain 프로젝트 기억으로 통합하는 기능이다.

```text
Terminal Collector = 사실과 실행 증거
Agent MCP           = 목적·판단·의미
Second Brain        = 프로젝트 단위 통합 기억
```

이 기능은 터미널 화면을 무차별 녹화하는 제품이 아니다. 다음 질문에 근거와 함께 답하기 위한 작업 기억 계층이다.

1. 이 터미널은 어느 컴퓨터에서 열렸는가?
2. 어느 프로젝트를 대상으로 작업했는가?
3. 어떤 에이전트와 모델이 작업했는가?
4. 어떤 명령과 도구를 실행했는가?
5. 무엇이 성공했고 무엇이 실패했는가?
6. 실패 원인은 무엇이었고 어떻게 해결했는가?
7. 어떤 파일·커밋·Issue·산출물이 만들어졌는가?
8. 최종 결과는 성공·부분 성공·중단·실패 중 무엇인가?
9. 남은 작업과 반복 문제는 무엇인가?
10. 다음에는 무엇을 자동화하거나 개선해야 하는가?

### 1.2 기존 1.0.0 방향과의 관계

기존 방향은 변경하지 않는다.

- 단일 사용자·단일 Vault
- `jm-cloud`가 원본·원장·Wiki·검색의 권위 있는 저장소
- Mac은 주 사용자 클라이언트
- 원본 보존, 출처 추적, Git 이력, 복구 가능성 우선
- 여러 에이전트가 MCP를 통해 하나의 기억을 공유
- 쓰기 작업은 단일 writer와 lock으로 직렬화
- 자동 삭제·외부 변경·Issue 생성은 승인 기반

Terminal Work Memory는 기존 문서·대화 기억에 실행 역사를 추가한다.

```text
문서·대화·업로드 기억
        +
터미널 작업 기억
        +
에이전트 의미 기억
        ↓
프로젝트의 연속적인 실행 역사
```

---

## 2. 현재 구현 기준선

| 영역 | 현재 상태 | 한계 |
| --- | --- | --- |
| Orca 기록 수집 | 부분 구현 | `worktree_comment`, `terminal_summary`, `artifact`를 수집함 |
| Orca 실시간 터미널 | 의도적 차단 | `live_terminal`, auth, credential 계열은 수집하지 않음 |
| Claude Code 세션 | 부분 구현 | `message`, `tool_use`, `tool_result`를 텍스트로 수집함 |
| Codex 세션 | 부분 구현 | 사용자 메시지와 최종 assistant 메시지를 수집함 |
| 일반 bash/zsh 명령 | 미구현 | 명령 경계·exit code·duration 자동 수집기가 없음 |
| Project 기록 | 부분 구현 | export JSONL과 Unified DB의 `project_id`를 읽을 수 있음 |
| Unified DB | 기반 존재 | `project_id`, `source_id`, `actor`, `action`, `status`, `summary` 매핑이 있음 |
| MCP | 구현 | 검색·읽기·기억·즉시 처리 6개 도구 제공 |
| 터미널 전용 MCP | 미구현 | context/checkpoint/failure/finish/search 도구 없음 |
| Mac offline spool | 미구현 | 네트워크 단절 재전송 큐 없음 |
| 터미널 타임라인 UI | 미구현 | 네이티브 앱 화면 없음 |
| 실패 해결 관계 | 미구현 | 실패 명령과 해결 명령을 구조적으로 연결하지 않음 |
| 개선점 자동 도출 | 미구현 | 반복 실패·수동 작업·테스트 누락 분석기가 없음 |

현재 커넥터의 공통 `ItemMeta`는 `relative_path`, `cursor`, `skip_reason` 수준이다. Terminal Work Memory는 기존 수집 계약을 무리하게 확장하지 않고 별도의 작업 이벤트 계약과 저장 계층을 추가한다.

---

## 3. 범위와 비범위

### 3.1 1.1.0~1.4.0 포함 범위

- Mac 및 `jm-cloud`의 bash/zsh 터미널 세션 식별
- 호스트·TTY·shell·terminal app·시작/종료 시각 기록
- 명령, exit code, duration, cwd 전후 상태 기록
- Git repository, branch, worktree, HEAD 연결
- 등록 프로젝트와 workername 기반 프로젝트 판별
- 한 터미널 안에서의 프로젝트 구간 분리
- OMP/Luna, Claude Code, Codex 에이전트 세션 연결
- 에이전트 checkpoint, failure, finish 의미 기록
- 실패와 해결 명령·checkpoint 연결
- Mac offline spool과 중복 없는 재전송
- 터미널 세션 최종 요약 Markdown 생성
- 프로젝트별 터미널 활동 검색
- 터미널 타임라인과 미해결 실패 UI
- 반복 실패, 반복 수동 작업, 테스트 누락, 기술 부채 분석
- 승인 기반 GitHub Issue 초안 및 생성
- 보안 마스킹, capture pause, 보존·삭제 정책
- 설치, upgrade, rollback, backup, restore, doctor

### 3.2 비범위

- 키 입력 전체 녹화
- 비밀번호 prompt 또는 secure input 수집
- stdout/stderr 무제한 영구 저장
- 터미널 영상 녹화
- 원격 명령 제어·자동 실행
- private reasoning 또는 hidden chain-of-thought 수집
- 사용자 승인 없는 Issue·commit·push
- 직원 감시 또는 생산성 점수화
- 공개 인터넷용 ingestion API
- Windows PowerShell 수집기
- multi-writer 분산 Vault

### 3.3 수집 원칙

```text
수집 가능한 최소 사실만 저장한다.
명령 실행 경계는 저장하되 키 입력은 저장하지 않는다.
출력은 기본적으로 preview와 hash만 저장한다.
민감 명령은 명령 이름만 남기고 인자를 제거한다.
의미는 에이전트의 명시적 checkpoint로 보완한다.
```

---

## 4. 운영 토폴로지

### 4.1 Mac

```text
Mac Terminal / iTerm / OMP / Claude / Codex
        ↓
Shell Hook + Agent Bridge
        ↓
Mac Local Collector Daemon
        ↓
Protected Local Spool
        ↓ SSH tunnel over Tailscale
jm-cloud Terminal Ingestion API
        ↓
Ledger + CAS + Terminal Summary + Search
```

### 4.2 jm-cloud

```text
jm-cloud bash / OMP / Claude / Codex
        ↓
Shell Hook + Agent Bridge
        ↓
Local Collector 또는 local CLI
        ↓
동일한 Second Brain Ledger + Vault
```

Mac과 `jm-cloud`는 별도 지식 DB를 만들지 않는다.

```text
Mac Terminal A ───┐
Mac OMP Session ──┤
jm-cloud Codex ───┼──→ 동일한 Second Brain Vault
jm-cloud Shell B ─┘
```

---

## 5. 용어와 핵심 엔터티

| 용어 | 정의 |
| --- | --- |
| Host | Mac 또는 `jm-cloud`처럼 이벤트를 생성하는 장치 |
| Terminal Session | 하나의 TTY·터미널 창·탭의 생명주기 |
| Project Segment | 한 터미널이 특정 프로젝트에 머문 연속 구간 |
| Agent Session | OMP, Claude Code, Codex 대화 세션 |
| Command Event | shell 명령의 시작·종료·결과 이벤트 |
| Tool Event | 에이전트 tool call과 tool result |
| Checkpoint | 목표·결정·진척·결과·handoff의 의미 단위 |
| Failure | 해결 추적이 필요한 명령·도구·작업 실패 |
| Resolution | Failure를 해결한 명령, checkpoint, commit 또는 결정 |
| Terminal Summary | 세션 전체를 사람이 읽을 수 있게 정리한 문서 |
| Improvement Finding | 반복 문제·자동화 후보·테스트 누락 등 개선 제안 |
| Spool | 서버 전송 전 클라이언트에 임시 보관되는 이벤트 큐 |

---

## 6. 목표와 성공 기준

| ID | 목표 | 성공 기준 |
| --- | --- | --- |
| TWM-GOAL-001 | 터미널 식별 | Mac 터미널 2개와 `jm-cloud` 터미널을 서로 다른 ID로 식별 |
| TWM-GOAL-002 | 프로젝트 연결 | 대표 평가 세트에서 자동 판별 정확도 95% 이상, 불확실하면 `unassigned` |
| TWM-GOAL-003 | 명령 정확성 | command, exit code, duration, cwd를 정확히 기록 |
| TWM-GOAL-004 | 실패 추적 | 중간 실패와 최종 세션 결과를 분리하고 해결 관계를 저장 |
| TWM-GOAL-005 | 에이전트 연계 | OMP, Claude, Codex 세션을 terminal/project와 연결 |
| TWM-GOAL-006 | 두 환경 지원 | Mac과 `jm-cloud`에서 같은 프로젝트 기억을 조회·저장 |
| TWM-GOAL-007 | 오프라인 복구 | Tailscale 단절 중 이벤트를 복구 후 중복 없이 전송 |
| TWM-GOAL-008 | 보안 | password, API key, token, private key 원문 저장 0건 |
| TWM-GOAL-009 | 사용성 | Mac 앱에서 세션·실패·개선점·spool 상태 확인 |
| TWM-GOAL-010 | 개선 지능 | 반복 실패와 수동 작업을 근거와 함께 개선 후보로 제시 |
| TWM-GOAL-011 | 복구 | backup/restore 후 동일 timeline과 검색 결과 복원 |
| TWM-GOAL-012 | 비침투성 | shell hook p95 10ms 이하, collector 장애가 명령 실행을 막지 않음 |

---

## 7. 개발 원칙

1. **사실과 의미 분리:** Collector는 사실, MCP는 의미를 기록한다.
2. **Fail-open capture:** 수집기 장애가 사용자 작업을 막지 않는다.
3. **No keylogging:** 실행이 확정된 command만 취급하고 키 입력은 수집하지 않는다.
4. **Bounded output:** 일반 shell은 제한된 transcript만, agent tool result는 가능한 범위에서 구조화한다.
5. **No forced project guess:** 신뢰도가 낮으면 `unassigned`로 둔다.
6. **Idempotency:** 재전송·재시작·중복 callback에도 한 번만 저장한다.
7. **Intermediate failure preservation:** 실패는 삭제하지 않고 해결 관계를 추가한다.
8. **Backward compatibility:** 기존 Wiki, Daily, MCP, macOS 기능을 깨뜨리지 않는다.
9. **Approval gates:** Issue 생성과 외부 변경은 사용자 승인 후 수행한다.
10. **Capture before intelligence:** 정확한 이벤트를 증명한 뒤 LLM 개선 분석을 붙인다.

---

## 8. 요구사항

### 8.1 Host와 Terminal

| ID | 요구사항 |
| --- | --- |
| REQ-TWM-HOST-001 | 각 장치는 안정적인 random `host_id`를 생성해야 한다. |
| REQ-TWM-HOST-002 | host ID에 이메일·IP·secret을 직접 사용하지 않아야 한다. |
| REQ-TWM-TERM-001 | 각 터미널 창/탭/TTY에 충돌하지 않는 `terminal_id`를 부여해야 한다. |
| REQ-TWM-TERM-002 | host, tty, shell, terminal app, 시작·종료 시각을 저장해야 한다. |
| REQ-TWM-TERM-003 | nested shell과 부모 terminal을 연결해야 한다. |
| REQ-TWM-TERM-004 | 비정상 종료는 heartbeat timeout으로 `abandoned` 처리해야 한다. |
| REQ-TWM-TERM-005 | 사용자가 terminal별 capture를 pause/resume할 수 있어야 한다. |

### 8.2 Project 판별

| ID | 요구사항 |
| --- | --- |
| REQ-TWM-PROJ-001 | 명시적 project ID와 workername을 최우선으로 사용해야 한다. |
| REQ-TWM-PROJ-002 | cwd가 등록 project root 하위인지 확인해야 한다. |
| REQ-TWM-PROJ-003 | Git root, remote, worktree metadata로 보조 판별해야 한다. |
| REQ-TWM-PROJ-004 | project가 바뀌면 새 Project Segment를 생성해야 한다. |
| REQ-TWM-PROJ-005 | 판별 방식과 confidence를 저장해야 한다. |
| REQ-TWM-PROJ-006 | 기준 이하 confidence는 `unassigned`로 저장해야 한다. |
| REQ-TWM-PROJ-007 | 사용자가 segment를 재지정할 수 있어야 한다. |

### 8.3 Command와 Output

| ID | 요구사항 |
| --- | --- |
| REQ-TWM-CMD-001 | command, 시작·종료 시각, duration, exit code를 기록해야 한다. |
| REQ-TWM-CMD-002 | cwd before/after를 기록해야 한다. |
| REQ-TWM-CMD-003 | Git root, branch, worktree, HEAD before/after를 선택적으로 기록해야 한다. |
| REQ-TWM-CMD-004 | signal 종료를 구분해야 한다. |
| REQ-TWM-CMD-005 | pipeline·compound command를 실행 원문 단위로 보존해야 한다. |
| REQ-TWM-CMD-006 | terminal-local sequence로 순서를 복원해야 한다. |
| REQ-TWM-OUT-001 | 출력은 크기 제한 preview와 content hash로 저장해야 한다. |
| REQ-TWM-OUT-002 | PTY 출력은 stdout/stderr를 억지로 구분하지 않고 `combined`로 표시해야 한다. |
| REQ-TWM-OUT-003 | agent tool result는 가능한 경우 stdout, stderr, exit code를 구조화해야 한다. |
| REQ-TWM-OUT-004 | 제한 초과 시 truncated flag와 원래 byte count를 남겨야 한다. |

### 8.4 Agent

| ID | 요구사항 |
| --- | --- |
| REQ-TWM-AGENT-001 | OMP/Luna, Claude Code, Codex session을 terminal ID와 연결해야 한다. |
| REQ-TWM-AGENT-002 | platform, model, session ID, 시작·종료 시각을 저장해야 한다. |
| REQ-TWM-AGENT-003 | private reasoning을 요청하거나 저장하지 않아야 한다. |
| REQ-TWM-AGENT-004 | 한 terminal에서 agent가 바뀌어도 같은 project segment를 유지해야 한다. |
| REQ-TWM-AGENT-005 | 연결 근거가 부족한 기존 세션은 독립 legacy session으로 유지해야 한다. |

### 8.5 Failure와 Resolution

| ID | 요구사항 |
| --- | --- |
| REQ-TWM-FAIL-001 | non-zero exit, timeout, signal, tool error를 failure candidate로 기록해야 한다. |
| REQ-TWM-FAIL-002 | fingerprint, category, severity, first/last seen을 저장해야 한다. |
| REQ-TWM-FAIL-003 | 해결 command/checkpoint/commit/Issue와 연결해야 한다. |
| REQ-TWM-FAIL-004 | `open`, `investigating`, `resolved`, `accepted`, `superseded` 상태를 지원해야 한다. |
| REQ-TWM-FAIL-005 | terminal 최종 outcome은 개별 command outcome과 별도로 계산해야 한다. |
| REQ-TWM-FAIL-006 | 자동 해결 확정은 금지하고 근거가 있을 때 제안만 해야 한다. |

### 8.6 MCP

| ID | 요구사항 |
| --- | --- |
| REQ-TWM-MCP-001 | `sb_terminal_context`를 제공해야 한다. |
| REQ-TWM-MCP-002 | `sb_terminal_checkpoint`를 제공해야 한다. |
| REQ-TWM-MCP-003 | `sb_terminal_failure`를 제공해야 한다. |
| REQ-TWM-MCP-004 | `sb_terminal_finish`를 제공해야 한다. |
| REQ-TWM-MCP-005 | `sb_terminal_search`를 제공해야 한다. |
| REQ-TWM-MCP-006 | `sb_project_activity`를 제공해야 한다. |
| REQ-TWM-MCP-007 | `sb_unresolved_failures`를 제공해야 한다. |
| REQ-TWM-MCP-008 | Mac bridge는 SSH/Tailscale을 통해 `jm-cloud`의 동일 Vault를 사용해야 한다. |
| REQ-TWM-MCP-009 | `jm-cloud` MCP는 local `sb mcp`를 사용해야 한다. |
| REQ-TWM-MCP-010 | MCP 쓰기는 run lock과 event idempotency를 준수해야 한다. |

### 8.7 Sync와 Offline

| ID | 요구사항 |
| --- | --- |
| REQ-TWM-SYNC-001 | Mac은 연결 단절 시 이벤트를 local spool에 보존해야 한다. |
| REQ-TWM-SYNC-002 | 복구 후 순서와 idempotency를 유지하며 batch 전송해야 한다. |
| REQ-TWM-SYNC-003 | device/terminal/sequence/payload hash를 포함해야 한다. |
| REQ-TWM-SYNC-004 | server receipt를 받은 이벤트만 spool에서 삭제해야 한다. |
| REQ-TWM-SYNC-005 | spool 크기·보존일·oldest age를 UI와 CLI에 표시해야 한다. |
| REQ-TWM-SYNC-006 | 손상 row를 격리하고 나머지 전송을 계속해야 한다. |

### 8.8 Security

| ID | 요구사항 |
| --- | --- |
| REQ-TWM-SEC-001 | key, token, password, private key, cookie를 저장 전 마스킹해야 한다. |
| REQ-TWM-SEC-002 | `.env`, `.ssh`, Keychain, credential 파일 원문을 수집하지 않아야 한다. |
| REQ-TWM-SEC-003 | `read -s`, password prompt, sudo password 입력을 수집하지 않아야 한다. |
| REQ-TWM-SEC-004 | 민감 command는 이름과 결과 분류만 남길 수 있어야 한다. |
| REQ-TWM-SEC-005 | `SB_NO_CAPTURE=1`과 terminal pause를 지원해야 한다. |
| REQ-TWM-SEC-006 | Mac spool은 0700 directory, 0600 file을 사용해야 한다. |
| REQ-TWM-SEC-007 | ingestion API는 loopback 또는 SSH tunnel 전용이어야 한다. |
| REQ-TWM-SEC-008 | 원본 출력 보존 기간과 완전 삭제 정책을 지원해야 한다. |
| REQ-TWM-SEC-009 | redaction 전 원문을 log, exception, metric에 남기지 않아야 한다. |
| REQ-TWM-SEC-010 | 가짜 secret corpus로 전 저장 층을 검사해야 한다. |

### 8.9 Search, Summary, Improvement

| ID | 요구사항 |
| --- | --- |
| REQ-TWM-SEARCH-001 | terminal, host, project, agent, date, outcome, failure로 검색해야 한다. |
| REQ-TWM-SEARCH-002 | redacted token을 검색으로 복원할 수 없어야 한다. |
| REQ-TWM-SUM-001 | 목적·작업·결과·실패·해결·산출물·남은 작업·개선점을 요약해야 한다. |
| REQ-TWM-SUM-002 | 핵심 요약 항목은 command/checkpoint/commit 근거와 연결해야 한다. |
| REQ-TWM-IMPR-001 | 반복 failure를 fingerprint 기준으로 군집화해야 한다. |
| REQ-TWM-IMPR-002 | 반복 command sequence를 자동화 후보로 제안해야 한다. |
| REQ-TWM-IMPR-003 | 수정 후 regression test 누락을 탐지해야 한다. |
| REQ-TWM-IMPR-004 | dirty worktree, 미커밋 결과, 문서 누락을 제시해야 한다. |
| REQ-TWM-IMPR-005 | unresolved finding을 GitHub Issue 초안으로 변환해야 한다. |
| REQ-TWM-IMPR-006 | Issue 실제 생성은 승인 후에만 가능해야 한다. |

### 8.10 Ops와 Performance

| ID | 요구사항 |
| --- | --- |
| REQ-TWM-OPS-001 | doctor가 collector, hook, spool, tunnel, API, schema를 점검해야 한다. |
| REQ-TWM-OPS-002 | launchd와 systemd user service를 제공해야 한다. |
| REQ-TWM-OPS-003 | backup/restore가 terminal tables, receipts, summaries를 포함해야 한다. |
| REQ-TWM-OPS-004 | migration이 기존 1.0 Vault를 보존해야 한다. |
| REQ-TWM-OPS-005 | 기능 비활성화와 hook 제거가 한 명령으로 가능해야 한다. |
| REQ-TWM-PERF-001 | shell hook p95 10ms 이하여야 한다. |
| REQ-TWM-PERF-002 | collector IPC enqueue p95 20ms 이하여야 한다. |
| REQ-TWM-PERF-003 | online Mac 이벤트 반영 p95 60초 이하여야 한다. |
| REQ-TWM-PERF-004 | 100,000 command에서 project activity 조회 p95 1초 이하여야 한다. |

---

## 9. 목표 아키텍처와 모듈

```text
┌──────────────── Client Host ────────────────┐
│ zsh/bash hook   Agent MCP bridge   Mac App  │
│        └─────────────┬──────────────┘       │
│                      ▼                      │
│             Terminal Collector             │
│                      ▼                      │
│                  Local Spool                │
└──────────────────────┬──────────────────────┘
                       │ batch/receipt
                       ▼
┌──────────────── jm-cloud Second Brain ────────────────┐
│ Ingestion API/local ingest                            │
│   → Validate → Redact → Idempotency → Ledger/CAS     │
│   → Failure Resolver → Summary → Improvement          │
│   → Search/MCP/Web/macOS UI                           │
└────────────────────────────────────────────────────────┘
```

신규 모듈:

| 계층 | 모듈 | 역할 |
| --- | --- | --- |
| L0 | `sb/terminal/contracts.py` | event·state·ID 계약 |
| L1 | `sb/terminal/store.py` | terminal schema, transaction, query |
| L2 | `sb/terminal/redaction.py` | command/output secret 제거 |
| L2 | `sb/terminal/project_resolver.py` | project/segment 판별 |
| L2 | `sb/terminal/agent_linker.py` | agent session 연결 |
| L3 | `sb/terminal/ingest.py` | validation, idempotency, batch ingest |
| L3 | `sb/terminal/failures.py` | fingerprint와 resolution |
| L4 | `sb/terminal/summarize.py` | evidence 기반 세션 요약 |
| L4 | `sb/terminal/improvements.py` | 개선 finding 생성 |
| L5 | `sb/vault.py` 확장 | `terminals/` 문서의 유일한 writer |
| L6 | `sb/pipeline.py` 확장 | finalize·summary·improvement stage |
| L7 | `sb/cli.py`, `sb/mcp.py`, `sb/web.py` | CLI/API/MCP/search |
| Client | macOS client | spool, timeline, control UI |
| Deploy | launchd/systemd/shell hooks | 자동 실행 |

---

## 10. 데이터 모델

### 10.1 Tables

```text
terminal_hosts
terminal_sessions
terminal_project_segments
terminal_agent_sessions
terminal_commands
terminal_outputs
terminal_checkpoints
terminal_failures
terminal_improvements
terminal_sync_receipts
```

핵심 필드:

- `terminal_hosts`: host ID, display name, platform, collector version, last seen
- `terminal_sessions`: terminal ID, host, TTY, shell, app, lifecycle, outcome, primary project
- `terminal_project_segments`: terminal, project, cwd root, start/end, source, confidence
- `terminal_agent_sessions`: platform, model, session ID, terminal/segment linkage
- `terminal_commands`: sequence, command redacted, timestamps, duration, exit code, cwd, Git context
- `terminal_outputs`: stream, preview, hash, CAS ref, sizes, truncation
- `terminal_checkpoints`: goal/progress/decision/result/handoff와 evidence refs
- `terminal_failures`: fingerprint, category, severity, state, resolution ref
- `terminal_improvements`: category, rationale, evidence, priority, approval, Issue URL
- `terminal_sync_receipts`: idempotency key, payload hash, accepted result

### 10.2 Event envelope

```json
{
  "schema": "second-brain-terminal-event-v1",
  "event_id": "evt_01J...",
  "event_type": "command_finished",
  "host_id": "host_01J...",
  "terminal_id": "term_01J...",
  "sequence": 42,
  "occurred_at": "2026-08-29T13:35:35+09:00",
  "collector_version": "1.1.0",
  "payload_hash": "sha256:...",
  "payload": {}
}
```

필수 event types:

```text
host_registered
terminal_started
terminal_heartbeat
terminal_finished
cwd_changed
project_segment_started
project_segment_finished
agent_session_started
agent_session_finished
command_started
command_finished
output_chunk
checkpoint_created
failure_reported
failure_resolved
capture_paused
capture_resumed
```

Event ID는 재전송해도 동일해야 하며 `host + terminal + sequence + type + payload_hash`의 canonical 값으로 생성한다. client timestamp와 server accepted timestamp를 모두 저장하고 ordering은 sequence를 우선한다.

---

## 11. 상태 전이

```text
Terminal: new → active → finished | abandoned | cancelled
Command : started → success | failed | cancelled | unknown
Failure : open → investigating → resolved | accepted | superseded
Finding : proposed → approved → implemented | rejected
```

중간 command 실패는 삭제하지 않는다. 이후 검증이 성공하면 failure를 `resolved`로 전환하고 terminal outcome은 `success`가 될 수 있다.

---

## 12. Project Resolver

판별 우선순위:

1. `SB_PROJECT_ID`
2. agent/project selector의 canonical project ID
3. workername exact mapping
4. workspace registry root와 cwd
5. Git worktree root
6. Git remote URL
7. 최근 segment 유지
8. `unassigned`

기본 confidence 예:

| 방식 | confidence |
| --- | ---: |
| explicit ID | 1.00 |
| workername exact | 0.99 |
| workspace root exact | 0.98 |
| cwd descendant | 0.95 |
| Git remote exact | 0.95 |
| basename 추정 | 0.75 |
| 최근 segment | 0.60 |

자동 할당 임계값은 0.90으로 한다. cwd 또는 Git root가 바뀌면 resolver를 다시 실행하고 project가 바뀌면 segment를 닫고 새 segment를 연다.

---

## 13. Shell Capture

### 13.1 기본 metadata mode

- zsh: `preexec`/`precmd`
- bash: `DEBUG trap`/`PROMPT_COMMAND`
- command start/end
- exit code와 duration
- cwd before/after
- TTY/shell/Git context
- pause/no-capture

### 13.2 Output mode

일반 hook만으로 command별 stdout/stderr를 안정적으로 분리할 수 없으므로 다음 모드를 구분한다.

| mode | 설명 | 기본 |
| --- | --- | --- |
| metadata | command와 exit 상태 | 활성 |
| agent-tool | agent tool event의 stdout/stderr | 지원 agent에서 활성 |
| pty-combined | `sb terminal shell` subshell의 제한 transcript | opt-in |

1.1.0은 metadata와 agent-tool을 우선한다. PTY mode는 interactive compatibility와 보안을 검증한 뒤 opt-in으로 제공한다.

### 13.3 민감 command policy

`export *KEY`, `*TOKEN`, auth/login, `security`, `pass`, `op`, `aws configure`, `ssh-add`, `read -s`, `sudo -S`, password URI, Authorization header 등은 인자를 제거하거나 마스킹한다.

### 13.4 성능 구조

매 command마다 Python을 새로 실행하지 않는다.

```text
shell hook → 작은 bridge/Unix socket → 장기 실행 collector daemon
```

IPC 실패 시 command는 계속 실행되며 local emergency queue 또는 drop counter를 사용한다.

---

## 14. Agent-aware MCP

추가 도구:

| 도구 | 기능 |
| --- | --- |
| `sb_terminal_context` | 현재 host/terminal/project/agent와 최근 맥락 조회 |
| `sb_terminal_checkpoint` | 목표·결정·진척·결과·handoff 저장 |
| `sb_terminal_failure` | 실패와 원인 평가 저장 |
| `sb_terminal_finish` | 최종 결과·산출물·남은 작업 저장 |
| `sb_terminal_search` | terminal/project/agent 필터 검색 |
| `sb_project_activity` | 프로젝트 최근 터미널 활동 조회 |
| `sb_unresolved_failures` | 미해결 실패 조회 |

권장 호출 시점:

```text
작업 시작 → context
계획 확정 → checkpoint(decision)
중요 실패 → failure
검증 통과 → checkpoint(result)
작업 종료 → finish
```

Mac에서는 `sb-mcp-bridge`가 현재 `SB_TERMINAL_ID`, cwd, host, agent platform을 읽어 SSH/Tailscale을 통해 `jm-cloud`의 `sb mcp`에 전달한다. `jm-cloud`에서는 local `sb mcp`가 환경을 직접 상속한다. Agent가 MCP 호출을 누락해도 shell collector의 사실 이벤트는 남는다.

---

## 15. API와 CLI

### 15.1 API

| Method | Path | 기능 |
| --- | --- | --- |
| POST | `/api/terminal/events` | batch ingest |
| POST | `/api/terminal/checkpoints` | 의미 checkpoint |
| POST | `/api/terminal/failures` | failure 생성·갱신 |
| POST | `/api/terminal/finish` | session 종료 |
| GET | `/api/terminal/sessions` | session 목록 |
| GET | `/api/terminal/sessions/{id}` | timeline |
| GET | `/api/terminal/project-activity` | project activity |
| GET | `/api/terminal/failures` | failure 조회 |
| GET | `/api/terminal/improvements` | finding 조회 |
| POST | `/api/terminal/reassign` | project 재지정 |
| POST | `/api/terminal/capture-state` | pause/resume |

### 15.2 CLI

```text
sb terminal install
sb terminal uninstall
sb terminal start
sb terminal stop
sb terminal status
sb terminal pause
sb terminal resume
sb terminal context
sb terminal checkpoint
sb terminal failure
sb terminal resolve
sb terminal finish
sb terminal search
sb terminal project-activity
sb terminal unresolved
sb terminal spool status
sb terminal spool flush
sb terminal doctor
```

실시간 event ingest와 LLM summary를 분리한다.

```text
실시간: validate/redact/store
주기적: finalize/summary/improvement
```

---

## 16. 사람이 읽는 Terminal Summary

저장 경로:

```text
terminals/YYYY/MM/DD/<terminal-id>.md
```

문서에는 다음을 포함한다.

- host, terminal, agent, model
- primary project와 project segments
- 작업 목적
- 수행한 작업
- 결과와 검증
- 발생한 실패와 해결 관계
- 변경 파일, commit, PR, Issue, artifact
- 남은 작업
- 개선할 부분
- command/checkpoint/commit evidence refs

근거 없는 LLM 추정은 `추정`으로 표시하고 사실처럼 기록하지 않는다.

---

## 17. Mac Offline Spool

위치:

```text
~/Library/Application Support/SecondBrain/terminal-spool/
```

필수 조건:

- directory 0700, file 0600
- SQLite WAL 또는 append-only segment
- atomic transaction
- event ID uniqueness
- batch lease
- server receipt 후 삭제
- crash recovery와 corruption quarantine

전송 정책:

```text
online: 5~30초 batch
failure: exponential backoff + jitter
offline: local queue
reconnect: oldest sequence first
```

기본 정책:

```text
max spool: 250MiB
retention: 30일
warning: 70%
critical: 90%
```

critical에서도 shell을 막지 않고 output preview를 축소하며 metadata event를 우선 보존한다.

---

## 18. 보안

Redaction은 local hook/collector와 server에서 중복 적용한다.

- API key, Bearer, password, token assignment
- URL credentials
- private key block
- cookie/session
- `.env` content
- auth command arguments

정책 수준:

```text
allow    = 정상 수집
redact   = 인자 마스킹
metadata = command name과 exit code만
ignore   = event 미저장
```

캡처 제어:

```bash
export SB_NO_CAPTURE=1
sb terminal pause
sb terminal resume
```

Terminal command/output 원문은 기본적으로 외부 LLM 전송 금지다. Redacted structured facts만 기존 source policy에 따라 요약에 사용할 수 있다.

---

## 19. macOS UI

새 sidebar:

```text
홈
파일 동기화
터미널 작업
실패
개선점
브리핑
설정
```

핵심 화면:

- 활성 terminal 목록
- host, project, agent, 최근 command
- terminal timeline
- open/resolved failures
- spool pending count/bytes/oldest age
- tunnel/API 상태
- capture pause/resume
- session finish/summary
- improvement approve/reject
- 승인 후 GitHub Issue 생성

알림:

- 장시간 작업 완료
- blocking failure
- spool 경고
- summary 생성
- approval 대기 finding

알림에는 command 원문이나 secret-like text를 표시하지 않는다.

---

## 20. Improvement Intelligence

### 20.1 Rule-first

- 동일 failure fingerprint 반복
- 동일 command sequence 반복
- source 변경 후 test 미실행
- test 통과 후 commit 없음
- 반복 P0/P1 failure에 Issue 없음
- 수동 SSH tunnel/login/deploy 반복
- dirty worktree 장기 유지
- rollback 반복

### 20.2 LLM 보조

LLM은 redacted facts를 기반으로 원인 후보, 자동화, 테스트 보강, 문서 누락, 다음 작업을 제안한다. 결과는 `proposed`이며 자동 확정하지 않는다.

### 20.3 Issue workflow

```text
finding 생성
→ Issue 초안
→ 사용자 승인
→ GitHub Issue 생성
→ finding↔Issue↔commit 연결
```

---

## 21. Version 1.1.0 — Terminal Capture Core

### 목표

Mac과 `jm-cloud`의 bash/zsh 명령을 terminal별로 안전하게 식별·저장하고 offline 재전송과 project 판별까지 완성한다.

### Work Packages

- `TWM-WP-1101`: event contracts와 additive schema migration
- `TWM-WP-1102`: host/terminal ID, nested shell, heartbeat
- `TWM-WP-1103`: project resolver, workername, segment
- `TWM-WP-1104`: zsh integration
- `TWM-WP-1105`: bash integration
- `TWM-WP-1106`: collector daemon과 Unix socket IPC
- `TWM-WP-1107`: Mac spool, backoff, receipt
- `TWM-WP-1108`: server ingestion API, idempotency, caps
- `TWM-WP-1109`: CLI, doctor, launchd, systemd

### 인수 기준

- Mac terminal 2개와 `jm-cloud` terminal 2개를 고유하게 식별
- zsh/bash command, exit code, duration, cwd 정확성 검증
- 한 terminal에서 project A→B 전환 시 segment 2개 생성
- 네트워크 단절 30분 후 재연결 시 손실·중복 0
- collector kill 상태에서도 shell command 정상 실행
- fake secret corpus 원문 저장 0건
- 10,000 command에서 sequence 손실 0
- hook p95 10ms 이하
- 기존 1.0 기능 회귀 없음

---

## 22. Version 1.2.0 — Agent-Aware Terminal Memory

### 목표

OMP/Luna, Claude Code, Codex의 작업 목적·결정·실패·결과를 Terminal Session과 연결한다.

### Work Packages

- `TWM-WP-1201`: agent bridge와 environment linkage
- `TWM-WP-1202`: OMP session integration
- `TWM-WP-1203`: Claude tool_use/tool_result 구조화
- `TWM-WP-1204`: Codex tool event와 command 구조화
- `TWM-WP-1205`: terminal MCP 7개 도구
- `TWM-WP-1206`: failure fingerprint와 resolution engine
- `TWM-WP-1207`: evidence-linked terminal summary
- `TWM-WP-1208`: 기존 Orca/Claude/Codex data의 보수적 backfill

### 인수 기준

- Mac과 `jm-cloud`의 OMP/Claude/Codex 총 6개 조합을 연결
- agent checkpoint가 같은 project activity에서 검색됨
- fail→fix→test pass에서 failure=resolved, terminal=success
- agent가 MCP를 누락해도 command facts 유지
- private reasoning 저장 0건
- summary 핵심 주장에 evidence ref 존재

---

## 23. Version 1.3.0 — macOS 및 운영 UI

### 목표

사용자가 terminal 기억과 capture 상태를 네이티브 앱에서 이해하고 제어할 수 있게 한다.

### Work Packages

- `TWM-WP-1301`: active terminal dashboard
- `TWM-WP-1302`: command/checkpoint/failure/commit timeline
- `TWM-WP-1303`: failure center
- `TWM-WP-1304`: spool과 tunnel 상태 UI
- `TWM-WP-1305`: global/terminal/project capture controls
- `TWM-WP-1306`: completion/failure/spool notifications
- `TWM-WP-1307`: web fallback
- `TWM-WP-1308`: accessibility, keyboard, Korean/Unicode UX

### 인수 기준

- Mac 앱에서 Mac 및 `jm-cloud` terminal을 구분해 표시
- project별 timeline 탐색
- pause 후 event 미저장, resume 후 정상 수집
- spool disconnect/recovery가 UI에 반영
- 알림에 secret/command 원문 노출 없음
- web fallback에서 동일 data 조회

---

## 24. Version 1.4.0 — Improvement Intelligence

### 목표

터미널 작업 기록을 반복 문제 해결과 개발 프로세스 개선으로 전환한다.

### Work Packages

- `TWM-WP-1401`: failure clustering
- `TWM-WP-1402`: 반복 command 자동화 후보
- `TWM-WP-1403`: regression test gap detector
- `TWM-WP-1404`: dirty worktree/미커밋/문서 누락 finding
- `TWM-WP-1405`: evidence 기반 LLM recommendation
- `TWM-WP-1406`: Issue draft와 approval
- `TWM-WP-1407`: project weekly briefing

### 인수 기준

- 동일 failure 3회 반복 시 하나의 cluster와 evidence 생성
- 반복 sequence를 재현 가능한 자동화 후보로 제시
- source 수정 후 test 미실행 경고
- golden set false positive가 허용치 이하
- 승인 전 Issue 생성 0건
- Issue URL과 finding 연결
- weekly briefing이 activity 원장과 일치

---

## 25. PR 계획

| PR | 버전 | 목적 |
| --- | --- | --- |
| TWM-PR-001 | 1.1.0 | contracts와 schema migration |
| TWM-PR-002 | 1.1.0 | host/terminal lifecycle |
| TWM-PR-003 | 1.1.0 | project resolver와 segment |
| TWM-PR-004 | 1.1.0 | zsh/bash hook와 collector IPC |
| TWM-PR-005 | 1.1.0 | Mac spool과 server ingestion |
| TWM-PR-006 | 1.1.0 | CLI, launchd, systemd, doctor |
| TWM-PR-007 | 1.2.0 | agent bridge와 session linkage |
| TWM-PR-008 | 1.2.0 | OMP/Claude/Codex structured event |
| TWM-PR-009 | 1.2.0 | terminal MCP tools |
| TWM-PR-010 | 1.2.0 | failure resolution과 summary |
| TWM-PR-011 | 1.3.0 | macOS dashboard와 timeline |
| TWM-PR-012 | 1.3.0 | failure/spool/capture UI |
| TWM-PR-013 | 1.4.0 | rule-based improvement engine |
| TWM-PR-014 | 1.4.0 | LLM suggestions, Issue approval, weekly brief |

각 PR은 tests, migration note, rollback note, security impact를 포함한다.

---

## 26. 테스트와 적대적 검증

### Unit

- event canonicalization와 ID
- redaction corpus
- project resolver confidence
- lifecycle와 state transition
- command pairing
- failure fingerprint/resolution
- spool lease/receipt
- summary evidence refs

### Integration

- zsh preexec/precmd
- bash DEBUG/PROMPT_COMMAND
- nested shell
- project A→B
- branch/worktree 변경
- agent bridge
- API batch ingest
- SQLite rollback
- MCP tools

### macOS E2E

1. Terminal.app tab 2개
2. 서로 다른 project
3. 하나는 성공, 하나는 실패 후 해결
4. Tailscale disconnect
5. command 추가
6. reconnect
7. app timeline 확인
8. 다른 agent에서 검색

### jm-cloud E2E

1. bash/zsh session
2. OMP/Claude/Codex 연결
3. project/workername 판별
4. command/tool/checkpoint 저장
5. summary 생성
6. Mac에서 검색

### Fault Injection

- collector kill -9
- server restart
- DB lock
- disk full
- spool corruption
- duplicate/out-of-order event
- missing command finish
- clock skew
- SSH/Tailscale disconnect
- stale heartbeat
- LLM unavailable

### Security Audit

spool, server DB, CAS, log, metric, summary, notification에서 fake API key, token, password, private key, URL credential 원문이 없어야 한다.

### Performance

- 10,000 command single terminal
- 100 concurrent terminal simulation
- 100,000 event search
- 250MiB spool flush
- hook latency benchmark

---

## 27. 평가 데이터 세트

### Project Resolution Golden Set

- 일반 repo
- worktree
- monorepo
- symlink path
- detached HEAD
- 같은 basename 다른 remote
- unregistered folder
- workername alias
- Mac/Ubuntu path 차이

### Failure Resolution Golden Set

- test fail→fix→pass
- auth fail→login→pass
- network fail→retry→pass
- expected negative test
- grep no-match exit 1
- accepted failure
- rollback 후 성공
- unresolved blocker

### Improvement Golden Set

- 반복 SSH tunnel
- 반복 build sequence
- 수정 후 test 누락
- 의도된 실패 테스트
- generated file dirty 상태

---

## 28. Migration과 Rollback

### Migration

- terminal tables는 additive migration으로 추가
- migration 전 backup
- transaction 실패 시 rollback
- 기존 session은 근거가 충분할 때만 terminal에 연결
- 근거 부족 시 legacy session 유지
- 가짜 terminal/project metadata 생성 금지

신규 config 기본값은 capture disabled다.

```toml
[terminal_capture]
enabled = false
mode = "metadata"
project_confidence_threshold = 0.90
heartbeat_seconds = 30
abandoned_after_seconds = 300
max_output_preview_bytes = 8192

[terminal_spool]
max_bytes = 262144000
retention_days = 30
flush_interval_seconds = 15

[terminal_improvements]
enabled = false
issue_creation = "approval-required"
```

### Rollback

```bash
sb terminal pause
sb terminal uninstall
```

- hook 제거
- launchd/systemd disable
- collector 종료
- 기존 spool과 server data는 보존
- 이전 Wheel 설치 가능
- feature flag off 상태에서 기존 1.0 기능 계속 사용

Terminal data 완전 삭제는 structured event, CAS, summary, search, Git history를 구분한 별도 승인 절차로 수행한다.

---

## 29. 운영과 관측성

Metrics:

- active terminals
- accepted/duplicate/rejected events
- sequence gaps
- hook/IPC latency
- spool event/byte/oldest age
- sync success/failure
- redaction count
- unresolved failures
- summary queue
- improvement findings

원문 command/output은 metric label로 사용하지 않는다.

`sb terminal doctor`는 host ID, collector, socket, hooks, spool permission/integrity, tunnel/API, schema, event round-trip, clock skew, disk, backup, MCP를 확인한다.

SLO:

| 항목 | 기준 |
| --- | --- |
| 정상 event 유실 | 0 |
| 중복 저장 | 0 |
| Mac online 반영 | p95 60초 이하 |
| hook latency | p95 10ms 이하 |
| activity query | p95 1초 이하 |
| collector로 인한 shell 실패 | 0 |
| secret 원문 저장 | 0 |

---

## 30. 위험과 대응

| 위험 | 대응 |
| --- | --- |
| command secret 노출 | local+server redaction, sensitive policy, corpus audit |
| shell hook 충돌 | existing hook chaining, install preview, one-command uninstall |
| output capture가 interactive app을 깨뜨림 | metadata default, PTY opt-in, agent-tool 우선 |
| project 오판 | confidence threshold, unassigned, manual reassign |
| spool 손상 | transaction/WAL, quarantine, receipt deletion |
| event 폭증 | caps, batch, truncation, retention |
| agent checkpoint 누락 | factual collector 유지, start/finish integration |
| LLM 개선 hallucination | rule-first, evidence, confidence, approval |
| multi-writer 충돌 | idempotency, DB transaction, run lock |
| 감시 제품 오해 | 단일 사용자 목적, visible state, pause, no keylogging |
| Mac/server version mismatch | protocol negotiation, backward compatibility, doctor |

---

## 31. 첫 구현 배치

1. 본 계획서 승인
2. ADR 4개 작성
   - Event store와 기존 ledger 관계
   - Shell hook/collector IPC
   - Output capture policy
   - Mac spool format
3. Terminal event contracts
4. SQLite migration과 repository
5. Redaction corpus와 storage security tests
6. Project resolver와 golden set
7. zsh metadata hook
8. `jm-cloud` local collector E2E
9. Mac spool과 SSH/Tailscale sync
10. bash hook
11. 1.1.0 adversarial gate
12. 1.2.0 agent bridge 시작

첫 코드 PR에 UI, LLM improvement, PTY capture를 포함하지 않는다.

---

## 32. 전체 완료 정의

완료 후 Second Brain은 다음 질문에 근거와 함께 답해야 한다.

```text
어제 jm-cloud의 mail-intelligence 터미널에서 무엇을 했나?
어떤 명령이 실패했고 어떻게 해결했나?
Mac의 OMP 세션에서 만든 commit과 Issue는 무엇인가?
아직 해결되지 않은 프로젝트별 실패는 무엇인가?
지난주 반복 수동 작업 중 자동화할 것은 무엇인가?
이 해결 방법을 예전에 어느 터미널에서 사용했나?
```

최종 방향:

> Mac과 `jm-cloud`의 각 터미널을 독립적인 작업 세션으로 식별하고, 프로젝트·에이전트·명령·결과·실패·해결·개선점·다음 작업을 하나의 추적 가능한 기억으로 남긴다.

```text
Mac / jm-cloud Shell Collector
        ↓ 사실
Agent MCP
        ↓ 의미
Second Brain Terminal Ledger
        ↓
Failure / Resolution / Summary / Improvement
        ↓
CLI + MCP + Web + Native macOS App
```

성공은 로그 양이 아니라 다음으로 판단한다.

```text
어떤 터미널에서
어떤 프로젝트를
왜 작업했고
무엇이 성공·실패했으며
어떻게 해결했고
무엇을 다음에 개선해야 하는지
근거와 함께 다시 찾을 수 있는가
```
