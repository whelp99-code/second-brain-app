# 쓰기 검증기 gateway CLI 연결 및 실제 TLS/MCP 인수

JARVIS `399fb4f`는 독립 gateway CLI의 옵션7개를 기존 memoryProviderVerifier 서버 옵션으로 연결한다. 일부 설정 누락·상대 경로·잘못된 ID는 시작 거절, 모두 없으면 비활성이다. 기존 context/reconcile 설정은 유지한다. [옵션별 구성](../Orca-JARVIS/docs/scoped-provider-cli-config-2026-09-09.md).

- CLI 소유 authority 연결은 기존 DB만 열고 initialize/migrate를 호출하지 않는다. SQLite fileMustExist를 열기와 reopen에 적용한다. 시작 실패·출력 실패·종료에 연결을 닫으며 중복 close도 처리한다. 일반 AuthorityDb 호출의 기본 동작은 유지한다.
- 세션은 기존 HTTP 로그인 저장소에서 공급하고, 원래 dispatch·현재 정책·시간을 기존 검증기가 계속 검사한다. 경로를 지정했다고 권한을 자동 발급하지 않는다.
- 실제 인수 스크립트가 새 parser로 구성한 독립 DB 연결을 서버에 공급한다. 기존 단일 fixture 연결만 공유하던 경로보다 실제 배포 구성에 가까워졌으며, 운영 배포를 대신하지 않는다.

| 실제 TLS→gateway→별도 MCP→SB CLI | 결과 | HTTPS 호출 | dispatch attempt / FK 오류 |
|---|---|---|---|
| 정상 | accepted→proved, 활성 세대 있음 | 5 | 1 / 0 |
| 수락 중 정책 철회 | 수락 거절, 수락 행 없음 | 2 | 1 / 0 |
| 실행 전 정책 철회 | failed, 활성 세대 없음 | 3 | 1 / 0 |
| 실행 전 세션 만료 | failed, 활성 세대 없음 | 3 | 1 / 0 |

재현: 자비스 작업공간에서 `TMPDIR=/var/tmp node /home/jm/orca/projects/second-brain-app/scripts/scoped-provider-https-acceptance.mjs <isolated-jarvis-build> --cli --mcp`. [실제 결과 JSON](SCOPED-PROVIDER-CLI-CONFIG-2026-09-09.json).

검증: 관련5파일64개(8.31초), 기존 reconcile CLI6개, 취소 DB 최종12개(9.97초), 서로 다른 총82개 통과. 격리 TypeScript emit·변경 ESLint·diff·스크립트 문법 검사 통과. 취소 DB 확대 검사에서 1건 실패 후 수정했다. 기존 fixture가 idle cursor 수락 순번을 직접 올려 migration076의 `cancellation settlement required`에 거절됐으며, `e6e36d7`에서 정식 claim→accepted로 준비하도록 수정했다. 직접 SQL 우회 거부 검사는 유지했고 제품/migration을 완화하지 않았다.

시간·인증서·원작업·Tailnet 전달자 identity는 fixture, 로그인/DB/HTTP/MCP/CLI는 실제 임시 프로세스 경로다. 고정 운영4176에서 독립 바이너리를 배포한 시험은 아니다. 정상 수락 응답과 최종 완료는 구분하며 실패 응답을 미수락 또는 재전송 허가로 사용하지 않는다.

이번에 [운영 대조](OPERATIONAL-HANDOFF-AUDIT-2026-09-09.md)의 쓰기 verifier CLI 연결 부족을 개발에서 해소했다. 운영 릴리스·키/정책/자격증명 공급·DB 전환·실제 A→B 공유, 전체 M1–M14의 삭제/복원/native 세션/검색/GUI 인수는 남는다. 운영 변경·push 없음. SB 제품 변경이 없어 직전 전체1,354통과/2skip을 재실행하거나 이번82개와 합산하지 않는다.
