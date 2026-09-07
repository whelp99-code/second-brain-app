# 수집 파일 수와 정규화 unit 예산

상태: 소스 구현·격리 CLI 및 구조 부하 검증 완료. 전체 회귀는 아래 최종 기록을 따른다. 기존 I5의 `max_new_units_per_run=1`에서 실제 unit 20개 저장 결함을 수정한다.

- `caps.max_new_units_per_run`은 한 수집 단계에서 새로 원장에 추가되는 고유 unit 수를 제한한다. 이미 존재하는 unit과 같은 batch 내 중복 unit은 다시 차감하지 않는다.
- `caps.max_source_items_per_run`은 새 원본 버전 처리 시도 수를 제한한다. 파서 결과 0건, 격리/차단 및 실패 원본도 비용에 포함한다. 이 키가 없는 이전 설정에서는 종전 `max_new_units_per_run` 값을 파일 수 상한으로도 계승하여 기존 파일 처리량을 조용히 확대하지 않는다.
- `sb ingest --limit N` 및 `run_ingest(limit=N)`은 기존 원본 시도 수 의미를 유지하고 unit 예산을 우회하지 않는다.
- 단일 원본은 CAS + 전체 unit + source_item 등록 후에만 완료된다. 일부 unit만 등록하는 새 중간 상태/DB를 추가하지 않는다.
- 단일 원본에 필요한 신규 unit이 전체 예산을 넘으면 해당 원본을 보존하고 `INGEST_UNIT_BUDGET_EXCEEDED`로 실행 실패를 보고한다. 제한을 명시적으로 조정하거나 원본을 나눈 뒤 재시도한다. 다른 원본의 성공 기록은 보존한다.
- 원본이 전체 예산에는 맞지만 이번 단계의 잔여 예산보다 크면 원본을 넘겨 두고 `capped`로 보고한다. 이후 더 작은 원본은 잔여 예산 내에서 처리할 수 있다. 다음 실행에서는 전체 예산으로 다시 시도한다.
- deferred/oversized 원본이 있는 adapter의 cursor는 앞으로 이동하지 않는다. inbox 완료 이동은 CAS/원장에 확정된 정확한 원본 버전만 대상으로 한다. 원장 commit 실패 시 unit 소비와 원본 완료 처리도 확정하지 않는다.
- 상한은 원장 신규 행 수이다. parser/normalizer가 한 원본을 처리하는 동안 사용하는 임시 메모리/CPU 상한이라고 주장하지 않는다. 기존 파일 bytes/scan 제한도 유지한다.
- 운영 caps는 변경하지 않는다. 구조 부하 harness만 자신이 만드는 격리 config에 목표 unit 수와 원본 수를 명시한다.

## 구현과 소스 인수

`sb/config.py`는 기존 파일 수 상한을 계승하는 별도 source cap을 제공한다. `sb/pipeline.py`는 실제 신규 unit ID를 adapter 간 공유 예산에 합산한다. source/CAS/전체 unit 확정 전의 단위는 차감하지 않고, 중복 unit도 다시 차감하지 않는다. `StageReport`/`RunOutcome`의 내부 failure 필드로 예산 초과를 `run_stage.detail`, `failed` 및 CLI 종료 코드 1에 연결했다. MCP frozen 응답에 새 필드를 삽입하지 않는다.

원본 일부를 저장하고 완료로 표시하는 방식은 보류했다. 부분 unit을 보호하는 별도 원장 상태 없이 그렇게 처리하면 원본 완료·CAS 보호·컴파일 입력이 불일치할 수 있다. 이번에는 원본 전체를 보존하고 정확히 완료 가능한 경우에만 원장과 cursor, inbox 완료 처리를 확정한다.

### 실제 관리형 CLI 시나리오

`TMPDIR=/var/tmp uv run python scripts/ingest-budget-acceptance.py`

새 격리 provider에서 실제 `remember`, `ingest`, `retention` CLI를 호출했다. 원문은 합성 자료이며 LLM compile은 호출하지 않는다.

| 단계 | unit 예산 | 결과 |
|---|---:|---|
| 20-unit 원본과 1-unit 원본 접수 후 `ingest --limit 100` | 1 | 종료 1과 `INGEST_UNIT_BUDGET_EXCEEDED`; 큰 원본은 inbox에 유지, 작은 원본만 확정. 1 source / 1 unit |
| 예산을 명시적으로 늘려 재시도 | 20 | 큰 원본 전체 확정. 2 source / 21 units |
| 신규 원본 12/12/8 units 접수 | 20 | 첫 12 + 마지막 8 처리, 중간 12는 보존. `capped`, 4 source / 41 units |
| 같은 예산으로 다음 실행 | 20 | 보존된 12 처리. `ok`, 5 source / 53 units |
| 예산을 1로 낮추고 변경 없는 재실행 | 1 | `ok`, 증가 0. 기존 완료 기록을 재차감하지 않음 |
| CAS/보존 대조 | — | 원본 5개 bytes 일치, protected 5 / orphan 0 / invalid 0 |

