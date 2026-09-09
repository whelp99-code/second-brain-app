# 공통 기억 검색: 요청 단위 무결성 검증

인계 방향의 공통 기억 인터페이스를 기존 구현에서 개선했다. 별도 기억 서버나 OSS 의존성은 추가하지 않았다.

## 결함과 수정

기존 `search_scoped_records`는 후보 페이지마다 `classified_page`의 전체 세대 검증을 앞뒤로 수행했다. 300페이지 단일 검색에서 약 12.4초가 걸렸으며, 이전 100페이지 profile에서 199후보에 세대 검증398회가 관측됐다.

`sb/memory_access.py`에 요청 수명의 `classified_pages` context를 추가했다. 시작과 종료에 전체 세대 무결성/동일성을 검사하고, 종료 후 reader 사용을 거부한다. 각 후보의 committed Git blob, 본문 digest에 결합된 page access, 모든 원본의 classification digest와 owner/project/revision 검사는 유지한다. `sb/scoped_search.py`는 종료 검증이 성공한 뒤에만 모아 둔 결과를 반환한다. 단일 페이지 API도 같은 context를 사용해 이전의 전후 검증을 유지한다. 호출자는 기존 generation lease를 유지해야 한다.

접근 검사 전 후보 수를 자르거나 전역 접근 결과 cache를 도입하지 않았다. MCP/자비스 공개 계약과 스키마 변경은 없다.

## 실제 합성 세대 검색 측정

| 페이지 수 | 질의 | 이전 초 | 수정 후 초 | 결과 |
|---|---|---:|---:|---|
| 100 | ScaleProbe | 1.8596 | 0.4559 | 허용1 |
| 100 | forbidden | 1.8442 | 0.4519 | 0 |
| 300 | ScaleProbe | 12.3971 | 1.4076 | 허용1 |
| 300 | forbidden | 12.4867 | 1.4143 | 0 |

300페이지 약8.8배, 100페이지 약4.1배 단축이다. 동일 스크립트와 페이지 구성의 독립 순차 1회 실행이며 p50/p95 또는 운영 성능 보장은 아니다. 300페이지 프로세스 peak RSS는 기존51,068→수정51,352 KiB이며 세대 생성 비용도 포함한다. MCP/native/동시 갱신은 이 측정에 포함되지 않는다. 원시 결과는 [JSON](SCOPED-SEARCH-BATCH-2026-09-10.json)에 보존했다.

명령: `TMPDIR=/var/tmp PYTHONPATH=. uv run python scripts/scoped-search-scale.py --pages 100` 및 `--pages 300`.

## 검증 및 한계

관련 memory access/scoped search/MCP generation/MCP scoped/generation integrity 45개가 20.79초에 통과했다. 새 검사는 context 이후 재사용, 원장 변조, 검색 접근 검사 직후 manifest 제거 시 결과 반환 차단을 확인한다. 첫 검색 변조 검사에서는 fixture가 Alpha가 아닌 Cited 본문을 생성해 해당 경로가 실행되지 않았다. 실제 생성 본문 질의로 바로잡아 통과했으며 제품 조건은 완화하지 않았다. Ruff 전체 및 두 변경 모듈 타입 검사0오류0경고.

전체 회귀 `TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py`: **1,712 passed, 2 skipped / 463.72초, exit0**. 선택 embeddings 모듈은 저장소 기본 검사 지침에 따라 제외했다. 검사 도중 제품/테스트 파일 변경은 없었으며 [전체 출력](SCOPED-SEARCH-BATCH-FULL-2026-09-10.txt)을 보존했다. M11의 대규모·동시 갱신·운영 지연 인수와 M1–M14 전체 목표는 남는다. 최신 설치 후보는 아직 이 제품 변경을 포함하지 않는다.
