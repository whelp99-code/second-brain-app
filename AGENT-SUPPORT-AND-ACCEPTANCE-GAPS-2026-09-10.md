# 클라이언트 지원 범위와 실제 업무 인수 조건

초기 대조는 소스45ba9ab 기준이며, 13cab77의 OpenCode 수집·설치 인수 증거를 아래에 갱신했다. 인계의 M1–M14는 유지한다. 최신 검색·설치 결과를 기존 운영 완료로 확대하지 않는다. 아래는 사용 가능성 추정이 아닌 관측 범위다.

| 연결부 | 수집 | 기억 조회·쓰기 증거 | 자동 주입·세션 삭제 |
|---|---|---|---|
| Claude Code | sessions_claude/claude_native 구현, native 형식 회귀 존재 | 2.1.261 실제 인증 MCP 조회 통과. 과거 별도 legacy 시험에서 읽기·쓰기 검증 | 모든 운영 세션의 자동 주입·compaction·로그·백업 삭제 인수는 미완 |
| Codex | sessions_codex 구현, cursor 재개·형식 오류 격리 회귀 존재 | 과거0.153.4 legacy 양방향 공유 성공. 최신 인증 경로는 모델 실행의 사용량 제한으로 미완 | 격리 native 세션 재개 시험 존재. 일반 사용자 세션 자동 저장은 원문 보존·삭제 경로 완성 전 보류 |
| OMO | sessions_omo 수집 fixture 회귀 존재 | 설치 MCP 엔진으로 실제 context2records 회수. native 모델은 당시 Cursor OAuth 재로그인 요구로 실패 | 엔진 초기화와 실제 모델 선택·자동 주입·전체 삭제를 구분. 재로그인 전 native lane 보류 |
| OpenCode | 내용 기반 resume·JSON/DB 읽기 예산·변경 중 재시도·고유 source ID 분리. 실제 격리 CLI 수집 검증 | 현재 설치 버전의 native 인증 기억 사용 완료 근거는 미확인 | 자동 수집기를 자동 주입 지원으로 해석하지 않음 |
| GJC | sessions_gjc 및 별도 형식 처리 구현 | 과거 조사에서 로컬 명령은 원격 실행 wrapper. 이번에 원격 실행·인증 조회를 하지 않음 | 실제 원격 세션 전체 수명 인수 미완 |
| 독립 SDK reader2개 | 자체 대화 수집 없음 | 최신 설치물의 실제 HTTPS/MCP 각2records·범위·철회·만료 검증 | 두 SDK 객체를 서로 다른 실제 모델 제품2개로 집계하지 않음 |

근거: [실제 두 제품 legacy 공유](AGENT-CLIENT-MEMORY-ACCEPTANCE-2026-09-08.md), [최근 인증 클라이언트](SCOPED-ACCEPTANCE-CLOCK-2026-09-10.md), [OMO 엔진](OMO-MCP-ENGINE-ACCEPTANCE-2026-09-09.md), [OMO 인증 보류](OMO-NATIVE-MODEL-HOLD-2026-09-09.md), [native 세션 보존 경계](NATIVE-SESSION-ACCEPTANCE-2026-09-08.md), [최신 설치](INSTALLED-SHARED-READ-2026-09-10.md). 과거 인증 실패는 이번 재시도의 결과가 아니다.

이번 실행: `tests/test_connectors_sessions_a.py`와 `tests/test_claude_native_sessions.py` **20 passed / 0.34초**. 이는 수집 형식·resume 등 fixture 회귀이며 실제 모든 에이전트 로그인·수집 활성화 검증이 아니다. 제품 변경 없음.

W5 빈 격리 HOME: Claude 2.1.261 `mcp list`와 Codex 0.154.0 `--version`은 운영 홈 항목을 바꾸지 않았다. 인증·MCP 없는 프로필은 기억을 만들지 못해 M5 삭제 수명 **미지원**. [격리 경계](W5-NATIVE-ISOLATION-2026-09-10.md).

## 실제 업무 인수에서 필요한 식별 정보

사용자에게 자비스 작업 ID 또는 원문 문서 경로, 공유할 프로젝트와 에이전트를 요청했다. 아직 답변을 받지 않았다. 선택한 업무에 대해 다음을 한 묶음으로 입증한다.

1. 원작업·프로젝트·검증 결과의 원문 계보 확인. 실패/미확정 결과를 성공 경험으로 승격하지 않음.
2. 현재 인증 범위에서 기억 저장 요청을 접수하고 request/candidate/provider record 및 완료 영수증을 연결.
3. 다른 실제 에이전트의 새 세션에서 원문·버전과 함께 회수. 허용되지 않은 프로젝트는 결과0 또는 명시적거부.
4. 정정·삭제 후 새 세션/재개/복원에서 과거 내용을 최신 기억으로 재사용하지 않음. provider 삭제와 native 사본 삭제는 별도 증거.