증거는 `/var/tmp/sb-ingest-budget-acceptance-z6hdjbv9/evidence.json`과 `commands.json`, `/var/tmp/sb-ingest-budget-acceptance-final.log`에 보존했다. commands에는 각 시점의 격리 설정, CLI 인수·종료 코드·출력도 기록했다. 초기 harness는 이미 봉인된 inbox에 fixture를 직접 쓰려다가 권한 거부됐다. 제품의 쓰기 보호가 올바르게 작동한 것으로, 최종 harness는 모든 접수를 실제 `remember` 명령으로 전환했다.

### 회귀 검사

집중 회귀 **65 passed / 12.02초**: 기존 CLI/runtime 54개와 신규 예산 11개다. `/var/tmp/sb-ingest-budget-regression.log`.

- legacy와 managed 경로의 초과 원본 보존·실패 detail·명시적 예산 변경 후 복구
- adapter 간 잔여 예산 적용과 deferred cursor 보존
- 같은 batch 및 기존 원장의 중복 unit 차감 방지
- CAS 실패 후 다른 원본의 예산 사용과 재시도
- 원장 unit 삽입 실패 시 source/cursor transaction rollback·inbox 보존
- unit을 만들지 않는 파일과 격리 원본도 source cap에 포함
- 기존 source cap 계승, 별도 cap 지정, 음수 예산 거부

타입 검사 오류 0, 경고 1이다. 경고는 수정 전부터 있던 `sb/pipeline.py`의 `KnowledgeRegistry.put` 반환값 미사용이며 이번 변경이 추가한 경고는 없다. Ruff/diff 검증 및 전체 회귀와 구조 부하 결과는 아래 최종 기록을 따른다.

## 운영 적용과 남은 경계

이 소스 수정으로 이전 코드가 unit 제한을 우회하던 결함은 수정됐다. 운영 배포/설정 변경은 수행하지 않았으므로 기존 서비스가 이 제한을 적용한다고 주장하지 않는다. 자동 대량 온보딩·운영 cap 증대는 실제 원본 크기·메모리·처리 시간과 배포 인수 후 판단한다.

전체 B4~B8은 유지한다. 실제 앱별 공통 기억·접근 범위·정정 UI, context pack·전달 이력, 운영 전환/DR, 100회 managed 쓰기 및 한국어 검색 품질·hybrid 검증은 이번 unit 예산 수정으로 완료되지 않는다.

## 최종 구조 부하 재검증

명시적 원본 5,000 / 신규 unit 100,000 예산을 넣은 `scripts/capacity-acceptance.py --full`이 통과했다. 실제 수집 5,000 sources / 100,000 units, 변경 없는 재수집 증가 0, page 10,000/conflict 1,000 fixture 봉인, 100회 CLI 읽기, 백업·새 경로 복원 및 CAS 대조가 모두 성공했다.

수집 26.99초, 세대 봉인 18.57초, CLI 검색 p95 336.16ms, 백업 8.75초, 복원/대조 7.12초였다. 이 수치는 해당 단일 실행의 관측이며 이전 대비 추가 성능 개선을 주장하지 않는다. corpus 및 의미 품질·100회 쓰기 인수 한계는 [구조 부하 보고서](CAPACITY-ACCEPTANCE-2026-09-08.md)와 같다.

증거: `/var/tmp/sb-capacity-8bg41jwy/evidence.json`, `commands.jsonl`, `/var/tmp/sb-ingest-budget-capacity.log`. 이 harness의 unit budget은 오직 새 격리 config에만 반영됐다.

## 최종 회귀 결과

전체 **638 passed, 2 skipped / 165.25초** (`/var/tmp/sb-ingest-budget-full-tests.log`). 집중 65개는 이 전체 검사에 포함되어 중복 합산하지 않는다. Ruff 전체 `sb tests` 및 두 검증 도구, `git diff --check` 통과. 타입 오류 0, 앞서 명시한 기존 경고 1이며 추가 경고는 없다.

대용량 인수 당시와 최종 `sb/**/*.py` 소스 트리 해시가 `08f60e4b6d609a7a9e78395e3532d525abb9f25a72004f3d59ed47e388ea89e3`으로 일치한다. 두 인수 도구도 실행 당시 해시와 일치함을 확인했다. evidence의 `commit=b1c53e6`은 미커밋 수정 검증을 시작한 진입점이며 이번 구현 전체를 이미 포함한 commit이라고 해석하지 않는다.
