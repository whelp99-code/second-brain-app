# Terminal Work Memory 요구사항 추적·릴리스 게이트

이 문서는 `TERMINAL-WORK-MEMORY-DEVELOPMENT-PLAN.md`의 실행 추적 부록이다.

## 1. 요구사항 추적 매트릭스

| 요구사항 영역 | 주요 ID | 구현 버전 | 주요 검증 |
| --- | --- | --- | --- |
| Host·Terminal | `REQ-TWM-HOST-*`, `REQ-TWM-TERM-*` | 1.1.0 | Mac/Ubuntu multi-terminal E2E, nested shell, heartbeat |
| Project 판별 | `REQ-TWM-PROJ-*` | 1.1.0 | Project Resolution Golden Set |
| Command·Output | `REQ-TWM-CMD-*`, `REQ-TWM-OUT-*` | 1.1.0~1.2.0 | zsh/bash integration, agent tool pairing |
| Agent 연결 | `REQ-TWM-AGENT-*` | 1.2.0 | OMP/Claude/Codex × Mac/jm-cloud 6개 조합 |
| Failure·Resolution | `REQ-TWM-FAIL-*` | 1.2.0 | Failure Resolution Golden Set |
| MCP | `REQ-TWM-MCP-*` | 1.2.0 | stdio MCP contract/E2E |
| Offline Sync | `REQ-TWM-SYNC-*` | 1.1.0 | Tailscale 단절·재접속, duplicate/out-of-order injection |
| Security | `REQ-TWM-SEC-*` | 1.1.0~1.4.0 | fake secret corpus 전체 저장 층 audit |
| Search·Summary | `REQ-TWM-SEARCH-*`, `REQ-TWM-SUM-*` | 1.2.0~1.3.0 | evidence audit, Unicode 검색, UI E2E |
| Improvement | `REQ-TWM-IMPR-*` | 1.4.0 | Improvement Golden Set, approval gate |
| Ops·Performance | `REQ-TWM-OPS-*`, `REQ-TWM-PERF-*` | 전체 | clean install, migration, rollback, load test |

## 2. 버전별 릴리스 Gate

### 1.1.0 Gate

- schema migration 및 rollback 통과
- Mac zsh와 jm-cloud bash/zsh 실기 수집 통과
- collector kill, API restart, DB lock, Tailscale 단절 검증
- event 손실·중복 0
- fake secret corpus 원문 저장 0
- hook p95 10ms 이하
- 기존 1.0.0 전체 회귀 테스트 통과

### 1.2.0 Gate

- OMP/Luna, Claude Code, Codex가 Mac과 jm-cloud에서 terminal context를 공유
- 7개 terminal MCP 도구 contract 및 E2E 통과
- failure→resolution→terminal final outcome 관계 검증
- terminal summary의 핵심 주장에 evidence reference 존재
- private reasoning 수집 0

### 1.3.0 Gate

- macOS native app에서 active terminal, timeline, failure, spool 상태 확인
- capture pause/resume와 project 재지정 검증
- Notification Center에 secret-like 내용 노출 0
- web fallback 동작
- VoiceOver·keyboard·Unicode 기본 검증

### 1.4.0 Gate

- 반복 failure와 command sequence 평가 세트 통과
- test-gap false positive가 합의 임계값 이하
- LLM recommendation은 evidence와 confidence를 포함
- 사용자 승인 전 GitHub Issue 생성 0
- weekly briefing과 terminal ledger 정합성 검증

## 3. Definition of Done

각 Work Package는 다음을 모두 충족해야 완료다.

1. 요구사항 ID가 코드·테스트·문서에 연결됨
2. unit 및 integration test 통과
3. security impact 검토
4. migration 및 rollback 검증
5. Mac과 jm-cloud 중 해당 범위 실기 검증
6. 운영·진단·장애 대응 문서 갱신
7. 적대적 검증에서 발견된 P0/P1 문제 0
8. 검증 증거와 알려진 제한 기록

## 4. 승인 전 확정할 ADR

| ADR | 결정 대상 |
| --- | --- |
| ADR-TWM-001 | terminal event store를 기존 ledger에 통합할지 별도 SQLite 영역으로 둘지 |
| ADR-TWM-002 | shell hook→collector IPC 형식과 emergency queue |
| ADR-TWM-003 | metadata/agent-tool/PTY output capture 정책 |
| ADR-TWM-004 | Mac spool의 SQLite WAL 또는 append-only segment 선택 |
| ADR-TWM-005 | host/device authentication과 revoke 방식 |
| ADR-TWM-006 | terminal summary의 Git commit 주기와 aggregation 단위 |

## 5. UNKNOWN과 ASSUMED

| ID | 상태 | 내용 | 해소 방법 |
| --- | --- | --- | --- |
| TWM-UNK-001 | UNKNOWN | OMP session log가 terminal ID를 직접 제공하는지 | 실제 OMP schema 조사 |
| TWM-UNK-002 | UNKNOWN | Claude/Codex tool output에서 exit code가 항상 노출되는지 | 버전별 fixture 수집 |
| TWM-UNK-003 | UNKNOWN | macOS Terminal/iTerm/기타 앱 식별의 안정성 | 환경변수·process tree 실기 검증 |
| TWM-UNK-004 | UNKNOWN | Mac spool 암호화가 1.1.0 필수인지 1.3.0 hardening인지 | threat model ADR |
| TWM-ASM-001 | ASSUMED | 주 shell은 Mac zsh, jm-cloud bash/zsh | 실제 사용 환경 inventory |
| TWM-ASM-002 | ASSUMED | 권위 있는 writer는 jm-cloud 한 곳 | 운영 정책 확인 |
| TWM-ASM-003 | ASSUMED | 모든 클라이언트는 Tailscale/SSH 경로를 사용 | 네트워크 설치 검증 |

UNKNOWN을 사실로 바꾸지 않는다. 해당 ADR 또는 실기 검증이 끝나기 전까지 관련 구현은 보수적인 기본값을 사용한다.
