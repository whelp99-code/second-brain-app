# 자비스 기억 저장 완료와 원래 명령 상태 연결

기준일 2026-09-08. 자비스 커밋 `20c8936`. 세컨드브레인 기반·오픈소스 장점 선별 흡수라는 인계 방향 중 **자비스 저장 요청→결과 확인→재사용**의 상태 불일치를 수정한 단위다. 운영 배포나 실제 모든 에이전트의 공통 기억 인수 완료를 뜻하지 않는다.

## 문제와 변경

이전 CLI 통합 실측에서는 provider `proved`, outbox `settled`, 독립 MCP 클라이언트 재조회 `current`까지 성공했지만 원래 자비스 제어 명령은 `uncertain`으로 남았다. 저장 영수증만 보고 다시 실행하면 중복 효과를 만들 수 있고, 그대로 두면 사용자가 성공 여부를 알 수 없다.

이번 구현은 자비스의 기존 DB 증거를 읽어 원래 명령의 결과를 갱신한다. 새 승인·provider 요청을 만들지 않는다.

| 경계 | 구현과 판정 |
|---|---|
| 원래 실행 식별 | command digest, candidate/classification, expected artifact, outbox identity, 승인 receipt와 redemption의 request/fence를 대응 |
| 과거 승인 | 서명과 원래 redemption/dispatch 시각의 유효성을 검사. 조회 시점에 승인이 만료됐어도 이미 실행된 결과를 기록할 수 있음 |
| 완료 증거 | dispatch marker, attempt/invocation digest, artifact observation, settlement receipt를 재계산해 대응. 정리된 review 원문을 다시 요구하지 않음 |
| 결과 | settled→completed, conflict/실행 전 failed/expired→failed. 접수만 됐거나 artifact가 없으면 uncertain 유지 |
| 취소·철회 | 취소/철회된 명령을 자동 completed로 덮어쓰지 않음. outbox에 이미 저장된 결과는 별도 증거로 남음 |
| 실행 중 소유권 | 살아 있는 claim은 원래 executor가 처리. lease가 끝난 claimed 또는 uncertain만 복구 대상으로 선택 |
| 원자성 | 명령 상태·effect·control event를 한 transaction에서 기록. 기존 uncertain 이력 보존, 반복 처리에서 추가 effect 생성 없음 |
| 복구 순서 | 새 060 migration의 content-free singleton cursor로 오류 작업도 지나가며 순환. DB 재연결 후에도 다음 작업을 처리 |
| 복구 실패 | 증거 검증 오류와 DB 기록 오류를 구분해 `control_error` 반환. 바깥 cursor transaction 실패 시 rollback된 완료 개수는 0. 저장 완료 결과는 보존 |
| 운영 연결 | 기존 CLI outbox cycle과 dashboard tick이 실행. 명령 복구만 발생해도 memory·approvals·overview 변경 통지 |
| 삭제/compaction | cursor는 기존 surface:43의 memory_outbox prefix 검사에 포함. 대상 outbox를 제거할 때 일치하는 cursor 힌트도 제거 |

주요 자비스 파일: `src/memory-outbox-control-proof.ts`, `src/memory-outbox-control.ts`, `src/control-plane.ts`, `src/memory-outbox.ts`, `src/approved-executor.ts`, `migrations/060_memory_outbox_control_cursor.sql`.

SB frozen MCP·쓰기 요청·effect 계약은 변경하지 않았다. 세컨드브레인 변경은 실제 연동 하네스의 최종 command 완료와 control_error 검증이다. 외부 OSS 소스 복사나 신규 패키지 도입은 없다.

## 검증

- 집중 control 검사 **19 passed / 1 file, 11.58초**. 재시작·원문 정리 후 복구, 살아 있는 claim 보존, 승인 만료 후 늦은 완료, 취소와 3종 철회, fence/observation/signature 훼손, 충돌/실행 전 실패/만료, effect/event rollback, cursor commit rollback, 순환 공정성과 cursor 제거를 검사했다.
- 독립 검토에서 발견한 오류 행 기아와 바깥 cursor transaction 오류 전파를 수정하고 회귀 시나리오를 추가했다.
- 최종 회귀 **160 passed / 52 files, 85.42초**. outbox/control/executor/CLI/SSE, Task32, migration, managed surface, 실제 DB compaction 경로 포함. 집중 검사와 중복하므로 합산하지 않는다. `/var/tmp/jarvis-outbox-control-final-regression.log`.
- 최종 backend build와 변경 ESLint 통과. `/var/tmp/jarvis-outbox-control-final-build.log`, `/var/tmp/jarvis-outbox-control-final-lint.log`. 독립 재검토의 두 지적을 수정한 후 추가 actionable 없음으로 확인했다. Python 제품 소스는 바꾸지 않아 전체 Python 검사를 반복하지 않았다.
- 초기 넓은 Vitest 실행은 Playwright의 e2e 파일까지 선택했고, 일부 migration 예상 목록이 당시 추가된 059를 반영하지 못했다. 최종 실행은 기존 npm test 정책에 맞게 dashboard/e2e/과거 복제 경로를 제외하고, 현재 059 및 이번 060 예상 목록을 명시해 통과했다. shipped SQL 바이트나 frozen 계약 검사를 완화하지 않았다.

