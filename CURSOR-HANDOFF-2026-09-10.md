# Cursor 인계 지시서 — 세컨드브레인·자비스 공통 기억 완성

작성일: 2026-09-10, Asia/Seoul.

사용자 요청: 현재 진행 중인 작업을 마무리하고, 나머지를 Cursor가 이어받을 상세 지시서를 작성한다. 이 문서는 그 인계 산출물이다. **개발 전체 완료나 운영 배포 완료 선언이 아니다.**

## 1. 목표와 작업 방식

최종 목표는 세컨드브레인을 자비스 및 여러 에이전트가 함께 쓰는 메인 기억 저장소로 완성하는 것이다. 실행 중인 서비스나 통과 테스트 개수만으로 완료 처리하지 말고 실제 업무의 저장·조회·정정·삭제·복구까지 검증하라.

사용자 확정 방향:

1. 세컨드브레인을 기반으로 유지한다. LightRAG, TencentDB-Agent-Memory, code-brain, jung-wan-kim/memory-bank의 필요한 장점만 선별 흡수한다.
2. 우선 자비스 연동과 여러 에이전트의 공통 기억 사용을 완성한다.
3. 개별 개발 또는 큰 단위 작업 완료 시 반드시 커밋한다.
4. 위험하거나 근거가 부족한 기능은 보류 판정하고 이유·해제 조건을 보고한다.
5. 기능 개발 뒤 실제 사용 경로로 검증한다. 합성 fixture, 실제 CLI/HTTP, 실제 모델, 실제 업무, 운영 배포의 증거를 구분한다.

작은 주변 수정과 보고서 추가만 반복하지 말라. 첫 검증 갱신 후 M1/M2의 실제 업무 인수를 중심으로 필요한 선행 문제를 해결하라. M1–M14 전체 범위를 유지하되 현재 구현이 있는 기능을 재작성하지 않는다.

## 2. 인계 시 작업공간 상태

- 실제 Linux 작업공간: `/home/jm/orca/projects/second-brain-app`
- 브랜치: `codex/shared-memory-completion-20260907`
- 마지막 개발/검증 정리 커밋: `b0d35b5ef58a4869e36c76131cbfd17704acc64a`
- 이 문서와 상태 진입점 갱신은 그 이후 별도 문서 커밋이다. Cursor 시작 시 `git log`에서 실제 HEAD를 확인하라.
- 이전 턴은 중단 알림이 있었지만 위 커밋은 성공했다. 마지막 검증 프로세스는 모두 종료 결과를 받았고, 인계 시 읽을 수 있는 `/proc`에서 이 작업공간의 pytest/릴리스 검사 실행 프로세스도 발견되지 않았다. 이는 모든 사용자·모든 프로세스의 부재 증명은 아니다.
- 추적 파일에 미커밋 개발 변경은 없었다. 다음 기존 미추적 자료는 건드리지 말라:
  - `/home/jm/orca/projects/second-brain-app/2n`
  - `/home/jm/orca/projects/second-brain-app/phone-history/`
  - `/home/jm/orca/projects/second-brain-app/sb/compile.py.bak-20260906-214804`
  - `/home/jm/orca/projects/second-brain-app/sb/llm.py.bak-20260906-214804`
- 운영 서비스·운영 DB·운영 current 링크를 이번 작업에서 전환하지 않았다. 원격 push도 하지 않았다.

시작 명령:

```bash
cd /home/jm/orca/projects/second-brain-app
git status --short
git branch --show-current
git log -12 --oneline
```

## 3. 먼저 읽을 정본과 해석 순서

1. 내부 규칙: `/home/jm/orca/projects/second-brain-app/AGENTS.md`
2. 리포 간 경계: `/home/jm/orca/projects/dev-wiki/README.md`
3. 원 인계: `/home/jm/orca/projects/Orca-JARVIS/docs/second-brain-oss-absorption-handoff-2026-09-07.md`
4. OSS 통합 계획: `/home/jm/orca/projects/second-brain-app/OSS-ABSORPTION-INTEGRATION-PLAN-2026-09-07.md`
5. 현재 상태 진입점: `/home/jm/orca/projects/second-brain-app/IMPLEMENTATION-STATUS.md`
6. 전체 M1–M14 표: `/home/jm/orca/projects/second-brain-app/SHARED-MEMORY-CONSOLIDATED-REVIEW-2026-09-09.md`
7. 클라이언트 구분: `/home/jm/orca/projects/second-brain-app/AGENT-SUPPORT-AND-ACCEPTANCE-GAPS-2026-09-10.md`

