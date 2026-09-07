# 대용량 저장·검색·복원 인수와 발견 결함

상태: **격리 구조 부하 인수 통과, 보존 조회 결함 수정, 세대 생성 병목 개선. B7 전체 완료는 아님.** Second Brain을 공통 기억 저장소로 유지하는 기존 방향을 따른다. 별도 검색 서버·LLM·OSS 의존성을 추가하지 않았다.

## 실제 실행 범위

`scripts/capacity-acceptance.py --full`은 새 `/var/tmp/sb-capacity-*` 디렉터리만 생성한다. 기존 운영 vault, DB, 서비스와 세대 포인터를 변경하지 않는다. 실행 결과와 합성 자료·복원본은 재검토할 수 있도록 보존한다.

1. Markdown 원본 5,000개 / 121,790,000 bytes를 생성하고 실제 `python -m sb.cli ingest`로 수집한다. 실제 parser/normalizer/CAS/원장을 통과한 unit은 **100,000개**다. 재수집 뒤 source/unit 행 수가 그대로임을 대조한다.
2. 기존 `Vault.write_pages`로 인용된 wiki 페이지 **10,000개**, conflicted 페이지 **1,000개**를 commit한다. 생성된 페이지는 합성 fixture이며 실제 LLM compile/충돌 추론 결과가 아니다.
3. 기존 `GenerationMutationService`로 전체 자료를 봉인하고 격리 활성 세대로 전환한다. 첫 원본 수집은 legacy batch 경로, 이후 봉인·검색·백업은 managed 경로다.
4. 실제 봉인 인덱스 검색 100회와 **각각 새 프로세스인 CLI 검색 100회**를 수행한다. wiki/active 조건의 결과 수를 확인하고 조회 전후 인덱스 해시가 같음을 검증한다.
5. 전체 CAS 보존 상태, 관리형 백업, 새 경로 복원, 검색 결과·원장 행 수·CAS 감사 결과 및 복구용 요청 journal 존재를 대조한다.

이는 MCP/에이전트 앱의 대용량 인수나 100회 예약 쓰기 순환의 증거가 아니다. 100회 읽기를 100회 pipeline 쓰기로 대체하지 않는다. 실제 일반 LF·두 MCP 클라이언트 인수는 [V3 보고서](REMEMBER-V3-ACCEPTANCE-2026-09-08.md)의 별도 증거다.

## 수정 1 — 봉인된 원장에서 보존 조회가 실패

첫 smoke 실행에서 `retention_report`가 `LedgerCorrupt: attempt to write a readonly database`로 실패했다. 실제 원장은 손상되지 않았으며, 원인인 `governance._ledger_hashes`가 `Ledger` 쓰기 객체를 열어 migration과 WAL 설정을 시도했다. 기존 읽기 전용 테스트는 raw blob의 mtime만 검사하여 이 문제를 놓쳤다.

이제 URI `mode=ro`로 원장을 열어 동일한 읽기 트랜잭션에서 integrity check와 보호 대상 source hash만 조회한다. 100,000개 unit 전체를 Python 객체로 로드하지 않는다. 읽기 실패 시 보호 대상을 빈 집합으로 추정하지 않고 예외를 전달해 GC 삭제를 막는다.

검증: 실제 managed 세대에서 함수와 CLI `retention --json`이 동일한 결과를 반환하며 모든 세대 파일의 목록·권한·mtime·해시가 유지된다. 이전 스키마를 migration하지 않음, 열린 WAL에 commit된 보호 대상 포함, 손상 원장에서는 삭제 거부도 검사했다.

## 개선 2 — 파생 인덱스 행별 durable commit

`_connect_fresh`가 autocommit connection을 반환하는 상태에서 `executemany`로 records/FTS 행을 삽입했다. `synchronous=FULL`이므로 행별 트랜잭션 비용이 누적됐다.

records 및 FTS 각각의 전체 행과 generation binding을 하나의 명시적 트랜잭션으로 commit하도록 수정했다. 오류 시 rollback하고 SQLite 정리 중 예외가 나도 connection을 닫는다. FULL 동기화, 최종 파일 fsync, manifest 대조, 세대 전환 규칙은 유지한다. 이 수정은 기존 봉인 DB를 제자리에서 변경하지 않는다.

실패 검증은 두 DB 각각에서 행 삽입 뒤 generation metadata INSERT를 SQLite authorizer로 거부한다. 삽입 행 수 0, 활성 세대 유지, staging 정리, 같은 요청 재시도·새 세대 활성화를 확인했다.

## 규모별 실측

동일 머신의 연속 실행이며, 실행별 세대 생성/백업/복원은 **각 1회 측정**이다. 전용 성능 장비나 통계적 성능 보장이 아니다. 검색 p95만 100개 표본의 nearest-rank 값이다. 검색 문구는 합성 공통 키워드 하나로, 한국어 검색 품질 평가가 아니다.

| 측정 | 행별 commit 기준선 | 일괄 트랜잭션 적용 |
|---|---:|---:|
| 원본 5,000개 → 100,000 units | 27.04초 | 26.87초 |
| 변경 없는 재수집 | 1.98초 | 0.89초 |
| 10,000 pages + 1,000 conflicts commit | 5.85초 | 5.61초 |
| 관리형 세대 봉인·활성화 | **59.36초** | **23.78초** |
| 내부 검색 p95 / 100회 | 110.91ms | 115.75ms |
| CLI 검색 p95 / 100회 | 345.24ms | 344.24ms |
| 전체 CAS 보존 조회 | 2.66초 | 1.88초 |
| 관리형 백업 생성 | 8.90초 | 8.71초 |
| 복원 및 검색/원장/CAS 대조 | 7.13초 | 7.08초 |

