# 일반 여러 줄 기억 — V3 구현과 실제 연결 검증

기준일 2026-09-08. [구현 전 결정](REMEMBER-V3-IMPLEMENTATION-ADR-2026-09-08.md)에 따라 일반 Enter 입력을 명시적 새 계약으로 구현했다. Second Brain 저장과 자비스 후보·승인·처리 결과 소비를 연결한 **소스/격리 실사용 검증**이다. 운영 배포나 실제 Codex/Claude 앱 공유 완료를 뜻하지 않는다.

자비스 대응 커밋: `1f7048ab0431dec3f591b921c74ef0cc0cf150e0`. 기존 작업 중 변경을 제외하고 이 단위 39개 파일(검증 소스 38개+보고서)을 커밋했다.

## 바뀐 동작

새 후보 입력에서 LF·CRLF·CR·탭과 가장자리 공백을 포함한 원문을 검토·승인·저장·인용·재조회까지 사용할 수 있다. 원문은 trim하거나 줄바꿈을 치환하지 않고 CAS에 보존한다. 화면은 기존 `pre-wrap` 표시를 재사용하며 자동 Markdown/HTML 해석을 추가하지 않았다.

Python/JavaScript의 BOM/NEL 판정 차이와 후보·요청의 분량 차이는 새 본문 전용 검증기로 일치시킨다. 기존 V1 입력/요청의 수용 범위는 그대로이며 구형 후보·승인·pending을 전송 시 새 버전으로 바꾸지 않는다.

| 계약 | 새 경로 | 유지한 경계 |
|---|---|---|
| 후보 입력 | schema2 + root `body_profile: plain-text-v1`, remember만 | 기존 schema1의 제목·ID·본문 검증 불변 |
| 검토·발행 | review spool schema2, dispatch spool schema3 | 원문·profile·digest 결합. 기존 classification/후보 출처 identity 유지 |
| provider 요청/수락 | request schema3, accepted schema3 | V1 receipt와 idempotency 유지, V2 effect는 별도 |
| Control Plane | 기존 digest 기반 spool command args schema2 | correction 전용 control args schema3와 구분 |
| MCP | 명시적 `remember-schema5`, 같은 9개 도구 | 구형 schema4 fixture/hash 보존, read wire 의미는 schema4 재사용 |

원문은 NFC·유효 Unicode scalar여야 한다. LF/CR/탭 외 C0와 DEL은 거부한다. 원문 상한 4096 UTF-8 바이트, Python splitlines/strip과 사용자 `[^` 이스케이프 후 record 1~64개, 각 4096바이트 이하다. 승인 전에 원문을 몰래 정규화하지 않는다. 일반 검색 예산은 유지하고 64개 완료 관측은 기존 `record-set-v1` 예산을 사용한다.

같은 원문·출처를 V1/V2 후보 입력으로 다시 분류해 다른 기억 후보를 만드는 경로도 차단했다. provider의 V1/V3는 같은 후보 idempotency를 사용하므로 버전만 바꿔 중복 materialize할 수 없다. 새 request/file digest는 V3 전용 domain이며 원문 source digest/page/sid 대응은 기존 규칙을 유지한다.

## 함께 수정한 접수 복구 결함

1. pending 파일을 저장하고 원장 INSERT 전에 종료되면, 나중 재시도의 새 `accepted_at` 때문에 같은 요청이 영구 충돌했다. 이제 동일 canonical request·schema인지 확인하고 원래 접수 시각·파일 바이트·digest를 보존해 원장을 복구한다. 현재 접수 요청의 유효 시각 검사는 유지하므로 만료를 연장하는 경로가 아니다.
2. link 생성 직후 temp unlink 전에 종료된 경우는 정확히 하나의 temp가 같은 dev/inode·내용·권한을 가진 두 번째 링크일 때만 복구한다. 확인된 temp를 제거하고 디렉터리를 fsync한다. 외부/불명확한 hard link를 일반 허용하지 않는다.
3. 실행 전 요청 ID·요청 digest·버전 외에 원장 `accepted_at`, 접수 결과의 `request_file_digest`까지 envelope 전체와 비교한다. 접수 시각만 바꾼 canonical 파일도 materialize 전에 거부한다.

