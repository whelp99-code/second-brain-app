# 인계 병합 후 운영 대조: 실행 중인 서비스와 개발 구현의 차이

2026-09-09 로컬 systemd, 실제 프로세스 경로, 설치 패키지, HTTP 상태, 운영 원장을 읽기 전용으로 확인했다. [자비스 인계](../Orca-JARVIS/docs/second-brain-oss-absorption-handoff-2026-09-07.md)의 방향을 유지한다. 세컨드브레인 정본과 기존 구현을 재사용하며 네 OSS의 기능을 선별 흡수한다.

**판정: 기존 SB 서비스는 응답하고 최근 실행도 성공했다. 그러나 개발 작업에서 검증한 새 scoped 공통 기억 경로는 현재 운영 릴리스에 포함되지 않았다. 따라서 자비스와 여러 실제 에이전트의 메인 기억이 완성됐다고 판정할 수 없다.**

## 실제 관측

| 확인 대상 | 관측 | 해석 |
|---|---|---|
| SB web | active/running, `/health` 200 `ok`, `/ready` 200 `ready` | 프로세스와 구버전 준비 조건 통과. 실제 에이전트 공유·검색 품질의 증거는 아님 |
| SB 실행 패키지 | 릴리스 `41f0751aca8906d612961e704bc60dd0855fdabd`, wheel을 전용 `.venv`에 설치 | 작업공간 HEAD와 별도 실행물 |
| 새 SB 모듈 | 실행 릴리스 전체에서 `scoped_write_mcp.py`, `scoped_status_mcp.py` 없음 | 새 쓰기/최초 세대 이전 상태 조회 경로 미배포 |
| SB web 프로세스 설정 | `/home/jm/.config/second-brain/config.toml`에 `scoped_provider_verifier`, `mcp_scoped_read` 없음 | 확인한 설정에는 새 경로 설정이 없음. 별도 MCP 프로세스의 모든 설정까지 조사한 것은 아님 |
| 자비스 phone gateway | active/running, 9월 7일 시작. 옵션은 host/port/upstream/static-root/env-file | 새 reconcile 옵션 13개 및 기존 memory context 옵션이 실제 실행 인수에 없음 |
| 자비스 gateway 실행물 | `artifact-4146a192b5fb9e489e2ce3fcb9629077739df0134bc26094750628369dcfdb98` | 실행 `dist/src`에 reconcile-cli/reconcile/provider-verifier 모듈 모두 없음 |
| 자비스 authority | active/running, 릴리스 `a3cbbbe1604798052db6051a8751f039573eb126` | gateway·SB와 별도 릴리스. 최신 원장 전환 및 혼합 버전 인수 필요 |
| 요청 처리·유지보수 | 요청 path, 유지보수 timer, refresh timer active/waiting. 대응 oneshot service inactive/dead, Result success, exit 0 | 대기형/단발 서비스의 inactive 자체는 장애가 아님. 현재 처리 성공이나 지연 부재를 보장하지 않음 |
| 최근 SB 실행 | 9월 9일 13:09 KST 시작, status ok | 최근 배치 성공 관측 |
| 파생 상태 | done 91, failed 5, pending/running 0 | 원장 직접 SELECT 결과 실패 5건은 모두 `brief`, attempts 1, 9월 5일 10:26–14:36 UTC 이력. 이번 실행 실패라고 해석하지 않음 |
| 데이터·백업 요약 | wiki 18, daily 2, conflicts 0; 최근 백업 파일 존재 | 문서 수는 정확성의 증거가 아니며 백업 파일 존재는 복원 성공 증거가 아님 |

운영 구버전 `sb/readiness.py`는 실패 건수를 응답에 넣지만 checks의 참/거짓에는 연결하지 않는다. 개발 작업공간의 `sb/readiness_checks.py:ledger_checks`에는 이미 `derivations_healthy = failed == 0` 검사가 있다. 같은 로직을 다시 만들지 않고 배포 및 이력 처리 절차로 연결한다. 최신 릴리스를 적용하면 보존된 실패 이력 때문에 degraded가 될 수 있으므로, 단순히 상태를 초록색으로 만들기 위해 실패 기록을 삭제하면 안 된다.

