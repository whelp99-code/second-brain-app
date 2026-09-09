# 관리형 기억의 실제 모델 생성과 기본 MCP 재시작 회수

검증 소스: `6f33059149f83ccb43ed3ada267757bdb0c01011`. [실행 결과](MANAGED-NATIVE-MCP-RECALL-2026-09-09.json).

소유한 임시 관리형 저장소에서 GenerationMutationService.remember로 합성 사실을 기록하고 정상 pipeline의 ingest/compile을 실행했다. 컴파일은 실제 Claude Code 2.1.261을 도구 없이 호출했다. 두 단계 exit_code=0을 검사했다. 이어 `python -m sb.mcp` 자식 서버를 각각 새로 시작해 MCP Client로 검색·본문 조회를 두 번 수행했다. 두 연결은 종료했다.

- 관리형 vault_root는 실제 active 세대 symlink다. 일반 vault용 명시적 bootstrap이나 세대 검사 완화를 사용하지 않았다.
- 각 검색 결과 1건, 같은 wiki page_id와 동일 본문을 회수했다. 입력 사실 “금요일 오후 세 시”와 inbox 원문 출처를 확인했다.
- SB_CONFIG, XDG_DATA_HOME, state/request/export/backup/share 및 명시적 knowledge_registry를 임시 경로로 지정했다. 비교용 다른 registry 파일은 생성되지 않았다.
- 이번 검증의 모델 작성 입력은 합성 사례다. 실제 자비스 업무 검증·인증 세션·다른 모델 에이전트 인수나 운영 배포 완료를 의미하지 않는다. 일반 기본 프로파일 검증을 scoped 권한 검사 증거로 대체하지 않는다.
- 본문에 같은 sid의 각주 정의가 두 번 존재한다. 모델의 span 포함 정의와 vault의 자동 정의가 함께 남았다. 사실 회수는 성공했지만 표시 정합성 개선 항목으로 추가한다. sb/vault.py의 _render는 모델 본문 뒤에 정의를 항상 추가하며, _strip_definitions는 끝부분의 완전히 동일한 정의만 제거한다. 이번 검증에서 제품 수정은 하지 않았다.

실행 스크립트: `/var/tmp/sb-managed-native-recall.py`. 과거 공용 레지스트리 영향의 복구 보류는 [별도 감사](REGISTRY-TEST-IMPACT-2026-09-09.md)를 유지한다.

## 누적 회귀 검증

동일 제품 소스에서 `uv run pytest -q --ignore=tests/test_embeddings.py`: **1,551 passed, 2 skipped / 321.62초**, 종료 코드0. `uv run ruff check sb tests`와 `git diff --check` 통과. 선택적 embeddings 모듈은 지정 명령에 따라 제외했으며 이번에 정적 타입 검사는 재실행하지 않았다. [전체 실행 로그](CURRENT-FULL-REGRESSION-2026-09-09.txt). 테스트 완료까지 제품 소스를 변경하지 않았다.
