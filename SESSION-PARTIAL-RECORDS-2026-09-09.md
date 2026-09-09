# 세션 JSONL 부분 기록 유실 수정

Codex/Claude 수집기가 파일의 현재 크기를 곧바로 다음 cursor로 저장했다. 작성 중인 마지막 JSONL 줄이 불완전하면 malformed-json으로 소비하고 다음 스캔에서 그 뒤부터 읽어, 나중에 완성된 기억을 유실할 수 있었다.

두 수집기는 이제 실제 소비한 위치를 반환한다. 개행 없이 끝난 파싱 불가 마지막 줄은 아직 작성 중일 수 있으므로 소비하지 않는다. 다음 scan은 그 줄 처음부터 다시 읽는다. 완전한 JSON은 마지막 개행 없이도 계속 처리하고, 개행으로 끝난 잘못된 줄은 기존대로 malformed-json으로 기록한다. 동일 파일을 읽는 동안 늘어난 실제 소비 위치도 cursor에 반영한다.

검증:
- 수정 전 한글 UTF-8 코드포인트 중간에서 기록을 끊은 회귀2건 실패. 수정 후 관련20개 통과.
- 전체 `TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py`: **1,358 passed / 2 skipped / 257.79초**. 관련20개는 전체에 포함하며 합산하지 않는다.
- 전체 Ruff 및 변경 두 모듈 basedpyright 0 errors/0 warnings.
- 별도 Python 프로세스를 수집기마다3회 실행: 부분 기록 시0행·cursor 이전 줄 끝, 기록 완성 후 새 프로세스1행, 다음 새 프로세스 재조회0행. 총6프로세스, 잘못된 오류 처리0건. 임시 합성 입력과 해당 connector의 실제 코드로 검증했다. native 앱 간 공유·자비스 운영 인수는 아니다.

[결과 JSON](SESSION-PARTIAL-RECORDS-2026-09-09.json), [회귀 검사](tests/test_session_partial_records.py).

## 추가 발견과 다음 수정

읽기 전용으로 실제 `.claude/projects`의 최근3파일에서 각 최대100줄의 구조만 집계했다. user44/assistant75 레코드를 확인했다. 현재 Claude connector의 _claude_extract는 정규화 export의 message/tool_use/tool_result만 처리하고 native user/assistant는 무시한다. 따라서 export fixture 검사를 실제 Claude 자동 수집 지원의 증거로 쓸 수 없다. 원문·비밀 값은 보고서에 출력하지 않았다.

후속 구현은 native user/assistant의 UUID·세션 출처, 가시 텍스트, tool_use/tool_result 결합과 오류 상태 보존이다. thinking 등 비가시 블록을 기억 본문에 포함하지 않는다. OMO/GJC에도 현재 파일 크기를 cursor로 삼는 패턴이 있어 재현·수정 범위를 추가 대조한다. 이번 두 모듈 수정만으로 그 수집기까지 해결됐다고 주장하지 않는다.

개행 없이 끝난 영구 손상 줄과 작성 중인 줄은 이 정보만으로 구별할 수 없다. 해당 tail은 계속 보류되며 자동 시간 제한이나 임의 건너뛰기는 추가하지 않았다. 기존에 잘못 저장된 운영 cursor를 일괄 되감거나 원문을 재수집하지 않았다. 운영 설정·서비스·DB 변경 없음. 전체 M1–M14의 실제 공통 기억 인수는 유지한다.
