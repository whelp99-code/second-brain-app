# 하이브리드 검색의 필터·출처·정정 일치 수정

상태: **격리 작업공간 구현·전체 회귀·실제 CLI 검증 완료. 원 작업공간 병합 및 운영 활성화 대기.**
제품 커밋 `ef3466e`, 작업공간 `/var/tmp/sb-korean-query-work`, 브랜치
`codex/korean-query-consistency-20260908`.

## 재현한 문제

[이전 읽기 전용 수정](HYBRID-READONLY-2026-09-08.md) 뒤에도 R10/B8에 남아 있던 cosine 전용
결과의 메타데이터·필터 결손을 실제 sqlite-vec로 재현했다. 최초 **4개 실패**:

| 재현 | 수정 전 영향 | 수정 후 |
|---|---|---|
| wiki/active/날짜 제한 + limit=1 | 상위의 부적격 daily 또는 candidate가 반환되고 유효 후보는 못 받음 | 메타데이터 필터를 거리 정렬·LIMIT 전에 적용하여 허용한 wiki 1건 회수 |
| candidate 범위의 의미 후보 | ACTIVE 자료가 섞이고 지식/승인 상태가 빈 문자열 | candidate만 반환, 원 상태·출처 보존 |
| Git에 본문 정정 후 벡터 미재생성 | 이전 벡터 본문 반환 | 현재 검색 행의 page/section/전체 본문과 일치하는 chunk만 허용 |
| 존재하지 않는 문자열 상태 필터 | lexical은 0건이지만 cosine은 결과 반환 | 같은 필터 의미 적용, SQL처럼 생긴 값도 문자열로 처리하여 0건 |

이 필터는 지식 상태·종류·날짜의 검색 조건이다. 사용자/프로젝트 접근 권한의 구현이나
민감도 분류를 대신하지 않는다.

## 구현

- `sb/search_filters.py`: 기존 lexical 메타데이터 조건을 공유한다. active는 ACTIVE+APPROVED,
  candidate는 CANDIDATE, reference/all은 기존 참조 범위를 유지한다. lexical 인자 의미는 같다.
- `sb/search.py`: 동일 SearchFilters를 hybrid 경로로 전달한다. 봉인 세대의 기존 lexical 경로는 유지한다.
- `sb/filtered_vectors.py`: vector DB와 검색 DB를 read-only로 열고 한 읽기 transaction 안에서 조회한다.
  현재 docs의 page/section/text와 정확히 일치한 vector chunk에 먼저 필터를 적용하고,
  그 후보의 cosine 거리→순위→limit 순으로 처리한다. 결과에는 현재 kind/status/knowledge_status/
  approval_status/canonical/source_ref/updated를 결합한다.
- `sb/hybrid_search.py`: 필터된 후보를 기존 RRF에 공급한다. 모델/의존성/메타데이터 또는 결과 오류는
  기존 lexical fallback을 유지한다. 인코딩 이후 실제 조회 snapshot의 모델 identity도 확인한다.
- 잘못된 JSON/행 형식, 유한하지 않거나 물리적 cosine 범위를 벗어난 거리 등을 정상 점수로 바꾸지 않는다.

