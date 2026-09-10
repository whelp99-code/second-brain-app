# W6 한글 붙여쓰기 검색

Hangul 토큰은 FTS MATCH 대신 공백을 제거한 `instr`로 찾는다. 특정 질문·정답 페이지를 코드에 넣지 않았다.

하드셋 CLI `state=measured` (봉인 불변):

| kind | Recall@5 |
|---|---:|
| spacing | **2/2** (이전 0) |
| stale_decision / mixed_alnum / no_answer | 유지 |
| natural_question / paraphrase | 여전히 0 |

정답 있는 15문 Recall@5 **86.7%** (이전 73.3%). `tests/test_search.py` 포함 22 passed. 사용자 지정 100–300문 아님. JARVIS 문맥 조립기는 이 리포에서 안 고쳤다.
