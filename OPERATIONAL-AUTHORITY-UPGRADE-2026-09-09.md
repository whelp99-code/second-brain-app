# 운영 authority 사본 업그레이드와 미확인 이력 차단

**최종 판정: 운영 전환과 구·신 실행물 혼합 운용은 HOLD.** 운영 DB에 현재 SQL 목록에서 찾을 수 없는 `028_budgeted_evolution_memory.sql` 이력이 있다. 최신 JARVIS `a2e59eb`는 이를 `MIGRATION_VERSION_UNSUPPORTED`로 거절하며, 거절 후 사본 행은 변하지 않았다. 이력을 삭제하거나 예외로 숨기지 않았다.

## 실제 사본 검사

원본 `/home/jm/.local/state/orca-jarvis/jarvis.sqlite`는 SQLite mode=ro와 query_only=ON으로 열었다. 온라인 backup은 별도0700 임시 디렉터리의0600 파일에 기록했고, 마이그레이션은 이 사본에만 실행했다. 성공·거절 후 임시 DB를 제거했다. 출력에는 원문 행이나 비밀 값이 없다.

| 검사 | 관측 | 의미 |
|---|---|---|
| 수정 전 개발 코드의 사본 전환 | 이력58→81, 23개 추가 | SQL 전환 자체는 실행되었지만 미확인 과거 이력을 무시했으므로 배포 호환성 증거로 부족 |
| 원래 데이터 보존 | schema_migrations를 제외한212개 테이블의 원래 열·행 값 일치 | 이 중17개 테이블만 비어 있지 않음. 데이터가 없는 기능의 운영 수명주기를 검증한 것은 아님 |
| 무결성/재실행 | FK0, integrity_check ok, migration 재실행 변경0 | 사본 기준 |
| 설치된 구 실행물의 준비 검사 | 전환된 사본을 accepted로 판정 | 미래/미확인 이력 누락 검사 결함. 실제 업무를 구 실행물로 수행하지 않음 |
| 수정 후 개발 코드 | 원래58개 이력에서 unknown ID를 발견해 전환 거절 | 원래 사본 행 전체 불변. 의도된 exit1/HOLD |
| 제품 회귀 검사 | 신규1 + 기존7 + rejected Task30 복구8 =16통과 | forward/replay/체크섬·복구 경계 유지 |

첫 리허설 스크립트는 존재하지 않는 assertReady helper를 호출해 실패했다. 실제 assertMigrationsReady API로 수정하여 이후 검사를 진행했다. 이후 수정 전 사본 전환 통과와 수정 후 의도된 거절은 서로 다른 검사 결과다. 이를 하나의 성공으로 합치지 않는다.

[결과 JSON](OPERATIONAL-AUTHORITY-UPGRADE-2026-09-09.json). [재현 스크립트](scripts/operational-authority-upgrade-rehearsal.py)는 --source-db, --jarvis-build, --migrations를 요구한다. --previous-build로 설치된 이전 MigrationStore를 읽기 전용으로 검사할 수 있다. --previous-migrations는 해당 비교 SQL 경로를 명시한다. 이전 실행물이 전환된 DB를 받아들이면 exit1을 반환한다. 현재 운영 원본은 unknown 이력 검사에서 먼저 거절되므로 이전 실행물 비교 단계에 도달하지 않는다.

## 수정과 보류 해제 조건

JARVIS MigrationStore는 이제 readiness와 migrate에서 자신이 모르는 이력을 차단한다. migrate는 기존 rejected Task30 ID만 원래 복구기로 전달하고 checksum/prefix/layout/data 검사를 유지한다. 이미 배포된 migration SQL과 운영 바이너리는 변경하지 않았다. 상세는 [자비스 수정 기록](../Orca-JARVIS/docs/migration-version-boundary-2026-09-09.md).

미확인 이력은 [기존 자비스 운영 인수 보고](../Orca-JARVIS/docs/planning/daemon-operating-rehearsal-2026-09-08.md)에도 기록돼 있다. 당시 원본 SQL을 찾지 못했고 운영 추가 객체3개를 확인했다는 기록이다. 이번 작업에서 그 객체들의 출처를 새로 확정한 것은 아니다.

다음은 원본 SQL과 배포 이력·객체 소유권을 증거로 복원하고 명시적인 호환/전환 절차를 정하는 것이다. 빈 객체라는 이유로 삭제하거나 ID만 허용하는 방식은 보류한다. 운영 전환은 exact migration vector/provider contract/sealed manifest 조건을 지켜야 하며, 구 실행물의 ready 응답으로 대체하지 않는다.

운영 서비스·DB·설정 변경 없음. SB 제품 변경이 없어 전체1,354통과/2skip을 재실행하지 않았다. 실제 A→B 공유, 세션·키 공급, native 보존/삭제, 검색·GUI·복원 및 전체 M1–M14 완성 목표는 남아 있다.
