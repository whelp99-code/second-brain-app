# 1.0.2 이후 진행 계획 — 2026-09-17

1.0.2가 CLOSED된 뒤 남은 전 범위를 단계로 나눈 문서다. 단계마다 **선행 조건 / 완료 기준 /
롤백 경로 / 증명 방법**을 적는다. 기계가 읽는 형식은 `docs/shipping-plan.json`에 같은 단계 ID로
들어 있고, 이 문서가 그 근거 원본이다.

## 이 계획이 서 있는 자리

| 항목 | 값 |
|---|---|
| 직전 릴리스 | 1.0.2 CLOSED — 계약 `bd131be5`, 증거 run `run-2026-09-17T06-19-51-869Z-dcc4d63d` |
| 종료 시점 소스 | `84ab2e6` (AC-001 ruff PASS, AC-002 pytest PASS, 블로커 0) |
| 태그 | `v1.0.2` (origin 푸시 완료) |
| 근거 문서 | `SECOND-BRAIN-LIFE-MEMORY-ANALYSIS-2026-09-17.md` 7단계 표, `RESUME-2026-09-17-UNIFIED-DB.md` |

## 증명 등급

단계마다 무엇으로 완료를 증명하는지가 다르다. 하네스는 저장소가 소유한 명령만 계약으로 잠글 수
있으므로, 나머지는 사람이 판단한다. 이 구분을 흐리지 않는다.

| 등급 | 뜻 | 하네스 처리 |
|---|---|---|
| `REPO` | 저장소 명령으로 증명된다 | `acceptanceRefs`에 후보 명령을 걸어 자동 게이트 |
| `OPT-IN` | 저장소 테스트지만 기본 실행에서 제외된다 | 자동 게이트 불가. 실행 기록을 증거로 남긴다 |
| `MANUAL` | 저장소 밖에서만 증명된다 | `acceptanceRefs` 없음. 하네스가 미해결로 표시하는 것이 정상 |

`acceptanceRefs`를 비워 둔 단계는 shipping-harness v1.13.4부터 **차단된다**. 참조가 없는 단계는
ready가 아니라 ungated로 처리되어 `UNGATED_STAGE`로 보고되고, 탐지된 명령을 지목할 때까지
`BLOCKED_BY_UNRESOLVED`로 남는다. 이 계획 파일에서는 S-02부터 S-09까지 여덟 단계가 그렇다.

이는 이 저장소에서 보고한 결함이 고쳐진 결과다. v1.13.3까지는 빈 참조가 "증명할 수 없음"이
아니라 "검사 없음"으로 취급되어 게이트 없이 READY가 됐고, 그 상태로 릴리스에 묶으면 아무것도
증명하지 않은 채 닫힐 수 있었다. 지금은 하네스가 스스로 막는다.

따라서 `MANUAL` 단계를 진행하려면 둘 중 하나를 택해야 한다. 그 단계가 지목할 수 있는 저장소
명령을 만들어 `acceptanceRefs`에 걸거나, 하네스 밖에서 끝낸 일이라면 계획에서 그 단계를 뺀다.
착수 전 단계는 자유롭게 고치고 지울 수 있고, DONE과 ACTIVE 단계만 불변이다.

순서 강제는 `dependsOn`이 맡는다. S-03 이후가 `BLOCKED_BY_DEPENDENCY`인 것은 그 때문이다.

---

## S-01 — 1.0.2를 발행 브랜치에 합치고 master 갱신

`(a)` · 증명 등급 `REPO` · 크기 `PATCH`

- **선행 조건**: 1.0.2 CLOSED 영수증 존재. 현재 브랜치 `claude/harness-truncation-fix-446f99`가
  `origin`에 푸시되어 있을 것.
- **완료 기준**: 발행 브랜치 `codex/shared-memory-completion-20260907`에 1.0.2 라인이 들어가고,
  `master`가 그 결과를 가리킨다. 합류 후에도 `uv run --frozen ruff check .`와
  `uv run --frozen pytest`가 통과한다.
- **롤백**: 합류 전 발행 브랜치 SHA로 되돌린다. 태그 `v1.0.2`는 종료 시점 소스를 가리키므로
  합류 실패와 무관하게 남는다.
- **증명**: 합류 커밋에서 AC-001·AC-002 재실행. 하네스 계약으로 자동 게이트 가능.

## S-02 — 격리 볼트에서 unified-db 수집 증명

`(b)` · 증명 등급 `OPT-IN` · 크기 `PATCH` · **2026-09-17 완료**

