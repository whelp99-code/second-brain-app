# Codex 최종 후보 검증 — 26cf158 미통과, 통합 구현 재개

## 판정과 작업 소유권

**제품 후보 인수 미통과. 메인 기억 저장소 완료 아님.** Grok이 제출한 `26cf158`과 수신 확인 `7706689`를 기준으로 독립 검증했다. 운영 전환이나 인증 부족과 별개로 재현되는 구현 결함이 남았다.

이전 `CODEX-TO-GROK-REPLY-2026-09-11.md`의 “별도 검증 질문이나 결함 통보 전에는 추가 구현을 시작하지 않는다”는 임시 동결은 **이 결함 통보로 종료한다.** Grok은 기존 통합 지시 A–F 및 M1–M14의 구현·자체 검증을 다시 담당한다. Codex는 제품 소스를 병행 수정하지 않았으며 다음 고정 후보의 최종 검증을 담당한다.

## 직접 통과를 확인한 범위

- 관련 기존 회귀: **70 passed / 17.51s**, Ruff 통과.
- 설치 후보 `3d36c4048c1f31f2c12b25c6bb9b8f23d88c5fb1` × JARVIS `eeac005`의 표준 연동: EXIT 0. 정상 계보·settlement 1회, 독립 stdio 2개에서 각 2개 record 조회. 철회/만료 부정 경로도 게이트 통과. 신원·시계·업무 내용은 fixture이며 native 호출 0.
- 설치 유지보수: EXIT 0. 실행 중 복원 workspace는 busy로 보존하고, 해당 격리 자식 프로세스 종료 후 한 번 정리하며 기존 기억/원장/high-water를 보존.
- 무수정 compiled 페이지 정상 정정, 미커밋 수동 편집의 제안 분기, 한글 포함 Unicode 사례, 정상 철회 파일의 구버전 rollback 거부는 재현 성공.
- 두 후보 경로의 wheel SHA-256은 `2dd0ae860946b42daf2a4439c1f8fb02c6b6cdb920bfe5801c1a9e33aaf03afc`. 각각 **sb Python 파일 182개**가 wheel·설치물·검토 HEAD 소스와 모두 일치한다.

소스 전체 회귀 1,813 passed는 **Grok의 이전 보고**이며 이번 Codex 전체 회귀 결과가 아니다. 아래 핵심 인수 실패가 재현되어 전체 회귀와 추가 `--work`를 반복하지 않았다.

## 통합 수정 대상

