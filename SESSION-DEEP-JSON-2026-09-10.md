# 세션 JSON 과도한 중첩 격리

Claude/Codex/OMO/GJC/OpenCode의 _obj는 JSONDecodeError 등은 처리하지만 RecursionError는 전파했다. 깊이10,000의 약20KB JSON 파일을 정상 형제 파일과 함께 scan하면 다섯 어댑터 모두 예외로 수집을 중단했다. 작은 파일도 전체 adapter 수집 결과를 잃게 하는 결함이다. 최초 깊이1,100 fixture는 이 Python JSON 파서에서 재귀 한도에 도달하지 않았으므로, 깊이10,000으로 조정해 실제 RecursionError 5건을 재현한 결과를 기준으로 삼았다.

각 파서의 기존 형식 오류 처리에 RecursionError만 추가했다. 시스템 재귀 한도를 올리거나 모든 예외를 무시하지 않는다. 해당 파일/행은 기존 malformed-json 또는 invalid-format 처리로 넘기고 정상 형제 파일은 수집한다. 커서 처리도 기존 각 adapter의 malformed 입력 정책을 따른다.

검증: 관련 세션 형식/파일 교체/여러 root/부분 레코드/export resume/native 형식 테스트 **69 passed / 0.67초**. 변경된5모듈 basedpyright 0 errors / 0 warnings. Ruff sb/tests exit0, 기존 sessions_gjc.py의 `# noqa: MATCH_OK` 두 곳에 invalid-directive 경고가 표시되었으며 이번 변경에서 그 주석은 수정하지 않았다.

실제 격리 CLI init+ingest2회 exit0. OpenCode 깊이10,000 snapshot은 invalid-format 사유만 기록하고 정상 형제는 본문 valid sibling을 원장/CAS에 저장했다. 두 번째 실행 원장은 동일했다. 결과 SESSION-DEEP-JSON-2026-09-10.json, 환경 /var/tmp/sb-deep-json-cli-9w9b5fjg. 다섯 제품의 실제 native 실행 인수는 아니며 CLI 실측은 OpenCode 경로다.

깊은 입력을 허용하는 기능은 제공하지 않는다. 모든 JSON 파서의 자원 예산을 완성했다는 뜻도 아니다. 최근 전체1,767통과 및 설치 인수는13cab77 기준이며 이번 수정 이후 전체/설치 검사는 미실행이다. 운영 전환과 실제 사용자 업무, 전체 M1–M14 완료 기준을 유지한다.