- **선행 조건**: 맥 PostgreSQL이 `127.0.0.1:5433`에 닿을 것. jm-acloud의 systemd 사용자 소켓
  `mac-postgres-5433.socket`이 테일넷의 macbook-pro(`100.109.217.124:5433`)로 포워드한다.
  SSH 터널이 아니다. 확인: `systemctl --user status mac-postgres-5433.socket`.
  상세는 `../dev-wiki/projects/unified-db.md`를 본다.
- **완료 기준**: 운영 볼트를 변경하지 않고 격리 볼트에 실수집이 완주하며, 커서가 전진하고
  심박 잡음이 걸러진다.
- **롤백**: 격리 볼트 디렉터리 삭제. 연결은 읽기 전용이라 원본 DB에 남는 변경이 없다.
- **증명**: 아래 실행 기록.

실행 결과(2026-09-17):

| 항목 | 값 |
|---|---|
| DB | PostgreSQL 17.11, `unified` |
| 읽기 전용 확인 | `test_live_scan_yields_orca_jarvis_when_database_reachable` PASS (`SB_LIVE_DB=1`), 세션 설정 `("on","on")` |
| 수집 결과 | run `e7e957de240c4628884b189fc5fa7247` 상태 `ok`, source_item 7,585건 |
| 커서 | `memory.events`·`evidence.items` 모두 `2026-09-17T05:53:14Z`까지 전진 |
| 프로젝트 분포 | global 7,039 / sangfor-os 297 / jarvis-ai 134 / unified-db 64 / toss-finance 42 / orca-jarvis 6 |
| 심박 잡음 | `memory.events` 4,704건 중 `[ClaudeProbe] session` 1,550건 포함 1,704건 스킵 → 3,000건만 수집 |
| 운영 볼트 | `~/.local/share/second-brain/vault` 무변경 확인 |

`unit`은 0이다. **이 기록의 원래 설명은 틀렸다.** LLM 호출을 0으로 막아서가 아니었다. 유닛은
compile이 아니라 ingest에서 만들어지고, 당시 `_materialize`가 unified-db의 행 식별자
`unified-db:<project>:<table>:<row>`에서 마지막 점 뒤를 파일 확장자로 읽어 `.events:evt_...`를
찾다가 파서를 못 만나 빈 목록을 돌려주고 있었다. 즉 내용은 저장됐지만 회상 가능한 유닛이 하나도
만들어지지 않았다. 2026-09-20에 운영에서 같은 증상을 다시 만나 원인을 특정하고 `ea00d18`로
고쳤다. 수집 경로가 증명된 것은 맞지만 검색은 그때 증명되지 않았다.

주의: 격리 볼트를 만들 때 `vault_root`를 심볼릭 링크로 가리키면 관리형 생성 경로가 발동해
`GENERATION_SPLIT_BRAIN`으로 실패한다. 절대 경로를 쓴다.

## S-02B — 1.0.2 라인을 운영에 배포 (relink)

`(b)` · 증명 등급 `REPO` · 크기 `PATCH` · **2026-09-20 완료**

이 단계는 원래 계획에 없었다. S-03을 착수하면서 드러났다. S-03은 `scopeExclude`에 `relink`를
두고 "relink 없이 refresh 1회"를 완료 기준으로 삼는데, 당시 운영 배포본은 `66b4e59`(9/17)로
1.0.2 이전이었고 S-02가 증명한 심박 잡음 필터(`low_value`)가 빠져 있었다. 그 상태로 소스를
추가하면 `[ClaudeProbe] session` 1,704건이 운영 볼트로 들어간다. relink를 S-03 안에 몰래
넣지 않고 선행 단계로 분리한 이유다.

- **선행 조건**: S-01 완료(발행 브랜치·master가 같은 줄). 백업 1회.
- **완료 기준**: `app/current`가 현재 줄을 가리키고, web 200 / `doctor` / `/ready`가 통과한다.
- **롤백**: 이전 `current`가 보존된다. 심볼릭 링크를 되돌리고 유닛을 재기동한다.
- **증명**: 배포 전 `ruff` + `pytest` 통과, 배포 후 `/ready`.

실행 기록(2026-09-20):

