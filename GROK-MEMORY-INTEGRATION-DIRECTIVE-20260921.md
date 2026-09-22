# Grok 실행 지시서 — JARVIS·Second Brain·Phone History 메모리 통합

작성일: 2026-09-21  
기준 계획: `JM_BLRO_Core5_MEMORY_INTEGRATED_PLAN_20260921.md`

## 목표

JARVIS가 Second Brain을 공통 메인 기억 저장소로 사용하고, Phone History가 업로드·철회를 수행하는 실제 종단을 완성한다. 기존 시스템의 정본·승인·삭제 불변식을 유지한다.

## 절대 규칙

- 현재 변경 사항을 먼저 보존한다. 삭제·reset·강제 checkout을 하지 않는다.
- `origin/master`를 바로 메인 checkout에 pull하거나 merge하지 않는다.
- 별도 worktree에서 작업하고, 작업 전후 HEAD·dirty 목록·release identity를 기록한다.
- 운영 DB·운영 Vault·실사용자 기억을 임의로 변경하지 않는다.
- 운영 서비스 재시작·release 전환·실제 삭제·복원·push를 하지 않는다.
- 비밀 토큰 값은 로그·문서·evidence에 기록하지 않는다.
- fixture 통과를 실제 provider·실사용자 세션 통과로 표현하지 않는다.
- 막히면 수정을 반복하지 말고 `OWNER_BLOCKED`로 중단한다.
- 각 단계가 끝날 때 commit hash, 명령, exit code, 결과 파일 경로를 기록한다.

## 현재 알려진 기준

- 작업 트리 보존본:
  - `/var/tmp/second-brain-pre-sync-20260921/worktree.patch`
  - `/var/tmp/second-brain-pre-sync-20260921/untracked.tar.gz`
- Second Brain 메인 checkout은 origin보다 41커밋 뒤처져 있다.
- 최신 기준선 격리 테스트 보고: `1946 passed, 2 skipped`
- Ruff와 운영 `/ready`는 통과 보고가 있다.
- 전체 basedpyright는 실패 보고가 있다. 전달된 집계는 오류 408건·경고 5,272건이다.
- Phone History 현재 `SecondBrainSink`는 직접 inbox 적재만 하며 `retract()`가 없다.
- 운영용 refresh·maintenance·backup timer와 구형 `second-brain.service/timer`를 구분해서 측정한다.

## 작업 순서

### W0 — 기준선과 증거 고정

대상 저장소:

- `/home/jm/orca/projects/Orca-JARVIS`
- `/home/jm/orca/projects/second-brain-app`
- `second-brain-app/phone-history`

수행:

1. 각 저장소의 `git status --short`, branch, HEAD, origin 차이를 기록한다.
2. 운영 release ID·source commit·wheel hash·서비스·timer·포트를 읽기 전용으로 기록한다.
3. `/ready`, `sb doctor`, 활성 client version을 기록한다.
4. 작업 전 보존본과 증거 경로를 확인한다.

완료 조건:

- `GROK-W0-BASELINE-20260921.json` 작성
- 불일치·미확인은 `unknown` 또는 `OWNER_BLOCKED`로 기록

### W1 — 공통 메모리 계약

수행:

- `operation_id`, `attempt_id`, `request_id`, `upload_id`, `receipt_id`, `fence`의 의미를 고정한다.
- JARVIS와 Python이 같은 golden fixture를 읽고 digest를 동일하게 계산하도록 한다.
- JARVIS가 요청 권한을 payload로 스스로 지정하지 못하게 한다.

완료 조건:

- 계약 파일과 Node/Python 테스트 추가
- 기존 MCP·업로드 계약 회귀 통과
- `GROK-W1-CONTRACT-20260921.json` 작성

### W2 — Second Brain 철회 release

수행:

- 현재 미커밋 철회 변경을 별도 commit으로 정리한다.
- 다음을 격리 Vault에서 검증한다.
  - upload
  - retract
  - receipt 조회
  - staged 파일 삭제
  - CAS tombstone
  - 검색 결과 제거
  - 재업로드 차단
  - 같은 upload ID 재철회 idempotency
- 새 wheel·manifest를 만들고 source commit과 hash를 기록한다.

금지:

- 운영 current 전환
- 운영 서비스 재시작
- 실사용자 업로드 삭제

완료 조건:

- 관련 테스트와 Ruff 통과
- `GROK-W2-SECOND-BRAIN-RETRACT-20260921.json` 작성

### W3 — Phone History 양방향 연동

수행:

- `SecondBrainSink.export()`가 upload ID와 digest를 보존하게 한다.
- `SecondBrainSink.retract(upload_id)`를 구현한다.
- HTTP API를 사용할 경우 base URL과 인증 환경변수 이름만 설정에 기록한다.
- 오류·404·receipt 지연 시 pending 상태를 유지한다.
- upload→retract→receipt→검색 제거→CAS tombstone을 sandbox에서 검증한다.

완료 조건:

- Phone History 테스트 통과
- 운영 서비스가 아닌 격리 서버 E2E evidence 작성
- `GROK-W3-PHONE-HISTORY-20260921.json` 작성

### W4 — JARVIS 실제 종단 준비

수행:

- 실제 provider·MCP profile·issuer·read/write 권한의 존재 여부를 확인한다.
- 값이 없거나 인증이 불가능하면 즉시 `OWNER_BLOCKED`로 기록한다.
- 값이 제공된 경우에만 다음을 실행한다.
  - JARVIS A write
  - Second Brain request journal 확인
  - 완료 receipt 확인
  - JARVIS B 또는 새 세션 read
  - 권한 회수·만료 fence·삭제 후 재검색 거부

완료 조건:

- 실제 인증 경로의 write→receipt→new-session-read evidence
- 합성 fixture와 실제 provider 결과를 별도 기록
- `GROK-W4-JARVIS-E2E-20260921.json` 작성

### W5 — 품질과 운영 안정성

수행:

- 전체 basedpyright 오류의 원인을 분류한다.
- import cycle·scoped request 타입 오류·테스트 mock 오류를 수정 가능한 범위에서 해결한다.
- 웹 서비스 OOM 재현 여부와 메모리 peak를 기록한다.
- refresh·maintenance·backup timer와 구형 유닛을 구분해 상태를 문서화한다.
- 같은 source commit에서 pytest·Ruff·basedpyright·build를 실행한다.

완료 조건:

- 실패한 게이트가 없거나 각 실패가 명확한 `OWNER_BLOCKED` 사유를 가짐
- `GROK-W5-QUALITY-OPS-20260921.json` 작성

## 최종 제출 형식

다음 파일을 작성한다.

- `GROK-MEMORY-INTEGRATION-REPORT-20260921.md`
- 단계별 JSON evidence W0~W5

보고서에는 다음 표를 포함한다.

| 단계 | 상태 | commit | 테스트 | 운영 변경 | 남은 문제 |
|---|---|---|---|---|---|
| W0 |  |  |  |  |  |
| W1 |  |  |  |  |  |
| W2 |  |  |  |  |  |
| W3 |  |  |  |  |  |
| W4 |  |  |  |  |  |
| W5 |  |  |  |  |  |

`W4`의 실제 인증 정보, 운영 release 전환, 실사용자 데이터 삭제, 서비스 재시작이 필요하면 작업을 중단하고 오너 승인 요청으로 남긴다. Codex가 최종 독립 검증하기 전에는 “완료”라고 선언하지 않는다.
