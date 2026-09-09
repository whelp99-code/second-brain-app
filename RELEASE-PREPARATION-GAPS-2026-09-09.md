# 운영 전환 준비: 의존성 재사용과 미추적 파일 혼입 수정

개발판을 운영에 적용할 준비 과정에서 실제 결함2개를 발견했다. 자비스 `a7a98e9`는 기존 운영 의존성의 무검증 재사용을 차단하고, SB `deploy/prepare-release.py`는 고정 커밋으로만 wheel을 만든다. [구조화 결과와 후보 manifest](RELEASE-PREPARATION-GAPS-2026-09-09.json).

## 1. 자비스 운영 의존성 재사용 보류

두 publisher가 새 package.json/lock/dist와 기존 control-center의 node_modules를 조합하는 구조였다. 실제 운영 release `artifact-4146a192b5fb9e489e2ce3fcb9629077739df0134bc26094750628369dcfdb98`에는 새 MCP 연결부가 요구하는 SDK package.json이 없었다. 이 상태의 재사용으로 새 기능의 실행을 보장할 수 없다.

새 읽기 전용 preflight는 정확한 lock bytes, manifest의 runtime dependencies, 설치된 직접 dependency 버전을 검사한다. 두 publisher가 build 전 및 stage 복사 후에 호출한다. 실제 운영 release는 `RELEASE_DEPENDENCY_LOCK_MISMATCH`로 거부했고 작업공간의7개 직접 의존성은 통과했다.

관련9개 검사 통과. 이 중 실제 Bash publisher4개 격리 시나리오에서 build 전 lock 차이 및 build 중 모듈 삭제를 각각 거부하고 current를 보존했다. TypeScript 격리 emit·ESLint·JS/Bash 구문·diff 검사 통과. 테스트의 verifier/npm/승인 환경 값은 모두 임시 runtime용이다. 운영 publisher를 실행하지 않았다.

이 검사는 transitive closure·native ABI·봉인된 모든 파일 검증을 대체하지 않는다. 현재 lock에 맞는 새 dependency artifact 준비와 정본 release gate가 남는다. [자비스 상세](../Orca-JARVIS/docs/release-dependency-reuse-2026-09-09.md).

## 2. SB wheel에 미추적 백업 파일 혼입

기존 빌더로 만든 실제 후보에는175개 커밋 파일 외에 `sb/compile.py.bak-20260906-214804`, `sb/llm.py.bak-20260906-214804`가 들어갔다. 작업공간이 dirty라는 manifest 표시만으로 혼입을 방지하지 못했다.

빌더는 시작 시 source commit/tree를 고정하고 `git archive`를 임시 디렉터리에 풀어 그곳에서 wheel과 frozen requirements를 생성하도록 변경했다. archive는 data filter로 추출하고 SOURCE_DATE_EPOCH도 해당 커밋 시각으로 고정한다. 원래 작업공간의 미커밋/미추적 파일을 바꾸거나 삭제하지 않는다. 배포하려는 코드 수정은 먼저 커밋해야 한다.

새 후보의 `sb/` 파일175개를 manifest가 가리키는 `b025e05888f5886460ab0457fb894a0ffd872d07`과 각각 byte 비교해 전부 일치, 미추적0·변경0·bak0을 확인했다. 기존 잘못된 후보 디렉터리는 제거했고 원래 백업2개는 보존했다.

검증한 후보는 `/var/tmp/sb-memory-release-pinned-daghgem0/releases/dc591781612a0e9acbc751aa2c6cc7b7b7b15093`다. wheel SHA-256은 `4b2da0bd145488f048c421fb457a8ef5d71f7f54fdc68823da50d613868efaa9`, requirements SHA-256은 `75ce0da3bace37b8e20a733acd1b1cc7db5c30c77586baa59eef8bdf18245177`이다. 임시 준비 후보이며 운영 current가 가리키지 않는다. 이 후보에 새 배포 스크립트의 커밋이 포함됐다는 뜻은 아니며, provider 제품 source commit은 위 manifest 값이다.

## 3. 설치물 실행 검사

후보의 새 가상환경에서 scoped write/status 및 수집 관련7모듈을 import하고 경로가 모두 후보 내부인지 확인했다. 실제 `bin/sb --help`도 성공했다. `deploy/check-release-mcp.py ABSOLUTE_RELEASE_PATH`를 추가해 설치물의 별도 stdio 프로세스4개를 검증했다.

| 프로필 | 실제 initialize/list_tools |
|---|---|
| scoped-record-read-v2 | generation status/read page/search |
| scoped-record-read-v5 | generation status/request status/read page/search |
| scoped-request-status-v1 | request status |
| scoped-request-write-v1 | write request |

이 검사는 임시 설정·가상 키·비운영 vault 경로로 실행한 시작/도구 목록 검사다. 실제 읽기/쓰기 완료·정책·운영 readiness 검사를 대신하지 않는다. 최초 fixture의 vault symlink 및 canonical credential JSON 요구를 맞춘 뒤4프로필이 통과했다. 검사 도중 실제 운영 자격증명이나 자료에 접근하지 않았다.

## 다음 전환 조건

정본 Linux release 절차의 exact migration vector, quick/FK check, doctor/status, dashboard health, MCP, scheduler cursor와 uncertain outbox, 봉인 manifest/rollback 호환성 인수를 유지한다. 실제 운영 DB 전환·구 worker 배제, 새 자비스 dependency artifact, 현재 로그인 자격증명 공급/교체와 설정, 실패 브리핑5건의 처리도 아직 남는다.

**운영 전환은 보류**다. 이번에 준비한 것은 SB 임시 설치 후보와 실제 결함을 차단하는 배포 코드다. 서비스·운영 current·운영 DB/설정을 바꾸거나 push하지 않았다. 제품 전체 검사1,388/2skip은 직전 SB 제품 커밋의 기록이며 이번 패키징 실행 수에 합산하지 않는다. 전체 M1–M14를 완료 처리하지 않는다.