| 항목 | 값 |
|---|---|
| 이전 배포본 | `d35b5e5a`(source `66b4e59`, `working_tree_modified: true`) |
| 유실 패치 확인 | 배포본과 HEAD의 차이는 unified-db 2개 파일뿐이고 모두 전진 방향 |
| 배포 | `0697933556…`(source `30e9ebc`), 이후 결함 수정마다 재배포 |
| 검증 | web 200, `doctor` 8 PASS / 1 WARN(`scheduler-assets`, 기존과 동일), `/ready` ready |
| 백업 | `second-brain-20260920T123758+0900.tar.gz` (17,552 파일, 검증 완료) |

`v1.0.2` 태그와 HEAD의 `sb/`는 동일해서 어느 쪽에서 빌드해도 같은 휠이 나온다. `origin/master`가
가리키는 줄을 그대로 쓰는 편이 운영 이력으로 읽기 쉬워 HEAD에서 빌드했다.

### 복구 경로 실측 (2026-09-20)

이전 릴리스로 되돌리고 다시 전진하는 것을 실제로 실행했다. 문서로만 적어 두면 증명이 아니다.

| 방향 | app/current | source_commit | web | /ready | doctor | refresh |
|---|---|---|---|---|---|---|
| 전진 | `fb3f6f8b…` | `5dfceeb` | 200 | ready [] | 8 PASS / 1 WARN | ok |
| **롤백** | `6385f600…` | `00373b5` | 200 | ready [] | 8 PASS / 1 WARN | ok |
| 재전진 | `fb3f6f8b…` | `5dfceeb` | 200 | ready [] | 8 PASS / 1 WARN | ok |

되돌린 빌드에서도 refresh가 완주했다. 즉 이전 릴리스는 보관물이 아니라 실제로 운영 가능한
상태로 남아 있다. 백업은 `second-brain-20260920T145852+0900.tar.gz`(40,302 파일, 격리 복원 검증
완료)이다.

**앱 롤백은 데이터 롤백이 아니다.** 롤백 전후로 볼트 세대 경로가 그대로였다
(`sbgen:v1:11a1de7f…`). `app/current`는 코드만 가리키고 볼트는 별도 생성 관리 아래 있다. 데이터를
되돌려야 하는 상황이라면 세대 롤백이나 백업 복원이 따로 필요하다. 이 둘을 섞어 생각하면
"롤백했는데 데이터가 그대로"라는 사고가 난다.

`doctor`의 `scheduler-assets` WARN은 배포본마다 항상 뜬다. 이번 변경과 무관한 기존 상태다.

### 1.0.4 배포 (2026-09-20)

S-02B의 마지막 남은 항목은 버전 표기였다. 그것을 고치자 수용 명령이 스스로 완결되지 않는다는
사실이 함께 드러났다. `uv run --frozen pytest`는 엑스트라를 설치하지 않는데 `sqlite-vec`가
`embeddings` 엑스트라에 있어서, 새 워크트리에서는 `tests/test_embeddings.py` 20건이
`EmbeddingUnavailable`로 실패한다. 메인 체크아웃이 통과한 것은 `.venv`에 남아 있던 옛
`uv sync --extra embeddings` 잔재 덕분이었다. 즉 1.0.3의 AC-002 PASS는 저장소가 아니라 그 기계의
숨은 상태에 기대고 있었다.

`sqlite-vec`만 기본 의존성으로 올렸다. 엑스트라를 통째로 올리면 torch·transformers·triton이 모든
배포에 따라 들어오는데, 그 20건은 `sqlite_vec`만 있으면 통과한다(엑스트라 제거 상태에서 30 passed,
1 skipped). `sentence-transformers`는 엑스트라에 남겼다.

| 항목 | 값 |
|---|---|
| 이전 배포본 | `fb3f6f8b…`(source `5dfceeb`) |
| 커밋 | `92ea7f5`(1.0.4 + sqlite-vec 기본 의존성), `9cd9953`(macOS 번들 버전) |
| 배포 | `8bd05730…`(source `9cd9953`, `working_tree_modified: false`) |
| 백업 | `second-brain-20260920T212342+0900.tar.gz` (40,374 파일, 격리 복원 검증 완료) |
| 검증 | web `/ready` 200 ready(reasons []), `doctor` 8 PASS / 1 WARN(`scheduler-assets`), `sb status` ok |
| refresh | `jm-second-brain-refresh.service` success (41.9s) |
| 하네스 | 1.0.4 SHIPPABLE, AC-001·AC-002 PASS, 블로커 0, 범위 위반 0 |

