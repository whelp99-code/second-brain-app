# d26dd7a 최종 후보 독립 검증 및 Grok 통합 후속 작업

## 판정

**후보 인수 미통과. 메인 기억 저장소 완료 아님.** Grok는 21:31에 제출까지 진행했다. 중단 문제와 별개로, 고정 후보를 독립 검증한 결과 정상 경로 개선을 확인했지만 기존 R4/R5/R6 미충족과 새 회귀가 남아 있다. `외부 입력만 남음`이라는 제출 문구는 현재 증거와 맞지 않는다.

구현은 기존 Grok/OmO, 최종 독립 검증은 Codex가 계속 담당한다. 이 문서는 다음 패치 하나를 주문하는 문서가 아니라 기존 A–F/R1–R7/M1–M14 전체 인수에 대한 통합 판정이다. Codex는 제품 소스를 수정하지 않았다.

## 고정 대상과 직접 통과한 범위

- 제출 HEAD: `d26dd7a799d256352fd6b7e8cc9b0fad6f98cb8a`.
- SB source: `839f718f98a42203617498c9361e2f1ffe7cb30b`; release: `c5b4308e7a4277d526c8d73e7332b0450b17021d`.
- 후보: `/var/tmp/sb-candidate-839f718/releases/c5b4308e7a4277d526c8d73e7332b0450b17021d`.
- wheel SHA-256: `69b9bab0a0dc4b4a86ccde91dd4656c213ec47c2499353353a7f93b3b0548d7f`. SB Python 파일 **182개** 모두 검토 소스·wheel·설치물과 일치했다.
- JARVIS: `87fc787`, `/var/tmp/jarvis-artifact-87fc787/source/dist`. 설치 게이트가 확인한 inventory `b1fed737e5b9ca91ae17326d4eefe06be55e815a1b336c12c1952419d10f5894`, 34,768개 항목으로 제출과 일치한다.
- Codex가 직접 실행한 관련 회귀 **120 passed / 21.71s**, `ruff check --no-cache sb tests` 통과.
- Codex가 직접 실행한 설치 표준·`--work`·유지보수 게이트 **모두 EXIT 0**. 표준/업무 게이트의 실제 HTTPS/CLI/MCP 연결은 통과했으며 신원·시계 등은 fixture이다. native 제품 세션 인수로 확대하지 않는다.
- R1: 무수정 페이지 정상 정정, 미커밋/커밋 수동 편집 및 커밋된 사람 본문 보존을 실제 managed `run_compile` 경로로 확인했다. 후자 세 경우 모두 `pages=0, proposals=1, edit_after=true`.
- R2: 지속 철회 후 scoped 키 거부, cancellation 활성 키 집합에서 제거, 초기화 후 store 유실 거부를 직접 확인했다.
- R3: 구버전 대상 정상 파일·빈 파일·디렉터리·symlink 모두 EXIT 2. 아무 철회 흔적이 없는 격리 초기 상태만 EXIT 0.
- R5: 이전 Unicode/줄바꿈/구문 여섯 사례는 SQL와 record 결과가 모두 일치했다. 검색 순위 회귀는 아래 별도 실패다.
- R4: 예전 3,500바이트 query + 2,400바이트 본문 두 개 사례는 1개 본문을 남겨 실제 요청 6,268/8,000바이트로 통과했다. baseline·만료·untrusted 사례도 실행했다. 실제 세션 연결의 증거는 아니다.

전체 **1,820 passed, 2 skipped / 594.31s**는 Grok가 실행한 원본 로그에서 확인했다. Codex가 전체 회귀를 다시 실행한 수치가 아니다. 이미 재현된 핵심 미충족을 해결하기 전에 같은 전체 회귀를 반복하지 않았다.

## 미충족 — 다음 통합 구현에서 함께 해결할 것