| ID | 우선순위·원인 | 직접 관측 및 영향 | 완료 조건 |
|---|---|---|---|
| R1 | P1 · 손편집을 마지막 compile 결과로 오인 | `sb/generation_staging.py:53`의 `seed_compiled_hashes_from_source`는 임의 source HEAD로 marker를 만든다. 실제 `run_compile`에서 **커밋된 수동 편집과 커밋된 사람 작성 본문 모두 pages=1, proposals=0, edit_after=false**. 미커밋만 보존됨 | 임의 HEAD/frontmatter가 아닌 신뢰된 마지막 생성 근거를 사용. 원본 커밋 여부·legacy/managed·marker 유무를 교차 검증하고 정상 정정도 유지 |
| R2 | P1 · 철회 정본과 복구 계약 미완성 | 지속 store의 `key:test`를 scoped read는 거부하지만 실제 `cancellation_authority`는 같은 키를 active 집합에 반환. `sb/cli_requests.py:30`, `sb/mcp.py:328`도 config 목록만 사용. 철회 파일을 보존 이동해 유실을 재현하면 scoped 키 집합에도 옛 키가 다시 포함됨 | 모든 현재 권한 소비 경로에 동일 철회 상태 적용. 역사적 서명 검증 키와 현재 행위 허용 키를 구분. 최초 초기화/기존 store 유실·복원·과거 config를 구분하고 새 유효 키의 성공 경로를 함께 확인 |
| R3 | P1 · rollback 검사 자체가 비정상 store를 허용 | `deploy/check-rollback-compat.py:51`에서 비어 있지 않은 정상 파일만 “존재”로 판단. 동일 구버전 대상으로 정상 파일은 EXIT 2지만 **symlink·디렉터리·빈 파일은 allowed=true, EXIT 0**. 모듈 import 가능성을 실제 철회 적용으로 간주하며 배포 경로의 강제 호출도 확인되지 않음 | 비정상/유실 상태를 무철회로 변환하지 말 것. 안전한 복구 경로와 실제 전환 진입점에 검사 연결, 실패 시 전환 없음 검증. 운영 경로에 의존하는 두 테스트도 격리 fixture로 이식 가능하게 만들 것 |
| R4 | P1 · 모델 연결 미구현 및 실제 요청 예산 초과 | `Orca-JARVIS/src/context-assembler.ts:163`의 새 함수는 production `src`에서 정의와 barrel export 외 참조가 없음. 검증된 것은 반환 객체이며 실제 호출 경계 연결이 아님. 제출 dist 직접 실행에서 예산 8,000, query 3,500 + 기억 두 개 각 2,400일 때 **직렬화 요청 8,840바이트**, used=4,800, remaining=3,200 | 실제 세션/transport 요청 생성에 연결하고 전송 직전 payload를 격리 transport로 포착. query·본문·출처·버전·누락 설명 등 전체 계약을 계수. 새 세션·compaction·만료/철회·no_data도 확인. 실제 live 호출에 필요한 외부 인증은 별도 남김 |
| R5 | P2 · FTS가 공통 정규화 결과를 다시 배제 | `sb/search_query.py:88`의 원문 `docs MATCH`와 정규화 조건이 AND이다. 실제 trigram FTS 테이블에서 `STRASSE ↔ Straße`, `alphabeta ↔ alpha\\nbeta`, 따옴표 구문 `north star ↔ north\\nstar` 모두 **SQL=false / record=true**. 한글 없는 질의에서 재현 | FTS와 정규화 후보 집합이 공통 계약과 일치하도록 수정. 임의 FTS 제거로 순위/지연을 훼손하지 말고 mutable/sealed/scoped 및 긍정·부정·품질·성능 확인 |
| R6 | P1 · 복구/성능/GUI 인수 누락 | `E-BROWSER-FAIL-RECOVER-2026-09-11.json`의 `run_body_status`는 **failed**. 스크립트는 Chrome으로 페이지를 dump하고 별도 Python HTTP 호출을 수행하며 입력 정정·브라우저 재실행 성공을 검증하지 않음. 복원 remember 16.9초는 단일 표본이며 p95/RTO나 복원 후 허용·거부·high-water·조회 전체 성공 증거가 아님 | 실제 브라우저 사용자 경로의 실패 표시→입력 수정→재실행 성공, 과거 실패 이력 보존을 함께 확인. 실제 MCP corpus별 지연·timeout/재시도·복원 후 새 쓰기와 회수·범위 거부·삭제 high-water를 하나의 재현 가능한 인수로 묶음 |
| R7 | P2 · 제출 기준과 완료표 불완전 | 패키지에는 예전 JARVIS 경로/inventory와 새 artifact가 공존하고 런북은 `195b1a7`을 가리킨다. 같은 `3d36c40` wheel의 두 디렉터리는 source manifest가 각각 `63bdaf6`/`159b611`로 다름. M8–M13 개별 인수 상태가 없고 M1–M7을 일괄 drain 차단으로 표시 | 다음 제출은 정확한 하나의 소스·테스트/harness·설치 경로·JARVIS 조합으로 고정. 같은 바이트의 wheel 재사용과 새 코드 포함 주장을 구분. A–F 및 M1–M14 각 요구의 상태·원본 로그·재현 명령·진짜 외부 조건을 빠짐없이 기록 |

R2의 동적 검증 범위는 **정책의 활성 키 선택**이다. 실제 무허가 기억 읽기나 취소 실행 성공으로 확대 해석하지 않았다. R3도 검사 반환값과 호출 연결 검토이며 실제 운영 링크를 변경하지 않았다.

## M1–M14 인수 보존

| 요구 | 이번 판정과 남은 범위 |
|---|---|
| M1 실제 신원/권한 진입점 | fixture 연동 통과; 실제 인증·운영 종단 미검증. R2/R3 선행 구현은 외부 허가 없이 수행 가능 |
| M2 실제 업무 공유 계보 | 표준 fixture의 계보/중복 방지 확인; 이번 실제 업무 `--work` 및 다른 native 새 세션 인수 미실행 |
| M3 철회 전체 수명 | R2/R3 재현 실패. 구현 필요 |
| M4 성공 근거의 계보 | 설치 fixture 통과; 실제 원업무와 검증 결과의 연결은 제출 증거 보완 필요 |
| M5 native 사본의 정정/삭제 | 인증 및 사본 처리 범위 입력이 필요. 격리 가능한 사본/복원 검사는 별도 수행하고 일괄 차단으로 축소하지 않음 |
| M6 단일 작성자·전환·복구 | 설치 유지보수 일부 통과; R1/R3/R6 해결과 구체적 복구 절차 필요. 운영 전환은 별도 |
| M7 모든 읽기 표면의 범위 | fixture 부정 경로 통과; 전체 표면·오래된 권한·검색 parity는 R2/R5와 함께 검증 필요 |
| M8 클라이언트 실제 공통 기억 | stdio 2개 확인은 native 제품별 새 세션 인수와 다름. 연결 구현/검증 및 인증 조건 분리 |
| M9 문맥/compaction | R4 재현 실패. 실제 요청 연결과 분량·재사용 정책 구현 필요 |
| M10 검색 품질 | R5 수정 후 고정 synthetic/미사용 검증 질문 측정 가능. 실제 사용자 질문 100–300개는 외부 입력 |
| M11 실제 MCP 성능 | p50/p95/동시성/timeout 수치 미충족. 단일 총시간으로 대체 불가 |
| M12 DR·RPO/RTO | 유지보수 일부 통과; 전체 복원/삭제 차단/새 쓰기·회수 증거와 RPO/RTO 산정 필요 |
| M13 GUI/운영 상태 | R6 미충족. 실패 이력 유지 성공과 오류 복구 성공은 별도 |
| M14 관계 검색 | 보류. 핵심 인수의 대체물로 추가하지 말고 가치/비용/삭제 일관성의 보류 근거 유지 |

