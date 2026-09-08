# 공통 기억 조회 — 자비스 CLI 연결·수정·검증 보고서

상태: **명시적 CLI 조회 구현 및 격리 실사용 경로 검증. 전체 공통 기억 목표·운영 배포는 미완료.**
자비스 커밋: `63bdd02` (`feat(memory): expose policy-bound reference reads through CLI`).

## 인계 방향과 완료 범위

[기존 준비 모듈](MEMORY-REFERENCE-PREPARATION-2026-09-08.md)과 자비스 인계서의 공통 인터페이스,
작은 context pack, 출처·정정·차단 수명주기를 기존 구현에 연결했다. 세컨드브레인 정본,
자비스 요청/권한, dev-wiki 개발 원문의 역할은 유지한다. 외부 코드를 복사하거나 네 제품을
설치하지 않았고 별도 기억 서버·원문 DB·전역 Proxy·자동 주입 훅을 추가하지 않았다.

현재 실제 동작 경로는 명시적 owner CLI → 기존 signed adapter → 실제 SB MCP status/search/page
→ 정책·세대 확인 → 제한된 reference JSON이다. 본문과 source/record/citation/digest/세대가
포함되며 신뢰는 `untrusted`, 실행 authority는 `none`이다. 기존 추천 조립기의 live observation
조건이나 frozen MCP를 완화하지 않는다.

## 수정·개선 항목과 판정

| 항목 | 확인한 문제·필요 | 구현 및 검증 결과 |
|---|---|---|
| CLI 연결 | 준비 라이브러리만 있어 실제 명령 경로가 없었음 | `memory context <query>`를 기존 CLI에 연결. 실제 별도 프로세스와 MCP로 조회/빈 결과 확인 |
| 전체 예산 | 본문만 제한하면 stdout 메타데이터·개행이 한도를 넘을 수 있음 | limit 1~32, max_bytes 1~65,536. 기본 8개/16,384 bytes. 최종 stdout까지 재계수; 지나치게 작은 예산은 오류 |
| 정책 공통화 | 새 읽기가 기존 웹 suppression을 우회할 위험 | 기존 surface/legacy SQL을 공통 함수로 추출. 차단 자료가 하나라도 있으면 이번 묶음 전체를 본문 없는 오류로 거부 |
| 변경 감지 | COUNT/MAX는 같은 개수·생성 시각의 REPLACE를 놓침 | 새 migration 070에 단조 증가 revision. 여섯 관련 테이블의 INSERT/UPDATE/DELETE 관측. 실제 owner forget 이후 REPLACE race와 rollback·revision 초기화 거부 검증 |
| 세대 확인 | 빈 결과도 조회 중 세대 전환을 놓칠 수 있음 | 조회 전후 status의 provider/generation/manifest/head/tree/삭제 sequence/root 비교. 결과가 비어 있어도 변경 거부 |
| 서명 목적 | status와 본문 읽기는 목적이 다름 | 기존 fence 생성기에 read/status 목적 인자 추가. 네 RPC의 목적·operation 검사 |
| 최종 권한·만료 | provider 정리 동안 key/기억이 만료·철회될 수 있음 | 정리 후 로컬 read transaction에서 revision·key 유효성·본문 만료 재검사. 사전 철회 0 RPC, 정리 중 철회/만료 거부 |
| 일관된 DB 읽기 | 여러 SELECT 사이의 정책 혼합과 네트워크 중 잠금 위험 | 짧은 일관된 DB snapshot 사용. RPC 시 inTransaction=false 검증 |
| 연결 종료 | owned close의 중복 호출/실패가 결과 또는 원 오류를 덮어쓸 수 있음 | close Promise를 한 번만 생성. 성공은 최종 정책 검사 전에 정리, 실패 경로는 원래 고정 오류 보존. 주입 transport는 caller 소유 |
| 키 파일 | 읽기에서 키 재생성·공개 권한 파일·링크 허용 위험 | 기존 private projection key만 읽음. 누락/권한/소유자/하드링크/심볼릭링크/크기 검사. HMAC domain 고정 벡터와 caller buffer 변경에도 값 보존 |
| 오류 경계 | DB transaction 또는 descriptor close 실패가 내부 경로를 노출할 수 있음 | DB/키/transport 고정 오류. 정상/잘못된 키 각각 real close 후 오류를 주입해 검증 |
| 관측 의미 | 준비/CLI 성공을 모델 전달 확인으로 오인할 수 있음 | `provider_status_received_at`과 prepared_at 구분. 모델 전달·세션 receipt 인수는 false로 기록 |

