# 취소 완료와 처리 위치의 원자적 저장 인수

2026-09-08. JARVIS `ea076ae`, Second Brain 제품 `9e30115` 유지.

## 구현

settleCancellation은 runtime 배제 안에서 로컬 복구·현재 검사를 수행한 뒤 immediate transaction으로 현재 provider 신뢰와 저장된 exact 로컬 영수증을 다시 검증한다. 신규 완료는 원 요청이 미전송 상태이며 실제 억제 근거가 있고, 진행 중인 lane 없이 직전 순번에서 이어지는 경우만 허용한다.

migration076의 불변 완료 기록과 cursor 증가를 같은 transaction에 저장한다. cursor 실패 시 완료 기록도 롤백된다. 재생은 동일 기록을 반환하며 두 번 증가하지 않는다. SQL binding은 provider 결과·로컬 입력/영수증·삭제 이력·직전 cursor를 대조하고, 증거 없는 idle cursor 증가를 차단한다. 기존 active 요청의 accepted 흐름과 취소 원 요청의 재전송 금지는 유지한다.

## 검사 및 실제 사용 검증

최종 관련 3파일 **29 passed, 96.46초**: 취소 compaction/settlement11개, 기존 정정 완료·복구11개, migration7개. cursor 갱신 실패 주입→settlement0행, 재시도→sequence1, 동일 재생→sequence1 유지, 증거 없는 sequence3 직접 증가 거부, 현재 provider 키 철회 거부를 확인했다. 타입/대상 ESLint/diff check와 격리 emit 통과.

실제 SB CLI가 발급한 provider 결과를 사용했다. Node PID600624가 로컬 DB 처분과 settlement를 저장한 직후 exit77로 종료했고, 새 Node PID600829가 동일 로컬 영수증 및 완료 기록을 재생했다. provider 가상 inventory를 사용하지 않았다.

- provider 결과 digest: `sha256:df5fa0bf1d099fc9fd31abef6c05f1c91676c2a6bb406513dfcd03f162e45335`.
- 로컬 영수증 digest: `sha256:86c83b366e6513b25848d79b3b056e4787a8bb6d6fabe0b78116d831886671e4`.
- 완료 삭제 sequence1, active_lane_id=null, accepted_through_sequence=1.
- 실제 로컬20 검사·spool 제거·같은 완료 기록 재생을 확인했다.

[기계 증거](CANCELLATION-SETTLEMENT-ACCEPTANCE-2026-09-08.json). 원본 `/var/tmp/cancellation-submit-acceptance-5l_9fbre/result.json`의 범위 설명은 이전 기본 문구였으므로 보존 사본과 이후 스크립트 출력에서 cursor1 완료 범위로 바로잡았다.
재현: `scripts/cancellation-submit-acceptance.py ISOLATED_BUILD --settle-result`.

## 다음 인수와 보류

**정상 V2 후속 요청이 sequence2로 양쪽 validator·실제 provider 실행·JARVIS 완료까지 이어지는 인수는 아직 수행하지 않았다.** provider 접수 코드는 저장 high-water 다음 항목과 이전 root의 연결을 검사한다. 이번 완료에서 provider와 JARVIS가 sequence1에 도달한 것은 확인했지만 그 사실만으로 seq2 성공을 선언하지 않는다.

기존 전체70 purge 영수증은 생성하지 않는다. 완료 기록의 범위는 검증된 미전송 취소 결과와 로컬 처분에 따른 처리 순번이며, 모든 외부 사본 삭제나 중앙 기억 운영 전체 완료를 뜻하지 않는다. 직접 DB/외부 작성자 배제, 관리 root 정체성, 사용자/프로젝트 ACL, 원작업→기억 계보, native 세션/WAL/백업 수명, 실제 앱 새 세션 사용, 수집/주입·검색·GUI·운영 복구 목표는 유지한다.

운영 DB/설정/서비스·배포·push는 변경하지 않았다. SB 제품 코드 변경이 없어 Python 전체 검사는 재실행하지 않았다.
