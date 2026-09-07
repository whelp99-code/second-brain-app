# 준비 상태와 백업 검증 — R8/I6

2026-09-08. 구현 전 결정: `/ready`의 파일 mtime 기반 백업 판정과 시간·요청 장애 누락을 수정한다. 실제 백업 검증은 별도 CLI에서 격리된 임시 경로로 복원하여 체크섬·원장·인용 검사를 재사용한다. 운영 세대를 활성화하거나 기존 자료를 대체하지 않는다.

검증 기록은 archive checksum·파일 identity·백업 생성 시각·검증 시각에 결합한다. `/ready`는 기록을 읽고 identity가 달라진 파일을 거부하며, 큰 archive를 매 HTTP 요청마다 해시하거나 복원하지 않는다. 검증 성공 기록과 전체 runtime의 tombstone/서명/복원 활성화 인수는 구분한다.

준비 상태는 마지막 실행 성공·완료 시각, 미해결 derivation, 요청 journal 가독성·정체·최근 실패를 명시적인 check/reason으로 반환한다. 백업/실행 48시간, pending/processing 15분을 기본으로 설정 가능하게 한다. 오래된 실패 이력은 집계로 남기되 최근 실패와 분리한다. 예외는 degraded로 반환하고 조회로 journal을 생성하지 않는다.

검증 계획: 오래된 성공/새 실행 실패, 파일만 있는 백업/손상/검증 후 바꿔치기, 검증 기록 시각 오류, 오래 멈춘 요청과 손상 journal, 실제 CLI backup/verify-backup 및 HTTP ready/health. 기존 managed generation reader 해제 회귀를 유지한다.


## 구현 결과

- `sb backup`의 기본 경로에 검증을 연결하고 기존 archive를 검사하는 `sb verify-backup <archive>`를 추가했다. 검증은 기존 `restore_backup`의 checksum·파일별 manifest·SQLite ledger·citation 검사를 재사용한다. 성공 기록은 원자적으로 기록하고 fsync한다.
- archive 이름·SHA256·device/inode/size/mtime/ctime·생성/검증 시각·원 저장소 identity를 기록한다. 관리형 백업은 임시 snapshot 경로 대신 provider identity와 source generation의 tombstone sequence/root를 보존한다.
- 준비 상태는 보관 파일의 존재나 mtime만으로 검증 성공을 추정하지 않는다. mtime은 가장 최근 파일 후보를 선택하는 데만 쓰고, 신뢰 판정은 검증 기록과 현재 identity·생성 시각·origin·tombstone 일치로 한다. 새 백업이 손상되면 이전 정상 백업을 별도로 표시하되 전체 상태는 degraded로 유지한다.
- 관리형 검증은 기존 generation exclusion과 요청 `BEGIN IMMEDIATE` 잠금을 유지한다. 검증 중 새 정정/삭제를 접수하지 못하며, provider 또는 삭제 이력이 다른 archive는 임시 복원 전에 거부한다. 원본 차단을 우회하는 복원 기능을 만들지 않았다.
- readiness는 ledger 전체 materialization·raw 파일 통계 수집 대신 read-only SQL로 마지막 실행과 미해결 실패를 집계한다. 요청도 read-only transaction으로 counts·oldest pending/processing·최근 terminal failure·시간 오류를 읽는다. journal이 없거나 손상되면 초기화하지 않고 degraded로 표시한다.
- `/health`는 생존 200을 유지하고 `/ready`는 조건에 따라 200/503과 안정적인 reason code를 반환한다. SQLite에 잘못된 BLOB run metadata가 들어 있어도 JSON 응답을 깨뜨리지 않는다.

## 주요 판정

