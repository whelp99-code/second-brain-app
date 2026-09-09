# 실제 Claude 근거 부족 답변 — 2026-09-09

phone-memory-client-acceptance.mjs에 선택 모드 SB_PHONE_NATIVE_ACCEPTANCE=claude-abstention을 추가했다. 실제 도구를 한 번 호출한 후 ‘deployment server IP address’를 묻고 status/value/explanation JSON을 요청한다. 반환한 기록은 기존 fixture의 ‘첫 결정’·‘두 번째 결정’이며 IP 근거가 없다. 기본 회수 모드는 유지한다.

실제 JARVIS 61b8a42 별도 빌드와 현재 SB에서 쓰기→완료→새 reader의 실제 Claude Code 2.1.261 호출을 실행했다. 독립 SDK 2개+Claude 1회, HTTPS 3회, 각 2기록 확인. 최종 4경로 전체 exit 0. Claude는 insufficient_evidence/value null을 반환하여 IP를 추정하지 않았다. 원문 응답 전체를 JSON에 보존했다.

앞선 두 실행은 모델 응답의 Markdown 포장 때문에 JSON 파싱에 실패했다. 코드 블록 내 JSON을 허용하고 원문 전체를 보존하도록 고쳤다. 최종 실행의 성공만 보고하며 앞선 응답 내용은 보존되지 않아 품질 통과로 계산하지 않는다. node --check 통과.

부분 판정: 답이 없는 값의 생성 억제는 이 1사례에서 확인됐다. 설명에는 omission counts가 0이므로 ‘nothing relevant was withheld from this query’라는 과도한 추론이 포함됐다. 제외 카운트는 검색 corpus 전체의 완전성이나 질문에 대한 관련 기록 부재를 증명하지 않는다. 따라서 설명의 근거 적합성까지 전체 합격으로 판정하지 않는다.

질의는 fixture 조회용 ‘결정’으로 지정했고 최종 사실 질문은 별도다. 실제 서버 주소 질의를 모델이 자율적으로 작성한 시험, 한국어 gold100~300개, 여러 모델 계열의 품질 검증을 대체하지 않는다. 운영 변경·실제 업무 데이터 사용 없음. native 메타데이터/서비스의 모든 사본 보존·삭제 수명도 별도 인수 대상이다.
