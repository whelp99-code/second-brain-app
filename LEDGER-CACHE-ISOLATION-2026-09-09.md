# 원장 간 컴파일 캐시 격리 결함 수정 — 2026-09-09

## 전체 검사에서 발견한 실제 결함

첫 전체 검사에서 1,413 passed / 1 failed / 2 skipped (271.01s). 접근 분류 projection 테스트의 입력 페이지가 MEMORY_ACCESS_UNCLASSIFIED로 거부됐다. 보존된 임시 원장의 source_access는 정상인데 page_access.complete=false였다.

`_BodyCache`가 ledger 객체의 정수 id만 영구 저장했다. Python 객체가 해제된 뒤 id가 재사용되면 같은 page ID의 이전 원장 본문이 다른 원장 컴파일에 들어갈 수 있었다. 이 경우 이전 본문에 대응하는 provenance가 없어 untracked_context로 판정된다. 접근 거부는 정상적인 보호 동작이지만, 원장 간 캐시 혼입 자체가 제품 결함이다. 기존 데이터에서 실제 유출이 있었다고 판정한 것은 아니다.

## 수정

캐시 항목은 ledger weak reference와 본문을 보관하고 조회 때 실제 객체 일치를 확인한다. ledger 해제 시 본문도 제거한다. 예전 reference의 callback이 동일 정수 key의 새 항목을 제거하지 않도록 reference 자체도 비교한다. weak reference를 지원하지 않는 ledger 구현은 전역 캐시를 사용하지 않고 명시적 existing_bodies/pages 경로를 사용한다.

강제 id 충돌과 객체 해제 후 캐시 제거 테스트를 추가했고 수정 전 2개 실패, 수정 후 통과했다. 제품 수정 커밋 `7bd16be`.

배포 준비 도구에서 --help가 출력 경로로 처리되어 실제 패키지를 만드는 별도 결함도 발견했다. argparse로 도움말/잘못된 옵션을 파일 작업 전에 처리하도록 수정했고 테스트 2개 통과, 커밋 `289e326`. 실수로 생성된 작업공간의 --help 디렉터리만 삭제했으며 운영 경로에는 쓰지 않았다.

## 최종 검증과 설치 후보

- 수정 후 전체 suite: **1,418 passed, 2 skipped / 253.73s** (`uv run pytest -q --ignore=tests/test_embeddings.py`).
- 전체 suite 이후에는 빈 cache bucket의 타입 표기만 추가. basedpyright sb/compile.py 0 errors/0 warnings, Ruff sb tests 통과, 관련 테스트 4개 재통과.
- 고정 커밋 `289e326`의 provider wheel 후보 `9f65b0b0b349297a4187e89f98079c8f62ba0eb7`를 별도 venv에 설치하고 새 의존성 자비스 후보와 4개 HTTPS/MCP/CLI 통합 경로 통과. 정상 쓰기→proved→settled→completed→새 로그인 읽기, 독립 SDK client 2개, 철회 후 403을 확인했다. 정확한 manifest/import 경로는 동명 JSON에 포함한다.
- 후보는 마지막 타입 표기·보고서 커밋 전 제품 코드다. 운영 current/service/DB는 변경하지 않았다. fixture 신원/시각/내용이며 native 모델 호출은 이번 검사에 없다.

운영 전환·복구·실제 계정 연결, 실제 품질 평가와 자동 수집/주입의 전체 목표는 계속 미완료다. 캐시 수정과 전체 검사 통과를 운영 완성으로 해석하지 않는다.