| 경우 | 판정/코드 |
|---|---|
| 백업 파일만 있고 검증 기록 없음 | VERIFIED_BACKUP_UNAVAILABLE / BACKUP_VERIFICATION_MISSING |
| 최근 백업이 깨짐, 예전 검증 백업은 정상 | LATEST_BACKUP_UNVERIFIED, last_verified_backup으로 이전 파일 별도 표시 |
| 검증 후 archive 변경·바꿔치기 | BACKUP_CHANGED |
| 검증 기록의 생성/검증 시간이 미래·역순 | BACKUP_TIME_INVALID |
| 생성 또는 검증 후 기본 48시간 경과 | BACKUP_STALE |
| 다른 저장소 또는 origin 미상 archive | BACKUP_ORIGIN_MISMATCH |
| 관리형 provider/삭제 sequence/root 불일치 | BACKUP_TOMBSTONE_OR_PROVIDER_MISMATCH |
| 마지막 실행 실패·없음 | LAST_RUN_UNSUCCESSFUL |
| 오래되거나 시각이 잘못된 실행 | LAST_RUN_STALE_OR_INVALID |
| 미해결 파생 작업 실패 | DERIVATIONS_FAILED |
| pending/processing이 기본 15분 초과 | REQUESTS_STALLED |
| 기본 최근 48시간 failed/expired/reapproval_required | RECENT_REQUEST_FAILURES |
| 요청/세대 journal 손상·누락 | REQUEST_JOURNAL_UNREADABLE / GENERATION_JOURNAL_UNREADABLE |
| proved 이전 세대 정리가 기본 15분 초과 | GENERATION_CLEANUP_STALLED |

시간 설정은 README의 `[readiness]`에 명시했다. 오래된 terminal 실패는 counts에 남기되 최근 장애와 분리한다. pending의 나이는 accepted_at부터 계산하므로 반복 상태 갱신으로 정체를 감추지 않는다.

## 실제 사용 검사와 한계

`TMPDIR=/var/tmp uv run python -m scripts.readiness-acceptance`는 독립 temp vault에서 실제 CLI subprocess와 HTTP 서버를 사용한다. run 행은 fixture로 seed했으며 LLM 수집 실행을 검증한 것은 아니다. 생성된 인용 페이지·CAS를 백업/검증하고, 관리형 generation에서도 CLI backup의 provider/삭제 이력을 확인한다.

관측: 최초 health 200/ready 503 → CLI backup 검증 후 ready 200 → archive 손상 후 ready 503, health 200 유지. 손상 archive의 verify-backup exit 1, 임시 복원 잔여 0. 검증 파일 37개인 fixture였으며 대용량 성능 실적이 아니다. 로그는 `/var/tmp/sb-readiness-final-acceptance.log`.

추가 테스트는 다른 vault 백업 오인 방지, 관리형 origin 보존, 검증 중 요청 writer 차단, 오래된 tombstone의 복원 전 거부, 세대 reader 해제, 시간/상태/손상 오류를 포함한다. 전체/집중 최종 수치는 아래 실행 완료 기록을 따른다.

보류·미완료:

1. 운영 서비스 배포·설정 적용과 기존 운영 archive의 검증은 수행하지 않았다. origin 없는 예전 archive의 출처를 추정해 정상으로 승격하지 않는다. 새로 만든 백업을 검증해야 한다.
2. 이 receipt는 격리 vault 복원 검사의 증거다. 완전한 runtime 재기동·현재 권한/서명 재검증·복원 세대 활성화 인수는 계속 별도 조건이다.
3. HTTP마다 archive를 재해시하지 않는다. 정기 backup/verify-backup 실행이 필요하다. 검사에는 archive 외 추가 복원 공간·I/O·잠금 시간이 들며 대용량 p95와 잠금 단축은 I5 후속이다.
4. 실제 자비스 adapter 인수 receipt의 readiness 결합, 전체 운영 부하·용량·재해 복구 인수는 남는다. 이번 변경으로 모든 앱의 공통 기억 사용 완료를 주장하지 않는다.


## 최종 실행 완료 기록

- 표준 전체: **591 passed / 2 skipped, 158.89초**. `TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py`. `/var/tmp/sb-readiness-final-full.log`.
- 관련 집중: **36 passed, 13.36초**. readiness·기존 ops·managed runtime·request backup/restore 포함. 전체 실행과 중복이다. `/var/tmp/sb-readiness-safe-focused.log`.
- Ruff 전체 sb/tests 및 실제 인수 script 통과, diff check 통과. readiness/readiness_checks/backup_verification/CLI 타입 검사 **오류 0 / 경고 0**. 기존 ops의 private-use 경고 1개와 runtime_backup의 미사용 반환값 경고 2개는 이번 검사에서 별도로 관측했으며 이번 기능 변경이 추가한 경고는 아니다.
- 실제 CLI/HTTP 인수: health 200 유지, ready 503→200→503, 손상 verify exit 1, 검증 파일 37개, 임시 복원 잔여 0. 관리형 CLI backup도 origin `provider:provider:second-brain:linux`와 tombstone sequence 0 보존을 확인했다. 운영 release/서비스/active generation은 변경하지 않았다.
