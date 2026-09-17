# Second Brain 전면 분석과 재가동 계획 — 2026-09-17

작성: Claude(분석·검증). 대상: jm-cloud(Ubuntu) + Mac 전체. 근거는 모두 실측이며 추정은 표시했다.

## 1. 목적 재확인 (문서 원문)

- `DEVELOPMENT-PLAN.md` §1.1 고정 정의(2026-08-28): "여러 로컬 자료와 **AI 작업 기록**을 수집하여 원본을 보존하고, 출처가 추적되는 지식 페이지로 변환하며, 상충하는 정보를 분리해 관리하고, CLI·MCP·최소 웹 화면으로 검색·열람·기록할 수 있게 하는 로컬 우선 개인 지식 엔진." 목표 사용자는 "프로젝트·대화·문서를 여러 도구에 분산 보관하는 단일 사용자".
- `ORCA-JARVIS-SECOND-BRAIN-JOINT-DEVELOPMENT-PLAN.md` §2.2(권위 있는 실행 기준선): "**ORCA가 일을 수행하고, JARVIS가 그 일을 통제·관찰·검증하며, Second Brain이 검증된 결과와 교훈을 장기기억으로 보존한다.**"
- 사용자 구술(2026-09-17): "나의 모든 걸 기억하고 내 기억을 대신해주는 역할. 메일, 개발, 내가 한 일, 전화통화기록, 통화내용, 카톡내용 등을 모두 모아서 기억한다."
- 경계(§2.3, §7.2): raw 터미널 전체 출력·키 입력·secret 원문은 저장하지 않는다. 도메인 시스템이 요약·검증한 짧은 레코드를 SB inbox로 넘긴다.

## 2. 왜 비었나 — 2026-09-11 단일 원인

맥 `~/Library/LaunchAgents/_disabled-2026-09-11/README.md`에 사용자 결정이 기록돼 있다.

> "사용자 결정: JARVIS·second-brain **미완으로** Sangfor 자동화 미사용, hermes gateway 미사용(venv 삭제됨)."

그날 LaunchAgent 13개(hermes gateway 4, sangfor autopilot·backup·boot-stack·daily-briefing·mail-classify·mail-learn·mail-sync·watchdog)를 `launchctl bootout` 후 보관 폴더로 옮겼고 복원 절차도 같은 README에 있다. 같은 날 메일 수집 마지막 기록(2026-09-11T06:28Z), 카톡 유입 마지막, 위키 소스 제외가 함께 일어났다. **SB가 미완이라 수집을 껐고, 수집이 꺼져 SB가 비었다.** 2026-09-17 기준 SB는 v1.0.1·readiness 녹색·충돌 판정 복구 완료이므로 전제는 해소됐다.

## 3. 두 기계 실측

### jm-cloud (Ubuntu 26.04)
- 8코어 / RAM 121GB 중 73GB 사용 / 디스크 984GB 중 466GB / 연속 가동 5주
- 사용자 서비스 **84개** 상시, 리스닝 포트 40여 개(buzz 8, bidwise 3, mail 2, jarvis 2, bami 2, toss-forward, action-hub, orca-healthcheck 등)
- 프로젝트 29개 69GB — Orca-JARVIS 27G, sangfor-mcp 13G, second-brain-app 12G, mail-intelligence 3.2G
- 데이터 — JARVIS 9.1G, SB state 2.7G + vault 533M, mail 2.9G
- AI 세션 원본 — `.omo` 2.7G, `.codex` 1.6G, `.claude` 1.4G (합계 492파일 약 1.5GB, 최근 7일 238개)

### Mac
- DevSpace 200GB 중 87GB, 가동 6일, LaunchAgent **52개 중 20개 로드**
- 살아 있음 — orca-jarvis·dashboard·portfolio, daily-rollup(9/16 23:51), inbox-analyze(9/15), weekly-review, grokbot-hold/askwatch, ocx-health, mcp-smoke, handoff-watch, gdrive-inbox-sync, wiki-spike shadow collector/watcher, sangfor ollama/learnall/learnkb/kpi-weekly
- grok-bot 데몬은 현재도 갱신 중(오늘 14:00), packets는 9/14 하루치 4.2MB
- 맥→클라우드 SSH 터널 3개

## 4. 영역별 자산과 연결 상태

