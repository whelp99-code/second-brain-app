# 한국어 공통 기억 검색 기준선과 후속 개선

## 판정

**저장된 근거를 정확한 문구·키워드로 회수하는 경로는 동작하지만, 한국어 질문을 그대로 보내는 검색은 개선이 필요하다.** 고정 합성 질문 100개를 실제 CLI와 schema-5 stdio MCP로 각각 실행했다. 정답 문서가 있는 90개 중 상위 5개에 정답을 포함한 질문은 40개였다. 어순 변경·자연어·의역 50개는 모두 빈 결과였다. 이는 20개 문서의 합성 회귀 기준선이며 실제 사용자 전체 검색 정확도를 추정하는 수치는 아니다.

자비스 인계의 “기존 검색의 부족을 측정한 뒤 LightRAG 등의 장점을 선별 흡수한다”는 순서에 대응한다. 추가 기억 서버·그래프 DB·모델 Proxy를 도입하지 않았다. 이번 단위는 평가 자료·도구·분석의 완성이며 검색 제품 코드 수정이나 전체 중앙 기억 인수 완료는 아니다. 동시에 실행 중인 100회 쓰기의 제품 소스는 고정했다.

## 측정 방식

- 입력: `tests/fixtures/korean_search_v1.json`, `korean-synthetic-regression-v1`. 개발·업무를 흉내 낸 가상 주제 10개, 정답 문서 10개와 유사 주제 참고 문서 10개, 명시적으로 작성한 질문 100개다. 실제 개인정보나 사용자 질문 기록을 사용하지 않았다.
- 각 주제마다 정확한 문구 2개, 키워드 2개, 어순 변경 2개, 자연어 질문 2개, 의역 1개, 정답 없는 질문 1개를 입력 전에 고정했다. 정답 page ID와 원문 안의 answer span도 입력에 포함하며 검색 출력에서 정답을 생성하지 않는다.
- 준비는 CAS와 `Vault.write_pages`로 인용된 fixture 문서를 commit하고 관리형 genesis를 봉인한다. ingestion·LLM 요약을 건너뛰는 평가 fixture다. 별도 임시 config·registry·state·request·backup 경로만 사용한다.
- 실제 `python -m sb.cli search ... --json --limit 5` 100회, 실제 MCP 서버 프로세스에 `sb_search` 100회 및 반환된 각 페이지의 `sb_read_page` 42회를 호출했다. hybrid는 꺼져 있다.
- MCP 성공 상태와 응답 형식, 7개 generation binding, 반환 record ID/digest, 출처 identity, 본문과 선택 record, 정답 span을 대조한다. CLI exit 0만으로 성공을 판정하지 않는다. 도구 오류·불완전 응답을 빈 결과로 계산하지 않고 평가를 실패 처리한다.
- 시작/종료의 제품·평가 코드 hash와 봉인 저장소 파일 hash가 일치해야 한다. 전체 native 응답과 순위를 보존하고, 별도 metrics 모듈로 계산한다. 품질 미달은 `measured` 결과로 남기며 `passed`로 승격하지 않는다.

## 결과

CLI와 MCP의 각 질문별 페이지 순위 및 아래 지표는 같았다.

| 유형 | 정답 있는 질문 수 | Hit@1 | Recall@5 | MRR@5 |
|---|---:|---:|---:|---:|
| 정확한 문구 | 20 | 100% | 100% | 1.0000 |
| 키워드 | 20 | 90% | 100% | 0.9500 |
| 어순 변경 | 20 | 0% | 0% | 0.0000 |
| 자연어 질문 | 20 | 0% | 0% | 0.0000 |
| 의역 | 10 | 0% | 0% | 0.0000 |
| 정답 있는 질문 전체 | 90 | 42.22% | 44.44% | 0.4333 |

정답 없는 10개 질문은 모두 빈 결과였다. 이 10개는 등록되지 않은 주제를 묻는 쉬운 음성 사례다. 이미 있는 주제에서 없는 사실을 묻는 어려운 사례, 답변 환각, 오래된 결정 노출, 접근 차단 검증을 대신하지 않는다. 음성 사례를 정답 회수율의 분모에 섞지 않았다.

