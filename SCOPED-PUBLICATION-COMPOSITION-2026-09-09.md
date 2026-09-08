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

## 후속: 최종 read 이후의 권한 철회

JARVIS `53c67b1`. 최종 spool.read 중 정책을 철회해도 prepared를 반환하는 회귀1실패를 재현했다. 파일 확인 뒤 기존 준비 경로를 다시 실행하여 현재 정책·원본 근거·범위 검토와 같은 canonical 요청인지 확인하도록 수정했다.

최종 관련23 passed/12.53초, 타입·변경 파일 ESLint·격리 emit·diff 검사 통과. read 도중 정책·원본 verification·범위 검토 철회3경우를 포함한다. DB 철회 주입은 해당 transaction rollback으로 취소되므로 독립 철회 지속성의 증거로 취급하지 않는다.

실제 독립 Node4개 인수에서는 private 정책 파일을 최종 read 직후 갱신하여 MEMORY_SCOPED_WRITE_POLICY_INVALID로 준비 결과를 차단했다. 이 변경은 DB rollback과 무관하며 후속 프로세스에서도 거부했다. 최초 발행 후 exit73·같은 요청 재시도·bytes/inode/DB 행 보존도 유지했다. [후속 실행 JSON](SCOPED-PUBLICATION-FINAL-READ-2026-09-09.json). 기존 인수 script가 최종 read 중 철회 시나리오까지 재현한다.

provider 호출0·outboxfalse·writes_authorizedfalse인 준비 단계다. 승인 단일 소비·outbox/공개 계약·운영 권한과 M1~M14 전체 인수 조건은 유지한다. 운영 DB/설정/서비스 변경과 전체 Python/JARVIS 재검사는 수행하지 않았다.
