# 선택적 벡터 검색의 읽기 부작용과 출처 유실 수정

2026-09-08. R10/B8의 기존 구현 보강이다. 세컨드브레인 기반을 유지하고 LightRAG의 검색·근거 연결 장점을 선별 흡수한다는 인계 방향에 따른다. 외부 코드를 복사하거나 새 검색 서버를 설치하지 않았다.

## 재현한 결함과 수정

| 결함 | 실제 영향 | 수정 |
|---|---|---|
| query_cosine이 knn_out을 DROP/CREATE | 조회가 DB 바이트를 변경하고 동시 조회가 중간 테이블을 공유 | 읽기 전용 SQLite 연결에서 materialized CTE로 KNN 실행 |
| RRF가 SearchHit 네 필드만 재생성 | 종류·색인/지식/승인 상태·canonical·출처·수정 시각 유실 | 선택한 결과를 유지하고 점수만 교체. 동일 결과는 기존 lexical 우선 |
| read_identity가 없는 DB를 먼저 열기 | 메타데이터 조회만으로 빈 vectors.db 생성 | 파일 존재 확인과 SQLite readonly open |
| 모델 차원만 일치 검사 | 모델명·revision이 다른 벡터를 비교 | ModelIdentity 전체 일치 검사 |
| 제어문자 구분자로 원문 분리 | 원문 일부를 새 결과로 오인하고 잘못된 거리를 0으로 처리 | JSON 행으로 원문 보존, 결과 형식·거리 검사. 잘못된 결과는 lexical fallback |
| query vector 검증 부족 | 비어 있거나 차원 불일치·NaN·영벡터를 조회에 사용 | SQL 실행 전 검증과 기존 fallback |

기존 쓰기 경로 rebuild는 계속 쓰기 연결을 사용한다. frozen MCP/schema4와 V2 효과 계약, 기본 hybrid 비활성 설정은 바꾸지 않았다.

## 검증

수정 전 메타데이터·없는 DB·DB 변경·모델 불일치 두 경우·제어문자 원문 **6건 실패**로 재현했다. 설치된 sqlite3와 sqlite-vec를 실제 호출하는 격리 Vault 테스트에서 다음을 검사했다.

- 순차 두 조회와 4개 worker의 8개 동시 조회 이후 DB 전체 바이트 및 디렉터리 항목 불변.
- readonly 연결의 DELETE 거부 및 원본 DB 불변.
- 한국어·인용부호·줄바꿈·행/필드 제어문자 원문 보존.
- 모델/revision 불일치 거부, 잘못된 벡터와 손상된 결과의 lexical fallback.
- 선택한 두 검색 결과의 모든 출처/상태 필드 보존.

실행 명령:

```bash
TMPDIR=/var/tmp uv run pytest -q tests/test_embeddings.py tests/test_hybrid_search.py
TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py
uv run ruff check sb tests
uv run basedpyright sb/hybrid_search.py sb/embeddings.py
git diff --check
```

집중 검사 **32 passed, 1 skipped (2.28초)**, 표준 전체 **566 passed, 2 skipped (138.94초)**. 두 실행은 test_hybrid_search.py의 2개 검사가 중복되므로 합산하지 않는다. 전체 Ruff·diff check 통과, 변경 Python 소스 타입 오류/경고 0. 실제 모델 다운로드/품질 smoke는 실행하지 않았다. 임베딩은 결정적인 테스트 encoder를 사용하므로 실제 sqlite-vec 조회 검증과 모델 검색 품질 평가를 구분한다. 로그: `/var/tmp/sb-hybrid-readonly-focused-tests.log`, `/var/tmp/sb-hybrid-readonly-full-tests.log`.

## 활성화 전에 남은 사항

1. cosine 전용 결과에는 현재 chunks 스키마상 지식 상태·출처 메타데이터가 없다. RRF 보존 수정만으로 없는 출처를 만들 수 없다.
2. 구형 비sealed SearchIndex의 cosine 경로에는 lexical의 kinds/status/날짜/지식 scope 필터가 전달되지 않는다. 프로젝트/사용자 접근 범위도 별도 계약이 필요하다. 운영 활성화 판정은 보류한다.
3. sealed SearchIndex는 여전히 lexical 조기 반환이다. generation manifest에 벡터 포함·무결성·모델 identity를 결합하고 동일 reader pin에서 metadata/검색을 수행해야 한다. mutable rebuild와 metadata 조회 사이의 교체 경쟁까지 이번 수정으로 해결했다고 주장하지 않는다.
4. 정정·삭제·재색인·복원과 벡터 출처의 수명 일치, 한국어 품질/지연/용량 평가가 남는다. lexical 기준선 대비 이득이 확인되지 않으면 비활성 상태를 유지한다.

R10 전체 또는 B8 완료가 아니다. 운영 서비스·활성 세대·배포·push는 변경하지 않았다.

## 자비스 작업 결과 연결의 별도 보류

task completion과 기억 접수를 대조했지만 작업 결과 자동 수집 초안은 반영하지 않았다. task_id 차단 누락 및 수집 뒤 원본 차단이 후보 조회·승인·저장·직접 MCP 회수까지 전파되지 않는 P1 공백 때문이다. 자비스 `73d59df`의 [보류 문서](../Orca-JARVIS/docs/planning/task-memory-source-privacy-hold.md)에 근거와 재개 조건을 기록했다. 기존 제품 classify와 검토/저장 경로는 유지한다. B4의 작업 자동 수집 완료로 계산하지 않는다.


## 후속 — 필터와 현재 본문 결합

격리 `ef3466e`의 [후속 검증](HYBRID-FILTERS-2026-09-08.md)에서 위 잔여 1·2의 legacy 경로를
개선했다. cosine 후보의 현재 메타데이터와 동일 필터를 거리 순위/limit 전에 적용한다.
봉인 세대·mutable rebuild/삭제 수명 및 실제 품질은 계속 남아 있으며 운영 활성화는 보류한다.
