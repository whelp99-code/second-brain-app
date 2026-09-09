# 본문 결합 지식 상태: 정정·삭제·복원 경계 감사

기준 5d2e820. 전체 회귀 실행 중 읽기 전용으로 확인한 코드 경계이며 아래는 새 lifecycle 실사용 검증 결과가 아니다.

- generation_staging.copy_operational_ledger는 기존 원장을 SQLite backup으로 복사한다. 일반 successor에 과거 본문의 상태 행이 남을 수 있다.
- sealed_knowledge_states는 records의 현재 page_id/content_digest와 모두 일치하는 행만 조회한다. 따라서 페이지 삭제 또는 본문 변경 시 이전 상태 행이 남아 있어도 그 상태를 검색 결과에 그대로 적용하지 않는다.
- erasure는 대상 본문을 수정하고 Vault.rebind_erased_sources로 살아남은 인용의 출처를 효과 snapshot에 다시 결합한다. 이 경로는 새 BoundKnowledge를 기록하지 않는다. 따라서 정정/삭제 이후 살아남은 본문도 UNKNOWN으로 내려갈 수 있다. 권한 있는 effect의 결과 상태를 명시적으로 기록할 후속 설계·인수가 필요하며 자동으로 과거 승인을 복사해서는 안 된다.
- ManagedRestoreInventory.sanitize는 derived_sqlite/git/generation_manifest를 복원 파일 목록에서 제외한다. materialize는 destination의 기존 자식을 제거한 뒤 sanitized 파일만 구성한다. GenerationRestoreSanitizer는 이 materialize를 공통 mutation 경로로 호출한다. 그러므로 선행 copy_operational_ledger의 상태도 제거되고 새 파생 원장에 과거 bound_knowledge가 자동 복원되지 않는다.
- 복원 원문의 정상 기억을 자동 상태로 재등록할지, 재컴파일을 요구할지 정해야 한다. 어느 경로든 tombstone 검사와 동일 본문 검증을 거쳐야 하며 과거 SQLite를 그대로 반입하는 예외는 추가하지 않는다.

이어갈 인수: 승인된 기억→정정 후 새 본문 상태, 부분 삭제 후 남은 사실 상태, 완전 삭제 후 결과 없음, 과거 backup의 정상 문서 회수 및 tombstoned 내용 재유입 없음, 중단/재시작과 승인·철회 충돌. 전체 운영 및 M1–M14 완료 판정은 유지하지 않고 계속 미완료로 둔다.