실패 오류 본문과 원문은 보고서에 수록하지 않았다. 오류의 원인까지 확정하지 않았으며, 해당 5건의 입력·실행 버전·재시도 가능 여부를 이어서 조사해야 한다. 운영 DB는 SQLite `mode=ro`와 `query_only=ON`으로 조회했다. 비밀키, 쿠키, 환경 비밀 값은 출력하지 않았다.

## 수정·개선·고도화 추가 목록

| 우선 | 분류 | 구체적인 다음 작업 | 완료 증거 |
|---|---|---|---|
| P0 | 연결 개선 | gateway의 쓰기 verifier 설정을 독립 CLI 시작 경로에 연결. 기존 서버 옵션/검증기 재사용 | 누락·잘못된 설정 거부 및 실제 CLI 구성→인증 HTTP→SB 수락·실행 검사 |
| P0 | 운영 연결 | SB/authority/gateway의 배포 후보 버전과 계약 해시를 한 세트로 고정하고, 실제 기존 DB 복사본에서 migration·구버전 호환성 확인 | 원장 보존, FK 검사, 구/신 worker 경계, rollback 시 미지원 데이터 처리 증거 |
| P0 | 운영 연결 | 등록 키/정책/agent/provider/세 spool/launcher/계약 경로를 대조해 실제 gateway 시작 설정과 SB 설정을 준비 | 경로와 실제 등록 값 일치. 13개 parser 통과만으로 준비 완료 처리하지 않음 |
| P0 | 세션 수명 | 실제 로그인에서 SB 검증 호출 자격증명을 공급·교체하는 절차 완성 | 만료·로그아웃·철회 후 기존 자격증명 거부, 새 세션 정상 사용 |
| P0 | 공유 인수 | 실제 클라이언트 A의 저장 완료를 원장으로 확인하고, B의 새 세션에서 출처/프로젝트/버전 회수 | 재시작 전후 동일 기억, 허용 범위 밖 거부, 한 요청에 한 완료 |
| P1 | 운영 수정 | 브리핑 실패 이력 5건의 원인을 개별 분류하고 필요한 것만 기존 retry 경로로 복구 | 원래 오류 보존, 재시도 결과·해소 근거, 최신 readiness와 일치 |
| P1 | 운영 개선 | `/ready`를 최신 검사로 전환하고 gateway 연동 준비 상태와 별도로 검증 | 오래된 배치·실패·백업 검증 실패·미설정 경로를 정상으로 오표시하지 않음 |
| P1 | 복구 인수 | 검증된 백업을 별도 복원 대상으로 복구하고 삭제/재유입 억제 및 읽기 범위 재검증 | 실제 복원 RPO/RTO와 기억 회수, 삭제된 내용의 재등장 없음 |
| P2 | 검색 고도화 | 한글 질문/근거 평가와 클라이언트 지원표 완료 후 관계 검색 채택 판단 | 동일 평가에서 recall·stale·no_data·p50/p95·문맥량·비용 비교 |

앞선 [13개 통합 우선순위](HANDOFF-MERGED-PRIORITIES-2026-09-09.md)와 M1–M14의 삭제·native 세션·전체 클라이언트·검색·GUI 범위는 유지한다. 이 운영 대조로 범위를 축소하지 않는다.

## 검증 기록과 적용 경계

- 기존 최신 SB 제품 검증: 전체 **1,354 passed / 2 skipped**, 선택 embeddings 제외. 이번 운영 관측에서 재실행한 수치가 아니다.
- 직전 gateway CLI 단위: 관련 **55 passed**, 격리 TypeScript emit/lint, parser→실제 로그인 HTTP→CLI→MCP의 pending/failed/proved 및 commit 후 종료 복구 인수. 운영 실제 사용자 인수와 구분한다.
- 이번 변경은 분석 문서다. 운영 HTTP GET 및 상태/파일/원장 읽기만 수행했고, 서비스를 배포·재시작하거나 설정·운영 원장을 변경하지 않았다.
- 배포 전 리뷰 대상은 세 릴리스, 실제 설정 차이, DB 복사본 검사 결과, 복구 절차까지 포함해야 한다. 인계 문서 자체는 운영 변경 승인으로 간주하지 않는다.