상태/계획 문서는 과거 이력이 누적돼 길다. 예전 본문의 “미구현”, “최신”, “보류”를 현재 상태로 바로 해석하지 말고 커밋·소스·최근 보고서를 대조하라. 특히 관리형 bound_knowledge와 scoped 연결은 이미 구현돼 있다. 초기 설계 문구만 보고 다시 만들지 않는다.

AGENTS.md의 `/Volumes/DevSpace/...`는 과거 macOS 경로다. 여기서는 위 Linux 작업공간을 사용한다. vault는 앱 리포와 다른 저장소다.

## 4. 유지할 경계와 금지 사항

- 세컨드브레인: 기억 정본·출처·저장·검색·정정·삭제·복구.
- 자비스: 작업 실행·승인·검증·처리 결과 소비. 기억 요약을 실행 성공 증거로 사용하지 않는다.
- dev-wiki/Git: 개발 결정과 운영 규칙의 원문 정본. 폐기/자동 이전하지 않는다.
- AGENTS의 레이어·단일 작성자 잠금·vault writer 경계를 지킨다. 커넥터에서 normalize/LLM/vault를 호출하지 않는다. 레지스트리 `sb/connectors/__init__.py`를 임의 확장하지 않는다.
- unified-db에 쓰지 않는다. vault에 remote를 추가하지 않는다. 기존 금지 경로를 수정하지 않는다.
- 현재 리포 지침의 no-push를 유지한다. push/PR이 필요하면 최신 사용자 지시와 대상 리포 규칙을 먼저 확인한다. 인계서 자체가 원격 배포 승인은 아니다.
- 새로운 서버 watcher/queue/event bus, 전역 모델 proxy, 에이전트별 별도 정본 DB를 만들지 않는다.
- 기존 서명/범위/버전 계약 및 validator를 통과시키기 위해 검사를 완화하지 않는다. 옛 “새 authority machinery 금지” 문구를 이유로 이미 구현된 자비스 계약을 삭제하지도 않는다. 구조적 충돌은 정본 ADR/현재 계약과 대조한다.
- 네 OSS 전체 설치, 그래프 DB 일괄 도입, hybrid 기본 활성화는 확정 사항이 아니다. 코드 복사 시 출처 커밋·라이선스/NOTICE를 기록한다. 지금까지의 인계는 주로 설계 선택이며 네 OSS의 신규 코드를 가져오라는 명령이 아니다.
- 사용자 요청 없이 고정 역할→모델 라우팅이나 강제 멀티에이전트 구성을 도입하지 않는다.
- 운영 재시작/데이터 이전은 해당 작업의 권한과 실제 writer 배제·복구 조건을 갖춘 뒤 수행한다. 일반 로컬 구현·검증에 불필요한 승인 단계를 새로 만들지 않는다.

## 5. 이미 완료한 최근 변경 — 되돌리지 말 것