실제 MCP 재현 명령:

```bash
TMPDIR=/var/tmp node scripts/jarvis-memory-acceptance.mjs ../Orca-JARVIS --owner-confirmed --approval-rollback --runtime-cli --record-limit --record-budget --sensitive
```

하네스는 합성 owner 승인과 격리 vault를 사용한다. 자비스 `execute()` CLI API를 호출할 때마다 새 DB/transport를 열고 닫으며, provider는 실제 별도 MCP 프로세스다. 독립 MCP 클라이언트 두 개의 회수는 실제 Codex/Claude 앱의 자동 수집·주입까지 검증한 결과가 아니다.

최종 실측: `control_state=completed`, `provider_status=proved`, `outbox=settled`, `commands_reconciled=1`, `evidence_count=64`, `second_client=current`, `replayed=true`, `reapply=idle`, `redispatched=0`, `remaining_review_files=0`, cleanup/control 오류 없음. `/var/tmp/sb-jarvis-control-completion-final-acceptance.log`.

운영 migration 적용, 서비스 재시작, release/활성 generation 전환, push는 수행하지 않았다. 060 cursor 테이블을 포함한 새 자비스 소스는 배포 시 기존 migration 준비 검사를 통과해야 한다. 이는 기존 배포 절차의 기술 조건이며 새 사용자 승인 체계를 도입한 것이 아니다.

## 인계와 병합한 다음 우선순위

| 우선순위 | 분류 | 미완료 항목 | 완료 판정에 필요한 증거 |
|---|---|---|---|
| 소스 완료 / 운영 P1 | 수정 | 기본 CLI/dashboard signed read fence 설정 | 후속 [삭제 이후 조회 보고서](MEMORY-READ-FENCE-INTEGRATION-2026-09-08.md)에서 삭제→64개 새 기억 저장→조회 검증. 운영 구성·배포 인수 남음 |
| P0 | 개선 | 실제 후보 수집→publication→저장 명령 준비→확인 UI | 실제 업무/owner 입력 하나가 기존 권한 경로를 거쳐 요청 ID와 원문 출처를 유지하며 완료·재사용 |
| 소스 완료 / 운영 P1 | 수정 | LLM 갱신 중 읽기 잠금/시간초과 | [동시 조회 보고서](GENERATION-READ-CONCURRENCY-2026-09-08.md)에서 실제 자비스·MCP·두 writer·삭제 검증. 대표 p95 및 운영 인수 남음 |
| P1 | 개선 | 일반 Enter 여러 줄 입력과 V2 정정 | 버전 계약, 정정 대상 변경 거부, 정정된 최신 기억 재조회 및 이전 출처 추적 |
| P1 | 개선 | 실제 에이전트 앱 연결과 프로젝트/사용자 범위 | 클라이언트별 읽기/쓰기/수집/주입 지원표, A 기록→B 출처·버전 회수, 허용되지 않은 범위 거부 |
| P1 | 고도화 | 관련 문맥 선택·세션 전달 이력·예산 | 선택 이유·버전·실제 전달 receipt, 세션 중복과 compaction 후 재시도 검사 |
| P1 | 개선 | 운영 release 전환·백업·복원·readiness | 실행 소스와 활성 generation 대응, 독립 복원 및 롤백, 실패/백업 상태 확인 |
| P2 | 고도화 | 한국어 검색과 부하 평가 | 고정 질문 100~300개 및 합의한 데이터 규모에서 근거 회수·오래된 결정·지연·분량 실측 |
| 조건부 | 고도화 | 기존 hybrid 검색 | sealed 읽기 부작용·출처/범위 손실 수정 후 같은 평가 기준선에서 효과 확인 |

LightRAG의 검색/수집 관측, Tencent의 기억 유형/시간, code-brain의 작은 문맥·인계, memory-bank의 원문 추적/중복·수명주기 아이디어는 위 기존 항목으로 흡수한다. 네 서버 일괄 설치, 별도 에이전트 정본 DB, proxy 전환, dev-wiki 정본 폐기는 추가하지 않는다. 최신 upstream 기능·성능을 새로 실측한 보고서는 아니다.
