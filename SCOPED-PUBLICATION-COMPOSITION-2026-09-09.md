# 자비스의 현재 권한 검사→v4 불변 자료 발행 연결

2026-09-09. 이전 발행 중단 복구는 진전이었다. 이번 JARVIS `862913e`는 기존 요청 생성기와 private spool을 `publishMemoryScopedWriteRequest`로 조합했다.

명시적 private root·현재 정책 resolver·clock으로 실행한다. IMMEDIATE transaction에서 원본 권한/검토/정책을 확인하고 파일을 발행한 뒤 요청을 다시 생성해 canonical bytes 일치를 확인한다. 최종 파일을 읽고 반환 직전에도 만료를 검사한다. 시각 역행·잘못된 시각을 거부한다. 반환은 kind prepared/writes_authorized false이며 provider 접수·승인 소비·outbox 등록을 뜻하지 않는다.

## 검증

- 최초 관련19통과 후 파일 재확인 도중 만료를 추가 검증해 최종 **20 passed / 10.48초**. 정상 재시도와 DB 행 불변, 발행 뒤 철회·만료·역행·변조·read 후 만료 거부를 확인했다.
- backend 타입·변경 파일 ESLint·격리 emit·양쪽 diff 검사 통과.
- 실제 CLI 생성 원본, 서명 owner review, private 정책 파일을 사용한 별도 Node 프로세스3개: 발행 후 exit73→새 프로세스 동일 요청/bytes/inode 재사용→정책의 agents 제거 후 MEMORY_SCOPED_WRITE_POLICY_INVALID. DB 행 수 불변, provider 호출0, outbox enqueuefalse.
- [JSON 결과](SCOPED-PUBLICATION-COMPOSITION-2026-09-09.json). 재현은 JARVIS cwd에서 `TMPDIR=/var/tmp node /home/jm/orca/projects/second-brain-app/scripts/scoped-publication-composition-acceptance.mjs <격리 build 경로>`다.

## 남은 조건

발행 후 검증이 실패하면 파일은 남을 수 있으나 성공을 반환하지 않는다. 이후 승인 소비/outbox 확정 경로는 현재 권한을 다시 확인해야 하고 파일의 존재만으로 발행 권한을 추론할 수 없다. prepared를 accepted/proved로 취급하는 방식은 보류한다.

미사용 파일 삭제 inventory·만료 수명, 승인 단일 소비/outbox 원자적 확정, 공개 v4 계약과 실제 provider 권한·영수증 소비 및 전체 M1~M14 실사용 목표는 남는다. 전체 Python/JARVIS 검사를 이번에 재실행하지 않았고 운영 서비스/DB/설정을 변경하지 않았다.