| 커밋 | 변경 | 핵심 검증/주의 |
|---|---|---|
| `13cab77`까지 | scoped 검색 조회 재사용, OpenCode 내용 기반 커서·입력 제한·다중 root 보류 등 | 아래 전체/설치 인수의 기준 |
| `1bdfb17` | 참조 SQLite 읽기 전후 파일 변경 검사, 실제 DB 이름의 WAL/SHM/journal 보류 | 실제 WAL 활성 중 보류→checkpoint 후 수집; 관련77개 |
| `19e7158` | Claude/Codex/OMO/GJC/OpenCode의 깊은 JSON RecursionError 격리 | 실제 깊이10,000 입력에서5종 예외 재현; 정상 형제 수집 유지 |
| `23bc34f` | 잘못된 noqa4곳을 일반 주석으로 정리 | 실행 AST 동일, 캐시 없는 Ruff 경고 제거 |
| `7a57eef` | 재시도할 읽기 실패를 ok/errors0으로 숨기지 않음 | CLI/HTTP 실패 사유, 정상 원문 저장, 복구 후 중복 없음 |
| `d38054a` | 수집 실패 뒤 compile 성공에도 전체 batch 실패 유지 회귀 | 별도 CLI2회와 실제 HTTP 검증 |
| `df5d822` | 삭제 검증 불능과 정상 tombstone 차단 구분 | 실제 SQLite 쿼리 한도 부족 재현→실패→복구 |
| `b0d35b5` | 확대 회귀 및 pipeline 반환값 표기 정리 | 97개 확대 검사+2개 walking-skeleton, 타입·Ruff 경고 없음 |

현재 중요한 동작:

- `sb/pipeline.py`는 size-limit/database-limit/unstable-session-file/unreadable-session-file을 중복 검사 전에 오류로 반영한다. 대표 사유는 `SOURCE_READ_INCOMPLETE: source-id: reason`, exit1. 정상 원문은 저장하고 실패 adapter cursor는 전진하지 않는다. 과거 skip 행이 있어도 실패를 숨기지 않는다.
- 정상 `TOMBSTONE_REINGRESS_BLOCKED`는 삭제 정책에 따른 차단이다. 다른 ErasureError는 `REINGRESS_VERIFICATION_FAILED`로 실패한다. 검증 불능을 임의 수락하지 않는다.
- 상태의 last_run은 마지막 개별 단계이고 last_batch는 전체 실행이다. 이후 빈 compile이ok여도 last_batch는failed일 수 있다. 상태 소비자는 두 의미를 구분해야 한다.
- OpenCode는 하나의 source ID에 여러 root를 묶지 않는다. 여러 root는 고유한 `[[sources]] id`로 선언한다. pipeline이 설정 행별로 어댑터를 격리한다. 기존 source ID를 임의 변경하면 출처/정정/삭제 이력이 달라질 수 있어 자동 재명명하지 않는다.
- OpenCode source version은 항목 ID+추출 본문의 해시, cursor는 URI/버전 목록 해시다. 구형 크기 커서는 최초 한 번 재수집한다. 포맷만 바뀐 JSON은 다시 내보내지 않는다.
- JSON64 MiB, DB 파일/반환 총량64 MiB·5,000행·SQLite VM100만 명령의 snapshot별 고정 한도다. 전체 프로세스 RSS/벽시계/전체 배치 예산의 보장은 아니다. DB 한도는 현재 `[caps] max_db_rows_per_run`을 읽는 구현이 아니다.
- 부분 DB 수집·활성 DB 자동 checkpoint·sidecar 삭제는 하지 않는다. 안정된 export만 읽는다.

관련 상세 보고서:

- `/home/jm/orca/projects/second-brain-app/INGEST-FAILURE-EXPANDED-REGRESSION-2026-09-10.md`
- `/home/jm/orca/projects/second-brain-app/INGEST-READ-FAILURE-STATUS-2026-09-10.md`
- `/home/jm/orca/projects/second-brain-app/INGEST-REINGRESS-VERIFICATION-2026-09-10.md`
- `/home/jm/orca/projects/second-brain-app/READ-FAILURE-BATCH-ACCEPTANCE-2026-09-10.md`
- `/home/jm/orca/projects/second-brain-app/SESSION-DEEP-JSON-2026-09-10.md`
- `/home/jm/orca/projects/second-brain-app/OPENCODE-DATABASE-STABILITY-2026-09-10.md`

## 6. 검증 증거의 정확한 범위

### 전체 회귀와 설치물

최신 전체 검사는 **13cab776643574f6559282e26d93087694e55cf6** 기준이다.

