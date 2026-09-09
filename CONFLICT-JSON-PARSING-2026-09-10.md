# 충돌 판정 JSON 파싱 수정

기준 제품 6c43c24. 이전 보고의 cites 필수 설명을 정정했다. 기존 _fstrs는 해당 필드가 없으면 빈 tuple을 반환하므로 프롬프트의 cites 생략 자체가 컴파일 실패 원인은 아니었다. 실제 재현된 실패는 --llm fake가 JSON 대신 Cited 문장을 반환한 문제였고 이전 수정은 이를 해결했다.

추가 점검에서 기존 parser가 정규식으로 JSON 필드를 검색해 confidence=1e-1을 1로 읽고, 키 뒤 공백이 있는 정상 JSON을 거부하며, 중첩 객체 필드/중복 키와 잘못된 cites 배열을 제대로 구분하지 못하는 것을 확인했다. 범위 밖 confidence도 ConflictVerdict에서 제한하지 않았다. 이 경우 잘못된 충돌 기록이나 판정 실패가 만들어질 수 있다.

새 parser는 JSON 객체와 최상위 필드 타입을 검사한다. 중복 키, Boolean/NaN/무한대/범위 밖 confidence, 비문자열 cites 원소를 거부한다. 지수 표기·공백·이스케이프를 JSON 규칙대로 해석하고, cites 생략 호환성을 유지한다. 더 이상 사용하지 않는 정규식 필드 parser를 제거했다. 불량 응답은 기존 derivation failed 경로로 보내며 근거 있는 판정으로 승격하지 않는다.

최종 conflict·fake source update·walking skeleton **25 passed / 5.54초**, Ruff 전체, conflict 타입 **0오류/0경고**, diff 검사 통과. 제품 변경 후 전체 suite와 실제 모델 재실행은 아직 하지 않았다. 이전 실제 자비스 연결 성공을 이 parser의 실제 모델 인수로 확대하지 않는다. 운영 DB·서비스·registry 변경 및 push 없음. 실제 JARVIS 복원/사용자 업무·운영/DR 및 전체 목표는 미완료다.
