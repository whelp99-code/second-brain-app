# 취소된 기억 본문 수집·정리 전 증거 보존 인수

2026-09-08. JARVIS 제품 `93f1344`. Second Brain 제품 `9e30115` 유지.
자비스 인계서의 세컨드브레인 기반·네 OSS 선별 흡수·여러 에이전트 공통 기억 방향을 유지한다.
이번 변경은 기존 정정/취소/compactor를 연결하는 결함 수정이다. 별도 기억 DB나 OSS 서버를 추가하지 않는다.

## 재현한 문제와 수정

직전 실제 fixture에서 차단 projection은 2개인데 기존 DB 본문 수집은 0개였고, 정정 대체 본문은 spool에 남았다.
그 상태로 기존 수집 결과만 정리에 사용하면 관리 대상 파일의 본문을 누락할 수 있다.

- 실제 저장된 취소 의향·원 요청·대상·범위·삭제 이력과 spool 파일 digest를 대조한다. 파일 본문으로 원 요청 payload digest도 다시 계산한다.
- 검증된 본문을 기존 compactor의 정리 재료에 합친다. 파일 삭제 전 기존 forbidden content identities와 본문 없는 체크포인트를 같은 SQLite transaction에 저장한다.
- 체크포인트는 원 요청/spool/payload와 실제 해시 식별자 집합에 결합한다. 중단 후 원문이 없어도 검증할 수 있으며, 증거 없이 파일만 없으면 거부한다. 중복 동시 호출은 1행으로 수렴한다.
- 신규 migration074만 추가했다. 체크포인트의 UPDATE/DELETE/REPLACE는 거부한다. 기존 migration bytes는 변경하지 않았다.
- spool 읽기는 비차단·최대 262,144바이트와 추가 1바이트 탐지로 제한한다. 읽기 전후 파일 메타데이터 및 root 동일성을 확인한다. 링크·잘못된 권한·변조를 거부한다.

## 검증 결과

1. 관련 4파일 **23 passed, 24.23초**: 신규 수집 7개, 기존 DB 교체 1개, 취소 결과 저장 8개, migration 7개.
2. 동시 호출·손상 증거 검사 추가 후 관련 2파일 **15 passed, 15.49초**: 신규 수집 최종 9개와 기존 정정 억제 6개. 앞 검사와 중복되므로 합산하지 않는다.
3. 최종 TypeScript noEmit·대상 ESLint·diff check 통과. 제품 코드 격리 emit 통과. 운영 dist를 빌드하지 않았다.
4. 실제 Node 분리 프로세스: 저장 직후 exit77 → 다른 프로세스 재개·실제 spool/JSON 사본 제거 직후 exit77 → 세 번째 프로세스 복구 성공. 저장 체크포인트 1행, 실제 제거 파일 2개, 관리 경로 본문 일치 0개, 무관한 파일 보존. cursor accepted_through_sequence는 0, active_lane_id는 null.

실제 프로세스 PID: 398480 → 398494 → 398515. 원본 증거는 `/var/tmp/cancellation-material-acceptance-jBYT8L/result.json`, 보존 사본은 [JSON](CANCELLATION-MATERIAL-ACCEPTANCE-2026-09-08.json).
재현 스크립트: [scripts/cancellation-material-acceptance.mjs](scripts/cancellation-material-acceptance.mjs). 격리 TypeScript 출력 경로를 인수로 받으며 임시 fixture만 생성한다.

첫 검사에서는 기존 DB 교체가 기본 5초 제한을 넘었다. 30초 제한으로 다시 실행해 4.802초에 통과했다. 새 검사의 Base64 기대도 실패했다. 기존 표현 수집은 원문과 두 단계 JSON 내부 문자열만 지원하므로 기대를 JSON으로 수정했다. Base64/임의 인코딩 지원을 추가하거나 검증했다고 주장하지 않는다.

## 미완료 및 다음 순서

- **P0: 취소 전용 로컬 완료 증거 계약.** 기존 전체 완료 검사는 provider40+JARVIS20+재유입10의 70개 영역을 요구한다. 현재 provider_local_suppressed 결과에는 provider40 inventory가 없다. 가짜 inventory를 만들거나 완료 gate를 낮추지 않았다.
- **P0: 전체 DB 교체와 cursor 연결.** 이번 실제 인수는 본문 수집/체크포인트/관리 파일 처분·재시작까지다. 취소 결과를 사용한 전체 DB 교체·완료 영수증·seq1 취소 후 정상 V2 seq2 처리는 아직 인수하지 않았다.
- **P0: 외부 전송 경합, 사용자·프로젝트 범위, 원작업→기억 계보, native 세션/WAL/백업 수명, 실제 앱부터 새 세션 재사용.** 기존 전체 범위를 유지한다.
- **P1: 복구·검색 품질·에이전트별 수집/주입·운영 가시성.** 원문 제거 후 사본 재유입은 기존 해시 검사로 차단하는 범위이며, 임의 인코딩·압축 및 증거 유실 복구는 별도 과제다.

Second Brain 제품 소스는 이번에 변경하지 않아 Python 전체 검사는 재실행하지 않았다. 운영 서비스의 가동 상태를 조회하거나 설정 활성화·재시작·배포·push하지 않았다. 중앙 기억 운영 완성 판정은 여전히 미완료다.
