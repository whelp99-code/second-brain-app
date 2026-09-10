# 한글 평가셋 초안 — 빠진 유형

[인계 보완](CODEX-REPLY-REVIEW-2026-09-10.md) 5.5, M10. 기존 [합성 100문](KOREAN-SEARCH-BASELINE-2026-09-08.md)은 정확한 문구·키워드·어순·자연어·의역·미등록 주제 음성 사례다. 아래 초안은 **그 세트가 빠뜨린 유형**만 고정한다.

입력: `tests/fixtures/korean_search_hard_v1.json`. `dataset_origin=synthetic`. 실제 사용자 질문·운영 vault 원문이 아니다. M10의 100–300문 실사용 인수를 대체하지 않는다.

| kind | 의도 | 초안 건수 |
|---|---|---:|
| `stale_decision` | 정정 후 현재 페이지, `forbidden`에 이전 결정 | 2 |
| `no_answer` | 주제는 있으나 없는 사실, 그리고 미등록 주제 | 3 |
| `mixed_alnum` | `v2.4.1`, `8MiB`, `policy:2` | 3 |
| `short_token` | 짧은 한글/숫자 구 | 2 |
| `spacing` | 붙여 쓴 주제명 | 2 |
| `multi_gold` | 정답 페이지 2개 | 1 |
| 기존 kind | 자연어/의역/키워드/어순/정확 문구 회귀 슬롯 | 5 |

재현:

```bash
cd /home/jm/orca/projects/second-brain-app
TMPDIR=/var/tmp uv run pytest -q tests/test_korean_search_hard_draft.py tests/test_korean_search_evaluation.py
TMPDIR=/var/tmp uv run python scripts/korean-search-acceptance.py --dataset tests/fixtures/korean_search_hard_v1.json
```

수락 스크립트는 품질 미달을 `measured`로 남기며 `passed`로 승격하지 않는다. 사용자 지정 원문이 오기 전에는 `user_curated` origin을 쓰지 않는다.

이번 CLI/MCP 실행(`state=measured`, 봉인 파일 불변, dataset SHA-256 `8329f1626de6ba72cacc75f62bedf33f8ca708a963dc29cb2d0edc83ed8e1f20`):

| kind | Recall@5 |
|---|---:|
| stale_decision | 2/2, 이전 결정 노출 0 |
| mixed_alnum / short_token / multi_gold / exact / keyword / reordered | 전부 회수 |
| no_answer | 빈 결과 3/3 |
| spacing | 0/2 |
| natural_question / paraphrase | 0/1 각각 |

정답 있는 15문 Recall@5 73.3%. 붙여 쓴 주제명과 자연어/의역은 기존 100문과 같이 미회수다. 증거 `/var/tmp/sb-korean-search-cycjfz2o/evidence.json`. 제품 코드는 바꾸지 않았다.