- 1,767 passed / 2 skipped, 516.57초, exit0.
- `tests/test_embeddings.py`는 지침에 따라 제외했다. 선택적 실제 LLM/DB 검사는 별도 환경 조건이다.
- 보고서: `/home/jm/orca/projects/second-brain-app/CONNECTOR-UPDATES-FULL-REGRESSION-2026-09-10.md`
- **그 이후 변경 전체를 위 결과로 보증하지 말라.** 최근 변경은 집중/CLI/HTTP 검사까지 완료했다.

같은13cab77 설치물:

- 경로 `/var/tmp/sb-connectors-release-o9xq0aek/releases/0d6938efdf9073044c9cd0f63b8d6972e24c0793`
- wheel SHA-256 `3c5c5ddeaab9979839575c379c91a5b0225c1d4d7dd6328b1b9fbf2b59b9db08`
- 실제 TLS/HTTP/CLI/MCP 저장→provider proved→자비스 settled/control completed→새 로그인2records 회수.
- 독립 stdio reader2개가 각각2records, 완료 재전송에도 settlement1/attempt1, FK오류0.
- 철회/만료 거부, 복원 작업 SIGKILL 뒤 정리1·재실행0·유지 기억 불변 검증.
- 실제 설치 Python 격리 모드의 OpenCode 두 출처 CLI도 검증.
- 합성 신원/업무/고정 clock이며 native 호출0, production_activated=false.
- 보고서/JSON: `/home/jm/orca/projects/second-brain-app/INSTALLED-CONNECTOR-UPDATES-2026-09-10.md` 및 같은 이름 `.json`.

최근 확대 회귀는97개(69+28, 중복 파일 없음), 반환값 표기 정리 후 walking-skeleton2개가 별도로 통과했다. 파이프라인 basedpyright0오류0경고와 캐시 없는 전체 Ruff가 통과했다. 전부 합산해 현재 전체 테스트 수라고 표현하지 말라.

### 실제 모델과 클라이언트

- Claude Code2.1.261: 최근 인증 MCP 경로 실제 모델 시험 통과 이력.
- Codex: 과거 Claude와 legacy 양방향 공유 성공 이력이 있으나 최신 인증 시험은 사용량 제한으로 미완이었다.
- OMO: 실제 MCP 엔진 회수와 실제 모델 실행은 다르다. 당시 native 모델은 Cursor OAuth 재로그인 요구로 중단됐다.
- GJC: 과거 확인한 로컬 명령은 원격 wrapper였다. 원격 실행/수명 인수는 미완이다.
- OpenCode: 수집 CLI 검증과 native 모델의 자동 수집·문맥 주입은 다르다. 후자는 완료 근거가 없다.
- Cursor 자체도 인계 수신자라는 이유로 기억 연동 검증된 클라이언트로 집계하지 말라. 실제 사용할 제품/버전/인증/수집/쓰기/조회/주입/삭제를 확인해 지원표에 추가한다.
- 사용량 제한/인증 실패는 과거 관측이다. 현재 상태를 확인하되 반복 실패를 무한 재시도하거나 다른 계정·모델로 우회해 완료 처리하지 않는다.

## 7. 남은 전체 작업과 완료 기준

아래 표는 원래 M1–M14를 보존한 실행 지시다. 구현이 없다는 뜻이 아니라 **최종 인수에 아직 남은 범위**다.

