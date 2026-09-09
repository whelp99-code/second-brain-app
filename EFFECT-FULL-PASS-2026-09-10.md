# 상태 재결합·실패 복구 전체 회귀 통과

검증 소스 f323e166eeab5036fdb276fde4c5cc6024605e00. 실행 중 제품/테스트 소스를 변경하지 않았다.

`TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py`: **1630 passed, 2 skipped / 350.80초**. exit 0을 실행 핸들로 확인했다. 원문 로그 EFFECT-FULL-PASS-2026-09-10.txt.

`uv run ruff check sb tests`: 통과. `uv run basedpyright sb/effect_knowledge.py sb/sealed_knowledge.py sb/generation_access.py sb/request_executor.py`: **0 errors, 0 warnings**. 타입 결과 EFFECT-STATIC-TYPES-2026-09-10.txt. 타입 검사는 위 네 모듈 범위이며 전체 저장소 타입 통과를 의미하지 않는다.

이번 전체 실행은 본문 결합 지식 상태 저장·세대 digest·관리형 검색, native 각주 수정, 승인된 정정/부분 삭제 상태 재결합, 효과 이후 상태 저장 실패의 reconciling/재처리 및 추가 회귀를 포함한다. tests/test_embeddings.py는 리포 기본 지침대로 제외했으며 2개 skip도 통과에 합산하지 않는다.

이전 KNOWLEDGE-FULL-REGRESSION 보고서의 1605통과/1실패는 당시 사실로 유지한다. schema 버전 fixture 수정 이후 최신 전체 통과의 증거는 본 보고서다. 이번 기록 작업은 제품 동작을 추가 변경하지 않는다.

## 완료되지 않은 인수

- 실제 OS 강제 종료를 지식 상태 저장/효과 적용 경계에서 실행한 복구 인수
- 정상 복원 문서의 자동 상태·처음 미검증인 페이지의 부분 record 정책
- scoped 접근 분류와 상태 재결합의 동등성·취소 경쟁
- 최신 SB/JARVIS 설치 쌍 및 운영 writer/DB 전환·rollback
- 실제 사용자 업무의 native/다른 에이전트 회수, 클라이언트별 수집/주입, 실제 질문 검색 품질과 보존/삭제/복구 및 M1–M14

전체 테스트 통과를 전체 프로젝트 완성이나 운영 배포 승인으로 해석하지 않는다. 운영 DB·서비스·공용 registry 변경과 push 없음. 기존 사용자 untracked 파일은 유지했다.
