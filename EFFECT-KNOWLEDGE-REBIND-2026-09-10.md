# 승인된 본문에 대한 정정 결과 상태 재결합

기준 533bfa7. 특정 record 정정만으로 미검증 page 전체를 승인하는 변경은 계속 보류한다. 대신 기존 page 전체가 정확한 현재 bytes에 ACTIVE/APPROVED로 결합돼 있던 경우에 한해, 이미 접수·검증된 effect 성공 후 결과 bytes에 같은 자동 처리 상태를 새로 기록한다.

## 구현 경계

새 effect_knowledge.apply_with_prior_knowledge는 staging 원장의 승인 상태와 effect 직전 페이지 실제 sha256을 대조한다. 현재 본문과 같은 prior 상태만 보관하고 SQLite 읽기 핸들을 닫은 뒤 effect를 실행한다. 성공 후 남은 페이지의 본문이 바뀌었을 때 새 digest로 기록한다. deleted page, missing prior, PENDING, 과거 digest 불일치는 승격하지 않는다. effect가 실패하면 상태 재결합도 실행하지 않는다.

RequestExecutor._effect의 기존 mutation 안에서만 호출하며 계약·접수·권한·tombstone 검사 및 세대 publication 경계를 변경하지 않았다. export 및 cancellation 별도 경로를 새 승인 경로로 바꾸지 않는다. 외부 registry는 쓰지 않고 기존 검색의 철회 우선 정책을 유지한다. 상태 재결합은 접근권한 부여가 아니며 scoped page_access의 새 요구사항 결합을 대신하지 않는다.

## 검증

- 실제 provider remember→correct→export→forget의 lexical/hybrid, 기존 승인 유무 네 경우: **4 passed / 19.05초**. 처음 전체 본문에 승인 상태가 있던 경우만 정정 결과가 active VERIFIED로 회수된다. 미승인 본문은 여전히 UNVERIFIED다. 실제 삭제·proof/inventory 검증도 유지했다. 초기 상태는 시험 fixture에서 컴파일과 동일한 digest로 seed했다.
- 상태 helper 예외·restore·generation 변조 회귀: **18 passed / 5.03초**. 정확한 prior, stale digest, pending, missing, deleted, failed 각 분기를 검사했다.
- request executor/correction cancellation/helper 회귀: **18 passed / 7.50초**. 위 helper 여섯 건은 중복이므로 40개의 서로 다른 테스트로 합산하지 않는다.
- Ruff 전체, diff 통과. 새 helper 타입 0오류/0경고.

## 남은 범위

정상 복원 문서의 자동 상태, 처음부터 미검증인 페이지의 부분 정정 상태, scoped 접근 분류, 부분 삭제 후 복수 surviving record의 상세 인수, 새 상태의 crash/rollback·대용량 비용, 실제 native 사용자 업무·다른 모델·최신 설치본·운영 및 M1–M14는 남는다. 새 사람 승인 gate는 추가하지 않았다. 제품 변경 후 전체 suite 재실행은 아직 하지 않았다. 운영 DB·서비스·공용 registry 변경과 push 없음.
