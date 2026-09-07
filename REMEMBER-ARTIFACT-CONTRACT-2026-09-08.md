# 공통 기억 저장 결과 검증 — 구현 및 인수 기록

기준일: 2026-09-08. 자비스 대응 커밋: `c7c5182`. 소스 구현과 격리 실제 MCP 검증 기록이다. 운영 서비스 배포·실제 앱 공유 완료 기록이 아니다.

## 발견한 문제와 수정

| 문제 | 영향 | 반영한 변경 |
|---|---|---|
| expected_artifact를 호출자가 직접 계산 | 정상 저장도 완료 관측 대상이 잘못될 수 있음 | 자비스 `prepareMemoryRememberDispatch`가 영속 publication과 기존 권한을 검증하고 승인 가능한 명령을 구성 |
| 같은 sid의 모든 record digest가 같아야 한다는 이전 판정 | 여러 문장으로 된 기억은 저장 후에도 완료되지 않음 | 승인된 원문에서 전체 record 기대값을 만들고 한 번의 페이지 읽기로 순서·개수·내용·출처·세대를 검증 |
| record 정렬/중복 처리에서 본문 순서와 반복 문장 구분이 어려움 | 일부 문장만 맞거나 같은 문장을 중복 반환해도 잘못 판정할 위험 | citation span을 소비자 내부 바인딩에 보존하고 span 순으로 비교. 동일 텍스트도 서로 다른 record로 검증 |
| remember 산출물에 요청 sensitivity 미전달 | sensitive 입력이 personal 기본값으로 취급될 수 있음 | RequestExecutor → PageSpec → Vault → 읽기 복원까지 등급 보존, 소비자 정책 마스킹 검사 |
| 수락 가능한 본문이 64개 record/이스케이프 후 4096바이트 한도를 넘음 | 접수 후 읽을 수 없는 결과가 생성될 수 있음 | 접수와 materialization이 같은 순수 validator 사용. pending/CAS 기록 전에 거부 |
| 64개 record의 메타데이터가 소비자 기본 총 65536바이트 예산 초과 | provider proved 이후 outbox가 reconciling에 남음 | schema4의 명시적 `record-set-v1` 로컬 예산 프로필 추가. 페이지·누적 상한 각각 262144바이트, 초과 시 전체 거부 |

## 결과 대응 계약

원문 UTF-8 SHA-256을 H라 할 때 페이지는 `wiki/memory-` + SHA-256(candidate_id + NUL + H), sid는 H 앞 8자리, 예상 source_digest는 `sha256:H`다. 원문 전체 해시와 각 record의 내용 해시는 서로 다른 값이다. 첫 문장만으로 전체 원문이 저장되었다고 판정하지 않는다.

provider는 사용자 `[^`를 문자 그대로 이스케이프하고 Python splitlines/strip 규칙으로 record를 만든다. 자비스도 같은 Unicode 줄 구분·공백 규칙을 적용한다. BOM은 일반 trim으로 제거하지 않는다. 빈 줄은 record가 아니며 반복 문장은 각각 별도 span/record를 가진다.

완료 관측은 전체 페이지를 한 번 읽는다. 반환된 모든 record의 개수, 순서, 내용 해시, page/sid, source identity, provider_owned, sensitivity, 겹치지 않는 정수 span 및 citation identity가 기대값과 일치해야 한다. extra sid/record도 무시하지 않는다. 서로 다른 generation의 결과를 합치지 않으며 세대 불일치는 완료 근거로 쓰지 않는다. 민감 본문의 excerpt가 정책상 생략되어도 검증된 digest로 대응한다.

원문 재구성은 관측용이다. 과거 요청 시각으로 복원하는 것이 새로운 쓰기 권한이나 만료 연장이 되지 않는다. 기존 비정형 selector 경로와 frozen MCP wire schema는 유지한다. `prepareMemoryRememberDispatch` 자체가 명령을 승인하거나 실행하지 않는다.

## 예산과 입력 범위

