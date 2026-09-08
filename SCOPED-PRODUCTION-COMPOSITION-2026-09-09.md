# 인증된 범위 기억의 제품 구성 함수

2026-09-09. JARVIS `ded750c`, SB 인수 `5b07d53`. [실측 JSON](SCOPED-PRODUCTION-COMPOSITION-2026-09-09.json).

`createProductionScopedMemory`를 public API에 추가했다. 기존 파일 정책 resolver, 목적별 issuer, scoped v2 전송기/소비자, 개인정보 membership와 reference reader를 한곳에서 구성한다. 인증 세션 공급자·정책 경로·기존 fence key 설정은 필수이며 소유자 세션을 추측하는 기본값이 없다. projection key는 기존 private 파일에서만 읽고 새로 생성하지 않는다. membership이 키를 복사한 뒤 임시 buffer를 지운다.

현재 인증 세션과 명시적 상태 조회 권한을 전송기 할당 전에 검사한다. record 4KB, 검색 32개, provider 전체 64KB 등 기존 문맥 공급기 기본 예산을 사용한다. 기본 전송기 프로필은 scoped v2로 고정한다. caller가 주입한 전송기와 authority DB는 caller 소유이며, 자체 생성 전송기만 close한다. 기존 일반 owner 생성 함수를 자동으로 대체하지 않는다.

검증:

- 구성/정책/scoped 연결 집중 6 passed / 3 files / 3.91초. 키·정책 누락, 인증 세션 부재 거부, 파일 자동 생성 없음, 키 원본 보존, 실행 전 초기 검증 및 반복 close를 확인했다.
- TypeScript 격리 emit·ESLint·diff 통과.
- 실제 구성 함수가 직접 생성한 기본 launcher/MCP 경로에서 record 문맥을 회수하고 종료했다.
- 동일 함수에 기존 monitored transport를 주입하고 close 이후에도 caller-owned transport를 사용해 record 2개/4,412바이트 문맥을 준비·제출했다. 중복 제출·빈 검색 세대 대체·쿠키 제거·응답 후 정책 철회 거부를 반복 확인했다.
- 실제 결과 `/var/tmp/page-access-acceptance-4rtuz0u9/scoped-mcp-result.json`.

이 구성 함수는 운영 배포나 CLI/HTTP 진입점 연결 완료를 뜻하지 않는다. 실제 인수는 테스트 owner/key·세션·고정 시각·합성 원본·fake compiler를 사용했다. 모델/native 세션 수신·보존·삭제는 확인하지 않았다. 인증 세션 전달과 프로젝트 정책 배정이 없는 CLI/HTTP 경로에 단순 연결하는 방법은 보류한다. scoped 쓰기·resolve·복구 및 전체 기존 운영 목표를 유지한다. 이번 변경에서 전체 스위트를 다시 실행하지 않았다.
