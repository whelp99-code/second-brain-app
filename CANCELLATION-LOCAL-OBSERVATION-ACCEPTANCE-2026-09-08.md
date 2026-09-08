# 취소 DB 교체 검증과 JARVIS 로컬 관측

2026-09-08. JARVIS `89dbfc8`, Second Brain 제품 `9e30115` 유지.

## 구현과 검증된 범위

기존 MemoryManagedSurfaceScanner에 scanLocal()을 추가했다. 기존 파일·SQLite 검사 코드를 재사용해 JARVIS 소유 20개 영역만 실제 검사한다. 저장된 금지 본문 해시가 없거나 읽기 실패·누락·본문 일치가 있으면 거부한다. 결과에는 검사한 해시 집합, 로컬 catalog, 각 영역의 관측과 전체 digest를 결합한다. 기존 70개 완료 inventory와 구별되는 scope/타입이며 반환 값과 각 entry를 동결한다.

취소 fixture의 서명 결과·체크포인트를 포함해 기존 compactor가 실제 SQLite inode를 교체하는 통합 검사를 추가했다. spool/JSON 사본 제거, 무관한 파일 보존, DB 교체 후 동일 취소 결과 조회·체크포인트 검증, cursor 진행 없음이 통과했다. 이후 본문 사본을 다시 만들면 로컬 검사가 거부한다.

**통합 검사의 provider40/재유입10 관측은 synthetic fixture다. 실제 취소 provider가 기존 전체70 계약을 충족했다고 해석하지 않는다.**

## 실제 프로세스 인수

기존 인수 스크립트에 별도 프로세스의 로컬 검사를 추가했다. 임시 실제 AuthorityDb와 spool만 사용한다.

- PID422238: 검증 재료/체크포인트 저장 후 exit77.
- PID422293: 재시작 후 실제 관리 파일2개 제거, 관리 본문 일치0·무관한 파일 보존 후 exit77.
- PID422307: 새 프로세스에서 체크포인트1행으로 재개, 본문 재수집0, provider/guard 관측 입력 없이 JARVIS20개 로컬 검사 통과.
- 로컬 scope: jarvis_managed_local_observation. digest: `sha256:fddb3fa18022f08c5e5ea45c4c00fe2224f3f1e5ba85fd7cd10889c3693ceddc`.
- cursor accepted_through_sequence=0, active_lane_id=null.

[기계 증거](CANCELLATION-LOCAL-OBSERVATION-ACCEPTANCE-2026-09-08.json), [재현 스크립트](scripts/cancellation-material-acceptance.mjs).
원본 실행 결과: `/var/tmp/cancellation-material-acceptance-wsKHY3/result.json`.

최종 관련 3파일 **6 passed, 11.55초**. TypeScript 격리 emit, 대상 ESLint, git diff check 통과. 기존 70개 catalog/검사 회귀를 포함한다. 전체 제품 테스트를 재실행한 수치가 아니다. 운영 dist·설정·DB·서비스·배포·push는 변경하지 않았다.

## 다음 구현과 보류

1. 로컬 관측을 특정 취소 intent/result, 삭제 이력, 관리 root 및 DB 교체·작성자 정지 증거와 결합한 불변 완료 기록으로 연결한다. 현재 scanLocal은 시점 관측이며 그 뒤의 파일 변경이나 외부 작성자 활동을 막지 않는다.
2. 기존 provider40 inventory를 요구하는 compactor와 취소 provider 결과 사이의 범위 차이를 해결한다. 이번에는 가짜 inventory를 추가하거나 완료 gate를 낮추지 않았다.
3. 위 증거와 현재 신뢰를 확인한 뒤 cursor 완료 및 실제 취소 seq1→정상 V2 seq2를 인수한다. 자동 건너뛰기는 보류다.
4. 사용자/프로젝트 범위, 원작업→기억 계보, native 세션·WAL·백업 수명, 실제 앱→새 세션 사용, 클라이언트 수집/주입, 검색 품질, GUI·운영 복구 인수는 기존 목표 그대로 유지한다.

이번 변경은 기존 중앙 기억 수명주기의 증거 연결을 전진시킨 것이다. 세컨드브레인 정본·자비스 실행·네 OSS 선별 흡수 방향을 유지하며 중앙 기억 운영 완성으로 판정하지 않는다.