여섯 revision 대상은 memory_surface_authority, memory_surface_target_versions,
memory_surface_suppressions, memory_suppressions, memory_effect_delegation_keys,
memory_effect_delegation_revocations다. 마지막 테이블은 개별 effect delegation의 철회이며
signing key 철회와 별개다. key 철회 정본은 기존 keys.state이고, 기존 API가 이를 revoked로
변경한다. 별도 delegation_id를 key_id처럼 비교하는 검사를 만들지 않았다.

## 검증 증거

최종 관련 회귀 **77 passed / 7 files, 36.31초**. 신규 reader 검사 25개, 기존 reference 준비
25개, migration 7개, 실제 웹 owner forget/runtime 2개, signing fence 15개, suppression 1개,
HMAC token 2개다. 최종 로그 `/var/tmp/jarvis-reference-read-regression-complete.log`.
앞선 집중/중간 실행은 중복이므로 합산하지 않는다. 초기 descriptor failure 검사 4개는 ESM
namespace를 spy할 수 없어 실패했다. 기존 리포 방식의 real filesystem module wrapper로
오류 주입을 고친 뒤 25개 집중과 최종 77개 회귀를 통과했다.

격리 tsc build와 최종 noEmit 타입 검사, 변경 소스/테스트 ESLint, SB 인수 도구 Node 구문검사와
변경 diff 검사를 통과했다. 로그는 `/var/tmp/jarvis-reference-read-build-verified.log`,
`/var/tmp/jarvis-reference-read-types-complete.log`, `/var/tmp/jarvis-reference-read-lint-verified.log`,
`/var/tmp/jarvis-reference-read-test-lint-final.log`. 다른 작업의 dashboard 변경을 포함한 전체
제품/GUI 인증이나 운영 migration 완료로 확대하지 않는다.

[실제 CLI 인수 도구](scripts/jarvis-memory-reference-cli-acceptance.mjs)는 새 격리 authority DB와
합성 provider 기억을 만들고 실제 Node CLI subprocess→production reader→`python -m sb.mcp`를
호출한다. signed 키 등록도 격리 fixture에만 존재한다. provider와 CLI는 실제 실행 시계를 쓴다.

| 실제 명령 시나리오 | 종료 코드 | stdout bytes | 확인 |
|---|---:|---:|---|
| ExampleAlpha 조회 | 0 | 3,073 | 1 record, 본문·출처·세대·text/context digest 일치, 4,000 byte 이내 |
| 없는 질문 | 0 | 943 | empty |
| max_bytes=1 | 2 | 0 | MEMORY_REFERENCE_BUDGET_IMPOSSIBLE |
| 공개 권한 projection key | 2 | 0 | MEMORY_REFERENCE_KEY_UNAVAILABLE |
| 기존 API로 철회된 signing key | 2 | 0 | MEMORY_READ_FENCE_KEY_UNAVAILABLE |

조회 4건 전후 전체 사용자 테이블의 논리 행 digest가 동일했다. 그 뒤 수행한 key 철회는 검증
fixture의 명시적 변경이다. 실제 DB 파일의 WAL/mtime 불변이나 운영 DB 무변경 증거로 혼동하지 않는다.
기억 내용은 합성이며 실제 LLM 요약 품질·실제 질문 정답률 시험이 아니다.

증거 경로: /var/tmp/sb-reference-cli-7QA91R. DB: /var/tmp/jarvis-task27-memory-WJeZGK.
본문 JSON 2,842 bytes, digest `sha256:df91b1bae2fab924629062fd35e2875cba932f844962713a3bd806ba7484d402`.
최종 provider 응답 관측 시각: `2026-09-08T01:36:47.059Z`.
로그: `/var/tmp/jarvis-reference-cli-acceptance-verified.log`.
재현은 contracts/migrations가 포함된 새 자비스 격리 build-root를 준비한 뒤 SB 루트에서
`TMPDIR=/var/tmp node scripts/jarvis-memory-reference-cli-acceptance.mjs <build-root>`.
이번 build-root는 `/var/tmp/sb-context-boundary-rjw8vhqx`다.

## 독립 리뷰와 수정 이력