| ID | 우선순위 | 근거와 실제 영향 | 완료 조건 |
|---|---|---|---|
| V1 / R4 | P1 | JARVIS `src/context-model-transport.ts:39`의 `sendAssembledModelRequest` 호출은 현재 테스트에만 있다. `src/personal-context-persistence.ts:53`은 `prepareModelTransport` 반환값을 버리고 기존 snapshot 저장만 수행한다. 새 `persistAssembledContextSnapshot`도 production 호출자가 없다. 따라서 JSON 생성 helper를 추가했지만 실제 세션에서 전달하는 연결은 입증되지 않았다. | 실제 제품 세션 진입점이 기억 선택→요청 생성→transport 호출을 수행하게 연결한다. 그 **진입점**을 격리 transport로 실행하여 query·기억 본문·출처·버전·최종 payload 예산, 새 세션/compaction, 철회·만료·no_data를 검증한다. live 인증 없이 가능한 구현이다. helper에 session 문자열만 바꿔 전달하는 시험으로 대체하지 않는다. |
| V2 / 신규, E·M11 | P1 | `sb/compile.py:165` 뒤에만 `used += 1`이 있어 실패한 LLM 호출을 한도에서 빼 버린다. 동일한 실패 LLM fixture, 문서 4개, cap=1에서 **이전 512a4c7은 calls=1/capped=true**, 후보는 **calls=4/capped=false**였다. 오류가 이어지면 설정한 작업량/호출 제한을 넘는다. | 호출 시도 자체를 한도에 반영하고 실패·성공 혼합, 정상 성공, deny 로컬 경로를 함께 검증한다. 정상 정정과 원장 실패/재시도 계약도 유지한다. |
| V3 / R5, C·M10 | P2 | `sb/search_query.py:80`이 항상 `uses_fts=False`를 반환해 모든 query의 BM25 점수가 0이 됐다. 한 번만 질의를 포함한 긴 문서 30개와 질의에 집중한 짧은 문서 1개의 실제 trigram DB 비교에서 기존 BM25 1위 `z-focused`가 현재 top5에서 빠지고 이름순 문서 5개만 반환됐다. `search.py:663`과 sealed 경로 모두 영향받는다. | Unicode/줄바꿈 일치를 유지하면서 질의 관련도 기반 순위를 복구한다. 제목/경로 이름만 달리해 핵심 문서가 밀리지 않는 긍정·부정·순위 검증, 충분한 corpus의 실제 MCP 지연을 함께 제시한다. 작은 corpus의 단일 바늘 조회 성공은 품질 인수가 아니다. |
| V4 / R2, B·M3 | P2 | 새 `sb/revoked_keys.py:58` 초기화 marker는 symlink 검사를 하지 않는다. 격리 state의 `.initialized`를 state 밖의 존재하지 않는 fixture 파일로 연결하면 `record_revoked_key_ids`가 성공하면서 **state 밖에 파일을 생성**한다. 원래 store/lock은 검사하면서 새 marker에는 같은 규칙이 빠졌다. | 초기화 marker도 안전한 읽기/쓰기·원자성·지속성 계약에 포함한다. dangling/기존 symlink·디렉터리·유실·초기화 중단을 검증하고 문제가 있으면 일관되게 거부한다. 이 재현은 격리 파일 생성이며 실제 무허가 기억 읽기나 운영 파일 변경은 아니다. |
| V5 / R6, E·M13 | P1 인수 공백 | `scripts/isolated-browser-fail-recover.py:49`가 브라우저 열기 전에 아무 작업도 하지 않는 성공 stage를 직접 삽입한다. 이후 실제 `/api/run` 결과는 제출 JSON에서도 `run_body_status=failed`이다. `success_row_present=true`는 그 주입한 행을 찾은 결과다. Chrome은 DOM dump만 하므로 사용자 입력 수정→화면 재실행 성공을 입증하지 못한다. | 브라우저에서 실패를 확인하고 실제 입력/설정을 수정한 뒤 동일 사용자 경로로 재실행해 성공하는 인수를 수행한다. 새 성공 run과 실제 작업 결과를 연계하고 과거 실패 이력도 보존한다. 성공 row 선삽입이나 Python 직접 POST를 브라우저 동작으로 부르지 않는다. |

추가 인수 한계: rollback 검사 helper의 수정은 확인했지만 실제 전환 진입점의 강제 적용 증거는 아직 없다. R6의 sealed 검색 1건은 Grok 제출 증거이며 전체 DR/RPO/RTO·삭제 high-water·범위 거부의 통합 인수와 같지 않다. 성능 스크립트의 `correction`은 새 페이지 추가 후 검색이며 기존 기억의 정정/이전 버전 제외 인수를 대신하지 않는다. 이번 검토는 이 한계들을 새 제품 버그로 단정하지 않는다.

## 원래 요구 범위 유지

| 범위 | 이번 판정 |
|---|---|
| A 원본/편집/정정 | 기존 R1 재현 통과. 최신 전체 수명 자체 검증을 유지한다. |
| B 철회/권한/복원 | 기존 R2 핵심 재현 개선, V4와 전체 복구 계약 남음. |
| C 검색/품질/본문 전달 | 일치성 개선, V1/V3 미충족. |
| D 실제 공유 기억 수명 | 설치 표준/업무 fixture 통과. 실제 신원/제품 세션은 외부 조건과 독립 구현을 구분한다. |
| E 가용성/복구/GUI | 유지보수 통과. V2/V5 및 통합 성능/DR 인수 미충족. |
| F 배포 재료/운영 절차 | 후보 식별과 설치 게이트 개선. 실제 전환·rollback 절차 및 외부 입력의 구체화는 별도. |

