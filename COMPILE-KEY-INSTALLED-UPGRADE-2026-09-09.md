# 페이지별 컴파일 키: 설치본 간 이전 검증 — 2026-09-09

실제 이전 wheel 설치본 `9f65b0b0b349297a4187e89f98079c8f62ba0eb7`에서 임시 원장을 만들고, 새 wheel 설치본 `91ad288b09aef84d6de42a14bfb8d0a76bbfc3b4`로 재컴파일했다. 두 출처는 같은 내용을 가지며 각각 project:a/project:b로 분류했다. 사용자 데이터나 운영 서비스를 사용하지 않았다.

- 이전 설치본: SourceItem 2개인데 wiki 페이지 1개인 기존 결함 재현.
- 새 설치본: 페이지 2개로 복구. 각 페이지의 단일 출처 분류 유지, 자기 프로젝트 읽기 허용/다른 프로젝트 읽기 거부.
- 기존 페이지의 page ID·출처 refs·프로젝트 분류 보존, SourceItem 2개 및 수집 cursor 위치 보존.
- 새 설치본 재컴파일: 페이지·분류·커서·derivation 수·Git head가 모두 이전 검사 결과와 동일. 불필요한 두 번째 컴파일 없음.
- 새 후보의 자비스 HTTPS/MCP/CLI 쓰기·새 세션 읽기와 철회/만료 4경로 통과.
- 페이지 키 수정 후 전체 검사: **1,418 passed, 2 skipped / 260.91s**. Ruff 통과.

`deploy/check-compile-key-upgrade.py PREVIOUS_RELEASE CANDIDATE_RELEASE`로 재현 가능하다. 도움말과 인자는 argparse로 처리한다. 실제 설치본 CLI를 사용하고 PYTHONPATH를 제거해 개발 소스 혼입을 피했다. FakeLLM·임시 분류 데이터이며 검사 종료 시 임시 원장을 삭제한다. 정확한 source commit/manifest·결과는 동명 JSON에 보존했다.

이는 운영 원장의 대규모 재컴파일 비용이나 내용 품질을 증명하지 않는다. 기존 페이지 1회 재컴파일 가능성, 실제 계정 연결·DB 전환/구버전 배제·복구 gate는 계속 남는다. 운영 활성화는 하지 않았다.
