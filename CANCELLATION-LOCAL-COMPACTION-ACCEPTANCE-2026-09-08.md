# 실제 provider 취소 결과→로컬 DB 처분→중단 복구

2026-09-08. JARVIS 제품 `0906655`, Second Brain 제품 `9e30115` 유지.

## 완료한 구현

MemoryAuthorityCompactor.compactCancellation(correctionId)를 추가했다. 현재 신뢰로 검증한 저장 provider 결과에서 원 lane/대상/범위/삭제 이력을 얻고 기존 검증 재료 수집·fresh DB 생성·관리 사본 처분·runtime 배제·파일 교체를 재사용한다. provider40/guard10 inventory를 받거나 대신 생성하지 않는다.

실제 로컬20 검사 후 결과 digest·관리 layout·DB 결과 세대/device/inode·physical scan·reader drain에 결합된 로컬 영수증을 저장한다. 기존 AuthorityDb에 migration075의 입력/영수증 테이블을 추가했고 UPDATE/DELETE/REPLACE를 거부한다. 기존 전체70 영수증은 생성하지 않고 purge 상태는 verifying, cursor는 그대로 둔다.

recoverCancellation은 현재 provider 신뢰와 관리 layout/DB 세대/inode, 체크포인트·spool 부재·실제 로컬 검사를 다시 확인해 동일 영수증을 반환한다. DB 교체 후 영수증 저장 전 실패도 복구한다. 일반 compactor의 전체 완료 계약은 유지한다.

## 실제 재현으로 수정한 복구 결함

- old DB inode 번호가 재사용되면 반복 FD 검사가 이전 DB의 열린 파일로 오인했다. swap에서 실제 old-FD 0 확인 직후 digest를 저장하고 복구 시 검증한다. 저장 증거가 없으면 FD를 다시 검사한다.
- runtime은 재시작 때 항상 1세대로 초기화되어 실제 교체된 2세대 DB를 거부했다. DB에 저장된 단일 활성 세대를 검증해 초기화하도록 수정했다. 최초 실제 분리 프로세스 복구 실패는 성공 수치에 포함하지 않았다.

## 검사와 실제 사용 인수

최종 관련 4파일 **25 passed, 74.42초**: 취소 compaction 6개, 기존 정정 완료·복구 11개, 독립 old-FD 복구 1개, migration 7개. 최종 noEmit/대상 ESLint/diff check 및 제품 격리 emit 통과. 전체 제품 테스트 수치가 아니다.

실제 흐름은 JARVIS DB 의향→Node MCP 접수→실제 Python CLI 처분·서명 결과→JARVIS 결과 저장 후 exit77→별도 Node 로컬 DB 처분·영수증 저장 후 exit77→다른 Node 재개·동일 영수증이다. 이 취소용 경로에는 synthetic provider inventory를 사용하지 않았다. 임시 실제 provider/vault/DB를 이용했으며 운영 서비스 인수가 아니다.

- 외부 접수·실행 소비 Node PID497524, MCP PID497589/497638/497650.
- 로컬 DB 처분 PID497766, 기록 후 exit77. 새 복구 PID497953, 동일 영수증.
- 로컬20 검사 통과, spool_preserved=false. 원 요청의 외부 writer 호출0.
- provider 결과 digest: `sha256:1c2152fd698a6c9b1c54183ae2c6e2c7ac6b077347ed7f087ca116e9c18037a4`.
- 로컬 영수증 digest: `sha256:2b7de4ea3287d74264651366ef0dd109dce096eac3250dfafead49f3e16a94d5`.
- cursor active_lane_id=null, accepted_through_sequence=0. 현재 provider 키 철회 거부도 유지.

[전체 기계 증거](CANCELLATION-LOCAL-COMPACTION-ACCEPTANCE-2026-09-08.json). 원본 `/var/tmp/cancellation-submit-acceptance-t8umocjj/result.json`.
재현: `scripts/cancellation-submit-acceptance.py ISOLATED_BUILD --compact-result`. 기존 --record-result 경로도 재실행해 로컬 처분 없음·spool 보존을 확인했다. 증거 `/var/tmp/cancellation-submit-acceptance-c80kq5ko/result.json`.

## 보류와 다음 구현

1. **교체 전 실패·rename 후 run 메타데이터 저장 전 중단의 자동 복구**: 현재 NOT_SWAPPED로 보류한다. 재료/키/기존 DB와 fresh 파일의 증거를 대조하는 재구축 복구가 필요하다. 무조건 재실행하지 않는다.
2. **전체 취소 settlement와 cursor**: 로컬 처분 기록과 provider 결과를 최신 삭제 이력·현재 신뢰·전송 경합에 결합하고 실제 취소 seq1 완료→정상 V2 seq2를 인수해야 한다. verifying을 전체 완료로 해석하지 않는다.
3. **직접 DB·외부 native 작성자**: 이번 runtime 배제의 전역 보호 밖이다. 관리 작성자 정지·세션/WAL/백업 수명 및 운영 복구가 남는다.
4. 사용자/프로젝트 ACL, 원작업→기억 계보, 실제 자비스 앱→새 세션 재사용, 클라이언트 수집/주입, 검색 품질, GUI·운영 복구의 전체 목표를 유지한다.

운영 DB migration, 설정 활성화, 서비스 재시작, 배포, push는 하지 않았다. SB 제품 코드 변경이 없어 Python 전체 검사는 재실행하지 않았다. 중앙 기억 운영 완성은 미완료다.
