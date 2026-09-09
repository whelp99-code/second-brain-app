# 실행 후보 내용과 연동 검증 결합 — 2026-09-09

`deploy/check-release-integration.py`가 기존 전체 내용 검사를 사용하도록 연결했다. 연동 전에 provider 설치 디렉터리와 JARVIS build 부모 디렉터리 전체를 기록하고, 종료 후 동일 여부를 검사한다. 전후 비교를 통과해야 성공 JSON을 출력한다. 변화가 있으면 `ACCEPTANCE_CANDIDATE_CHANGED`로 실패한다. 이전처럼 테스트만 통과하고 실행 후보 변경을 놓치지 않도록 했다.

실제 사용할 Node 바이너리는 시작 시 정규 경로로 고정하고 해시·크기·권한을 전후 검사한다. Python 외부 실행기 링크는 provider inventory에서 이미 검사한다. Python bytecode 생성을 환경 변수로 억제하며 새 파일이 생기면 inventory 차이로 취급한다. 외부 디렉터리 symlink에 의존하는 이전 후보는 전체 내용을 고정할 수 없어 검사 단계에서 거부된다. contained candidate를 사용해야 한다.

검증:

- 관련 16 passed/0.31초, Ruff 및 diff check 통과. provider/JARVIS/Node 변경 거부와 변경 없는 경우 원래 transport 실패 보존을 확인했다.
- 실제 설치 SB ebe227c + contained JARVIS e6984ad에서 최종 도구 실행 exit0. provider 8,045항목, JARVIS 19,588항목, 실제 Node 실행 파일의 전후 내용 일치.
- 실제 TLS·별도 MCP·CLI의 정상/수락 중 철회/실행 전 철회/만료 4경로 통과. 정상은 proved→settled→completed, 새 로그인 독립 2클라이언트에서 각각 2기록, settlement/attempt 각각1, 모든 경로 FK0.
- [최종 실행 결과](CONTENT-BOUND-INTEGRATION-2026-09-09.json)에 inventory digest·실행기 해시와 개별 결과를 기록했다. Node 검사 추가 전 실행도 통과했지만 보고서 JSON은 추가 후 최종 실행이다.

신원·시각·원작업은 fixture이며 native 모델 호출은 수행하지 않았다. 검사 중 변경 후 원상 복구하는 행위까지 추적하지 않으며, 검사 이후 쓰기나 동적 라이브러리·OS 변경을 막는 봉인 기능도 아니다. 전후 내용 일치는 운영 승인 및 실제 업무/에이전트 인수를 대체하지 않는다. 운영 DB/current/서비스 변경 없음.
