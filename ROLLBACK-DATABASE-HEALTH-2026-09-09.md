# 복원 DB 구조 검증 — 2026-09-09

이전 스냅샷 복구 검사에 SQLite integrity_check와 foreign_key_check를 추가했다. 이전 바이너리가 받아들이고 행 inventory가 같아도 DB 구조나 참조가 잘못되면 PRE_UPGRADE_SNAPSHOT_ROLLBACK_FAILED로 보류한다. 원시 행/위반 내용을 출력하지 않고 무결성 여부와 외래 키 오류 수만 기록한다.

검증: 실제 임시 SQLite에 정상 참조와 부모 없는 참조를 각각 구성해, 둘 다 integrity_check=ok여도 후자는 foreign_key_errors=1로 구분함을 확인했다. 기존 artifact 선검사 포함 5개 통과(0.21초), Ruff 통과.

운영 DB 읽기 전용 사본의 최신 후보 이전/복원 리허설: 복원본 이전 실행물 수용=true, 원래 inventory 보존=true, integrity_ok=true, foreign_key_errors=0. 전체 exit1은 PREVIOUS_BINARY_ACCEPTS_UPGRADED_DATABASE 때문이다. 해당 사유를 제거하지 않았다. 스냅샷 이후 쓰기 보존은 검증하지 않으며 운영 전환/복구 승인을 의미하지 않는다. 운영 DB/current/서비스 변경 없음.