| ID | 우선순위 | 다음 작업 | 완료 증거 |
|---|---|---|---|
| M1 | P0 | 기존 인증 세션·범위 resolver·issuer·gateway 구성을 실제 운영 진입점에 연결 | 실제 로그인에서 허용 읽기/쓰기 성공, 다른 프로젝트 거부, 종료/철회 정리 |
| M2 | P0 | 실제 사용자 업무 한 건의 자비스 조회→검증된 결과→저장 요청→영수증→다른 에이전트 새 세션 회수 | 같은 task/request/candidate/record 계보 및 완료1회·재전송 중복0 |
| M3 | P0 | 정책 revision/기발급 claim/백업 rollback의 전체 수명 검증 | 발급 뒤 철회·열린 연결·과거 설정 복구에도 과거 권한으로 읽지 못함 |
| M4 | P0 | 원작업→검증 결과→기억 원문의 실제 계보 완성 | 실패·미확정·철회된 결과가 성공 경험으로 승격되지 않음 |
| M5 | P0 | native session/compaction/log/WAL/백업 사본의 정정·삭제 수명 | 재개·요약·복원·재색인에서 삭제 기억 부활 없음, 사본별 처분 증거 |
| M6 | P0 | 운영 writer/lease 배제와 단일 작성자 전환·복구 | 실제 작성자 배제, 중단·재시작·경로 교체에도 단일 결과·손상 없음 |
| M7 | P0 | 모든 지원 읽기 표면의 범위 일관성 확인 | 제목/snippet/score/원문/벡터/관계 조회에서 불허 정보 노출0 |
| M8 | P1 | 실제 사용 클라이언트별 수집·조회·쓰기·자동 주입 연결 | 제품/버전별 실제 새 세션 상호 회수·오류 격리·중복 방지·지원표 |
| M9 | P1 | 자비스 실제 세션의 문맥 예산·중복 주입·compaction 연결 | 근거/버전/분량/지연 관측, 만료·철회 후 재사용 없음, 근거 부족 no_data |
| M10 | P1 | 실제 한글 사용자 질문100–300개와 정답 근거 확보 | lexical 기준선 대비 근거 회수/오래된 결정/no_data 정확도·지연 측정 |
| M11 | P1 | 큰 corpus의 실제 MCP 및 동시 조회/정정·갱신 측정 | 고정 자료에서 메모리·p50/p95·정정 직후 최신 결과·권한 불변 |
| M12 | P1 | 원장/원본 journal 소실 DR와 운영 RPO/RTO 인수 | 신뢰된 근거에서 복구·삭제 high-water 유지·재유입 차단·시간 측정 |
| M13 | P1 | GUI 정정/삭제·원문/영수증·실패 복구·운영 timer 확인 | 실제 브라우저에서 전체 수명과 실패 원인/복구 확인 |
| M14 | P2 | 관계 검색의 추가 가치 측정 후 제한 채택 | 고정 질문에서 비용 대비 효과 및 정정/삭제 일관성 입증 |

완료 순서는 첫 검증 갱신 → M1/M2의 실제 업무 사례 확정 → 필요한 M3–M7 선행 조건과 운영 전환 → M8–M13 인수다. 그래프나 새 UI로 핵심 연동 결손을 대신 해결하지 말라.

## 8. Cursor의 첫 작업 묶음

### A. 현재 소스 검증을 먼저 갱신

위 HEAD와 작업공간 변경을 확인하고 테스트 중 제품 코드를 고정하라.

```bash
cd /home/jm/orca/projects/second-brain-app
TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py
uv run ruff check --no-cache sb tests
uv run basedpyright sb/pipeline.py sb/connectors/sessions_opencode.py
```

실패하면 원인과 범위를 분류해 수정하고 해당 회귀부터 재검증하라. 이전1,767 수치를 현재 결과에 복사하지 않는다. 별도 full 실행 동안 다른 작업이 파일을 바꿨다면 같은 커밋 검사라고 주장하지 않는다.

최근 집중 검사 진입점:

- `/home/jm/orca/projects/second-brain-app/tests/test_ingest_read_failures.py`
- `/home/jm/orca/projects/second-brain-app/tests/test_ingest_reingress_failure.py`
- `/home/jm/orca/projects/second-brain-app/tests/integration/test_read_failure_batch_status.py`
- `/home/jm/orca/projects/second-brain-app/tests/test_opencode_database_stability.py`
- `/home/jm/orca/projects/second-brain-app/tests/test_session_deep_json.py`
- `/home/jm/orca/projects/second-brain-app/tests/integration/test_session_source_isolation.py`
- `/home/jm/orca/projects/second-brain-app/tests/integration/test_walking_skeleton.py`

### B. 새 설치 후보의 paired 인수 갱신

검증 대상 변경을 커밋한 뒤, 새 임시 app root를 지정해 아래 스크립트를 사용한다. prepare-release의 인자를 생략하면 운영 위치가 기본값이므로 생략하지 말라. 소스 전체 복사나 미추적 파일 포함 설치를 하지 않는다.

