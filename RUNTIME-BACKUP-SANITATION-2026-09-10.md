# 실제 런타임 백업의 정제 복원 연결 수정

기준c95bbdc. backup_runtime은 pinned generation과 제어 journal/request 사본을 .recovery 아래 보존한다. 반면 ManagedRestoreInventory는 이 경로를 미지원으로 처리하여 실제 런타임 백업을 해제한 뒤 정제하려 하면 RESTORE_INVENTORY_INCOMPLETE가 발생했다. 새 회귀에서 수정 전1실패로 재현했다.

.recovery를 기존 derived_sqlite 표면(파생·제어 상태를 집계하고 복사하지 않는 분류)에 포함했다. 새 wire 표면/계약을 추가하지 않는다. 각 사본은 manifest inventory에 집계하되 정제 후보에 materialize하지 않는다. 과거 요청·제어 journal·권한을 새 운영 상태로 실행하거나 승계하지 않는다. 원본 세대 검증은 현재 운영 journal의 독립 anchor를 계속 요구한다.

실제 runtime backup archive 생성→restore_backup으로 격리 해제→운영 anchor와 전체 archive manifest 검증→서명된 status fence로 GenerationRestoreSanitizer를 실행했다. 원본 .recovery/requests/journal.db 및 state/generation-journal.db 존재, 새 후보에는 .recovery 없음, 기억 inbox 본문 보존, blocked_matches/scan_errors0, 기존 active generation 불변을 확인했다. 이 시험의 tombstone은 genesis이며 추가 삭제 이력 시나리오는 별도 기존 검사와 구분한다.

관련 runtime inventory/spans/restore integration19통과/26.79초. 이후 같은 새 테스트를 실제 sanitizer 단계까지 확장해 최종1통과/0.90초. Ruff 전체·diff 통과, restore_inventory 타입0오류0경고. 제품 변경 후 전체 suite는 아직 재실행하지 않았다.

이 변경은 현재 운영 원장이 남아 있을 때 실제 백업 형식과 정제 복원을 연결한다. 원장까지 소실된 DR, 운영 권한/요청 복구, 실제 업무/운영 인증·native 삭제 수명 및 전체M1–M14는 여전히 미완료다. 운영 DB·서비스·타 리포 변경과 push 없음.
