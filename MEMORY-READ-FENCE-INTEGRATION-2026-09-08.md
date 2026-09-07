# 삭제 이후에도 이어지는 자비스 공통 기억 조회

기준일 2026-09-08. 자비스 커밋 `502f32e`. 인계의 최우선 순환인 저장 요청→완료 확인→재사용에 삭제 이력이 있는 경우를 추가했다. 격리 저장소에서 실제 MCP 프로세스로 검증했으며, 운영 배포·실제 Codex/Claude 앱 연결 완료를 뜻하지 않는다.

## 확인한 문제와 수정

| 문제 | 영향 | 수정과 검증 경계 |
|---|---|---|
| 기본 CLI/dashboard에 signed read fence 구성이 없음 | 삭제 원장의 sequence가 0보다 커지면 정상 조회·저장 완료 확인도 거부됨 | 기존 자비스 Ed25519 위임 키와 현재 DB 원장으로 요청마다 fence 구성. CLI outbox·dashboard 조회·완료 reader에 연결 |
| 키 상태와 삭제 원장 시점을 고정하면 실행 중 철회/삭제를 놓침 | 오래된 서명으로 조회하거나 다른 DB의 상태를 사용 | 각 조회에서 등록 키·유효기간·fingerprint·최신 high-water 확인. dashboard outbox별 해당 DB 사용 |
| 마지막 출처 삭제 후 `sources: []`가 공개 문자열 `"[]"`로 나옴 | 자비스가 정상적인 빈 페이지를 `SECOND_BRAIN_PAGE_MALFORMED`로 거부 | SB `public_frontmatter`에서 정확히 `"[]"`만 기존 공개 scalar `""`로 정규화. 누락·잘못된 값은 보존해 소비자가 거부하도록 유지 |
| 키 오류가 adapter 밖으로 예외 전파 | 완료 확인 실패의 원인을 잘못 처리할 가능성 | key/authority 오류를 adapter `invalid`로 반환하고 무서명 요청을 보내지 않음. 키 철회 후 전송 0회 검사 |

자비스 변경: `src/memory-read-fence.ts`, `src/memory-read-fence-production.ts`, `src/memory-outbox-production.ts`, `src/dashboard/memory-production.ts`, `src/dashboard/main.ts`, `src/second-brain-adapter.ts`, `src/second-brain-effect-service.ts`, 공개 export와 회귀 검사. 기존 effect service의 서명 구현을 공통 함수로 옮겨 중복을 줄였다.

SB 변경: `sb/public_page.py`, 해당 회귀 검사, `tests/fixtures/jarvis_memory_provider.py`, 실제 연동 하네스와 `scripts/jarvis-read-fence-fixture.mjs`. frozen MCP V1/V2 요청·서명 계약은 유지한다. OSS 소스 복사·추가 라이브러리 설치는 없다.

## 구성 계약

기본 CLI와 dashboard는 다음 세 환경변수를 함께 읽는다. 프로그램으로 구성할 때는 `MemoryReadFenceProductionConfig`를 명시할 수 있다.

| 환경변수 | 값 |
|---|---|
| `JARVIS_MEMORY_PROVIDER_INSTANCE_ID` | 연결할 SB의 기존 provider identity와 정확히 일치하는 값 |
| `JARVIS_MEMORY_SIGNING_KEY_ID` | 자비스 `memory_effect_delegation_keys`에 등록된 owner Ed25519 키 ID |
| `JARVIS_MEMORY_PRIVATE_KEY_PATH` | 같은 키의 PKCS8 PEM 파일 절대 경로 |

키 파일은 실행 사용자 소유의 일반 파일이어야 하며, group/other 권한·symlink·여러 hard link·16KiB 초과를 거부한다. private key fingerprint가 등록 키와 일치하고, 등록 키가 active이며 현재 시각이 유효기간 안에 있어야 한다. SB의 기존 `jarvis_public_keys` 설정에도 같은 key ID와 공개키가 있어야 한다. 이 구현은 키를 생성·등록하거나 provider의 high-water를 자비스 DB에 복사하지 않는다.

조회 fence는 기본 60초이며 등록 키 만료가 먼저 오면 그 시점으로 줄인다. nonce는 매번 다르고, 키 철회·만료는 다음 조회에 반영한다. PEM은 구성 시 읽으므로 키 교체 시 구성 인스턴스를 다시 만들어야 한다. 세 변수가 모두 없으면 기존 무서명 초기 경로를 유지하고, 일부만 있거나 값이 잘못됐으면 `MEMORY_READ_FENCE_CONFIG_INVALID`다. 삭제가 있는 vault에서 구성 누락은 여전히 provider의 `TOMBSTONE_FENCE_REQUIRED`로 거부된다.

운영 환경변수·키·DB·서비스·active generation은 이 작업에서 변경하지 않았다. 이 항목의 소스 연결 완료와 운영 구성·배포 인수는 구분한다.

## 검증