| 영역 | 자산 | 위치 | 현재 | SB 연결 |
|---|---|---|---|---|
| 에이전트 일지(내가 한 일) | unified-db `journal.entries` 2,426 / `raw.events` 7,032 | **맥 Postgres 5433** | **매일 유입 중** | 9/05에 302건만, 이후 끊김 |
| AI 세션 원본 | 수집기 8종 + 세션 492개 1.5GB | 클라우드 | 방치 | 꺼짐 |
| 메일 | mail-intelligence v1.2.2, 메시지 535·스레드 375·첨부 585 | 클라우드 | 9/11 멈춤(요청 구동, CPU 2초) | 연계 코드 없음 |
| 카톡 | grok-bot AX/OCR 자동화 `~/.grokbot/ops/bin` | 맥 | 도구 생존, 전송 중단 | 9/10~11 32건이 마지막 |
| 전화·통화녹음 | phone-history 서버·계약·iOS 완성 | 저장소 내 | 실기기 검증 대기 | 설계상 inbox handoff |
| 작업 종료 기억 | JARVIS closeout·memory candidate | 클라우드 | 일일 루프만 동작 | 수동 CLI뿐, 끊김 |
| 개인 위키 | dev-wiki 24문서(9/13까지) | 클라우드 | 갱신 중 | 꺼짐 |
| 일일 운영 | daily-rollup·weekly-review | 맥 | 동작 | 알림만, 저장 없음 |
| 9/11 중단분 | LaunchAgent 13개 | 맥 보관 폴더 | 복원 절차 문서화 | 꺼짐 |

## 5. 통합DB는 SB로 통합하는 것이 원래 결정

- SB `AGENTS.md`: "**No writes to unified-db.** 커넥터가 `default_transaction_read_only`를 확인한 뒤 SELECT만. INSERT/UPDATE/DELETE/DDL 없음."
- 통합계획 §2.1·§3: Unified DB는 "선택적 관측/증거 아카이브 및 교환 계층"이며 **최종 장기기억 권위를 갖지 않는다**. 장기기억 정본은 SB.
- `dev-wiki/projects/unified-db.md`: `raw.*` append-only 원본 / `journal.*` 에이전트 일지+임베딩, "기록은 훅으로 자동, 회수는 다이제스트+온디맨드 2단", "저널(사건) → 주 1회 증류기 → me-wiki 수정안 제안".
- 실측(2026-09-17): journal 2,426건(2026-07-02~오늘), raw 7,032건, 최근 7일 11/61/55/18/25/6/10건. 맥의 `com.whelp99.memory-router.maintenance`가 claude·codex·hermes·git 활동을 훅으로 적재한다.
- **품질 주의**: journal 2,368건이 agent=claude, 그중 1,548건이 project=ClaudeProbe·summary="session"인 저가치 프로브. 의미 있는 것은 home 143, jmpark 103, sangfor-os 66, second-brain-app 65, jarvis-ai 58 등. 선별 수집 필요(`sb/connectors/unified_db_mapping.py`).

## 6. 민감 자료 처리 수단 (이미 구현됨)

- 소스별 `llm_policy` = allow / deny / local-only, `sensitive` = mask / allow / deny. 외부 LLM 사용 시 신규 소스 기본값은 **deny**.
- `sb/compile.py`는 deny 소스에 대해 `_compile_without_llm`으로 **LLM 없이도 각주 붙은 페이지를 생성**한다 → 메일·카톡·통화를 외부 전송 0으로 저장·검색 가능.

## 7. 단계별 재가동 계획

| 단계 | 내용 | 기간 | 완료 기준 |
|---|---|---|---|
| 1 | **unified-db 재연결**(읽기 전용, 프로브 노이즈 선별) | 반나절 | "9/16에 무엇을 했나"가 검색으로 응답 |
| 2 | AI 세션 직접 수집(claude → codex → omo) | 1일 | 세션 세부까지 회상 가능 |
| 3 | 카톡 일일 요약 전송 복구 | 반나절 | 하루 1회 자동 적재 |
| 4 | 메일 결론 일일 핸드오프(본문 미전송) | 1일 | "이번 주 메일 결정" 응답 |
| 5 | 9/11 중단 자동화 선별 복구 | 1일 | 복구 목록과 제외 목록 기록 |
| 6 | JARVIS closeout 자동 적재 + ORCA 관측 | 1주 | 작업 종료가 승인 후 자동 기억 |
| 7 | 전화·통화(phone-history 실기기), 위키 재연결, 한국어 검색 개선 | 조건부 | 각 항목별 |

## 8. 이번 분석에서 확인하지 못한 것

- JARVIS 라이브 DB(`/var/lib/jarvis-svc/state`)는 권한이 없어 열지 못했다. JARVIS 내부 상태 판단은 로그·소스·SB측 기록에 근거한다.
- wiki-spike shadow collector가 무엇을 수집하는지는 실행 경로만 확인했고 내용은 보지 않았다.
- unified-db `raw.events`의 payload 내용은 열지 않았다(민감도 미판정).
