# v4 요청 bytes의 발행·강제 종료 복구

2026-09-09. 이전 원장 metadata 연결·검증·커밋은 진전으로 확인했다. 이번에는 실제 요청 파일 발행 단위를 구현했다.

## 구현

기존 `stable_requests._publish`의 directory flock, private file 검사, temp write/fsync, hard-link publication, directory fsync, temp 제거와 복구를 재사용한다. 기존 v1/v3 복구 parser와 크기 제한은 기본값으로 유지하며 v4에만 별도 검증 callback/33,792bytes 봉투 상한을 전달한다. 디렉터리 소유자와 0700 권한도 파일을 쓰기 전에 확인한다.

`publish_scoped_pending`는 v4 요청을 재검증하고 schema4 pending 봉투를 만든다. 복구 시 정확한 canonical bytes·원본 요청 일치·기존 시각이 재시도보다 미래가 아님을 확인한다. 기존 파일이 있으면 최초 bytes와 accepted_at 필드를 보존한다. 반환 전에 파일을 O_NOFOLLOW로 다시 열어 inode·권한·links·내용을 재검증하고 발행값과 일치해야 한다. 파일 digest는 별도 `second-brain/inbox-write-request/v4` domain을 쓴다.

이 함수는 디렉터리 내 파일만 발행한다. RequestStore 수락 row·scope review 소비·provider 효과는 만들지 않는다. 봉투의 accepted_at 필드는 향후 원장 수락과 일치시킬 시각이며 이 파일만으로 accepted 응답을 반환해서는 안 된다. 현재 권한·replay 검사 후 호출하고, 파일 digest를 원장에 확정하는 다음 단계가 필요하다.

## 검증

- 초기 신규/v3/journal 검사31통과. 반환 전 재검증 추가 후 같은 범위와 walking skeleton **33 passed / 5.86초**. 이후 타입 오류 처리 조건을 정리하고 신규3통과.
- 최종 기존 write requests+신규 발행 **30 passed / 0.47초**. 위 실행에는 중복 테스트가 포함되므로 단순 합계로 보고하지 않는다. 전체 SB Ruff·helper Ruff·diff 검사 통과.
- 실제 Python 프로세스4개: temp write fsync 직후, pending publish fsync 직후 각각 `os._exit(73)`로 종료하고 새 프로세스로 복구했다. 두 경우 모두 원본 bytes·최초 시각·file digest 동일, 최종 파일1개, journal row 생성0.
- 변조 파일, 심볼릭 링크, 공개 권한 디렉터리 거부 및 기존 대상 파일 미변경을 검증했다. 합성 v4 요청·임시 private 디렉터리이며 끝난 뒤 정리했다.
- [실행 결과](SCOPED-REQUEST-PUBLICATION-2026-09-09.json), `scripts/scoped-request-publication-acceptance.py`로 재현한다. 전체 Python/Vitest·운영 서비스/실제 모델 검증은 이번에 재실행하지 않았다.

## 보류·다음 단계

기존 v1/v3 parser를 완화하거나 v4 요청을 v3로 재명명하는 방식은 채택하지 않았다. 파일만 존재하는 상태를 수락/처리 완료로 노출하지 않는다. 실제 수락 경로에 v4를 연결하려면 원장 replay 확인→현재 권한 확인→발행→file digest와 원장 기록→재시도 원본 수락 재현을 완성해야 한다. 자비스 검토 단일 소비/outbox, provider 실행기·완료 영수증·새 agent 회수도 계속 남는다. 전체 목표를 이번 파일 발행 단위로 축소하지 않는다.
