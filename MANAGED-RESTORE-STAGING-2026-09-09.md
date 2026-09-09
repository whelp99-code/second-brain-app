# 관리형 복원 작업별 임시 자료 분리

GenerationRestoreSanitizer는 요청 ID의 SHA256으로 staging 경로를 고정하고, 이미 존재하면 rmtree로 삭제했습니다. 이전에 중단된 복원 증거나 같은 요청의 다른 진행 자료가 삭제될 수 있습니다. 서명된 복원 fixture에서 미리 생성한 recovery-evidence.txt가 사라지는 실패를 재현했습니다.

mkdtemp로 요청 식별 prefix를 유지하면서 실행마다 고유한 0700 staging을 생성합니다. 기존 자료를 재사용하거나 삭제하지 않습니다. 정상 완료 및 manifest 불일치 실패의 두 경우 모두 이전 증거가 보존되고, 이번 호출의 staging만 정리되는 것을 실제 디렉터리 상태로 확인했습니다.

검증: restore/authority/inventory/재유입 통합 18 passed (13.35초), Ruff sb/tests 및 diff 공백 검사 통과. 수정 전 증거 파일 삭제를 재현했습니다. 기존 CLI ops.restore_backup 수정과 별개로 관리형 generation 복원 경로를 수정한 것입니다.

한계: 강제 종료 시 임시 자료가 남을 수 있고, 관리자가 명시적으로 처분하기 전에는 자동 삭제하지 않습니다. 동일 요청의 비즈니스 멱등성·세대 잠금은 기존 mutation 서비스가 담당하며 이번 변경을 전체 동시 실행 인수로 간주하지 않습니다. 운영 서비스와 DB는 변경하지 않았습니다.