자비스 charter의 구현/검토 모델 분리에 따라 별도 gpt-5.6-sol native Codex read-only 리뷰를
사용했다. 도구 없이 제공된 소스를 검토했고 테스트는 이 작업에서 별도로 실행했다.
초기 지적의 중복 close, count-only 변경 감지, DB 오류 노출과 후속 descriptor close 오류를
수정했다. CLI finally의 오류 재발 및 lint 지적은 성공 경로의 중복 finally를 제거해 해결했다.
provider 상태가 최종 관측 이후에도 고정된다는 보장은 하지 않으며 관측 timestamp와 후속 재조회
요건을 문서화했다. 리뷰 중 signing key와 effect delegation 철회를 혼동한 지적은 실제 모듈과
기존 철회 API·테스트를 추가 제공하여 재검토했다. 최종 추가 actionable finding 없음,
turn.completed/process exit 0: `/var/tmp/jarvis-reference-read-review-verified.jsonl`.
이는 모델 세션 전달·후속 무효화 또는 운영 배포의 승인/완료를 뜻하지 않는다.

## 남은 수정·개선·고도화와 보류

| 우선순위/영역 | 남은 작업 | 완료 증거·현재 판정 |
|---|---|---|
| P1 / B5·C6 실제 전달 | 기존 context/projection을 실제 client 요청·session/compaction 경계에 연결 | 준비/전송 실패/수신 확인을 구분한 원문 최소 receipt, 확인 후 중복 억제, 새 session/compaction 재공급. 자동 주입 활성화 보류 |
| P1 / B5·C7 수명 | 준비 후·전송 중/후 정정·삭제·suppression/범위 변경 연결 | 오래된 payload 폐기/재조회와 전달 계보 무효화. 현재 CLI는 최종 provider 관측 시점의 snapshot이며 이후 변경까지 보장하지 않음 |
| P1 / B4·C8 범위 | 검증된 원본 분류와 자비스 scope의 version 결합 | search/page/conflict/export/context 모두 같은 경계. 임의 project 문자열이나 같은 OS owner 공유를 보안 격리로 해석하는 방식 보류 |
| P1 / B4 수집 | task 원본 차단의 파생 후보/저장 전파 | 수집 전후·전송 중·저장/복원 후 차단 검증. 기존 자동 task completion 수집 보류 유지 |
| P1 / B7 쓰기 인수 | 대규모 100회 write cycle와 동시 reader, 마지막 재실행/복원 | 이번 보고 시점 65/100, 아직 terminal 성공 아님. SB sb/ 소스를 고정하여 진행 |
| P1 / 검색·복구 병합 | 격리 worktree의 세 커밋을 원 작업공간으로 통합 | d174276→47fa507→9323a6d. full 쓰기 종료 후 병합 및 통합 회귀. 앞선 764 passed/2 skipped는 격리 코드 증거 |
| P1 / B6 운영 | migration 070 포함 release·키 구성·백업 복원·재시작 인수 | 운영 DB migration/배포/서비스 변경 미수행. 검증된 구성과 실제 운영 순환의 별도 인수 필요 |
| P2 / B7·B8 품질 | 실제 한국어 질문 100~300개, 자연어/의역·실제 tokenizer | 합성 100개 60/90 회수는 회귀 기준일 뿐. 실제 질문 자료와 모델 encoding 기준의 근거 사용/분량 평가 필요 |
| P2 / B4 앱 경로 | 실제 GUI/클라이언트별 수집·주입 및 정정 화면 | 기존 native Codex/Claude 공유 인수와 이번 명시 CLI 인수를 앱별 전체 인수로 확대하지 않음 |
| P2 / OSS 검색 확장 | 측정된 결손에 한정한 hybrid/관계 확장 | 별도 그래프 DB·서버·Proxy 일괄 도입, 근거 없는 품질 향상 주장 보류 |

SB 제품 고정 SHA-256은 `387d6c7f5b9c1b9db98c31d53c224181757d4eddba5aaf8cfba0641176cb53c4`로
실행 시작 evidence와 일치했다. 쓰기 검증 로그 `/var/tmp/sb-write-cycle-full-fixed.log` 및
`/var/tmp/sb-write-cycles-ynvxjoyu`는 계속 같은 실행의 증거다. 관측 timeout으로 재시작하지 않았다.
이 단위에는 SB 도구/문서와 자비스 지정 18개 파일만 포함하며 동시 dashboard 작업과 사용자
미추적 원본은 포함하지 않았다. 전체 개발 목표는 계속 미완료다.
