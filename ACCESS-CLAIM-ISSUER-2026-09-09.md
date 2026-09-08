# 자비스 범위 claim 발급기 — 현재 키 검사와 실제 상호 검증

2026-09-09. JARVIS 제품 `c5ad24b`, Second Brain 제품/인수 `3b2a08d`.

## 구현과 대조 결과

기존 JARVIS `createProductionMemoryReadFence`는 현재 authority DB의 key 상태·principal·algorithm·지문·유효 기간과 실제 키 파일을 대조한다. 이 경로를 공유하는 `createProductionMemoryReadAuthorization`을 추출하고 기존 fence API를 유지했다. 새 `createProductionMemoryAccessClaim`은 매 호출마다 범위 공급자를 다시 조회한 뒤 같은 키 검사를 수행한다.

claim은 실제 method/arguments의 digest와 새 fence를 결합한다. 만료는 허용 범위와 fence/키 만료 중 빠른 시점이다. 범위가 없거나 만료됐거나 project 집합이 잘못됐으면 거부한다. 범위 공급자가 요청 인자를 바꿔 다른 요청에 서명하도록 하는 경우도 거부한다. 발급기는 키·권한을 생성하거나 등록하지 않는다.

기존 계약에서 긴 provider ID와 `jarvis.keys/owner.v1` 같은 key ID를 허용하는 회귀 검사를 발견했다. SB claim의 새 식별자 정규식이 이 값을 거부할 수 있어 provider/key는 기존 canonical text 계약을 따르도록 수정했다. principal/project/policy 등의 분류 규칙은 유지한다.

## 검증

- JARVIS 직렬 Vitest: 새 issuer 및 기존 read-fence production **17 passed, 13.10초**. 키 철회·범위 공급 중단·만료·중복 project·요청 변조 및 기존 발급 경로 회귀를 확인했다.
- JARVIS 타입 검사·변경 파일 ESLint·격리 디렉터리 emit 통과. 운영 dist/build와 npm pretest를 실행하지 않았다.
- SB 최종 관련 **31 passed, 6.02초**. 긴 provider와 key 경로 식별자 검증도 포함한다. Ruff·diff 통과, 변경 모듈 basedpyright 0 오류/0 경고.
- 실제 프로세스: `/var/tmp/page-access-acceptance-d3bf7sjp/access-claim-result.json`. 실제 JARVIS issuer가 격리 authority DB의 등록된 키를 검사해 발급하고, SB가 서명·fence·요청·실제 봉인 페이지 분류를 검증했다. 원본 요구2/record2, 변조 project 거부를 확인했다.

## 인수의 한계와 유지하는 보류

범위 공급자는 **명시적인 미연결 포트**다. 실제 인수에서 fixture 범위를 공급했으며 운영 사용자 인증·작업 권한 판정이 완료된 것으로 확대하지 않는다. 프로젝트 존재나 dashboard session ID만으로 project 접근 권한을 자동 부여하는 방식은 보류했다. 운영 resolver는 인증된 서버 세션 및 현재 허용/철회 정책을 확인해야 한다.

기존 unscoped adapter/MCP를 바꾸지 않았다. 다음은 실제 resolver와 새 scoped profile의 전달·기대 문맥 연결이며, 검색·직접 page·status·resolve·쓰기·export·restore·context 전체 표면에 일관된 검사와 회귀가 필요하다. provider에서 현재 정책을 어떻게 공급하고 갱신할지도 같은 계약으로 확정해야 한다.

같은 소유자 범위라는 기존 fence 제한을 유지한다. 여러 사용자의 인증·OS 파일 격리, 원작업 계보·native 세션 사본 수명·실제 앱 순환·여러 writer 배제·검색/GUI/복구 등 전체 목표는 남는다. 서비스 재시작·운영 config/vault 변경·push를 수행하지 않았다.
