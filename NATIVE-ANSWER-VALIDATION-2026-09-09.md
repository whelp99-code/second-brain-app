# Native 답변 검증 누락 수정 — 2026-09-09

기존 abstention 검증은 응답 어디서든 첫 JSON 코드 블록을 추출했다. 정상 null JSON 뒤에 ‘The server IP is 192.0.2.1.’을 붙여도 파서는 바깥 문장을 버려 status/null 검사에 통과했다. 실제 저장된 Claude 응답에 합성 문장을 덧붙여 이 동작을 재현했다.

scripts/native-answer-validation.mjs로 검증을 분리했다. 전체 응답이 JSON 한 개 또는 그 JSON만 포함한 단일 코드 블록이어야 한다. 허용 필드는 status/value/explanation뿐이며 insufficient_evidence/null/비어 있지 않은 설명을 요구한다. 추가 문장·추가 블록·추가 필드·값 추정을 거부한다. 실제 native helper가 이 검증기를 사용한다.

node --test scripts/native-answer-validation.test.mjs: 3개 통과. node --check 통과. NATIVE-OMISSION-SCOPE의 실제 원문 응답을 새 검증기에 재생하여 통과하고, 추가 IP 문장을 붙인 경우 거부되는 것을 확인했다. 이번에는 모델을 새로 호출하지 않았다.

범위: 형식 밖의 설명을 누락하지 않도록 보강한 것이다. explanation 안의 의미적 과장까지 자동 판단하지 않는다. 실제 원문 수동 검토 및 다양한 근거/질의 평가가 필요하며 전체 native 품질 합격은 아니다. 운영 변경 없음.