버전을 올리면 `clients/macos/SecondBrainMac/Resources/Info.plist`의
`CFBundleShortVersionString`도 함께 올려야 한다. `tests/test_macos_client_contract.py`가 그것을
`pyproject.toml`의 버전과 같아야 한다고 못박고 있어서, 한쪽만 고치면 AC-002가 깨진다. 첫 verify가
그 한 건으로 FAIL했다.

수용 명령 실측은 두 번 모두 예산 안쪽이다. 397.7초·395.9초 / 600초 = 66%.

롤백 경로는 위 "복구 경로 실측"에서 같은 기계·같은 절차로 양방향 증명했고, 직전 릴리스
`fb3f6f8b…`는 `app/releases/` 아래 그대로 보존되어 있다.

## S-03 — 프로바이더 설정에 unified-db 소스 추가

`(c)` · 증명 등급 `MANUAL` · 크기 `PATCH` · **2026-09-20 완료**

- **선행 조건**: S-02 완료. 사용자 승인. 설정 파일은 저장소 밖(`~/.config/second-brain/`)이라
  하네스 범위에 들어가지 않는다.
- **완료 기준**: unified-db 소스가 프로바이더 설정에 들어가고, relink 없이 refresh 1회로
  적재가 확인된다. "9월 16일에 무엇을 했나"가 검색으로 응답한다(재가동 계획 1단계 완료 기준).
- **롤백**: 설정에서 소스 항목을 제거하고 refresh 1회. 추가된 유닛은 세대 롤백으로 되돌린다.
- **증명**: refresh 전후 유닛 수와 검색 응답. 사람이 확인한다. 저장소 명령으로는 증명되지 않는다.

실행 기록(2026-09-20) — **완료**:

| 항목 | 값 |
|---|---|
| 설정 | `jarvis-provider.toml`·`config.toml` 양쪽에 `{id=unified-db, adapter=unified-db, llm_policy=deny, sensitive=mask}` |
| 백업 | 변경 전 `config.toml.bak-unified-db-*` 2개, 볼트 백업 4회 |
| 적재 | source_item 0 → 2,543건, unit 55 → 2,155건 |
| refresh | `jm-second-brain-refresh.service` 성공, `/ready` ready(reasons []) |
| 검색 | `sb search "unified-db"` 가 unified-db 유래 wiki 페이지를 반환 |

`llm_policy`는 `deny`로 넣었다. 이 문서의 "외부 LLM 사용 시 신규 소스 기본값은 deny"와
`SECOND-BRAIN-LIFE-MEMORY-ANALYSIS-2026-09-17.md`의 "payload 민감도 미판정"을 따른 것이다.
`deny`는 하드 실패가 아니라 `_compile_without_llm` 경로로 처리되어 유닛과 페이지가 생기고 검색에
걸린다. LLM 호출 상한도 쓰지 않는다. 반대로 `local-only`는 외부 모델(Grok) 환경에서
`SecurityPolicyError`를 던져 refresh를 깨뜨리므로 쓸 수 없다. 민감도를 판정한 뒤 `allow`로
올리는 것은 한 줄 변경이고 되돌릴 수 있다.

완료 기준의 "어제 한 일을 검색으로 답할 수 있다"도 충족했다. `memory.events` 커서가
`2026-09-20`까지 전진한 뒤 `sb search "2026-09-19"`가 그날 14:30의 작업 기록을 반환하고,
`"shipping harness"`·`"unified-db 수집"` 질의도 최근 작업 메모를 찾는다. 상한은 올리지 않고
회차를 반복해서 소진시켰다.

적재 회차를 돌릴 때 주의할 점이 하나 있다. ingest 단계의 `ok`는 **소스가 소진됐다는 뜻이 아니다.**
어댑터가 내부적으로 페이지를 나누므로 `ok`는 "이번 회차가 상한에 걸리지 않았다"는 뜻일 뿐이고,
`capped`가 아니게 된 뒤에도 커서는 계속 전진한다. 실제 종료 조건은 source_item 건수가 더 이상
늘지 않는 것이다. 처음에 `ok`를 종료로 읽어 3,119건에서 멈췄는데 `evidence.items` 커서는 아직
2026-06-13에 있었다.

이 단계에서 제품 결함 넷이 드러났고 모두 고쳐 배포했다. `ea00d18`(점 든 행 식별자를 확장자로
오독), `7d37584`(미기재 모델을 로컬로 취급), `056cbec`(거부 소스가 brief 단계를 죽임),
`c30e377`(본문의 날짜 모양 문자열이 brief를 깨뜨림), `00373b5`(인용 근거가 없을 때 실패).
앞의 둘은 S-02가 "unit = 0"을 잘못 설명하고 지나간 것과 같은 뿌리다.

