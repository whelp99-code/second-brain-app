# native 모델의 실제 MCP 검색과 답변

기준 제품df0fe91. 기존 native-search-answer-acceptance에 --live 경로를 추가했다. captured 응답은 비교용으로만 사용하고 prompt에 주입하지 않는다. native Claude가 실제 provider stdio 서버의 sb_search를 호출해 응답을 받는다. 별도 허용 MCP/도구 한 개만 노출하고 일반 도구·훅·세션 보존을 끈다. 기억 데이터·키는 격리 fixture 범위다.

최종 /var/tmp/sb-native-search-answer-wJnPAf, exit0. 세 질문 각각 도구 호출 정확히1회, 메서드명·원래 query·limit5, matching tool_use_id의 성공 result1개, 실제 generation ID와 모든 검색 결과가 기존 실측 결과와 동일함을 검사했다. 완료 event1개/success 뒤 최종 JSON 값을 기존 validator로 판정했다.

결과: current와 current-natural은 supported/21일, absent는 insufficient_evidence/null. 모델이 자체 지식만으로 응답한 것을 도구 호출 성공으로 취급하지 않는다. [원문 최종답변·세대·raw event SHA256](NATIVE-LIVE-SEARCH-2026-09-10.json).

Node 구문·기존 엄격 답변 검사기6개·diff 검사 통과. 제품 검색/자비스/운영 변경이 없어 전체 제품 테스트는 반복하지 않았다. 모델 prompt에는 gold값을 넣지 않으며 원래 질문과 근거 사용 지침만 전달한다.

실제 native→MCP→provider 경로이나 remember-schema5 단일 trusted-owner fixture다. JARVIS 호스트 인증 세션 전달이나 scoped 정책 발급 인수와는 다르다. 본문 폐기 표시를 모델이 구분한 것이며 정정/삭제 metadata 수명 검증을 대신하지 않는다. 단일 모델·3질의·명시 지침이며 설명 문장 전체의 독립 의미 검증도 아니다. hybrid 기본 활성화 보류 유지, 실사용gold100–300·운영·다중 모델과 전체 M1–M14 미완료. push 없음.

재현: node scripts/native-search-answer-acceptance.mjs /absolute/measured/synthetic/evaluation --live. 현재 개발 로컬BGE 캐시 경로를 사용하며 원본 평가 세대가 유지돼야 한다.