봉인 시간은 이 실행에서 약 **60% 감소**했다. 검색 성능 향상은 관측되지 않았다. 재수집·보존 조회 차이를 모두 이번 트랜잭션 수정 효과로 해석하지 않는다. warm cache 및 실행 부하가 다를 수 있다.

최종 백업: 16,025 files, 비압축 입력 170,463,426 bytes, 압축 20,705,373 bytes. 합성 본문은 반복 문자열이 많으므로 이 압축률로 실사용 용량을 산정하지 않는다. CAS 5,000개 모두 보호됐고 orphan/invalid는 0개다. 백업 checksum은 `91cc93a61a4e0e8ba7e83da180d18e46e1a2ab9979e5565cab6f672bfd6d0257`이다.

## 추가 발견 — unit 제한이 파일 수에 적용됨

`max_new_units_per_run=1`을 설정한 격리 CLI에서 원본 1개가 **unit 20개**로 저장되고 stage가 `ok, attempted=1, written=1, errors=0`이었다. `_prepare_adapter_ingest`의 `attempted`는 파일마다 증가하는 반면, 제한 이름은 unit 수다. 따라서 현재 이 설정을 정규화 unit의 엄격한 상한으로 취급할 수 없다.

증거: `/var/tmp/sb-unit-cap-probe-i1biafhp/evidence.json`. 이 문제는 이번에 수정 완료로 표시하지 않는다. **I5/P1 후속 필수 수정**으로 원본 수 제한과 unit 예산을 분리하고, 한 원본이 잔여 예산보다 클 때 원본·cursor를 보존하는 재개/초과 정책과 CLI 호환성을 함께 검증한다. 이 경계가 해결되기 전 자동 대량 온보딩과 운영 cap 증대는 보류한다. 구조 부하 통과가 해당 상한의 안전성을 보증하지 않는다.

## 검증 및 재현 근거

- 집중 회귀: **29 passed / 15.34초**, 보존/세대/실제 runtime/워킹 스켈레톤. `/var/tmp/sb-capacity-focused.log`.
- 전체 회귀: **627 passed, 2 skipped / 161.44초**. `/var/tmp/sb-capacity-full-tests.log`. 집중 29개는 전체에 포함되므로 합산하지 않는다. Ruff 및 diff check 통과.
- 변경 소스·테스트·도구 타입 검사: **0 errors, 0 warnings**. `/var/tmp/sb-capacity-types-clean.log`.
- 첫 실제 결함 재현: `/var/tmp/sb-capacity-smoke-final.log`. 그보다 앞선 smoke의 list/dict 오류는 검증 스크립트의 CLI 응답 가정 오류이며 수정했다.
- 보존 수정 후 smoke: `/var/tmp/sb-capacity-smoke-fixed.log`.
- 기준선: `/var/tmp/sb-capacity-1gocfv_b/evidence.json`, `/var/tmp/sb-capacity-full.log`. 보존 조회 수정은 포함하고 트랜잭션 개선은 포함하지 않은 상태다.
- 최종: `/var/tmp/sb-capacity-k4djwit1/evidence.json`, `/var/tmp/sb-capacity-full-optimized.log`; 각 디렉터리 `commands.jsonl`에 실제 CLI 인수·종료 코드·출력·시간을 보존했다.
- 최종 환경: Linux x86_64, Python 3.12.13, 논리 CPU 8. 시작 load average 2.77/1.81/1.62. `implementation_commit`은 실행 진입점 `71928b6`이며 당시 미커밋 구현을 포함한다. 실제 검증 소스는 `source_tree_sha256=e13d023ee453c62a26740bf7e01a1ac22cc5efae5c537e555a418b47b16e44f9`, 도구 hash는 `029139a6768d40814cabfd9ae0aee0b0dc86a06a49881bcfa4716f8b67b77cb3`으로 결합했다.

```bash
TMPDIR=/var/tmp uv run python scripts/capacity-acceptance.py         # 작은 smoke
TMPDIR=/var/tmp uv run python scripts/capacity-acceptance.py --full  # 구조 부하
TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py
TMPDIR=/var/tmp uv run ruff check sb tests scripts/capacity-acceptance.py
```

## 남은 원래 완료 조건

B4 실제 앱별 읽기/기록/수집/문맥 공급과 프로젝트·사용자·에이전트 접근 범위, 정정 UI는 유지한다. B5 공통 context pack/실제 전달 receipt/compaction 재공급, B6 운영 검증 백업·독립 runtime 복구·전환/rollback, B7 100회 managed 쓰기·대용량 동시 읽기 지연·원본 증분 성장·한국어 고정 질문 평가, B8 삭제/세대 결합을 보장하는 hybrid 활성화도 미완료다.

23.78초의 세대 생성과 백업의 writer lock 점유는 후속 부하 검증 대상이다. 이번의 복원은 archive를 새 경로로 복원한 인수이며, 자비스까지 포함한 운영 DR 전환이나 backup verification receipt 전체 운영 인수가 아니다. 기존 원본 차단 전파가 없는 task 자동 수집 보류도 유지한다.