| M | 요구 | 인수 상태 |
|---|---|---|
| M1 | 실제 신원/권한 | fixture 통과, 실로그인 미검증 |
| M2 | 실제 업무 공유 계보 | `--work` 설치 게이트 통과, 실제 사용자/다른 제품 세션 미검증 |
| M3 | 철회 전체 수명 | 기존 거부/유실 재현 통과, V4/복원 전 범위 남음 |
| M4 | 검증 결과 원계보 | fixture 게이트 통과, 원업무 실사용자 인수 남음 |
| M5 | native 사본 수명 | 미인수. 실제 사본 접근/처분 조건과 격리 가능 검사를 구분 |
| M6 | 단일작성자·전환복구 | 유지보수 통과, 전환/rollback 강제 연결 인수 남음 |
| M7 | 전체 읽기 범위 | fixture 거부 통과, 전체 표면/오래된 권한 검증 유지 |
| M8 | 제품별 공유연결 | 실제 native 경로 미인수, V1은 독립 구현 가능 |
| M9 | 문맥·compaction | 예전 크기 재현 개선, V1 실제 세션 수명 미충족 |
| M10 | 검색 품질 | 일치성 통과, V3 순위 회귀. user_curated는 별도 외부 입력 |
| M11 | 성능 | 작은 corpus 수치는 제출 증거. V2 호출 한도 회귀, 실제 정정/지연 전체 인수 남음 |
| M12 | DR/RPO/RTO | 유지보수 일부 통과, 전체 복원 인수/수치 미완료 |
| M13 | GUI | V5 미충족 |
| M14 | 관계검색 | 보류 유지. 이번 핵심 인수를 대체하는 신규 확장 금지 |

## 증거와 재현

기계 판독 결과: `CODEX-FINAL-REVIEW-D26DD7A-2026-09-11.json`.
원본 harness/로그: `/var/tmp/codex-final-d26dd7a-uemozlpf`.

```bash
cd /home/jm/orca/projects/second-brain-app
TMPDIR=/var/tmp PYTHONPATH=. .venv/bin/python /var/tmp/codex-final-d26dd7a-uemozlpf/boundary_probe.py /var/tmp/codex-final-d26dd7a-uemozlpf/boundary-reproduced.json
TMPDIR=/var/tmp PYTHONPATH=. .venv/bin/python /var/tmp/codex-final-d26dd7a-uemozlpf/new_boundaries.py /var/tmp/codex-final-d26dd7a-uemozlpf/new-boundaries-reproduced.json
node /var/tmp/codex-final-d26dd7a-uemozlpf/model_request_probe.mjs /var/tmp/codex-final-d26dd7a-uemozlpf/model-request-reproduced.json
TMPDIR=/var/tmp uv run pytest -q tests/test_compiled_marker_recovery.py tests/test_search.py tests/test_search_query.py tests/test_revoked_keys.py tests/test_scoped_read_policy.py tests/test_mcp_scoped.py tests/test_rollback_compat.py tests/test_security.py tests/test_compile.py tests/test_conflict.py
uv run ruff check --no-cache sb tests
```

`cap-ab.json`은 이전 compile 모듈과 후보에 동일한 실패 fixture를 적용한 비교다. 최초 새 harness는 `LLMUnavailable` 생성자 인자를 잘못 전달해 TypeError가 났고, 실제 서명에 맞춰 수정한 뒤 재실행했다. 최초 오류 로그를 별도 보존했으며 제품 결함으로 세지 않았다. 운영 current는 읽기 확인만 했으며 `41f0751aca8906d612961e704bc60dd0855fdabd` 그대로다.

## Grok 실행 지시

이 검토를 기존 통합 인계에 병합해 V1–V5 및 관련 원 요구의 구현·자체 검증을 함께 마친다. 매 수정마다 Codex 승인을 기다리지 않는다. 각 예제만 맞추지 말고 같은 실패 유형의 정상/부정/복구와 변경 영향 범위를 검증한다. 후보가 달라지면 한 조합의 소스·wheel·JARVIS dist·harness·증거로 다시 고정한 후 최종 검증을 요청한다.

제품 준비 목표는 아직 충족되지 않았다. 공식 native goal을 현재 범위로 재개하고 이후 `get_goal`/실제 실행 화면으로 확인한다. 이전 운영 전환 blocked 목표로 돌아가지 않는다. 운영 허가·인증 부족을 V1–V5의 차단 사유로 쓰지 않는다. 외부 입력은 실행 가능한 구현과 자체 검증을 완료한 다음 준비된 대상·절차·복구안으로 한 번에 제시한다. 30분 감시는 그대로 유지한다.
