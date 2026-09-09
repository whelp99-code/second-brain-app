슬롯: {left_id}
슬롯: {left_text}
슬롯: {right_id}
슬롯: {right_text}

규칙:
- 출력은 JSON 객체 하나만. 설명·코드펜스 금지.
- 키는 relation, confidence, rationale, cites 만.
- cites는 근거로 사용한 입력 단위 ID의 문자열 배열. 근거가 없으면 빈 배열.
- relation은 supports, contradicts, unrelated, supersedes 중 하나.
- confidence는 0과 1 사이 숫자.
- rationale은 280자 이하 한국어.
- 입력 두 단위에 있는 내용만 근거로 쓴다.
