# 최근 검색·세션·OpenCode 수정 전체 회귀

검사 전후 HEAD `13cab776643574f6559282e26d93087694e55cf6`가 동일했다. 명령:

```bash
TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py
```

**1,767 passed / 2 skipped**, 516.57초, 종료 코드0. [전체 출력](CONNECTOR-UPDATES-FULL-REGRESSION-2026-09-10.txt). 이전 f9fbe55의 1,730통과 이후 검색 분류 조회 재사용·변조 검증, 세션 파일 열기, OpenCode 읽기 실패/DB 경계/크기·내용 변경/SQLite 예산/읽기 일관성/다중 root 보류 등이 포함된 현재 트리를 검사했다. optional embeddings 모듈은 명령대로 제외했다. 선택적 실제 LLM/DB smoke는 별도 환경 조건이 필요한 범위다.

검사 중 제품·테스트·배포 스크립트·계약 소스는 고정했고 종료 후 git diff --quiet -- sb tests deploy scripts contracts가 exit0이었다. 수정된 것은 상태/지원 문서와 새 검증 보고서다. Ruff sb/tests 통과. 회귀 시간 일부는 격리 설치 준비·인수 검사와 겹쳐 순수 단독 성능 측정으로 쓰지 않는다.

같은 커밋의 [설치물 자비스 인수 및 OpenCode CLI](INSTALLED-CONNECTOR-UPDATES-2026-09-10.md)도 통과했다. 운영 조건은 [UTC01:40 읽기 재확인](OPS-RECHECK-2026-09-10-0140.md)에서 작성자2서비스·만료 전lease1로 전환 보류다.

전체 테스트 통과를 실제 사용자 업무, 모든 native 제품의 자동 수집·문맥 주입·정정/삭제 사본 수명, 운영 배포·DR 완료로 확대하지 않는다. M1–M14 목표와 인수 조건은 유지한다.