운영 전환에는 검증된 설치 후보 외에도 기존 DB writer/실행권의 배제와 복구 경로가 필요하다. 큐0·서비스active·도구목록만으로 완료 처리하지 않는다. 최근 운영 관측과 미확인 프로세스 범위는 [운영 보고서](MAINTENANCE-CLI-AND-OPS-2026-09-10.md)를 따른다.

현재의 병목은 단일 검색 속도만이 아니다. 실제 업무 인수와 M1–M9의 인증·계보·수명 연결을 우선하고, M10 실제 질문집·M11 MCP/동시 갱신·M12 복구·M13 GUI 인수를 병행한다. M14 그래프 및 hybrid 기본 활성화는 검색 품질 이득·삭제 일관성 근거 전까지 보류한다. 사용자 응답을 합성 작업으로 대신해 실제 업무 완료를 선언하지 않는다.

## 후속 갱신 — 운영 경로의 실제 업무 공유(2026-09-10)

이후 실제 업무 한 건을 운영 agent MCP로 저장하고 두 제품이 각자 새 세션에서 회수했다. 위 표의 "미확인" 문구를 이 결과로 일괄 확대하지 말고 아래 범위로만 갱신한다.

- Claude Code 2.1.261: 운영 MCP로 `sb_remember` 저장 영수증, 별도 새 세션의 `sb_search`+`sb_read_page` 회수, 근거 없는 질의의 빈 결과와 vault 이탈 거부까지 확인.
- Codex CLI 0.154.0: 같은 운영 MCP에서 새 세션 회수 성공. 단 `codex exec`는 `--approve-for-me` 없이는 MCP 호출을 approval policy로 거부하며, 이 옵션은 `-s/--sandbox`와 함께 쓸 수 없다. 로그의 `refresh_token_invalidated`는 이번 실행을 막지 않았다.
- 두 제품 모두 **자동 수집·자동 문맥 주입·세션 사본 삭제 수명은 여전히 미확인**이다. 이번 증거는 명시적 저장과 명시적 조회 경로다.
- 사용자에게 요청했던 자비스 작업 ID는 여전히 받지 못했다. 대신 오늘 실제로 수행·검증한 개발 업무를 대상으로 삼았고, JARVIS 계보(candidate→영수증)의 운영 종단은 미완이다.

근거: [실제 업무 공유](REAL-WORK-SHARED-MEMORY-2026-09-10.md).

최신 설치 인수: 전환 대상은 [4aa7111 후보 c04dee1](OPERATIONAL-CUTOVER-PREP-2026-09-10.md)이다. 이전 [d4cbdda 후보 25d49b4](CONTINUATION-INSTALLED-PAIR-2026-09-10.md)와 wheel이 다르다. 과거 [13cab77 설치물](INSTALLED-CONNECTOR-UPDATES-2026-09-10.md)과 합산하지 않는다. OpenCode 수집 근거: [출처 분리·정상 CLI와 모호한 설정 거부](OPENCODE-SOURCE-ISOLATION-2026-09-10.md), [읽기 중 변경](OPENCODE-SNAPSHOT-STABILITY-2026-09-10.md), [SQLite 제한/복구](OPENCODE-DATABASE-LIMITS-2026-09-10.md). 모두 native 모델의 자동 수집·주입 전체 인수와 구분한다. 최신 운영 읽기 관측은 [UTC01:40 재확인](OPS-RECHECK-2026-09-10-0140.md)을 따른다.

## 후속 정정 — 지원표가 닫지 않는 항목(2026-09-10)

[인계 보완](CODEX-REPLY-REVIEW-2026-09-10.md)과 라이브 재측정을 이 표에 반영한다. 표를 완료로 바꾸지 않는다.

- **Codex 사본 0건:** 지정 문자열 주사에서 `~/.codex` 0건은 보존한다. 모든 `codex exec`·대화형 세션·로그/압축 형식에 사본이 없다고 보지 않으며 M5를 이 관측만으로 닫지 않는다. [사본 정책](M5-COPY-POLICY-2026-09-10.md).
- **운영 authority memory 모듈:** “memory CLI가 없다”는 말은 재측정과 맞지 않는다. 세는 규칙은 `dist/src/*.js` 파일명이 `memory-`로 시작하거나 `second-brain`을 포함하는 경우다. 운영 `a3cbbbe`는 **124**, 페어 `195b1a7`은 **197**(JS 차 144). 이전 125/198은 파일명 substring `memory`까지 넣은 값이다. `cli-memory-*.js`와 `memory-outbox-production.js`는 페어에만 있다. 개수만으로 활성화 후 연결이 정상이라고 보지 않는다. [W0](W0-BASELINE-2026-09-10.md).
- **설치 후보 wheel:** 업무 본문에 인용된 `25d49b4`/`aa6fad5f…`와 실행 후보 `c04dee1`/`ac8fcd16…`는 다르다.