`복원 연습`과 `삭제 검증` 두 키워드에서는 참고 문서가 1위, 지정한 정답 문서가 2위였다. 주제명이 없는 키워드는 여러 문서가 관련될 수 있으므로 이 두 건만으로 의미적 오답이라고 단정하지 않는다. 반면 어순 변경/자연어 사례에는 주제 식별자가 포함되는데도 정답을 회수하지 못했다.

MCP 선택 레코드/출처 대조 42건과 그중 정답 span 대조 40건을 완료했고 봉인 파일은 변하지 않았다. 한 질문의 반환 페이지 수와 레코드 수는 일반적으로 다를 수 있다. 지표는 실제 상위 5개 반환 슬롯의 순서를 보존하며, 반복된 page ID로 순위를 앞당기거나 recall을 중복 계산하지 않는다.

| 표면 | 호출 수 | p50 | p95 | 최대 |
|---|---:|---:|---:|---:|
| CLI 검색, 프로세스 시작 포함 | 100 | 232.36ms | 257.91ms | 275.69ms |
| MCP 검색, 지속 연결 | 100 | 34.05ms | 43.75ms | 93.25ms |
| MCP 페이지 읽기 | 42 | 34.97ms | 45.69ms | 57.29ms |

한 번 순회한 작은 자료이며 같은 호스트에서 대규모 쓰기 인수가 진행 중이었다. 이 지연을 대용량 운영 SLO나 모델 응답 시간으로 사용하지 않는다.

## 코드에서 확인한 원인

1. `sb/sealed_search.py:iter_sealed_rows`는 3자 이상의 질의 전체를 따옴표로 감싼 FTS `MATCH` 문구로 만든다. `배포 오로라`는 원문 `오로라 배포는 ...`와 연속 문구가 달라 누락된다.
2. `sb/search.py:_lexical`도 같은 문구 처리다. 비관리형 검색만 고치면 봉인 세대와 결과가 달라진다.
3. `sb/mcp.py:sb_search`의 schema 4/5는 후보 페이지를 얻은 뒤 다시 전체 질의가 `record_text`의 연속 부분 문자열인지 검사한다. 하위 검색에 단어/의미 검색만 추가하면 MCP에서 다시 제거될 수 있다.
4. 따라서 후보 검색, 레코드 선택과 근거 반환의 질의 의미를 함께 맞춰야 한다. record ID/digest·generation·삭제 fence·반환 개수 검사를 완화해 맞추는 방식은 제외한다.

## 기존 목록에 추가하는 수정·개선·고도화 항목

| 우선순위 / 기존 범위 | 작업 | 완료 기준과 제한 |
|---|---|---|
| P1 / G2·B7 | 한국어 질의 분석과 문구/단어 검색의 공통 처리 | 봉인·비봉인·MCP가 같은 의미를 사용한다. 정확한 문구 회귀를 유지하고 어순 변경 개선을 고정 자료에서 확인한다. 과도한 OR 확장·임의 조사 제거에 의한 잘못된 주제 회수를 함께 측정한다. |
| P1 / I7·B4 | 질문으로 선택한 근거 record의 일관된 반환 | 후보 page의 관련 없는 record가 결과 슬롯을 소비하지 않게 한다. search/read의 ID·digest·출처·세대를 유지하고 권한/삭제 검사 이후 limit을 적용한다. |
| P1 / G2·B7 | 실제 질문 100–300개와 정답 근거 확보 | 사용자가 지정한 실제 기록으로 평가한다. 주제는 있으나 요청한 사실은 없는 사례, 정정 전/후, 한글 조사·띄어쓰기·짧은 단어·혼합 영문/숫자, 복수 정답과 근거 없는 질문을 포함한다. 개발용과 별도 평가용 사례를 나누고 이 합성 세트를 최종 인수로 대체하지 않는다. |
| P1 / G3·G4·B5 | 회수 결과의 공통 context pack·전달 이력 | 검색 성공과 모델에게 실제 전달/재사용된 결과를 구분한다. 근거/버전/분량, 세션 중복, compaction 뒤 재공급, 실패 결과 취급을 검증한다. 이번 SDK 검색은 자동 주입 증거가 아니다. |
| P2 / R10·B8 | 측정된 미회수에 대한 선택적 hybrid/관계 확장 | 같은 질문으로 기준선 대비 이득·지연·근거/상태/출처 보존을 비교한다. 봉인 세대·삭제/재색인/복원 수명주기까지 결합한 후 활성화를 판단한다. 임베딩/그래프의 선제 일괄 도입은 보류한다. |