- 자비스 집중 검사 20 passed / 2 files, 13.82초. ID 호환, 서명 검증, key expiry/revocation, DB별 분리, 설정/파일 오류, 기존 callback 우선순위와 transport 소유권 포함.
- 자비스 관련 회귀 149 passed / 26 files, 53.64초. 위 집중 검사와 중복하므로 합산하지 않는다. outbox/control, adapter/effect, Task32, dashboard SSE 포함. `/var/tmp/jarvis-read-fence-regression.log`.
- Python 공개 응답·MCP 계약·프로필·generation·삭제/복원 회귀 18 passed, 22.79초. `/var/tmp/sb-read-fence-regression.log`.
- `uv run ruff check sb tests`, 변경 자비스 ESLint 통과. 독립 검토에서 지적된 DB 연결과 ID 제한을 수정했으며, SB 빈 sources 정규화 후 추가 actionable 없음.
- 최종 자비스 backend build 통과. `/var/tmp/jarvis-read-fence-final-build.log`. 중간 빌드는 다른 작업이 추가 중인 `task-candidate-certifications.test.ts`의 readonly signature 대입 3건에서 실패했으나, 해당 작업의 수정 후 최종 빌드가 통과했다. 이 작업은 그 파일을 변경하지 않았다.

실제 재현:

```bash
TMPDIR=/var/tmp node scripts/jarvis-memory-acceptance.mjs ../Orca-JARVIS --owner-confirmed --approval-rollback --runtime-cli --record-limit --record-budget --sensitive --after-delete
```

합성 owner 승인과 별도 DB/vault를 사용한다. V2 서명 삭제를 실제 provider에 접수·처리한 뒤, **fence callback을 직접 주입하지 않은 자비스 CLI 구성**으로 새 기억을 저장한다. 삭제 전에 만든 reader도 이후 최신 원장으로 다시 서명한다.

실측: 삭제 proved, tombstone sequence 1, 무서명 `TOMBSTONE_FENCE_REQUIRED`, 이전 서명 `TOMBSTONE_SET_STALE`, 삭제 페이지의 회수 record 0. 이후 sensitive record 64개 저장이 provider proved→outbox settled→control completed로 이어졌다. 두 독립 MCP 클라이언트 current, 동일 record ID 회수, replay true, 재실행 idle, 추가 dispatch 0, review 원문 잔여 0, cleanup/control 오류 없음. `/var/tmp/sb-jarvis-read-fence-final-acceptance.log`.

삭제 요청의 authority receipt는 fixture로 구성했다. 실제 자비스 삭제 UI·권한 흐름 전체의 인수 증거는 아니다. 두 MCP 프로세스는 실제 Codex/Claude 앱별 자동 수집·주입 지원 증거도 아니다. 최근 변경 목록의 `current`는 비어 있어도 가능하므로 이번 저장·회수 판정은 식별 가능한 페이지와 64개 record에 근거한다. 고정 fixture 시각과 Git의 상대 `--since` host 시각 차이에 대한 recent 목록 검증은 별도 개선 항목으로 남긴다.

## 인계와 합친 남은 실행 목록

| 순서·관점 | 남은 작업 | 완료 증거 |
|---|---|---|
| P0 수정 | 느린 LLM 갱신 중 읽기 잠금과 10초 조회 deadline | 동시 검색·writer·중단 복구·삭제 보장을 함께 확인 |
| P0 개선 | 실제 후보 수집→publication→저장 명령 준비→UI 확인 | 실제 입력 하나가 출처·요청 ID를 유지하며 완료되고 다음 요청에서 재사용 |
| P1 개선 | 운영 read fence 구성·release/generation 전환·백업/복원 | 실행 소스·키·원장 대응, 운영 저장/삭제/조회, 독립 복원 및 롤백 |
| P1 개선 | 실제 에이전트 앱 연결 및 프로젝트/사용자 범위 | 앱별 조회/쓰기/수집/주입 지원표, A 저장→B 회수, 범위 밖 조회 거부 |
| P1 개선 | 일반 Enter 여러 줄·V2 정정·시간 조회 | 버전 호환, 승인 대상 변경 거부, 최신 기억과 이전 출처 추적, 최근 변경 목록의 실제 record 검증 |
| P1 고도화 | 관련 문맥·세션 전달 이력·분량 예산 | 근거/버전/선택 이유·전달 receipt, 중복 방지·compaction 후 재시도·실패 결과 구분 |
| P2 고도화 | 한국어 검색 품질과 부하 측정 | 고정 질문 100~300개, 근거 회수·오래된 결정 노출·지연·주입량 기준선 |
| 조건부 고도화 | hybrid와 선택적 관계 확장 | 읽기 전용·출처/범위 보존 수정 후 기준선 대비 효과 확인 |

LightRAG의 근거/검색·삭제 일관성, Tencent의 공통 기억/범위, code-brain의 작은 문맥, memory-bank의 원문/중복·수명주기 장점은 위 기존 구현에 흡수한다. 상세 기존/연결 부족/신규/제외 대조는 [OSS 통합 계획](OSS-ABSORPTION-INTEGRATION-PLAN-2026-09-07.md), 전체 B0~B8 상태는 [구현 원장](IMPLEMENTATION-STATUS.md)을 따른다.
