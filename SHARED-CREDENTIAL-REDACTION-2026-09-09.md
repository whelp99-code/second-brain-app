# 공통 자격증명 마스킹 모듈

normalize 내부의 자격증명 정규식과 치환 함수를 표준 라이브러리만 사용하는 sb/redaction.py의 redact_credentials로 이동했다. 웹과 ops는 공통 공개 함수를 사용한다. normalize는 기존 _redact 이름을 별칭으로 유지해 기존 호출·검증과 호환된다.

정규식, 치환 순서, 결과 문자열을 변경하지 않았으며 NORMALIZER_VERSION은 유지한다. 이메일·전화번호를 삭제하는 prompt 보안 함수와 통합하지 않았다. 새 의존성은 없다.

정규화·고정 기존 규칙과 동등성·웹·운영 검사 **94 passed, 10.37초**, Ruff/diff 통과. redaction/normalize/web/ops 타입 검사 **0 errors, 4 warnings**이며 남은 경고는 ops의 SQL 타입·문자열 연결·기존 비공개 manifest 메서드다. 웹과 ops의 _redact 비공개 접근 경고는 제거됐다.

독립 Python -I 프로세스에서 공통 모듈만 import하고 token= 값을 마스킹하면서 이메일·전화번호를 유지하는 것을 확인했다. llama_index 모듈은 로드되지 않았다. 이는 공통 모듈의 독립성 검증이며 전체 웹 시작 시간이 줄었다는 실측 주장은 아니다.

운영 서비스는 변경하지 않았다. 최신 설치 후보에는 이 모듈 분리가 아직 포함되지 않는다. 전체 운영·실제 사용자 업무 인수는 남는다.
