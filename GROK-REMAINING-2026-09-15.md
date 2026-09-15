# 잔여 (착수 금지)

M10 평가에서 natural_question/paraphrase 79건 hit@1 0.0이다. `sb/search_query.py`가 공백 토큰 전부를 문서 부분문자열로 요구해 한국어 조사("unified-db의", "며칠인가요?")가 붙으면 검색이 불가하다. 설계 대안은 조사 제거, n-gram, 하이브리드 임베딩이며, 사용자 판단 전까지 구현하지 않는다.
