# 복원 상태 검증에 사용할 기존 세대 근거

기준 제품 25b6f54. 제품 변경 없이 실제 삭제/복원 fixture를 통해 다음 사실을 검증했다.

- 원래 source generation 디렉터리는 삭제·정리 후 존재하지 않는다.
- 운영 GenerationStore activations 원장에는 그 generation_id의 manifest_digest가 남고, 기존 archive source_generation_manifest_digest와 일치한다.
- 임의 generation ID는 원장에 없다. 아카이브가 자신의 metadata/hash를 재계산한 값과 별개로 운영 원장 값을 읽을 수 있다.

현재 sanitize가 이 값을 이용해 지식/접근 상태를 복원한다는 뜻은 아니다. 다음 연결을 만들 때 사용할 수 있는 기존 근거를 확인한 것이다. 초기 테스트의 디렉터리명 비교가 실제 full generation_id와 달라 약했으므로, store.generations / source_generation_id의 실제 경로 부재 검사로 고친 뒤 재실행했다.

`TMPDIR=/var/tmp uv run pytest -q tests/test_restore_authority.py tests/integration/test_memory_restore_reingress.py --tb=short`: **5 passed / 6.98초**. Ruff 전체·diff 통과.

## 이어갈 구현 경계

1. 별도 세대 파일이 있는 백업에서 기존 load_verified_manifest로 self identity·derived inventory·ledger digest를 검증한다. source_generation ID/digest/provider와 독립적으로 보관한 운영 원장 digest가 모두 맞아야 상태 복원 후보로 삼는다. 단순 archive inventory 일치로 대신하지 않는다.
2. 검증된 원장에서 구조화된 상태만 추출한다. SQLite 파일 자체를 복원 destination에 넣지 않는다.
3. 현재 tombstone로 정제한 본문의 canonical page ID와 전체 bytes digest가 같은 상태만 재결합한다. source_access/PageAccess를 복원할 때도 모든 요구사항과 incomplete를 그대로 유지한다. 변경된 본문이나 근거 없는 페이지를 일괄 승격하지 않는다.
4. 복원하는 metadata가 삭제 차단 대상 bytes를 다시 들여오지 않는지도 최종 inventory/scan에서 검증한다. 기존 sanitize가 derived SQLite를 제외한다는 이유로 그 검사를 생략하지 않는다.
5. 외부 철회와 현재 policy revision을 우선하고, 복원은 기존 비활성 후보·proof 경계를 유지한다.

운영 원장까지 소실된 DR에는 위 1번의 독립 근거가 없다. 그 경우 검증 가능한 원장/manifest의 보관·복구 경로도 필요하다. 원장이 살아 있는 경우만 구현해서 복원 전체를 완료한 것으로 판정하지 않는다. 이 문서는 새 서명/승인 시스템 채택이나 계약 확정이 아니다.

복원 구현, 실제 JARVIS 인증 세션, 최신 설치 쌍·실제 업무·운영과 M1–M14는 남는다. 이번 전체 suite 재실행 없음. 운영 DB·서비스·공용 registry 변경과 push 없음.
