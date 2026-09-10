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

## 실제 업무 인수에서 필요한 식별 정보

사용자에게 자비스 작업 ID 또는 원문 문서 경로, 공유할 프로젝트와 에이전트를 요청했다. 아직 답변을 받지 않았다. 선택한 업무에 대해 다음을 한 묶음으로 입증한다.

1. 원작업·프로젝트·검증 결과의 원문 계보 확인. 실패/미확정 결과를 성공 경험으로 승격하지 않음.
2. 현재 인증 범위에서 기억 저장 요청을 접수하고 request/candidate/provider record 및 완료 영수증을 연결.
3. 다른 실제 에이전트의 새 세션에서 원문·버전과 함께 회수. 허용되지 않은 프로젝트는 결과0 또는 명시적거부.
4. 정정·삭제 후 새 세션/재개/복원에서 과거 내용을 최신 기억으로 재사용하지 않음. provider 삭제와 native 사본 삭제는 별도 증거.

운영 전환에는 검증된 설치 후보 외에도 기존 DB writer/실행권의 배제와 복구 경로가 필요하다. 큐0·서비스active·도구목록만으로 완료 처리하지 않는다. 최근 운영 관측과 미확인 프로세스 범위는 [운영 보고서](MAINTENANCE-CLI-AND-OPS-2026-09-10.md)를 따른다.

현재의 병목은 단일 검색 속도만이 아니다. 실제 업무 인수와 M1–M9의 인증·계보·수명 연결을 우선하고, M10 실제 질문집·M11 MCP/동시 갱신·M12 복구·M13 GUI 인수를 병행한다. M14 그래프 및 hybrid 기본 활성화는 검색 품질 이득·삭제 일관성 근거 전까지 보류한다. 사용자 응답을 합성 작업으로 대신해 실제 업무 완료를 선언하지 않는다.

최신 설치 인수: [13cab77 설치물](INSTALLED-CONNECTOR-UPDATES-2026-09-10.md). OpenCode 수집 근거: [출처 분리·정상 CLI와 모호한 설정 거부](OPENCODE-SOURCE-ISOLATION-2026-09-10.md), [읽기 중 변경](OPENCODE-SNAPSHOT-STABILITY-2026-09-10.md), [SQLite 제한/복구](OPENCODE-DATABASE-LIMITS-2026-09-10.md). 모두 native 모델의 자동 수집·주입 전체 인수와 구분한다. 최신 운영 읽기 관측은 [UTC01:40 재확인](OPS-RECHECK-2026-09-10-0140.md)을 따른다.
