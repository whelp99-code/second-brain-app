# 누적 수정 전체 회귀 및 최신 설치본 연동 인수

검증한 Second Brain 소스는 `d12c1837fb0f34e1087f5c4c273caa9246d2472c`다. 이전 전체 회귀 이후 추가된 관리형 복원 입력 보호·삭제 내용 검사·웹 요청 경합·YAML 제목·검색 색인 v3·백업 삭제 테스트를 포함한다.

## 전체 회귀

`uv run pytest -q --ignore=tests/test_embeddings.py` → **1532 passed, 2 skipped in 314.30s**. 선택적 embeddings 전용 테스트는 저장소 기본 검사 규칙에 따라 제외했다. `uv run ruff check sb tests` 및 `git diff --check` 통과. 테스트 통과를 실제 모델 품질 또는 운영 배포 완료로 해석하지 않는다.

## 최신 설치 후보

독립 캐시 snapshot의 별도 사본으로 `deploy/prepare-release.py --offline`을 실행했다. 커밋된 Git archive로 빌드해 기존 미추적 자료는 포함하지 않았다.

- 후보: `/var/tmp/sb-latest-regression-pair-1x4ibfku/app/releases/184abd3c13e3a12eb09c1c0b171d30389e34018b`
- 준비 결과: exit 0. 캐시 사본과 준비 로그는 같은 상위 작업 디렉터리에 보관했다.
- 자비스 소스 HEAD 재확인: `195b1a7d4588a8386def5e7dce2067a141942708`.
- 재사용한 자비스 격리 빌드: `/var/tmp/jarvis-current-pair-_mq15nmd/source/dist`. 이전 인수와 전체 내용 digest가 동일하다.

`deploy/check-release-integration.py`를 새 설치본에 실행했다. 작업공간의 `sb` 소스 없이 설치 경로에서 실제 Python 모듈을 불러왔으며, TLS·gateway·CLI·MCP를 통과했다.

| 경로 | 실제 결과 |
|---|---|
| 정상 쓰기와 재조회 | provider proved, JARVIS settled, control completed; 새 로그인·독립 MCP 클라이언트 두 개가 각 2개 기록 회수 |
| 접수 중 권한 철회 | 접수 차단 |
| 실행 전 권한 철회 | provider failed, 활성 세대 없음 |
| 실행 전 권한 만료 | provider failed, 활성 세대 없음 |

정상 요청 settlement와 attempt는 각각 1이며 외래키 오류는 0이다. 실제 전송과 설치 코드를 검증했으나 사용자·작업·시각·정책 근거는 fixture다. 이번에는 native 모델을 호출하지 않았다.

## 설치된 최신 수정 검증

별도 임시 테스트 디렉터리에서 설치 패키지 경로를 우선하도록 Python `-I -B`로 실행했다. pytest 실행기와 테스트 자료만 개발 환경에서 공급했으며 `sb.restore`, `sb.search`, `sb.page_metadata`의 실제 import 경로가 후보 내부임을 확인했다.

- 복원, 삭제, 검색, 증분 검색, YAML 제목: **58 passed, 26.17초**.
- 정확한 압축 복원 테스트 파일 `tests/test_restore_archive_members.py`: **18 passed, 0.39초**. 첫 실행 목록의 존재하지 않는 `test_restore_archive.py`는 실행하지 않았고, 정확한 파일을 확인해 별도로 실행했다.
- 총 76개는 전체 1532개와 중복되는 설치 환경 재검증이며 합산한 고유 테스트 수로 보고하지 않는다.
- 76개 실행 후에도 설치본 전체 18,456항목의 digest가 연동 검사 전과 같았다: `4f952c8230e3d9f82857556ecaa5e7d8e18de59ca2edd97eea511a9b9b42dd6d`.
- 자비스 19,588항목 digest: `8b3ebc1901256636f33c6218adee47d6e294355afd64b569af343ea7676b8d10`.

세부 결과는 [JSON 증거](LATEST-SOURCE-INSTALLED-ACCEPTANCE-2026-09-09.json)에 보관했다.

## 남은 인수 조건

운영 서비스·DB·활성 포인터는 변경하지 않았다. 이 후보에는 준비 도구의 `release-manifest.json`이 있지만 최신 후보에 대한 정본 `release.manifest.json`, 재현 빌드 쌍, 영구 봉인 증거는 아직 없다. 이전 후보의 정본 증거를 이 후보에 승계하지 않는다.

운영 작성자 관측·혼합 버전 차단, 실제 사용자 업무의 서로 다른 에이전트 간 공유, native 세션과 관리 외 복사본의 삭제 수명, 실제 검색 평가 및 GUI·운영 복구 인수는 남는다. 이번 검증은 최신 소스와 설치 후보의 차이를 줄였으며 전체 M1–M14 완료를 의미하지 않는다.
