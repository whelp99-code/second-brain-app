# 취소 DB 교체 전 중단 재구축 인수

2026-09-08. JARVIS 제품 `112c520`, Second Brain 제품 `9e30115` 유지.

## 구현

recoverCancellation은 현재 DB의 device/inode/세대가 저장된 원본과 일치하고 결과 inode가 없는 경우 기존 입력으로 재구축한다. transaction 안에서 현재 검증 결과 digest, correction/lane/대상/범위/삭제 이력, layout 문자열, source/result 세대, 미완료 상태, 영수증 부재를 대조한다. 기존 job의 fence를 증가시키고 동일 입력·체크포인트를 재사용한다.

기존 소스 DB에서 새 파일을 다시 만들며, spool을 이미 제거한 경우 검증된 체크포인트가 있어야 한다. 최초 요청의 자동 재전송이나 무조건 재실행을 추가하지 않았다. 현재 provider 신뢰와 runtime 배제, 로컬20 검사는 기존 경로를 따른다.

## 검증

최종 관련 2파일 **10 passed, 49.05초**. 신규 build 전 실패·사본 처분 뒤 swap 전 실패·변경된 layout 거부를 포함한다. 동일 job/input/receipt 각1행, 무관한 경로로 재구축 없음, cursor0 유지, 기존 old-FD 복구를 확인했다. 최종 noEmit·대상 ESLint·diff check 및 제품 격리 emit 통과.

실제 인수 스크립트에 --rebuild-result를 추가했다. 실제 SB CLI 결과를 저장한 뒤 별도 Node PID529700이 검증 재료 수집·fresh DB 생성·사본 처분을 실행하고 swap 진입 직전 exit77로 종료했다. 이 중단은 인수용으로 private swap 경계에 주입했으며, 앞선 실제 처리 결과를 모의 응답으로 대체하지 않았다.

새 Node PID530132가 원 DB에서 재구축·교체·로컬20검사·영수증 저장을 완료했다. 다시 다른 프로세스로 recover를 실행해 동일 영수증을 확인했다. provider 가상 inventory를 사용하지 않았다.

- provider 결과 digest: `sha256:971778e901b05f84a34884c4b13302e1d72fe5be72c0709abb5c19f51da5db1e`.
- 로컬 영수증 digest: `sha256:5d9da6b26e108c56bdd7ccbd60a89875c2b6d7e8af9c7116d58307a9a3914be3`.
- exit_before_swap=77, exact_replay=true, spool_preserved=false.
- cursor active_lane_id=null, accepted_through_sequence=0.

[기계 증거](CANCELLATION-PRESWAP-RECOVERY-ACCEPTANCE-2026-09-08.json). 원본 `/var/tmp/cancellation-submit-acceptance-6i3de8wb/result.json`.
재현: `scripts/cancellation-submit-acceptance.py ISOLATED_BUILD --rebuild-result`.

## 남은 보류

rename 완료 후 결과 inode 메타데이터 저장 전 중단은 NOT_SWAPPED로 거부한다. 그 순간의 실제 교체를 입증할 별도 근거가 필요하다. 이번 layout 검증은 저장 경로 문자열의 일치이며 외부 작성자나 동일 경로 디렉터리의 교체까지 전역 통제한다고 주장하지 않는다.

다음은 남은 swap 중단 구간 복구와 전체 취소 settlement/cursor, 실제 seq1→V2seq2 인수다. 사용자/프로젝트 ACL, 원작업→기억 계보, native 세션/WAL/백업 수명, 실제 앱 재사용, 클라이언트 수집/주입·검색·GUI·운영 복구의 전체 목표를 유지한다.

운영 설정/DB/서비스·배포·push는 변경하지 않았다. Python 제품 코드를 바꾸지 않아 전체 Python 검사는 재실행하지 않았다. 중앙 기억 운영 완성은 미완료다.
