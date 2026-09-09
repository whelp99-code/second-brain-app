# 게이트웨이 쓰기 검증의 DB 버전 검사

JARVIS `867c274`에서 기존 migration 검사를 쓰기 검증기 시작과 각 HTTP 요청에 연결했다. openPhoneMemoryProviderCli/startPhoneGatewayCli는 이제 async이며 저장소 내 호출과 실제 TLS 인수 helper는 await한다. 시작 시 검사가 실패하면 소유 DB 연결을 닫고 포트를 열지 않는다. 요청 시에는 DB 검사 후 현재 원작업/정책 검증을 수행하고 HTTP handler가 현재 세션을 다시 확인한다.

관련67개 통과/9.72초·격리 emit/ESLint 통과. 미래/미적용/체크섬 변경 이력의 시작 거절과 연결 정리, 실행 중 unknown 이력에 대한 HTTP403·검증 요청 DB 변경0, 시험 이력 복원 후200을 확인했다. 기존 context/reconcile 설정·로그인·CSRF·철회·만료도 통과했다.

실제 CLI 설정→TLS gateway→별도 MCP→SB CLI 재검증은 정상proved, 수락 중 철회 미수락, 실행 전 철회/만료 failed·활성세대 없음, 각 attempt1/FK0다. 운영 사본에서는 최신 검사기에 이전 SQL 목록을 지정했을 때 MIGRATION_VERSION_UNSUPPORTED 거절을 확인했다. [결과 JSON](PROVIDER-MIGRATION-BOUNDARY-2026-09-09.json), [자비스 상세](../Orca-JARVIS/docs/provider-migration-boundary-2026-09-09.md).

이는 기존 설치 바이너리의 동작을 바꾸거나 혼합 버전 운영을 허가하지 않는다. DB upgrade와 요청의 모든 경합을 증명한 시험도 아니다. 운영 exact vector/서비스 교체/rollback, 실제 A→B 및 전체 M1–M14는 남는다. 운영 변경 없음. SB 제품은 변경하지 않아 이전 전체1,354통과/2skip을 이번67개와 합산하지 않는다.
