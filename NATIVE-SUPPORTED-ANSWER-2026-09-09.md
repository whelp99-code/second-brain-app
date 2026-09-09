# 실제 모델의 근거 있는 답변 — 2026-09-09

claude-supported 선택 모드를 추가했다. fixture에 ‘첫 결정’ 원문이 있는지 모델 호출 전에 확인하고, 첫 결정의 정확한 한국어 원문을 묻는다. 프롬프트에는 정답을 직접 넣지 않고 실제 MCP 반환 기록에서 찾도록 했다. 검증기는 supported와 gold 원문 일치를 요구한다. 항상 insufficient_evidence를 반환하거나 두 번째 결정을 답하면 실패한다.

검증: native-answer-validation Node 테스트 4개 및 구문 검사 통과. JARVIS f0394b9 별도 빌드에서 실제 Claude Code 호출 1회, 독립 SDK2개와 HTTPS3회, 기존4경로 전체 exit0. 모델은 supported/value ‘첫 결정’을 반환했고 해당 record ID를 설명에 인용했다. 원문 전체를 동명 JSON에 보존했다. 설명의 citation span 등 모든 세부 주장을 자동 검증하는 것은 아니다.

이전 NATIVE-OMISSION-SCOPE의 부족 근거 사례는 insufficient_evidence/null, 이번 긍정 사례는 supported/정확한 원문이었다. 두 사례를 합쳐 일반 정확도나 안정적 성공률로 보고하지 않는다. 질의는 fixture 회수를 위해 고정되며 모델 자율 검색 전략/실제 사용자 100~300문항/다른 모델 계열/운영 활성화는 여전히 남는다. 운영·계정·실제 업무 데이터 변경 없음.
