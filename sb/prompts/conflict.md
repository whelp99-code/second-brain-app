입력 단위 A
ID: {left_id}
본문:
{left_text}

입력 단위 B
ID: {right_id}
본문:
{right_text}

규칙:
- 출력은 JSON 객체 하나만. 설명·코드펜스 금지.
- 키는 relation, confidence, rationale, cites 만.
- cites는 근거로 사용한 입력 단위의 ID 문자열 배열. 근거가 없으면 빈 배열.
- cites에 넣을 수 있는 값은 위 "ID:" 줄의 두 문자열 "{left_id}", "{right_id}" 뿐이다. 이 문자열을 접두사까지 그대로 복사한다. 축약·변형·재작성·설명 덧붙이기 금지.
- 본문 안에 나오는 사건·작업·결정·문서 번호(예: EVT-…, TASK-…, DEC-…)는 입력 단위 ID가 아니다. cites에 넣지 않는다.
- relation은 supports, contradicts, unrelated, supersedes 중 하나.
- confidence는 0과 1 사이 숫자.
- rationale은 280자 이하 한국어.
- 입력 두 단위에 있는 내용만 근거로 쓴다.