```bash
python deploy/prepare-release.py /var/tmp/sb-cursor-candidate-UNIQUE --offline
python deploy/check-release-integration.py ACTUAL_RELEASE_PATH VERIFIED_JARVIS_DIST_PATH
python deploy/check-release-maintenance.py ACTUAL_RELEASE_PATH
```

`UNIQUE`, `ACTUAL_RELEASE_PATH`, `VERIFIED_JARVIS_DIST_PATH`는 실제 확인한 경로로 바꿔라. 설치 과정의 출력·manifest·hash를 보존한다. 자동 current 전환은 하지 않는다.

과거 paired JARVIS 빌드 경로는 `/var/tmp/jarvis-current-pair-_mq15nmd/source/dist`였고, 원 소스 커밋은 `195b1a7d4588a8386def5e7dce2067a141942708`이었다. 임시 파일이 지금도 존재하거나 최신 JARVIS라고 가정하지 않는다. 기존 후보를 쓸 경우 그 후보를 명시하고, 새 자비스 소스와 연동할 경우 자비스 리포 규칙과 변경 이력을 확인한 격리 빌드로 검사한다. 서로 다른 버전 결과를 합치지 않는다.

### C. 실제 업무 인수에 필요한 입력 확보

기존 작업에서 사용자에게 **자비스 작업 ID 또는 원문 문서 경로, 공유할 프로젝트와 에이전트**를 요청했지만 답변은 받지 못했다. 실제 업무를 특정할 근거가 없다면 이 세 가지를 한 번에 요청하라. 합성 fixture를 실사용으로 이름만 바꾸지 않는다. 입력을 기다리는 동안 A/B와 독립적인 결함 수정은 가능하다.

입력을 받은 후 다음 하나의 증거 묶음을 만든다:

1. 원문·업무 ID·프로젝트·성공/실패 검증 근거.
2. 현재 인증 범위에서 조회와 저장 요청의 request/candidate/provider record 연결.
3. provider 완료 증거와 자비스 settled/control completed. 같은 요청 재전송에도 결과1회.
4. 다른 실제 에이전트의 새 세션에서 원문/버전/범위와 함께 회수.
5. 불허 프로젝트 조회 거부.
6. 정정/삭제 이후 새 세션·재개·복원에서 이전 내용을 최신 사실로 쓰지 않음.

native 기록을 만들기 전 그 클라이언트의 로컬 보존 사본도 검사 범위에 포함하라. 일반 사용자 세션의 무조건 자동 저장/전역 훅 활성화는 처분 수명 검증 전까지 보류한다.

## 9. 운영 전환 보류와 해제 조건

가장 최근 읽기 관측은 **2026-09-10T01:40:09.857557+00:00**이다. 현재 상태가 아니다.

- 대상 DB `/home/jm/.local/state/orca-jarvis/jarvis.sqlite`
- 지정 대기열6개 빈 집계, dispatch cursor1행 중 active0.
- GJC lease1행 만료 전, microloop lease0.
- 순차 /proc 관측에서 DB/WAL/SHM holder는 PID1625716 `jm-jarvis-dashboard.service`, PID2123274 `jm-jarvis.service`.
- 같은 UID371프로세스 검사 중 관측 불가22개. 미래 open/다른 UID/원격 writer 배제는 입증하지 못했다.
- 보고서 `/home/jm/orca/projects/second-brain-app/OPS-RECHECK-2026-09-10-0140.md`

재확인 도구:

```bash
python deploy/check-jarvis-pending-state.py /home/jm/.local/state/orca-jarvis/jarvis.sqlite
python deploy/check-database-handles.py /home/jm/.local/state/orca-jarvis/jarvis.sqlite
```

두 도구는 읽기 관측이고 drain_authorized=false다. 큐0·lease행·서비스active·과거PID를 작성자 배제 증거로 대체하지 않는다. 사용자/리포 권한에 맞춰 실제 writer와 실행권을 정리하고 복구 가능한 후보·원장/삭제 이력 보존·전환 후 인수 시나리오를 준비해야 한다. 관련 작업과 조율 없이 서비스 종료나 운영 DB migration을 수행하지 말라.