독립 Reviewer가 발견한 교차 입력 프로필 중복, orphan 재시도, envelope 전체 결합 문제를 반영했다. 최종 재검토에서 추가 actionable 결함은 보고되지 않았다.

## 원장 전환

- SB: 기존 requests DDL의 버전 CHECK `(1,2)`를 `(1,2,3)`으로 확장한다. BEGIN IMMEDIATE 안에서 재확인하고 행·FK·명시 index/trigger·view와 나머지 제약을 보존한다. 실패 시 전체 rollback, 원래 PRAGMA 복원. 기존 DB를 새 DDL 문자열로 덮어쓰지 않는다.
- JARVIS: 새 migration066으로 dispatch publication을 remember schema1/3 또는 correction schema2에 한정한다. 기존 행·FK·immutable trigger를 보존한다. 과거 migration 파일은 수정하지 않았다.
- 이번 검사는 임시 DB에서만 전환했다. 운영 journal·DB·release·서비스는 변경하지 않았다. V3 pending이 있는 원장을 V3 미지원 provider로 실행하는 rollback은 지원한다고 주장하지 않는다. 운영 인수에서 release·계약·원장 버전을 함께 검사해야 한다.

## 실제 연결 검증

실제 자비스 backend 빌드와 별도 Python stdio MCP 공급자를 사용했다. owner 서명과 입력은 synthetic fixture이며 DB/vault는 매번 새 임시 경로다. 자비스 작업 중 변경을 포함하지 않고, 커밋 `24de897ebb0244d0fb96ae7310f53d8733ebbcde` + 이 단위의 소유 파일 38개로 최종 격리 빌드했다.

| 시나리오 | 결과 | 증거 |
|---|---|---|
| LF/CRLF/CR/탭·빈 줄·반복·사용자 footnote, sensitive | 실제 CLI candidate intake→승인→V3 접수→proved→outbox settled→control completed, 두 클라이언트 record 4개, 추가 dispatch 0 | 최종 `/var/tmp/sb-jarvis-remember-v3-final-mixed-acceptance.log` |
| 환경변수로 계약 선택, 같은 혼합 본문 | 위 전체 순환, dashboard stored=true, 원문 검토 파일 정리, cleanup/control 오류 없음 | `/var/tmp/sb-jarvis-remember-v3-env-acceptance.log` |
| 일반 LF 64개 sensitive·승인 rollback·삭제 후·컴파일 중 조회, 최신 자비스 기준 | record 64개·두 클라이언트 current·control completed·dashboard stored=true. 삭제 record 0개, 무서명/과거 fence 거부, replay 후 추가 dispatch 0 | `/var/tmp/sb-jarvis-remember-v3-final-acceptance.log` |
| provider 저장·복원 | 혼합 줄바꿈/BOM/NEL/64개 record의 CAS 원문·페이지 바이트·인용 감사, 재시도 후 idle | `tests/test_remember_v3.py` |
| 원장 migration과 실패 복구 | 기존 행/FK/index/trigger/view 보존, ALTER 실패 후 원상복구·재시도. V1/V3 orphan 2분 뒤 재접수 및 접수 파일 변조 거부 | `tests/test_request_schema.py`, `tests/test_remember_v3.py` |
| 구/신 MCP 계약 | 구형 profile은 V3 거부, 새 profile은 수락/replay. 실제 Python 9개 tools/list를 자비스의 엄격한 normalizer로 검사 | `tests/test_mcp_remember_profile.py`, JARVIS transport profile tests |

최종 컴파일 중 완료 확인·두 클라이언트 조회 묶음은 약 **1.508초**였다. 단일 질의의 지연이나 p95로 해석하지 않는다. 전체 runtime 재해 복구·실제 사용자 앱/세션 자동 주입의 증거도 아니다.

## 검사 기록

