# 실제 런타임 백업으로 자비스 복원 인수

기준79ec701. restore-probe의 디렉터리 copytree 백업을 실제 backup_runtime→tar.gz→restore_backup 격리 해제로 교체했다. 백업에 .recovery/requests/journal.db 및 .recovery/state/generation-journal.db가 있는지 확인하고, 두 정제 복원 후보 모두 .recovery가 없는지 검사한다. 기존 current operational anchor 및 자비스 fence 검증을 그대로 사용한다.

최종 실제 acceptance exit0. /var/tmp/sb-jarvis-restore-o8Dpac, [구조화 결과](JARVIS-RUNTIME-BACKUP-2026-09-10.json). backup.format=runtime-backup, control_journals_present=true. 실제 삭제1→복원→서로 다른 두 scoped client 동시조회/정책 격리·철회→복원 기억 재삭제2→최초 백업 재복원까지 통과했다. 첫 복원 유지1기록, 두 번째 복원0기록, 최종 자비스 highwater2, 두 복원 blocked/scan0이다.

이 검사는 실제 runtime archive 형식을 사용하지만 stale backup 재유입을 시험하기 위해 archive/extracted copy를 격리 probe root 아래에 보존하며 managed backup_root의 자동 처분 시험으로 취급하지 않는다. 백업의 제어 journal은 존재를 확인하고 버리는 자료이지 원장 소실 이후 신뢰를 새로 만드는 근거가 아니다. 모델 호출0, source/authority/session은 합성 fixture이며 JARVIS195b1a7 격리 빌드를 사용한다.

Ruff sb/tests/Python probe 및 diff 검사 통과. 이번 변경은 acceptance 연결부뿐이어서 전체 suite를 반복하지 않았다. 직전 제품79ec701의 runtime backup 정제 수정은 관련19통과·확장1통과 기록이며 최신 전체 suite1690통과는 그 이전 제품 기준이다. 이 범위를 구분한다.

재현: `TMPDIR=/var/tmp PYTHONPATH=. JARVIS_SECOND_BRAIN_CONTRACT_PROFILE=scoped-record-read-v5 node scripts/jarvis-restore-acceptance.mjs /absolute/isolated-jarvis-build/dist`. 운영 DB·서비스·타 리포 변경과 push 없음. 실제 업무·운영 인증·native 수명·원장소실DR 및 전체M1–M14는 미완료다.
