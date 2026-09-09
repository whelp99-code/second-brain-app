# 새 의존성 후보의 운영 DB 복사본 검증 — 2026-09-09

운영 DB를 SQLite 읽기 전용으로 열어 임시 online backup을 만들고, 신규 의존성 자비스 후보로 마이그레이션했다. 임시 DB는 검사 후 삭제했다. 운영 DB·서비스·current는 변경하지 않았다.

## 실제 결과

- 마이그레이션 58→81. 기존 58개 이력의 ID/checksum/applied_at 보존.
- 기존 비즈니스 테이블 212개에서 원래 열의 전체 행 집합 보존. 이 중 17개는 비어 있지 않았다.
- 전후 FK 오류 0, integrity_check=ok, 두 번째 migrate의 변경 건수 0.
- **현재 운영 authority 구버전은 새 DB를 정상으로 받아들였다.** 전체 검사는 exit 1, `PREVIOUS_BINARY_ACCEPTS_UPGRADED_DATABASE`로 보류한다. 마이그레이션 성공이 구버전 혼재 허용을 뜻하지 않는다.
- 대조 검사: 새 후보의 MigrationStore에 구버전 SQL 목록을 주면 `MIGRATION_VERSION_UNSUPPORTED`로 새 DB를 거부했다. 이 대조 검사만 exit 0이다. 현재 운영 바이너리가 수정됐다는 뜻이 아니다.

## 검증 도구 보강

`operational-authority-upgrade-rehearsal.py`는 실행 전에 supplied SQL 파일명·SHA256 목록을 build/migrations와 대조한다. 비어 있거나 다르면 DB를 열기 전에 거부한다. 결과에 SQL 전체 digest 목록과 실제 db.js/migration-store.js digest를 포함한다. 서로 다른 후보의 코드/SQL로 나온 결과를 혼동하지 않도록 했다. 이는 전체 의존성/릴리스 봉인을 대체하지 않는다.

SQL 변경·누락·추가 3개 회귀 테스트에서 DB를 열기 전 거부됨을 확인했다 (`3 passed`). 기존 데이터 변경·FK·무결성·재실행 변화·구버전 수용은 각각 hold_reasons로 기록한다. `--previous-migrations` 단독 지정도 거부한다.

## 전환 전 필수 작업

구버전 프로세스를 확실히 배제하는 전환·복구 절차와 실제 서비스 실행 gate가 필요하다. 과거 바이너리를 새 DB에 연결하는 롤백은 보류한다. 이번 결과는 read-only 복사본 리허설이며 운영 전환 승인 또는 완료가 아니다. 상세 수치와 후보 digest는 동명 JSON을 참고한다.
