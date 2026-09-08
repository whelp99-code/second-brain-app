# 남는 정상 백업의 무결성·정정·취소·복원 인수

## 판정과 수정 원인

이전 압축 사본 처분 다음의 운영 공백을 수정했다. 삭제 대상과 무관한 canonical archive를
보존하면서 정정/취소를 완료하고, 중단 복구 뒤 그 백업을 실제로 복원했다. 중앙 기억 전체
목표와 취소의 최종 외부 완료 계약은 계속 진행 중이다.

기존 `RequestExecutor._validate_managed_lifecycle`은 백업 root의 모든 항목을 디렉터리와
`schema_version=1` manifest로만 인정했다. 반면 `create_backup`/`backup_runtime`은 압축
archive와 `.sha256` 파일을 만든다. 이 두 기존 경로의 형식 불일치로, 정정 대상 백업을 지운
뒤에도 무관한 정상 archive 때문에 `reconciling / UNMANIFESTED_BACKUP`에 멈췄다.

`test_unrelated_canonical_backup_survives_correction_and_restores`에서 위 실패를 먼저
재현했다(수정 전 1 failed / 2.93초). 해당 백업을 무조건 제거해 통과시키지 않고 정상 사본을
보존하는 방향으로 구현했다.

## 구현

- `sb/managed_backup_manifest.py`: archive/checksum 묶음과 기존 manifest 디렉터리를 인식한다.
  지원 압축 형식을 기존 제한 검사로 먼저 확인하고 checksum을 대조한다.
- 내부 canonical manifest와 실제 regular member의 전체 집합·경로·크기·SHA-256·사용자 권한
  비트를 스트림으로 대조한다. 중복·누락·추가·경로 이탈·초과 예산은 거부한다.
- 디스크에 해제하지 않으며 manifest 32 MiB, 내용 합계 10 GiB, 파일 100,000개 한도를 둔다.
  파일을 다시 열 때와 검사 종료 때 inode/크기/mtime/ctime의 일치를 확인한다.
- `.sha256`와 선택적 `.verified.json`의 고아 파일을 거부한다. 기존 verification receipt는
  보존용 sidecar이며 이 검사가 그 영수증의 시점·origin·최신 권한을 인정하는 것은 아니다.
- 기존 처분 체크포인트 작성 전에도 동일 검사를 실행한다. 잘못된 잔여 manifest가 있으면
  pointer를 바꾸거나 처분 완료 증거를 기록하지 않는다. 최종 proof 검증에서도 다시 검사한다.
- 별도 기억 DB·작업 queue·Proxy·외부 route를 추가하지 않았다. SB 정본/JARVIS 실행의 역할과
  네 OSS 선별 흡수 방향을 유지한다.

추가 검토에서 서명 요청용 canonical JSON 검사를 재사용하면 유효한 NFD 유니코드 origin과
JSON 공백 표현을 거부함을 2개 실패 검사로 확인했다. backup manifest의 형식에 맞춰 별도
중복 키 거부와 엄격한 필드 검증으로 수정했다. 백업 생성기의 경로를 강제 정규화하거나
데이터를 바꿔 검사에 맞추지 않았다.

## 실제 사용 검증

증거: `/var/tmp/retained-backup-acceptance-53c2k881/result.json`.
실행 스크립트: `/var/tmp/retained-backup-process-acceptance.py`.

합성 기억을 provider에 저장하고 관련 export와 runtime archive를 생성했다. 이와 별도로 Git,
CAS, 원문 인용 및 분해형 유니코드 경로(`e + U+0301`)를 가진 다른 기억 vault의 정상 backup을 같은 관리 root에 배치했다. 정정과 취소
각각에서 원본 세대 제거 직후 프로세스를 exit 77로 종료하고 새 프로세스로 복구했다.

| 시나리오 | 복구 PID / 결과 | MCP 이전→이후 PID | 보존·복원 |
|---|---|---|---|
| 정정 | 3757299 / `proved` | 3756900→3758258, stale→healthy | 무관한 archive SHA-256 불변, 37개 파일 실제 복원 |
| 취소 | 3760522 / `generation_active` | 3759706→3760804, stale→healthy | 무관한 archive SHA-256 불변, 37개 파일 실제 복원 |

두 시나리오 모두 이전 본문 검색 0건, 관련 archive/export/원본 세대 제거를 확인했다. 정정된
새 본문은 1건이고 취소된 replacement는 0건이다. active/backup/export 검사에서 일치 0,
오류 0이다. 운영 서비스·vault·자비스 DB는 변경하지 않았다. 실제 LLM 요약 품질이나 사용자
프로젝트 권한을 이 합성 자료 검사로 입증하는 것은 아니다.

## 테스트와 남은 조건

새 검사 17개: 정상 사본 보존/실제 복원, 해시·크기·권한·checksum 불일치, 누락·추가·중복
member, 중복 manifest entry, 이탈 경로, 점 경로, 선택적 sidecar 읽기 불변, 고아 sidecar,
잘못된 사본이 있을 때 전환/체크포인트 없음. 유니코드 origin·JSON 공백 표현·중복 JSON 키까지 포함해 모두 통과했다(4.26초).
변경 제품 4개 모듈의 basedpyright 오류 0·경고 0, Ruff/diff 검사를 통과했다.
최종 리뷰에서 legacy manifest 누락 시 `FileNotFoundError`에 로컬 경로가 포함됨을 재현하고
일정한 `UNMANIFESTED_BACKUP` 코드로 정규화했다. 누락·잘못된 JSON·권한 오류의 경로 비노출과
기존 디렉터리 형식 유지 검사 4개를 추가했다.

확정 제품 커밋: **`5d9f7d4`**. [기계 판독 인수 기록](RETAINED-BACKUP-ACCEPTANCE-2026-09-08.json).

- 전체 회귀: **1,024 passed, 2 skipped / 189.42초**. 마지막 오류 정규화 전 실행이다.
- 오류 정규화 후 최종 백업 관련 회귀: **45 passed / 25.60초**. 기존 전체와 중복되며 신규 4개를 포함한다.
- 최종 제품 4개 모듈 basedpyright 오류 0·경고 0, `ruff check sb tests`/diff 통과.
- 오류 정규화 후 실제 프로세스·stdio MCP·백업 보존·복원을 위 최종 경로에서 재실행했다.

전체 로그 `/var/tmp/sb-retained-backup-final-test.log`, 최종 관련 로그
`/var/tmp/sb-retained-backup-focused-test.log`. 실패를 수정하는 동안의 이전 전체 1,021 통과와
이전 실제 실행은 최종 수치에 추가로 합산하지 않았다.

이 검사는 backup 파일 집합의 무결성이다. 원장 내용의 의미적 정확성, 최신 tombstone/ACL을
적용한 운영 restore 권한, RPO/RTO의 완료를 의미하지 않는다. 임의 ZIP/xz/bz2/Git pack/sparse/
연결 gzip은 이전과 같이 보류한다. 원본 제거 후 관리 inventory가 달라진 경우 및 오래된 버전의
체크포인트 누락 복구도 별도 조건이 필요하다.

다음 P0는 취소의 최종 결과/상태/서명 영수증/MCP와 자비스 seq1 완료→정상 V2 seq2 연결이다.
native 보존면·범위 권한·출처 계보·실제 자비스 앱 순환·자동 수집/주입·검색 평가·GUI·운영 인수는
이전 14개 잔여 목록을 유지한다. 내부 generation_active를 자비스의 최종 완료로 확대하지 않는다.