- 기본 interactive 예산 65536바이트는 유지한다. `record-set-v1`은 schema4에서만 명시적으로 선택할 수 있다. 개별 excerpt 4096바이트 및 기존 깊이·노드·정체성 검사를 유지한다.
- 완료 검증용 reader를 운영에 구성할 때 이 프로필을 주입해야 한다. 일반 사용자 검색 예산을 일괄 확대하는 변경이 아니다.
- V1의 일반 LF/CR 본문 거부는 그대로다. 이번 실제 여러 record 검사는 V1이 이미 허용하던 Unicode 줄 구분자를 썼다. 보통 Enter로 입력한 여러 줄 지원 완료로 보고하지 않는다.
- 일반 여러 줄은 별도 버전/명시적 본문 계약으로 추가해야 한다. 기존 V1 검증을 느슨하게 바꾸거나 승인된 원문을 줄별로 분할해 다른 요청으로 재해석하지 않는다. 기존 V2 effect 계약도 임의로 재사용하지 않는다.
- sensitivity 보존은 프로젝트·사용자·에이전트 ACL 구현을 대체하지 않는다. 이미 저장된 페이지를 이번 변경이 자동 재분류하지 않는다.

## 검증 증거

| 검사 | 결과 | 로그 |
|---|---|---|
| Second Brain 전체 pytest (optional embeddings 제외) | 556 passed, 2 skipped, 124.09초 | `/var/tmp/sb-record-set-full-tests.log` |
| 변경 Python 타입 | 0 errors, 0 warnings | `/var/tmp/sb-record-set-types.log` |
| 자비스 기억 관련 검사 | 287 passed / 32 files, 36.09초 | `/var/tmp/jarvis-record-set-final-tests.log` |
| 자비스 변경 ESLint·backend build | 통과 | `/var/tmp/jarvis-record-set-build.log` |
| 4개 record, 반복·공백·사용자 footnote | 실제 MCP proved→settled, 두 클라이언트 current | `/var/tmp/sb-jarvis-record-set-acceptance.log` |
| 같은 4개 record sensitive | 위 순환 및 excerpt 정책 생략 통과 | `/var/tmp/sb-jarvis-record-set-sensitive.log` |
| 64개 record / 원문 4029바이트 | 64개 회수, settled, 재전송 추가 dispatch 0 | `/var/tmp/sb-jarvis-record-limit-new-budget.log` |
| 같은 64개 record sensitive | 전체 회수·등급·정책 생략 통과 | `/var/tmp/sb-jarvis-record-limit-sensitive.log` |
| 기본 예산으로 같은 64개 요청 | 의도한 음성 검사 실패: AGGREGATE_OVERSIZE, reconciling 유지, 원문 보존 | `/var/tmp/sb-jarvis-record-limit-old-budget.log` |

Ruff 및 Node 구문 검사도 통과했다. 자비스 독립 코드 검토에서 발견한 누적 예산 문제를 반영했고 최종 검토에서 추가 actionable 결함은 보고되지 않았다. 전체 Python 타입의 기존 경고 55개 해소를 뜻하지 않는다.

재현은 자비스 backend 빌드 후 Second Brain 루트에서 수행한다.

```bash
TMPDIR=/var/tmp node scripts/jarvis-memory-acceptance.mjs ../Orca-JARVIS --owner-confirmed --record-set
TMPDIR=/var/tmp node scripts/jarvis-memory-acceptance.mjs ../Orca-JARVIS --owner-confirmed --record-limit --record-budget
TMPDIR=/var/tmp node scripts/jarvis-memory-acceptance.mjs ../Orca-JARVIS --owner-confirmed --record-limit --record-budget --sensitive
```

`--record-budget`을 빼고 64개 검사를 실행하면 settled assertion에서 exit 1이 예상된다. provider 접수/완료만으로 소비자 성공을 표시하지 않는다는 증거다. 합성 owner 서명과 격리 DB를 사용하며 하네스가 provider apply/reconcile을 호출한다. 실제 운영자 승인·현실 업무 실행·Codex/Claude 앱 공유 실적이 아니다.

## 다음 완료 조건

1. I1-a/c/e: 실제 runtime에서 outbox·완료 reader·명령 구성기를 연결하고 기존 주기적 실행으로 비동기 완료/정리 오류를 관측한다.
2. I1-b 후속: 자비스 `316b8f2`에서 승인 바깥 SQL rollback metadata 복구를 구현하고 새 receipt·실제 MCP 순환을 검증했다. 운영 반영은 남아 있으며 상세는 순환 인수 보고서의 마지막 절을 따른다.
3. I1-d: 일반 LF 본문 계약을 양쪽에 명시적으로 추가하고 전체 원문 승인·저장·재조회까지 검사한다.
4. 기존 V2 target/delegation으로 정정·재조회를 연결한다. V1 owner-confirmed correct의 승인 범위 부족을 우회하지 않는다.
5. 실제 서로 다른 에이전트 앱, 프로젝트 범위 거부, 세션별 문맥 전달, 운영 release 전환·복구를 순서대로 검증한다. B3/B5~B8 잔여 범위는 구현 원장에 유지한다.
