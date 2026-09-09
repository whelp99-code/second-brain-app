# 운영 스냅샷 재컴파일 규모 — 2026-09-09

실제 운영 config의 vault symlink를 한 번 resolve해 고정한 generation을 읽었다. SQLite mode=ro/query_only와 읽기 트랜잭션으로 원장 상태를 읽고, 실제 materialize/protect_units/page grouping 규칙으로 새 derivation key를 계산했다. 모델 호출·compile·DB 변경·운영 활성화는 하지 않았다. 원장 파일 SHA256 전후 동일, 읽은 CAS 내용은 저장된 digest와 대조했다.

## 결과

- SourceItem 321개, 컴파일 대상 페이지 그룹 18개.
- 기존 key는 18개 모두 done, 새 페이지별 key는 모두 missing: **첫 적용 시 18개 페이지 재컴파일 대상**.
- 설정된 회당 max_llm_calls_compile=120. 모두 성공하고 추가 작업이 없다는 조건에서 1회 run 안에 처리 가능한 규모다. 토큰 수/금액/실제 모델 성공률을 추정한 것은 아니다.
- CAS 없는 3개 행은 모두 skip digest 규칙에 맞는 기록이었다. 원인을 설명할 수 없는 CAS 누락은 이 스냅샷에서 0개.
- 원장 상태: compile done 35, conflict done 49, brief done 7 / failed 5. 브리핑 실패 원인 해결은 별도 남아 있다.

## 재현과 검사

`PYTHONPATH=. uv run python deploy/estimate-compile-key-upgrade.py CONFIG_PATH` (리포 루트에서 실행).

임시 원장의 같은 내용 두 출처를 사용한 회귀 검사에서 첫 estimate는 페이지 2개/기존 key 1개로 계산됐고, 실제 새 compile 후 estimate는 새 done 2개/추가 호출 0개였다. estimator 실행 전후 원장 SHA도 동일했다. `1 passed in 3.40s`, Ruff 통과.

분석은 고정 generation의 관측 결과다. 이후 새 수집이나 설정 변경이 있으면 다시 산정해야 한다. 파일 SHA는 원장 주파일 기준이며 전역 프로세스 정지 또는 전체 서비스 snapshot 증명이 아니다. 운영 전환/실제 계정 연결/구버전 배제/복구 gate를 대체하지 않는다.
