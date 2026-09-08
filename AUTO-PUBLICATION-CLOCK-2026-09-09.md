# 자동 발행 시각 역행 검사 수정

2026-09-09. JARVIS 제품 `8ffc993`.

발행 시작 시각을 clock()이 반환한 Date 객체 그대로 보관하던 문제를 재현했다. 공급자가 같은 객체를 수정해 뒤로 이동시키면 시작 시각도 변경되어 `at < now`가 거짓이 되고 잘못된 발행이 수락됐다. 시작 시각을 milliseconds 숫자로 고정하고 Date 객체도 별도로 생성했다.

## 검증

- 수정 전 mutable-rewind 회귀 1개 실패, 나머지5개 통과. 새 Date 객체의 역행과 만료는 이미 거부됐으나 같은 객체의 역행만 통과했다.
- 수정 후 자동 발행과 기존 CLI 경로 19 passed/16.35초. 만료·일반 역행·같은 객체 역행 모두 publication 원장 행 없이 거부됐다. 기존 중복 방지·발행 실패 후 같은 파일 복구도 통과했다.
- TypeScript noEmit·격리 emit·변경 파일 ESLint와 diff 검사 통과.
- 실제 컴파일된 CLI→자동 v3 발행→MCP 저장→provider proved→outbox settled/control completed→독립 MCP client의 records4 회수를 다시 실행해 통과했다. duplicate replay=true, 추가 dispatch0, 남은 review 파일0. [결과 JSON](AUTO-PUBLICATION-CLOCK-2026-09-09.json).

시각 역행은 결정적 테스트 시계로 재현했고, 실제 저장 인수는 fixture 키·고정 시각·합성 검증 결과와 결정적 compiler를 사용했다. 운영 시계 변경·서비스 변경·실제 모델 작업을 실행한 것은 아니다. 이 인수는 일반 owner 쓰기이며 scoped 승인 소비·project 분류·완료 영수증 연결을 완료한 것으로 취급하지 않는다.

## 누적 세컨드브레인 검사

SB `cc236a3` 기준 제품/테스트 소스를 고정하고 필수 명령 `TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py`를 실행했다. **1,153 passed, 2 skipped / 219.73초**. 전체 `uv run ruff check sb tests`도 통과했다. 로그는 `/var/tmp/shared-memory-full-latest.out`, `/var/tmp/shared-memory-ruff-latest.out`이다. 이후 이번 SB 변경은 문서·인수 JSON뿐이다. 이 결과는 JARVIS 전체 테스트나 optional embeddings extra 검사까지 포함하지 않는다.

재시도하지 않는 오래된 orphan 정리와 scoped 쓰기 전체 인수는 유지한다.