## S-04 — AI 세션 직접 수집 (claude → codex → omo)

`(d)` 재가동 2단계 · 증명 등급 `MANUAL` · 크기 `MILESTONE`

- **선행 조건**: S-03 완료.
- **완료 기준**: 세 계열 세션이 수집되어 세션 세부까지 회상 가능하다.
- **롤백**: 소스별로 끄고 해당 세대 롤백.
- **증명**: 특정 세션에 대한 질의 응답. 사람이 확인한다.

## S-05 — 카톡 일일 요약 전송 복구

`(d)` 재가동 3단계 · 증명 등급 `MANUAL` · 크기 `PATCH`

- **선행 조건**: S-03 완료. 민감 소스 처리 수단은 이미 구현되어 있다.
- **완료 기준**: 하루 1회 자동 적재가 돈다.
- **롤백**: 자동화 비활성화. 적재분은 세대 롤백.
- **증명**: 연속 2일 적재 기록.

## S-06 — 메일 결론 일일 핸드오프 (본문 미전송)

`(d)` 재가동 4단계 · 증명 등급 `MANUAL` · 크기 `PATCH`

- **선행 조건**: S-03 완료.
- **완료 기준**: "이번 주 메일 결정"에 응답한다. 본문은 전송하지 않는다.
- **롤백**: 핸드오프 중단, 적재분 세대 롤백.
- **증명**: 본문 미전송 확인과 질의 응답. 본문 유출 여부는 반드시 사람이 본다.

## S-07 — 2026-09-11 중단 자동화 선별 복구

`(d)` 재가동 5단계 · 증명 등급 `MANUAL` · 크기 `PATCH`

- **선행 조건**: S-03 완료.
- **완료 기준**: 복구 목록과 제외 목록이 기록된다. 무엇을 되살리지 않기로 했는지가 남아야 한다.
- **롤백**: 복구한 자동화를 다시 끈다.
- **증명**: 두 목록 문서. 사람이 검토한다.

## S-08 — JARVIS closeout 자동 적재 + ORCA 관측

`(d)` 재가동 6단계 · 증명 등급 `MANUAL` · 크기 `MILESTONE`

- **선행 조건**: S-04 완료.
- **완료 기준**: 작업 종료가 승인 후 자동으로 기억된다.
- **롤백**: 자동 적재 비활성화, 세대 롤백.
- **증명**: 승인 → 적재 경로 기록. 무단 적재가 0건이어야 한다.

## S-09 — 전화·통화, 위키 재연결, 한국어 검색 개선

`(d)` 재가동 7단계 · 증명 등급 `MANUAL` · 크기 `MILESTONE` · 조건부

- **선행 조건**: 실기기 접근(phone-history). 항목별로 조건이 다르다.
- **완료 기준**: 항목별로 따로 정한다. 한 덩어리로 닫지 않는다.
- **롤백**: 항목별 비활성화.
- **증명**: 항목별. 착수 전에 이 단계를 셋으로 쪼개는 것을 권한다.

---

## 하네스 게이트 골격

계획 모드로 돌린 하네스가 돌려준 릴리스 트레인이다. 위 단계 분해와 별개로, 각 버전이 무엇을
증명해야 닫히는지에 대한 골격으로 병기한다.

| 버전 | 단계 | 가치 게이트 | 롤백 등급 |
|---|---|---|---|
| v1.0.3 | DELIVER_CORE_VALUE | `CORE_FLOW_USABLE`(사용자 흐름) + `CURRENT_SCOPE_PROVEN`(인수) | 직전 종료 릴리스 |
| v1.1.0 | OPERATE_AND_RECOVER | `OPERABLE_INTERNAL_RESULT`(운영 스모크) + `ROLLBACK_PROVEN` | 백업 복구 또는 직전 릴리스 |
| v1.1.1 | FIELD_HARDEN | `FIELD_PILOT_PASS` + `FALSE_COMPLETION_ZERO` | 직전 종료 릴리스 |

공통 종료 게이트: `VALUE_GATE_PASS`, `REQUIRED_ACCEPTANCE_PASS`, `BLOCKER_ZERO`, `UNKNOWN_ZERO`,
`SCOPE_DRIFT_ZERO`, `CURRENT_GIT_EVIDENCE_FRESH`, `ROLLBACK_PROVEN`.

