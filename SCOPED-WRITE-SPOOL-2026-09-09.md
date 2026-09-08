# 자비스 v4 요청 자료 저장·새 프로세스 재사용

2026-09-09. 이전 codec 연결은 진전이었으며, 이번 JARVIS 제품 `a158052`은 기존 content-free outbox를 위한 v4 private 요청 자료 저장 경로를 구현했다.

기존 private 파일 publisher를 재사용한다. 운영자가 준비한 기존 private root만 사용하고 idempotency digest 이름으로 publish한다. 같은 key/bytes의 재발행은 기존 inode를 보존하며 다른 bytes는 덮어쓰지 않고 충돌로 거부한다. 원본 v1/v3 spool은 유지한다. 현재 시각의 provider v4 codec·원본/범위/digest 검사와 정확한 bytes 비교를 사용한다.

공통 reader에서 무제한 readFileSync와 FIFO open 정지 가능성을 확인해 O_NONBLOCK·사전 크기 제한·제한 readSync·읽은 뒤 descriptor/경로/root identity 재검사를 추가했다. v4는32,768bytes, 기존 호출은4,194,304bytes 이내다. BOM을 자동으로 제거하여 canonical 검사를 우회하지 않도록 보강했다.

## 검증

- 첫 관련27통과. BOM/잘못된 UTF-8 검사 추가 및 기존 자동 발행/파일 검사까지 확대한 최종 **36 passed / 10.62초**. 일부 기존 privacy/concurrency 테스트는 정적 소스 검사이므로 다중 writer 실증으로 취급하지 않는다.
- backend 타입·변경 파일 ESLint·격리 outDir emit, 인수 helper Ruff·양쪽 diff 검사 통과.
- 수정 전 compiled reader: 실제 FIFO에 READY 출력 후2초 timeout. 수정 후 동일 유형 특수 파일은 MEMORY_SPOOL_FILE_INVALID로 종료했다.
- 실제 독립 Node 프로세스3개: 요청 publish 직후 exit73→새 프로세스 read/republish→FIFO 읽기 거부. created=false, request/body 일치, inode 보존, mode0600. provider 호출0, 승인 소비false, outbox enqueuefalse.
- [JSON 증거](SCOPED-WRITE-SPOOL-2026-09-09.json). 재현: `TMPDIR=/var/tmp uv run python scripts/scoped-spool-acceptance.py <격리 JARVIS build 경로>`.

## 남은 조건

이번에는 파일 저장 API를 추가했으며 승인 소비·outbox 확정을 연결한 것은 아니다. 기존 scope review를 memory_confirmation/dispatch로 위장하거나 candidate UNIQUE를 완화하지 않는다. 이 API는 새 queue·provider 권한이 아니다.

hardlink 직후 임시 링크 삭제 전 종료에서 남는 orphan 복구, 완성/임시 파일의 삭제 inventory·만료 수명, 승인 단일 소비와 자료 확정의 원자성을 운영 연결 전에 보강해야 한다. 실제 provider 권한·공개 v4 계약·자비스 영수증 소비 및 전체 M1~M14의 실사용/운영 인수 목표도 유지한다. 전체 Python/JARVIS 검사는 이번에 재실행하지 않았고 운영 DB/설정/서비스를 변경하지 않았다.