- SB 전체: **621 passed, 2 skipped, 170.33초**. `/var/tmp/sb-remember-v3-full-tests.log`.
- 전체 검사 후 타입상 tuple 비어 있음 분기를 명시했다. 해당 복구 경로 집중 검사 **27 passed, 3.48초**(`/var/tmp/sb-remember-v3-final-focused.log`)이며 테스트·원문 정책을 바꾸지 않았다. 변경 Python 타입 **0 errors, 0 warnings**, 전체 Ruff 및 Node 구문 검사 통과.
- 자비스 최신 커밋 결합 검사: **245 passed / 1 timeout**, 31개 파일, 85.78초. `/var/tmp/jarvis-remember-v3-final-tests.log`. 기존 만료 경계 검사 하나가 9개 DB를 순차 생성하면서 기본 5초를 넘었다. 같은 시기의 단독 재검도 timeout이었다.
- SB 전체 검사가 끝난 뒤 실패한 **동일 검사·동일 5초 설정**으로 재검: **1 passed (4.955초)**. `/var/tmp/jarvis-remember-v3-final-timeout-after-sb.log`. 최초 결합 실행 전체가 녹색이었다고 보고하지 않는다. I8 후속으로 해당 9개 시나리오의 테스트 단위 분리를 기록한다.
- 자비스 backend build·소유 파일 ESLint 통과. `/var/tmp/jarvis-remember-v3-final-build.log`. 두 작업공간의 기존 frozen schema4 hash `ae2e4b4f41ade29e8781e47e60dad6ddb17ed8cea516b82ccd16454acd5dc3e0` 유지. 새 schema5 hash `78def950055c108a11790ea9d2f6f7729d1084114b09e89fef6a735e04e65d5e`.
- 자비스의 다른 작업이 이후 커밋한 `d6cfdd1`은 제품 소스 변경 없이 migration 호환 검사와 문서를 갱신했다. 새 커밋의 관련 3개 검사 파일을 격리 빌드에 반영해 **15 passed**를 추가 확인했다. `/var/tmp/jarvis-remember-v3-latest-migration-verified.log`. 같은 소유 소스 38개의 해시는 바뀌지 않았다.

## 사용과 재현

새 후보 JSON은 기존 schema1 입력의 나머지 필드를 유지하고 `schema_version: 2`, `body_profile: "plain-text-v1"`을 명시한다. statement는 JSON의 일반 `\n`/`\r\n`/`\t` 표현을 사용한다. 기존 publication을 수정해 새 버전으로 바꾸지 않는다.

자비스 CLI/runtime에서 새 provider 계약을 선택하는 환경변수:

```bash
JARVIS_SECOND_BRAIN_CONTRACT_PROFILE=remember-schema5
```

실제 실행 명령에 이 값을 전달하거나 해당 서비스 환경에 명시한다. 미설정 기본값은 schema4이며 빈/알 수 없는 값은 실패한다. 프로그램에서는 `transport_options.contractProfile: "remember-schema5"`를 명시할 수 있다. 생성 시 선택이 고정되며 재시작 때 자동 downgrade하지 않는다. 64개 완료 reader에는 기존 record-set 예산을 설정한다.

격리 인수 재현:

```bash
TMPDIR=/var/tmp node scripts/jarvis-memory-acceptance.mjs <빌드한-JARVIS> --owner-confirmed --candidate-intake --runtime-cli --record-budget --plain-text-v3 --profile-env --sensitive --dashboard-progress
TMPDIR=/var/tmp node scripts/jarvis-memory-acceptance.mjs <빌드한-JARVIS> --owner-confirmed --candidate-intake --runtime-cli --record-budget --plain-text-v3 --profile-env --record-limit --sensitive --approval-rollback --after-delete --during-compile --dashboard-progress
```

I1-d의 일반 여러 줄 **소스·실제 격리 순환**은 구현했다. 실제 정정 UI, 프로젝트/사용자 범위, 실제 서로 다른 에이전트 앱, context pack·전달 이력, 운영 배포/복원·부하/한국어 검색 평가는 B4~B8에 계속 남는다. 원본 차단 전파 없는 task 자동 수집과 평가 없는 hybrid 활성화는 보류를 유지한다.
