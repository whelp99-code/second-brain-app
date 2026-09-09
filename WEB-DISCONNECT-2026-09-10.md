# 운영 콘솔 연결 종료 처리

직전 실제 브라우저 QA에서 페이지를 즉시 닫았을 때 BrokenPipeError가 발생하고, GET 오류 처리기가 같은 끊어진 연결에500 JSON을 다시 쓰다 두 번째 traceback을 남겼다.

`sb/web.py`에서 JSON 헤더/본문 전송의 BrokenPipeError·ConnectionResetError는 연결을 닫는 상태로 처리한다. GET HTML 전송과 POST 요청 읽기에서 발생한 같은 종료 오류도 별도로 처리한다. 다른 OSError 및 업무 오류의 기존 오류 응답은 유지한다. 완료된 쓰기 효과를 되돌리거나 자동 재전송하지 않는다.

검증:
- 헤더/본문별 broken pipe/reset4개 경로: 한 번만 응답 시도, 연결 종료, 예외 유출 없음.
- 관련 없는 I/O 오류는 계속 예외로 전달.
- 실제 TCP 클라이언트를 SO_LINGER로 reset하고 서버가 reset을 읽은 뒤 응답을 쓰도록 event로 조율. 임의 sleep 없이 서버 handle_error0회와 후속 health200을 확인.
- 웹 상태/실패/접근·쓰기 관련 **22 passed / 10.95초**. Ruff 전체/diff 통과. web.py 타입0오류, 기존 상태 snapshot dict 추론 관련 경고5개가 남음. 새 close_connection 경고는 명시적 타입으로 해소.

화면 UI는 변경하지 않아 브라우저 전체 흐름을 반복하지 않았다. 격리 서버/합성 기억 검증이며 운영 current/서비스/DB 변경 없음. 이번 변경도 다음 설치 후보 인수에 포함해야 한다. 운영 전환·실제 업무의 공통 기억과 전체 M1–M14 목표는 남는다.