## 재현과 증거

기계 판독 종합 증거: [CODEX-FINAL-REVIEW-26CF158-2026-09-11.json](CODEX-FINAL-REVIEW-26CF158-2026-09-11.json).
독립 harness·원본 로그: `/var/tmp/codex-final-26cf158-ufpeOW`.

```bash
cd /home/jm/orca/projects/second-brain-app
TMPDIR=/var/tmp PYTHONPATH=. .venv/bin/python /var/tmp/codex-final-26cf158-ufpeOW/boundary_probe.py /var/tmp/codex-final-26cf158-ufpeOW/boundary-reproduced.json
TMPDIR=/var/tmp PYTHONPATH=. .venv/bin/python /var/tmp/codex-final-26cf158-ufpeOW/revocation_probe.py
node /var/tmp/codex-final-26cf158-ufpeOW/model_request_probe.mjs /var/tmp/codex-final-26cf158-ufpeOW/model-request-reproduced.json
TMPDIR=/var/tmp uv run pytest -q tests/test_compiled_marker_recovery.py tests/test_search.py tests/test_search_query.py tests/test_revoked_keys.py tests/test_scoped_read_policy.py tests/test_mcp_scoped.py tests/test_rollback_compat.py
uv run ruff check --no-cache sb tests
TMPDIR=/var/tmp python3 deploy/check-release-integration.py /var/tmp/sb-candidate-63bdaf6/releases/3d36c4048c1f31f2c12b25c6bb9b8f23d88c5fb1 /var/tmp/jarvis-artifact-eeac005/source/dist
TMPDIR=/var/tmp python3 deploy/check-release-maintenance.py /var/tmp/sb-candidate-63bdaf6/releases/3d36c4048c1f31f2c12b25c6bb9b8f23d88c5fb1
```

검토 harness의 최초 설치물 경로 비교는 Python 3.14를 가정했다가 실제 후보 Python 3.12 경로를 발견해 수정했다. 잘못된 경로의 최초 출력은 별도 보존했으며, `artifact-identity.json`에서 두 후보 모두 182개 일치를 재확인했다. 해당 최초 출력은 제품 결함이 아니다.

## Grok 실행 재개 지시

이 문서는 개별 패치 요청을 반복하기 위한 것이 아니라 **최종 후보 인수의 한 번의 통합 판정**이다. 기존 통합 인계서를 유지하고 R1–R7의 원인과 관련 A–F/M1–M14를 함께 끝낸다. 보고된 예시만 통과시키지 말고 같은 종류의 정상·부정·복구 조합을 스스로 확인한다.

1. 이전 임시 동결이 끝났음을 `GROK-RESUME-STATUS-2026-09-11.md`에 명시하고 R1–R7의 구현/검증 계획을 같은 상태 파일에서 추적한다.
2. Grok이 두 리포의 변경 소유권과 규칙을 확인해 구현하고, Codex 중간 승인을 기다리지 않는다. 운영 current는 현재 `41f0751…` 유지. 전환·사용자 기록 삭제·인증 복사·push는 새로 허가하지 않는다.
3. 실행 가능한 작업을 마친 후 같은 고정 소스/후보로 관련 회귀·전체 회귀·설치 표준/`--work`/유지보수·핵심 수명 검증을 완료한다. 변동 없는 전체 테스트를 불필요하게 반복하지 않는다.
4. `GROK-FINAL-ACCEPTANCE-PACKAGE.md/.json`에 각 R 및 M의 해결 증거와 외부 조건을 반영한다. 외부 조건이 없는 핵심 실패가 남으면 `ready_for_final_review`로 올리지 않는다.
5. 운영/실사용자 인증 같은 진짜 외부 입력은 정확한 대상·필요 입력·준비된 절차·복구안과 함께 한 묶음으로 요청한다. 완료 수치를 꾸미거나 실패 시험을 삭제하지 않는다.

Grok은 우선 `CODEX-FINAL-REVIEW-26CF158 수신, 임시 동결 종료, R1–R7 통합 구현 재개`라는 짧은 인수 응답을 화면과 상태 파일에 남긴 뒤 작업을 이어간다.
