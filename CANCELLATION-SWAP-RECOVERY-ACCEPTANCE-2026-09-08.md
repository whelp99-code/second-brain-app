# 취소 DB 교체 직후 중단 복구 인수

2026-09-08. JARVIS `91f2f95`, Second Brain 제품 `9e30115` 유지.

## 구현과 실제 발견

취소용 새 DB 파일 안에 결과 device/inode/세대와 검사 정보를 교체 전에 기록한다. 파일을 다시 닫고 금지 본문 hash로 검사·fsync한다. 재시작은 현재 파일과 그 안의 기록을 대조해 교체 여부를 판단한다. 사전 물리 검사 digest와 현재 로컬 물리 검사를 함께 사용하며 DB 자신을 포함한 자기 참조 hash라고 주장하지 않는다.

최초 사전 기록 구현의 검사는 old inode가 새 WAL에 재사용되어 FD 검사에서 실패했다. 검사를 생략하지 않고 이전 DB를 동일 디렉터리의 purge별 .retired hard link로 보존하도록 수정했다. single-link source의 정체성을 확인해 보존하고, 실제 old-FD0를 기록한 뒤 정확한 device/inode의 보존 파일만 제거·디렉터리 fsync한다. FD가 남거나 파일 정체성이 다르면 완료를 거부한다.

복구 시 보존 파일이 있으면 과거 FD0 기록만 믿지 않고 다시 열린 파일을 검사한다. source가 여전히 active이면 보존 링크를 정리하고 기존 pre-swap 재구축을 따른다. result가 active이면 사전 정보를 대조한 후 현재 provider 신뢰·체크포인트·spool 부재·로컬20 검사로 동일 영수증을 저장/재생한다.

## 검증

최종 관련 3파일 **22 passed, 83.26초**: 취소 복구10개, 기존 정정 완료·복구11개, 실제 독립 프로세스 old-FD 복구1개. 교체 직후 중단 시 .retired 파일이 실제 이전 inode를 보존하며 복구 후 제거됨을 확인했다. noEmit·대상 ESLint·diff check와 제품 격리 emit 통과.

실제 SB CLI 서명 결과를 입력으로 받은 Node PID569560이 실제 rename 직후 observeOldInode 호출에서 exit77로 종료됐다. 아직 런타임 후속 메타데이터가 기록되기 전이다. 새 Node PID569949가 교체된 DB를 열어 로컬20 검사·영수증 저장을 완료했고, 또 다른 프로세스의 재조회도 동일 영수증이었다. provider 가상 inventory를 사용하지 않았다.

- exit_after_rename=77, exact_replay=true.
- provider 결과 digest: `sha256:59a721462c0c89d07c981c87f76c660fbf96d0d71ed9611d572e25c1cdcd8c4b`.
- 로컬 영수증 digest: `sha256:dd9e9941c7440cc9a42575aff2a910ad79944c01f90eb862696f6a2b71b03b4f`.
- 로컬20 검사, cursor active_lane_id=null/accepted_through_sequence=0 유지.

[기계 증거](CANCELLATION-SWAP-RECOVERY-ACCEPTANCE-2026-09-08.json). 원본 `/var/tmp/cancellation-submit-acceptance-6knc779z/result.json`.
재현: `scripts/cancellation-submit-acceptance.py ISOLATED_BUILD --swap-result`.
중단은 실제 처리 경계의 process.exit(77) 주입이며 전원 장애나 파일시스템 손상을 시험한 결과는 아니다.

## 남은 조건

새 사전 정보가 없는 과거 미확정 교체 파일은 여전히 증거 부족으로 보류한다. 관리 경로 문자열의 일치만으로 같은 경로의 디렉터리 교체를 통제했다고 주장하지 않는다. 직접 DB·외부 native 작성자의 전역 배제도 별도 과제다.

다음은 전체 취소 settlement/cursor와 실제 seq1→정상 V2 seq2 인수다. 사용자/프로젝트 ACL, 원작업→기억 계보, native 세션/WAL/백업 수명, 실제 앱 재사용, 클라이언트 수집/주입·검색·GUI·운영 복구 목표를 유지한다. 로컬 처분 기록을 전체 운영 완료로 해석하지 않는다.

운영 DB/설정/서비스·배포·push는 변경하지 않았다. SB 제품 소스 변경이 없어 Python 전체 검사는 재실행하지 않았다.
