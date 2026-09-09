# 원본 진단과 실제 설정 경로 일치 — 2026-09-09

source_policy_snapshot은 raw root에 expanduser만 적용했다. 수집 설정 Config.source_roots와 달리 환경 변수·설정 파일 기준 상대 경로를 해석하지 않아 `sources` 및 웹 원본 목록에서 다른 위치의 존재 여부를 보고할 수 있었다.

상대 경로와 환경 변수 경로 각각에서 회귀 실패를 재현했다. Config.resolve_path를 명시적 경로의 공통 해석 함수로 제공하고 source_roots와 source_policy_snapshot이 사용하도록 연결했다. 기존 Config._path의 환경 변수/홈 확장·base_dir·절대 경로 처리 규칙을 그대로 재사용한다. 원본 내용이나 수집 cursor는 변경하지 않는다.

검증: 경로·security·web 관련 **23 passed/7.57초**, Ruff sb/tests, basedpyright config/security 오류0·경고0, diff check 통과. 실제 별도 CLI 프로세스의 doctor와 sources를 설정 폴더 밖에서 실행해 둘 다 정확한 settings/notes 경로와 존재/pass를 확인했다. 첫 검사 명령에는 존재하지 않는 test_config.py를 지정해 수집이 실패했으며, 올바른 파일 목록으로 다시 실행한 결과만 위 수치에 포함했다.

운영 설정/서비스 변경 없음. 이번 변경은 진단 경로의 일치이며 실제 에이전트 자동 수집·주입이나 운영 배포 완료를 뜻하지 않는다.
