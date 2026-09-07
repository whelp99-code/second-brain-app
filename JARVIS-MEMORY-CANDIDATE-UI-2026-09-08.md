# 자비스 기억 후보 화면·완료 상태 연결 인수

검증일: 2026-09-08. 자비스 구현 커밋: `c4c5c98` (기준 `49446db`). 인계 기준은 Second Brain 유지·네 OSS 장점 선별 흡수·자비스와 공통 에이전트 기억 우선이다. 기존 통합 계획 14절의 후보 UI 네 공백을 구현·검증했으며 B4 전체 및 운영 인수는 계속 미완료다.

## 이번에 닫은 공백

| 기존 문제 | 구현 결과 | 확인한 실패 경계 |
|---|---|---|
| 후보 목록만 있고 원문 검토 경로가 없음 | 영속 publication과 대조하는 별도 상세 API·화면 | 원문/출처/정책 digest 불일치, 만료, 비공개 민감도, 억제된 후보 거부. GET은 spool을 생성·복구·삭제하지 않음 |
| 기존 결정 API와 기억 화면이 미연결 | 검토한 digest로 확인/거절 명령 준비 후 기존 Approvals 연결 | CSRF, 오래된 검토, 재시도, 이중 클릭, privacy 초기화와 늦은 응답 처리 |
| 확인된 후보에서 저장 명령을 만들 수 없음 | 기존 stageMemoryRememberDispatch와 새 HTTP/UI 연결 | publication·기존 권한 검사 유지, 중복 명령 준비는 같은 ID, 20개 과거 명령 뒤 새 후보도 노출 |
| remember 완료를 화면에서 추적할 수 없음 | request ID별 control/outbox 상태 및 실패 코드 표시 | completed와 settled를 함께 확인해야 stored=true. pending은 저장 완료가 아님 |
| remember 확인 실행기가 correct 전용 경로로 실패 | 영속 owner 결정과 receipt·digest·적용 시도를 검사해 해당 확인 명령 완료 | 확인 완료와 실제 저장 완료를 별개로 유지 |
| 동시 명령 요청이 Overview 500을 유발 | 비동기 health 진단 후 동기 DB 투영만 읽기 불변 검사 | 다른 요청의 정상 쓰기는 허용, 투영 자체 쓰기는 계속 거부; 진단 한 번 관측 |

자비스 변경 상세·파일·단위 검사 근거는 [자비스 보고서](../Orca-JARVIS/docs/memory-candidate-ui-runtime-2026-09-08.md)에 있다. Second Brain 제품 Python은 이번 단위에서 변경하지 않았다. 외부 OSS 코드 복사·라이브러리 추가·MCP frozen 계약 변경은 없다.

## 실제 프로세스 인수

`scripts/jarvis-memory-acceptance.mjs`에 `--dashboard-progress`를 추가했다. 실제 provider 완료 뒤 같은 격리 자비스 authority에 HTTP dashboard를 열고 session/CSRF를 거쳐 진행 API를 검사한다. 응답의 명령 ID·completed·settled·오류 없음·stored=true를 assert한다. 기존 원문 정리·재시도·삭제 fence 검사도 유지한다.

```bash
TMPDIR=/var/tmp node scripts/jarvis-memory-acceptance.mjs /var/tmp/jarvis-candidate-ui-final.8_drqe6d --owner-confirmed --approval-rollback --runtime-cli --record-limit --record-budget --sensitive --after-delete --during-compile --dashboard-progress
```

최종 관측: provider proved, outbox settled, control completed, dashboard_stored=true, 민감 record 64개, 두 MCP 클라이언트 current. 승인 rollback 복구 성공, 재전송 replayed=true, 추가 dispatch 0, 남은 review 원문 파일 0, cleanup/control 오류 없음. 삭제 sequence 1 이후 무서명·과거 fence 거부, 삭제 record 회수 0개다. 컴파일 준비 중 완료 확인·조회 묶음 약 1.401초이며 개별 요청 p95가 아니다. 로그: `/var/tmp/sb-jarvis-candidate-ui-rebased-acceptance.log`.