1.0.2에서 이 골격이 실제로 작동했다. `CORE_FLOW_USABLE`이 미증명이라 `LOCAL_REVERSIBLE`
정책에서도 자동 CLOSE가 `VALUE_GATE_UNPROVEN`으로 거부되고 사람에게 넘어왔다. 게이트는 막지만
통과 경로를 주지는 않는다. 그래서 이 문서가 필요하다.

### 기계 계획에서 뺀 단계 (2026-09-20)

`docs/shipping-plan.json` revision 8에서 S-02와 S-03을 뺐다. 둘 다 끝났지만 저장소 커밋으로는
증명할 수 없는 일이다. S-02는 격리 볼트에서 돌린 실수집이고 S-03은 저장소 밖 프로바이더 설정
변경이라, 어느 쪽도 인수 명령이 붙지 않아 `UNGATED_STAGE`로 영원히 `BLOCKED_BY_UNRESOLVED`에
머문다. 그 상태로 두면 뒤따르는 S-04 이후가 결코 풀리지 않는 선행 조건에 묶이고, 진행률은
닫을 수 없는 분모를 세게 된다. 하네스가 실제로 닫을 수 있는 단계만 기계 계획에 남기고, 두
단계의 실행 기록은 이 문서 위쪽 절에 그대로 둔다. S-04~S-07의 선행 조건은 S-02B로 옮겼다.

### 계획 단계 범위는 경로 범위를 바꾸지 못한다 (2026-09-20 실측)

하네스가 `uv.lock` 하나를 계약 경로 범위 밖으로 표시했다(`scopeWarning.outside`). 버전 동기화가
`pyproject.toml`·`uv.lock`·`Info.plist` 를 함께 고쳤는데, 첫째는 경로 범위에 이름이 있고 셋째는
`clients/**` 에 덮이지만 잠금 파일에는 아무것도 닿지 않았기 때문이다.

계획 단계의 `scopeInclude` 에 `uv.lock` 을 이름으로 적고 rescan 했으나 `scope.paths.include` 는
그대로였다. 원인은 하네스 소스에 있다 — `applyPlanStageToContract` 는 `scope` 를 펼치면서
`include` 와 `exclude` 만 교체하고 `paths` 는 손대지 않는다. **계획 파일로는 경로 범위를 절대
바꿀 수 없다.** 산문에서 경로를 뽑는 기능은 제안 시점의 목표 문장에만 적용되고, 그것도 확장자가
있거나 끝에 슬래시가 붙은 형태만 인식한다.

`uv.lock` 은 이미 기준선 커밋에 들어가 있어 1.0.4 진행 중에 다시 바뀌지 않으므로 이번 릴리스를
막지는 않는다. 단계 범위에 남긴 문장은 사람이 읽는 범위 기술로서 유효하되, 경로 범위를 넓히는
효과는 없다. 잠금 파일을 실제로 경로 범위에 넣어야 할 때는 계약의 `scope.paths.include` 를
직접 고치는 수밖에 없다.

## 알려진 한계

- 하네스의 단계 계획은 릴리스 진행 절차 템플릿(PLAN-001~004)이지 작업 분해가 아니다. 분해는
  이 문서가 담당한다.
- S-02는 실제로 끝났지만 하네스 진행도에서는 DONE이 아니다. 진행도는 CLOSED 영수증의
  `planStageId`에서만 나오고 우회로는 없다. 그것이 진행도를 믿을 수 있게 하는 근거이므로 옳다.
  기록하려면 그 단계를 릴리스에 묶어 정식으로 닫거나, 하네스 밖에서 한 일로 보고 계획에서 뺀다.
- 릴리스 번호는 계획 파일이 아니라 저장소의 버전 근거에서 나온다. 계획 단계는 무엇을 닫을지만
  정하고 몇 번으로 닫을지는 정하지 않는다. `planPath`는 `docs/shipping-plan.json`이 기본값이며
  다른 경로는 `ERR_PLAN_PATH_FIXED`로 거부된다. 계획 파일이 둘이면 진실이 둘이 되기 때문이다.
- 증명 수단 없는 항목이 목표에 섞이면 이제 하네스가 `UNPROVEN_OBJECTIVES`와 `EXTERNAL_REFERENCE`로
  알린다. 둘 다 경고일 뿐 차단하지 않으므로, 판단은 여전히 승인하는 사람의 몫이다.
- S-09는 단일 단계로 두기에 너무 넓다. 착수 시 분할한다.
