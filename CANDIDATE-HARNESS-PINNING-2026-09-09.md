# 설치 후보와 검증 자료의 소스 버전 결합

check-release-integration.py는 provider manifest의 source_commit을 보고하면서 실제 scripts/tests/contracts는 현재 저장소 HEAD에서 추출했다. 두 버전은 기존 결과에 각각 표시됐지만 HEAD가 이동하면 같은 후보를 검사하는 자료가 바뀌었다. 최근 문서 커밋만 다른 검증 결과를 무효라고 판단하지 않으며, 이후 실행의 재현 조건을 개선한다.

후보 manifest의 40자리 source_commit이 실제 Git commit인지 확인하고 source_tree도 대조한다. 후보와 동일한 commit에서 검증 자료를 가져온다. 잘못된 값, 없는 commit, tree 불일치는 프로세스 실행 전에 거부한다. 운영 후보 또는 계약을 수정하지 않았다. 후보별 최신 교차 버전 검증을 별도 제공한 것은 아니다.

검증:
- 실제 임시 Git 리포에 두 commit을 만들고 HEAD가 앞서도 후보 commit 선택, 잘못된 commit/branch 문자열/옵션/없는 객체/tree 불일치 거부를 확인했다.
- 관련 release integration/contents/prepare 검사 **17 passed / 0.36초**, Ruff/diff 통과.
- 실제 설치 provider fa79861과 JARVIS195b1a 후보에서 TLS/CLI/MCP 네 시나리오 통과. harness_commit과 provider source_commit이 fa79861로 동일했다. provider/JARVIS/Node 검사 전후 불변.
- [실제 실행 결과](CANDIDATE-HARNESS-PINNING-2026-09-09.json). 인증 주체·시각·업무 내용 fixture라는 기존 한계를 유지한다.

이 변경은 저장소의 검증 도구이며 설치 패키지의 sb 제품 코드는 바꾸지 않는다. 기존 최신 후보를 재빌드할 필요 없이 검증 도구로 검사했다. 운영 전환과 전체 M1–M14 완료는 남는다.
