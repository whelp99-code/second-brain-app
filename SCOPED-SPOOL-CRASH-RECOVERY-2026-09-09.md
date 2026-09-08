# 자비스 scoped spool의 발행 중단 복구 인수

2026-09-09. 이전 private spool 구현은 진전이었다. 이번 JARVIS `65f1e15`에서 hardlink 생성 직후 종료로 임시 link가 남는 문제를 수정했다.

범위 spool의 publish 재시도는 v4 현재 시각/provider/bytes 검증 이후에만 복구한다. 정확히 같은 최종 파일·임시 파일 inode/link2·같은 요청 bytes와 종료된 publisher PID를 확인한다. 최대4096개 이름만 검사하며, live/reused PID와 출처 불명 link는 손대지 않는다. 최종/임시/root를 재검사 후 해당 임시 링크만 제거하고 directory fsync·최종 nlink1/bytes를 다시 확인한다. 일반 reader의 link1 규칙은 유지한다.

## 실행 근거

- scoped spool9/기존 private4/자동 발행6 **19 passed / 6.45초**.
- backend 타입·변경 파일 ESLint·격리 emit 및 helper Ruff·diff 검사 통과.
- 실제 수정 전 compiled publisher에서 fs.linkSync 후 exit73: final+temp link2, 일반 reader 거부, 새 프로세스 publish 재시도도 MEMORY_SPOOL_FILE_INVALID.
- 수정 후 같은 종료 지점: reader는 계속 거부하고 명시적 publish retry에서 created=false/request 일치/link1/임시 파일0/동일 inode·bytes로 복구했다. 전후 각3개 프로세스이며 기존 정상/FIFO 인수도3개 프로세스로 재실행했다.
- [전후 JSON](SCOPED-SPOOL-CRASH-RECOVERY-2026-09-09.json). `TMPDIR=/var/tmp uv run python scripts/scoped-spool-crash-acceptance.py <격리 JARVIS build 경로>`로 수정 후를 재현한다. `--expect-unfixed`는 이전 빌드의 실패 확인용이다.

## 남은 경계

합성 자료·임시 디렉터리·Linux/POSIX 파일시스템 검증이다. provider 호출0·승인 소비false를 유지한다. PID 재사용은 복구를 거부하는 가용성 제한이 있다. 최종 link 생성 전의 단독 임시 파일, 만료·삭제 inventory, 외부 비협조 writer와 다중 OS 전체 인수는 아직 남는다. 근거 없이 임시 이름을 일괄 삭제하거나 일반 hardlink를 허용하는 방식은 보류한다.

승인 단일 소비·outbox 원자적 확정·공개 v4 계약·실제 권한/영수증 연결과 전체 M1~M14 목표는 유지한다. 운영 서비스/DB/설정을 변경하지 않았고 전체 Python/JARVIS 검사는 이번에 재실행하지 않았다.
