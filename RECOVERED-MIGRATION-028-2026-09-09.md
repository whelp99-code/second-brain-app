# 운영 미확인 028 SQL 원본 발견·복원 및 사본 인수

이전 [운영 사본 전환 보고](OPERATIONAL-AUTHORITY-UPGRADE-2026-09-09.md)의 unknown 이력 차단 원인을 해소했다. 과거 배포 릴리스3곳에서 원본 SQL을 발견했고, 각각502bytes의 SHA-256이 운영 journal의 값과 일치했다. JARVIS `a6afd5a`에서 원본을 그대로 복원했다. unknown history 검사를 완화하거나 운영 journal을 삭제하지 않았다.

원본 경로는 `/home/jm/.local/state/orca-jarvis/control-center/releases/<release>/dist/migrations/028_budgeted_evolution_memory.sql`. 확인한 release는 `57dec90f40f9f280eff88700106aed433518e265`, `6078b6d5f669cadcd7a451c9a219744cd8f0b205`, `9e35736be7315c4a66808ea03bcbbb68931a8c3b`다. 공통 SHA-256은 `55faa41aa1c3c0b2c78ebfa4f59cd9daf6e4793deac91f39bfb3ea7e00955386`이며 운영 기록의 적용 시각은2026-08-21T14:45:52.570Z다. 당시 작업자·승인 과정 전체를 확인했다는 뜻은 아니다.

실제 운영 DB를 읽기 전용으로 열고 private online backup 사본에 최신 migrate/assert/replay를 적용했다.

| 확인 | 결과 |
|---|---|
| 마이그레이션 이력 | 58→81, 기존58개의 ID/checksum/applied_at 보존 |
| 기존 업무 테이블 | 212개 원래 열·행 값 보존, 변경0 |
| 비어 있지 않은 기존 업무 테이블 | 17개 |
| 외래키/무결성 | FK0, integrity_check ok |
| 마이그레이션 재실행 | 변경0 |
| 운영 기억 요청 관련4개 테이블 | memory_candidates/outbox/control_command_requests/correction_requests 모두0행 |

관련 고유17개 테스트 통과(기존15+version-boundary 최종2). 복원 파일의 해시를 고정하고 값이 있는 performance row가 재실행 후 보존되는지, successes<=runs 제약이 유지되는지 확인했다. 격리 tsc emit/ESLint·diff 통과. [자비스 상세 기록](../Orca-JARVIS/docs/recovered-028-migration-2026-09-09.md), [사본 결과 JSON](RECOVERED-MIGRATION-028-2026-09-09.json).

리허설 스크립트도 기존 journal 항목을 ID뿐 아니라 checksum/applied_at까지 비교하도록 강화했다. 원본 DB와 서비스에는 변경하지 않았으며 사본은 종료 시 제거했다.

**해제된 보류:** 원본 SQL을 찾지 못해 unknown 이력을 해석할 수 없던 문제. **유지되는 보류:** 구 실행물이 최신 DB를 수락하는 혼합 버전 위험 및 미인수 운영 전환. 실제 운영 실행물/설정/키·세션 자격증명·A→B 공유·삭제/복원·검색/GUI 등 전체 M1–M14는 남는다. 빈 운영 요청 테이블의 마이그레이션 통과를 실제 요청 수명주기 완료로 취급하지 않는다.
