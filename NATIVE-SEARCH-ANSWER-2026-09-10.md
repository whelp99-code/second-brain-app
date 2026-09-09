# 실제 native 모델의 검색 근거 사용 진단

제품3eeb409에서 자비스 memory-reference-context.ts를 읽기 전용 대조했다. 참고 문맥에는 reference_only/untrusted/authority:none과 실행 성공·승인 근거로 취급하지 말라는 지침, freshness·출처 binding·예산 검사가 이미 있다. 검색 후보 자체가 질문의 정답이라는 보장은 포함하지 않는다. 같은 정책의 중복 구현 대신 실제 답변 동작을 분리 검증했다.

새 scripts/native-search-answer-acceptance.mjs는 measured 합성 평가의 dataset/mcp.jsonl SHA256을 검증하고, 질문별 실제 MCP 검색 응답을 그대로 native Claude에 제공한다. 각 질문은 별도 호출이며 session persistence·도구·MCP·훅을 끈다. prompt에는 요구 사실이 없으면 보류하고 폐기 결정을 현재 사실로 사용하지 말라는 지침을 넣는다. gold answer_span은 prompt에 제공하지 않고 결과 검증에만 사용한다. 기존 엄격 JSON 응답 검사기를 재사용하며 실패 원문도 저장한다.

실제3호출 결과 모두 status/value 검사 통과:
- 키워드 현재 보관 기간: supported, 21일.
- 자연어 현재 보관 기간: supported, 21일.
- 무근거 연락처: insufficient_evidence, null.

원시 응답은 [구조화 결과](NATIVE-SEARCH-ANSWER-2026-09-10.json)에 보존했다. 실행 /var/tmp/sb-native-search-answer-3mnKr9, exit0. 기존 답변 검사기6개 테스트 및 Node 구문·diff 통과. 제품 검색/자비스 코드/운영 설정은 변경하지 않았다.

이 검사는 실제 모델의 답변이지만 저장된 응답의 재생이며 실시간 JARVIS 인증 세션 전달이 아니다. 단일 모델·명시적 지침·작은 합성3질의로 전체 정답 품질을 보장하지 않는다. 판정기는 status와 gold값/보류 여부, 형식, 비어 있지 않은 설명을 검사하며 설명의 모든 문장을 독립 의미 검증하지 않는다. 기본 hybrid 활성화 보류는 유지한다.

다음은 이 구분이 실제 자비스 세션 전달 경로에서 유지되는지와 다른 모델/질문에서 재현되는지 확인하는 것이다. 사용자 기반gold100–300·실제업무·운영 전환과 전체 M1–M14 미완료. push 없음.