거리 계산은 sqlite-vec의 scalar distance 기능을 사용한다.
[공식 KNN 문서](https://alexgarcia.xyz/sqlite-vec/features/knn.html)와
[공식 API 참조](https://alexgarcia.xyz/sqlite-vec/api-reference.html)를 확인하고 설치된
**sqlite-vec 0.1.9**에서 실행했다. 제품/OSS 코드를 복사하거나 그래프 DB·추가 검색 서비스를 설치하지 않았다.
이 방식의 대용량 처리 성능은 별도 측정 대상이다.

## 검증

- 수정 전 네 실패: `/var/tmp/sb-hybrid-filter-before-real.log`.
- 집중 **63 passed / 1 skipped, 6.34초**: `/var/tmp/sb-hybrid-filter-focused-complete.log`.
- 표준 전체 **775 passed / 2 skipped, 219.87초**: `/var/tmp/sb-hybrid-filter-full.log`.
  두 실행은 중복 테스트가 있으므로 합산하지 않는다. live embedding model smoke는 건너뛰었다.
- 새 native 회귀 11개: 필터 전 limit, 메타데이터, candidate scope, 정정, 인자 인용,
  인코딩 중 model revision 변경, 4 worker/8회 동시 읽기, 잘못된 거리 5종.
  vector/search 두 DB의 전체 바이트와 .sb 디렉터리 항목이 조회 전후 같았다.
- 전체 Ruff 및 도구 lint, diff check 통과. 새 모듈·hybrid·테스트·도구 타입 검사는
  **0 errors / 0 warnings**. 전체 search.py까지 포함하면 기존 위치의 경고 6개가 있으며 오류는 0개다.
  신규 경고를 기존 경고로 숨기지 않았다. `/var/tmp/sb-hybrid-filter-new-types.log`.

처음 격리 작업공간의 기본 uv 환경에는 optional sqlite-vec가 없어 4개가 모두 skip됐다.
그 실행은 재현/검증 통과로 계산하지 않았다. 기존 앱의 설치된 Python 환경과 명시적 PYTHONPATH로
격리 소스를 불러온 것을 확인한 뒤 실패 재현과 위 검증을 수행했다. 실제 모델은 내려받지 않았다.

## 실제 CLI 인수

`/var/tmp/sb-korean-query-work/scripts/hybrid-filter-acceptance.py`가 실제 CLI parser/명령 경로를
별도 Python process에서 실행한다. encoder만 명시적 결정적 fixture로 주입했고 DB·Git·CLI·
검색은 실제 구현이다. CLI의 일반 설정 파일에서 hybrid=false/true를 전환했다.

| 시나리오 | 실제 CLI 결과 |
|---|---|
| hybrid=false, 검색어 없는 허용 page | 0건 |
| hybrid=true, 같은 필터·limit=1 | wiki/z-allowed 1건, 출처·CANONICAL/VERIFIED 보존 |
| candidate scope | wiki/a-hidden 1건, REFERENCE/UNVERIFIED 보존 |
| SQL 모양의 상태 문자열 | 0건 |
| 본문 정정 뒤 오래된 vector | 0건, 정정 전 본문 미반환 |

다섯 CLI 모두 exit 0, stderr 비어 있음. vector DB SHA-256은 전후 일치했다.
최종 artifact `/var/tmp/sb-hybrid-filter-nc0pfzn0`, 로그 `/var/tmp/sb-hybrid-filter-cli-final.log`.
이 인수는 의미 모델 품질이나 실제 한국어 질문 정답률을 주장하지 않는다.

재현 환경:

```bash
cd /var/tmp/sb-korean-query-work
PYTHONPATH=$PWD TMPDIR=/var/tmp /home/jm/orca/projects/second-brain-app/.venv/bin/python -m pytest -q --ignore=tests/test_embeddings.py
PYTHONPATH=$PWD TMPDIR=/var/tmp /home/jm/orca/projects/second-brain-app/.venv/bin/python scripts/hybrid-filter-acceptance.py
```

## 보류와 다음 완료 조건

1. **운영 hybrid 활성화 보류:** 이번은 legacy 비봉인 SearchIndex 경로다. 봉인 generation manifest,
   벡터 파일 무결성·모델 identity·삭제/복원 수명을 같은 reader pin에 결합해야 한다.
2. **mutable rebuild 수명:** 동일 SQLite 읽기 snapshot과 본문 대조가 Git/registry/vector 전체의
   원자적 세대 전환을 제공하는 것은 아니다. 직접 저수준 query_cosine은 원시 chunk API이며
   새로 필터된 SearchIndex와 같은 계약으로 확대하지 않는다.
3. **품질·용량:** 실제 encoder/tokenizer·한국어 질문·지연/용량 평가가 필요하다. 이번 fixture는
   필터와 저장소 동작만 검증한다. 알려진 자연어/의역 결손의 해결로 계산하지 않는다.
4. **B5 자동 전달 보류 유지:** 기존 자비스 projection은 target/source identity 기반이고 새 조회
   surface는 HMAC membership 기반이다. 키·record version·session/compaction·차단 전파를 확인하는
   연결 없이 같은 의미의 전달 이력으로 취급하지 않는다. 승인 TaskSpec 밖의 자동 기억 추가도 하지 않는다.
5. **병합 순서:** 대규모 100회 쓰기 종료 후 d174276 → 47fa507 → 9323a6d → ef3466e를 원 작업공간에
   병합하고 통합 인수한다. 이번 전체 회귀는 위 네 변경이 있는 격리 소스에 대한 증거다.

원 작업공간 sb/는 계속 SHA-256
`387d6c7f5b9c1b9db98c31d53c224181757d4eddba5aaf8cfba0641176cb53c4`로 고정한다.
이번 관측은 기존 full write 실행의 80/100회 진행이며 최종 성공 판정이 아니다.
B4 실제 업무 수집·앱/범위, B5 전달 수명, B6 운영/DR, B7 최종 쓰기/질문 및 B8 잔여 전체를 유지한다.
