# 검색 개선 설치물의 자비스 paired 인수

제품 a2861f38a82cb5ea1e00de7ed9e0c1e3982c7b37을 git archive로 고정하여 offline release 준비에 성공했다. 검색 요청 단위 검증, YAML 단일 해석, scoped 표시 메타데이터 생략을 포함한다.

- 후보: `/var/tmp/sb-search-release-vvfabt4l/releases/e82d3858eca1c81f5e56307e2261e93abdd0fde9`
- wheel SHA256: `007f9e0e98d269ed33cfd3df446797223f145594a32bd9b5591c0afac207b62a`
- JARVIS: 기존 격리 build `/var/tmp/jarvis-current-pair-_mq15nmd/source/dist`
- 실행: `python deploy/check-release-integration.py <위 후보> <위 JARVIS build>`, exit0.

harness는 후보 커밋의 scripts/tests/contracts만 복사하며 sb 소스 트리는 제공하지 않는다. 네 주요 모듈 import가 설치된 venv 아래임을 검사했다. manifest의 working_tree_modified=true는 보존 중인 미추적 파일이 있는 작업공간 관측이며 패키지는 git archive에서 만들었다. 미추적 bak 파일을 빌드 소스로 사용하지 않았다.

## 실제 경로 결과

검증된 TLS, gateway session, 별도 Python verifier, 공개 MCP 쓰기와 CLI 실행을 거쳤다.

| 경로 | 관측 |
|---|---|
| 정상 저장 | accepted→provider proved→JARVIS settled/control completed |
| 새 로그인 재조회 | 같은 generation, 독립 stdio client2개가 각2records |
| 중복 완료 재생 | settlements1, attempts1, FK errors0 |
| reader 철회 | HTTP403 |
| 접수 중 철회 | denied, accepted row 없음 |
| 실행 전 철회/만료 | provider failed, active generation 없음 |

전후 전체 inventory 비교에서 SB18,474항목/JARVIS19,588항목 및 Node 실행 파일 동일. 이 검사가 끝난 뒤에만 성공 결과를 출력했다. [전체 구조화 증거](INSTALLED-SEARCH-PAIR-2026-09-10.json).

## 범위와 후속

신원 forwarder·원문·정책·clock은 fixture이며 native 모델 호출0회다. 실제 사용자 업무 계보·운영 인증/DB/서비스 전환까지 완료됐다는 뜻이 아니다. 이번에는 설치물·실제 전송 경로의 검색 변경 호환성을 인수했다. 기존 source 관련60통과를 유지하며 전체 회귀를 다시 실행한 결과로 확대하지 않는다.

운영 current/서비스/DB 및 자비스 소스는 변경하지 않았다. 운영 writer 배제·세션 수명과 실제 업무의 A저장→B회수·원장소실 DR 및 M1–M14 전체 목표는 남는다. 코드 계약 변경은 없다.