합성 owner 승인과 격리 vault를 사용했다. 서로 다른 두 MCP 프로세스 검증이며 실제 Codex/Claude 앱의 수집·주입 지원을 의미하지 않는다. 운영 release나 active generation은 전환하지 않았다.

## 브라우저·회귀 검사

자비스에 동시 task 작업이 있어 커밋된 `49446db`를 임시 archive로 만들고 이 단위 변경만 복사했다. 최종 backend/dashboard build, dashboard typecheck, 변경 TS/TSX ESLint, 후보·HTTP·동시성 15개 테스트가 통과했다. 타입/lint 로그는 `/var/tmp/jarvis-candidate-ui-rebased-types-lint.log`다. 이전 집중 회귀는 72개, 공통 투영 호출자 26개, 최종 Overview 13개(일부 중복), frontend 전체 143개가 통과했다. 숫자를 합산해 전체 repository 테스트 수로 제시하지 않는다.

Browser 플러그인 부재로 로컬 Playwright Chromium을 사용했다. 1440×1000 및 375×812에서 후보 검토 → Approvals의 테스트 서명 receipt 제출 → 확인 명령 실행 completed → 저장 명령 pending → 새로고침 후 pending 유지가 통과했다. 콘솔 오류 0, serious/critical axe 위반 0, framework overlay 0, 가로 넘침 0. 브라우저에는 fixture provider read adapter를 사용했으며 실제 저장 완료는 위 별도 MCP/HTTP 검사로 확인했다. 브라우저 로그: `/var/tmp/jarvis-candidate-ui-rebased-browser.log`.

직전 Second Brain 전체 회귀는 564 passed / 2 skipped, Ruff 통과였다. 이번 Python 변경이 없으므로 이를 새 실행으로 주장하지 않는다. 하네스 Node 구문 검사·양쪽 diff 검사를 수행했다. 독립 코드 재검토에서 추가 actionable 지적은 없었다.

## 남은 수정·개선·고도화 순서

1. **P0 / I1·G6:** 실제 사용자 입력과 자비스의 검증된 작업 결과를 candidate/classification/publication으로 연결. 단순 요약 또는 실패 결과를 성공 경험으로 승격하지 않는 실제 입력 인수.
2. **P1 / I1·G4:** 일반 Enter 여러 줄·V2 target 기반 정정. sensitive/restricted 후보 원문 UI와 더 쉬운 owner 승인 UX는 기존 정책에 맞춘 별도 설계/검증 필요.
3. **P1 / I7·B4:** 실제 사용 앱별 조회·쓰기·수집·주입 지원표와 A 기록→B 동일 출처/버전 회수. 공통 project/user 범위 계약, 직접 원문·검색 모두 범위 밖 거부.
4. **P1 / G1·G3·G4:** 관련 기억 예산, 세션 중복 방지, 전달 receipt, 정정·compaction 후 재전달, 기억 시간/재검토 근거.
5. **P1 / R6·R8·I2·I3·I4·I6:** 과거 세대 잔여물 원장 대조, signed export lifecycle 소비, 검증 백업과 readiness, 릴리스/설정/세대 전환 및 독립 복원 인수.
6. **P2 / I5·I8·G2·R10:** 재현 설치·타입 잔여, 한국어 검색/부하 평가. hybrid는 읽기 전용·출처/범위 보존을 먼저 수정하고 기준선 대비 이점 확인 후 활성화.

LightRAG의 검색/근거, Tencent의 공통 범위, code-brain의 작은 문맥, memory-bank의 수명주기/세션 이력을 이 순서에 선별 흡수한다. 네 서버·Proxy 일괄 설치, dev-wiki 정본 이전, 에이전트별 기억 DB는 보류한다. 실제 upstream 재조사는 하지 않았으며 인계서의 고정 커밋 분석을 재사용했다.
