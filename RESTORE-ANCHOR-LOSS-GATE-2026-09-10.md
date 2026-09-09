# 원본 세대 근거 소실 시 복원 거부

기준62aee49. 전체 백업과 최신 tombstone authority는 유지하고, sanitizer가 참조하는 generation store journal만 실제 신규 GenerationStore의 빈 journal로 대체하는 integration test를 추가했다. 디스크나 운영 DB를 지운 것이 아니라 누락된 독립 근거 상황을 격리해 주입한 검사다.

실제 sanitizer는 RESTORE_SOURCE_ANCHOR_MISSING을 반환했다. 기존 active generation ID와 ledger bytes, tombstone high water 불변, staging 및 restore 추출 workspace가 비어 있음을 확인했다. 빈 journal과 원래 executor는 각각 종료하며 운영 journal에 행을 만들어 백업의 주장을 승인하지 않는다.

`TMPDIR=/var/tmp uv run pytest -q tests/integration/test_memory_restore_reingress.py tests/test_restore_source.py --tb=short`: **18 passed / 27.61초**, Ruff 전체·diff 통과. 제품 변경 없음. 새 테스트 이후 전체 suite는 반복하지 않았다.

보류 판정: 운영 journal까지 소실된 상태의 자동 신뢰 복구. 현재 전체 archive manifest의 자체 해시와 자비스의 최신 read fence만으로 원본 세대의 승인/접근 상태를 증명할 수 없다. fence는 현재 삭제 이력과 읽기 권한의 근거이며 과거 백업 상태를 승인하는 증거가 아니다. 이 조건에서 백업 주장으로 운영 anchor를 생성하거나 현재 tombstone 이력을 낮추는 fallback은 추가하지 않았다.

후속 DR 완료 조건은 원본 세대에 대한 별도 보존 근거의 검증, 최신 삭제 이력 보존, 격리된 실제 저장소 소실·재구성 시험과 정상 조회/권한 제한/삭제 억제 인수다. 기존 서명·권한 계약을 우회하거나 새로운 승인 절차를 임의로 만들지 않는다. 안전한 거부 검증을 복구 완료로 표시하지 않는다.

운영 DB·서비스·타 리포 변경과 push 없음. 실제 업무·운영 전환·native 수명·DR 및 전체M1–M14 목표는 미완료다.
