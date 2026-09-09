# 검색·콘솔·받은편지함 누적 변경 전체 회귀

대상 커밋:6b3c906d92ec91519f25aa1b36dc9341cbd7f912. 검사 시작/종료 HEAD동일. 검사 중 제품/테스트 파일 변경 없음. 종합 상태 문서만 최신 검증 범위로 갱신했다. 기존 미추적2n/phone-history/bak파일은 보존했다.

`TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py`: **1724 passed,2 skipped / 483.04초,exit0**. 저장소 기본 지침에 따라 선택 embeddings 모듈 제외. [전체출력](INBOX-CONSOLE-FULL-2026-09-10.txt). `uv run ruff check sb tests` 및 `git diff --check` 통과.

이 회귀에는 최근 scoped검색 최적화·독립작성자/출처분리,웹 연결종료·준비상태,받은편지함FIFO/제한읽기/교체감지/.done링크거절 변경이 포함된다. 개발 코드 전체 회귀 결과이며 최신 설치 후보 a2861f3의 paired 자비스 인수와 구분한다. 그 후보는 이후 콘솔/받은편지함 변경을 아직 포함하지 않는다.

종합 M1–M14 표의 출처 분리·1,000페이지검색·동시조회·최근운영관측을 갱신했다. 실제 사용자 업무의task→검증결과→기억 계보,운영버전전환과native전체수명/DR등 완료조건은 유지한다. 받은편지함 검증과최종rename 사이의 원문교체 및 기존done파일보존정책도 이번 전체통과로 해소됐다고 주장하지 않는다. 운영 current/서비스/DB 및타리포변경/push없음.