일반 agent의 삭제 이후 fence·프로젝트/사용자 범위, 자비스 정정 UI, 업무 결과 원본 차단 전파, 실제 앱별 수집/주입, 운영 전환·독립 복원, 100회 쓰기와 staging 정리의 기존 잔여 범위는 유지한다.

## 재현 및 증거

```bash
TMPDIR=/var/tmp uv run python scripts/korean-search-acceptance.py
TMPDIR=/var/tmp uv run python scripts/korean-search-acceptance.py --dataset /absolute/path/curated.json
TMPDIR=/var/tmp uv run pytest -q tests/test_korean_search_evaluation.py tests/test_search.py tests/test_search_incremental.py tests/test_mcp_generation.py
```

외부 dataset은 같은 schema 1의 documents/cases, 명시적 `dataset_origin`(`synthetic` 또는 `user_curated`)과 provenance를 요구한다. 원문이 없는 질문 목록만으로 정답을 추측하지 않는다. 도구는 입력에 담긴 문서로 격리 fixture를 구성하며 실제 운영 저장소를 자동 조회하지 않는다. 문서당 하나의 말미 인용을 부여하므로 여러 레코드/정정 이력을 가진 운영 문서 평가에는 별도의 corpus 준비가 필요하다.

- 최종 실행: `/var/tmp/sb-korean-search-b2gaayar/evidence.json`, `cli.jsonl`, `mcp.jsonl`, `rankings.jsonl`, `dataset.json`. 로그 `/var/tmp/sb-korean-search-baseline-final.log`. 100개 완료, 프로세스 exit 0, `state=measured`.
- 제품 기준 커밋: `e1e9e28afacccfddbbf0992d81cf8613b94484aa`. 평가 중 제품 변경 없음. 평가 도구 hash는 evidence에 기록한다.
- 고정 자료 SHA-256: `8f82e7f1b431766c2a39e018055daa56dcd9430fd67a572c07065f6c1e9d3c55`.
- 제품 hash: `bb298a4a5bc2baddb3f046c4f20780ffc37248884d51e5c589fe26d2d99aa1a1`. 이 도구는 경로를 `sb/` 디렉터리 기준으로 해시하므로 리포 기준 상대 경로를 쓰는 대규모 인수 도구의 hash와 문자열이 다르다.
- 집중 회귀 **42 passed (3.53초)**. 이 안에 신규 평가 검사 16개가 포함된다. 전체 제품 suite를 이번 문서/평가 도구 추가 때문에 재실행하지 않았다. 직전 제품 커밋의 전체 687 passed/2 skipped는 별도 증거다.
- `ruff check sb tests` 및 평가 스크립트 통과. 변경 스크립트/테스트 basedpyright **0 errors / 0 warnings**. 로그 `/var/tmp/sb-korean-search-tests-final.log`, `sb-korean-search-ruff-final.log`, `sb-korean-search-types-final.log`.
- 초기 도구 실행 `/var/tmp/sb-korean-search-uzdu9ym9`도 같은 회수 지표였다. 최종 표의 지연/증거는 위 최종 실행 한 건을 사용했다.

실제 사용자 질문의 파일/프로젝트 경로는 요청했으며 현재 이 평가에 제공되지 않았다. 합성 질문은 회귀 도구 검증과 결함 재현에만 사용한다.