원본 journal이 없는 DR에서 RESTORE_SOURCE_ANCHOR_MISSING가 나왔던 경로는 우회하지 않는다. 해제하려면 신뢰할 원본/처분 증거와 정책에 맞는 복구 설계가 필요하다. hash/validator 예외를 추가해 통과시키는 것은 금지한다.

## 10. 미완성 구현의 구체적 위험

1. OpenCode DB 검사는 경로의 metadata 전후 비교다. descriptor를 끝까지 고정한 것은 아니므로 검사 사이 교체 후 원상복구·상위 디렉터리 교체·sidecar가 잠깐 생겼다 사라지는 모든 경우를 방어했다고 볼 수 없다. 재현 가능한 반례부터 만들고 기존 fs_safety와 통합할 수 있는지 검토하라. 임시 DB 사본을 도입한다면 새로운 원문 보존·삭제 표면까지 처리해야 한다.
2. snapshot별 한도가 전체 배치 메모리 상한은 아니다. JSON 객체 확장, SQLite 내부 정렬/표현식, 여러 파일 누적, JSONL의 큰 행 비용은 추가 측정이 필요하다. 측정 없이 한도만 높이지 않는다.
3. inbox 원문 보존/ack 경합 방어는 구현됐지만 최종 stat→unlink 사이, 상위 경로 이동·전원 차단의 모든 원자성을 입증한 것은 아니다. 원문 보존을 약화시키는 overwrite fallback을 넣지 않는다.
4. source ID 변경·cursor 마이그레이션은 정정/삭제·재유입 정책과 함께 검증한다. 원본 소실을 감지했다고 자동 삭제 권한을 부여하지 않는다.
5. 일반 malformed 입력과 live-store는 현재 일반 보류이고 네 읽기 실패만 명시적 실행 실패다. 이 정책을 더 확장하려면 실제 운영 기대/반복 재시도/오류 가시성 테스트를 함께 조정한다.
6. scoped 검색은 요청 전후 세대 검증·범위 검사·내용 hash를 유지한다. 성능 개선을 위해 검증을 제거하지 않는다. 최근1,000페이지 각5회 p50은 전체허용2.023초/허용1개0.317초이며 library·합성 소규모 표본이다. 운영 p95나 실제 MCP SLA로 주장하지 않는다.
7. hybrid는 일부 자연어 회수를 개선했지만 폐기/무근거 후보도 늘었다. 기본 off를 유지하고 실제 질문 gold로 이득을 입증한 뒤 변경한다.
8. 일반 native 세션/compaction/log/WAL/backup 전체 삭제 인수가 없다. SDK reader2개를 서로 다른 모델 제품2개로 세지 않는다.

## 11. 산출물과 종료 판정

매 의미 있는 변경마다 다음을 남기고 커밋하라:

- 무엇이 잘못됐고 사용자에게 어떤 영향이 있었는지.
- 재현 근거, 실제 수정 지점, 재사용한 기존 계약.
- 실행한 테스트/실사용 경로·대상 커밋·설치물 hash·결과·한계.
- 남은 항목과 보류 해제 조건.

상태는 `/home/jm/orca/projects/second-brain-app/IMPLEMENTATION-STATUS.md`의 첫 진입점과 관련 보고서에 반영하되, 큰 완료 단위별로 읽기 쉬운 현재 요약을 유지하라. 과거 보고서를 덮어써 당시 수치를 현재 결과로 만들지 않는다.

사용자에게 요청할 추가 정보는 실제 작업 ID/원문, 공유 프로젝트·에이전트, 필요한 인증/운영 조율처럼 의존성이 있는 것만 묶어서 물어라. 이미 승인된 로컬 구현·가역 검증을 반복 확인 때문에 중단하지 않는다.

최종 완료는 M1–M14의 명시적 요구마다 현재 증거를 대조한 뒤 판정한다. 미지원/보류 기능은 목록과 이유를 사용자에게 남긴다. 전체 작업을 현재 구현된 부분만으로 축소해 완료라고 하지 않는다.
