# 잠금 의존성 신규 설치 후보 검증 — 2026-09-09

이전 배포의 node_modules 재사용을 피하고, 자비스 고정 커밋의 git archive에서 새 설치 후보를 준비했다. 운영 current와 DB는 변경하지 않았다.

## 실행 및 결과

- 후보: `/var/tmp/jarvis-locked-candidate-j9w0jrk8/source` (정확한 커밋·lock digest는 동명 JSON).
- `npm ci --ignore-scripts --no-audit --no-fund`: 430개 설치 성공. 이어서 `npm rebuild better-sqlite3 esbuild --no-audit --no-fund` 성공.
- 의존성 재사용 검사: 직접 런타임 의존성 7개와 lock 일치.
- Node v24.19.0 / ABI 137에서 새 better-sqlite3를 직접 로드하고 메모리 DB SELECT 성공, SQLite 3.53.2.
- 후보 내 `node_modules/.bin/tsc --outDir dist`, `node scripts/copy-migrations.mjs dist` 성공.
- 정본 release.md의 full-loop fixture 리허설 성공. 복원 quick_check=ok. systemd와 운영 DB 검사는 명시적으로 건너뛰었으므로 운영 검증 통과로 해석하지 않는다.
- 실제 HTTPS + MCP 쓰기 + CLI 처리 + 새 로그인 읽기 통합: 정상/접수 중 철회/실행 전 철회/실행 전 만료 4개 경로 통과. 정상 경로 proved→settled→completed, 완료 반영 1회·시도 1회, 독립 stdio 클라이언트 2개에서 각 2개 기록 조회, 읽기 권한 철회 후 403, 전체 FK 오류 0.

통합 첫 실행은 검사 스크립트가 기대하는 `dist/node_modules` 경로가 없어 실패했다. 후보에 `dist/node_modules -> ../node_modules`를 추가한 뒤 동일 검사를 재실행해 성공했다. 다른 작업공간의 의존성은 연결하지 않았다.

## 완료 범위와 보류

새 잠금 의존성으로 공통 기억 경로가 실제 프로세스 간 동작함을 확인했다. 이번에는 모델 호출 없이 SDK 클라이언트로 검증했으며, 신원 전달·정책·시각·검토된 내용은 fixture다. 세컨드브레인은 통합 검사 스크립트가 사용하는 개발 구현이며, 양쪽 설치 패키지를 함께 검증한 것은 아니다.

후보는 아직 봉인된 운영 릴리스가 아니다. 전체 운영 건강 검사, DB 전환·구버전 배제·복구 계획, 실제 계정 연결과 설치 패키지 간 통합을 완료해야 활성화 검토가 가능하다. 이전 운영 의존성 재사용 금지는 유지한다.
