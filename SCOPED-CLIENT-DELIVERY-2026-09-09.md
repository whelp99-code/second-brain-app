# 범위 기억 클라이언트와 반환 직전 권한 재검사

2026-09-09. JARVIS `62af9e2`, SB 인수 `67a2e22`. [실측 JSON](SCOPED-CLIENT-DELIVERY-2026-09-09.json).

## 문제와 변경

claim 발급 후 요청이 전송 대기열에 있거나 응답을 기다리는 동안, 자비스의 인증 세션·프로젝트·정책·키가 바뀔 수 있다. 서버의 현재 정책 검사만으로 소비자 측 변경을 검증했다고 할 수 없다.

`createMemoryScopedClient`를 추가하고 public index에 노출했다. 이미 구현한 issuer→기존 supervised transport→scoped response parser를 연결한다. `readPage`와 `search` 요청 인자를 동결하고 최초 발급 권한의 식별값을 보존한다. 전송기의 beforeSend, 응답 도착 후, 파싱 후 반환 직전에 다음을 확인한다.

- 원 claim 발급 시각보다 과거가 아니며 만료 전인지.
- 실제 issuer가 현재 DB 키·인증 세션 공급자·현재 파일 정책을 여전히 허용하는지.
- provider/principal/agent/session/projects/policy revision/purpose/request/key와 삭제 sequence/root가 최초 발급과 일치하는지.
- 반환된 record가 원 요청·claim·세대·본문·유효 시각·분량 제한에 맞는지.

권한 재검사는 기존 issuer를 재사용한다. 추가 서명은 요청 내부에서만 만들고 전송·영속화하지 않는다. 정상 호출은 최초 1회와 재검사 3회 발급 경로를 거치며 이 비용은 아직 성능 인수하지 않았다. 향후 필요하면 같은 검증 로직에서 서명 없는 현재 권한 검사 함수를 추출해야 하며, 검증을 생략해서 비용을 줄이지 않는다.

## 검증

JARVIS 19 passed / 3 files / 5.37초: 새 연결의 실제 issuer·authority DB와 기존 issuer/record 소비 회귀. 전송 전 범위 철회는 전송 횟수가 증가하지 않았고, 응답 후 세션·프로젝트 변경, 만료, 키 철회를 거부했다. 빈 검색 결과는 빈 pages로 유지한다. 해당 단위 테스트의 transport는 결정적 fixture다.

별도 실제 인수는 `/var/tmp/page-access-acceptance-i4sqvvuz/scoped-mcp-result.json`에 기록했다. 실제 정책 파일 resolver·issuer→기본 launcher→Python MCP→새 클라이언트에서 페이지·검색 각 1개 페이지 그룹을 회수했다. 이어 실제 응답을 받은 직후 resolver 정책 파일의 sessions를 비우고, 클라이언트가 반환 전 `MEMORY_ACCESS_SCOPE_UNAVAILABLE`로 거부하는 것을 확인했다. 이전 직접 소비자 변조 3종과 transport 재시작 검증도 같은 인수에서 반복 통과했다.

TypeScript 격리 emit·ESLint·diff 검사 통과. 운영 dist·서비스·권한 DB를 수정하지 않았다. 합성 기억과 fake compiler, 테스트 authority DB·세션 공급자·고정 시각을 사용했다. 첫 인수 시 스크립트 입력의 page_id 누락으로 canonical JSON 검사가 거부했으며 인수 입력을 수정한 후 다시 통과했다.

## 미완료·보류

이 함수는 실제 앱 로그인 세션 저장소를 새로 만들지 않는다. 인증된 세션 공급자를 연결하고 결과를 기존 context/모델 세션에 전달하는 제품 경로가 남는다. 소비자에 전달한 이후의 native 로그·compaction·캐시·백업 수명은 이 재검사로 해결되지 않는다.

검사 사이에 바뀌었다가 원래 값으로 되돌아오는 정책까지 감지하는 단조 revision 저장소, 이전 claim 전역 철회, 다른 process의 최신 삭제 상태, scoped 쓰기/status/resolve/복구와 M2~M14 전체 인수는 남는다. 기존 일반 adapter의 운영 프로필 일괄 전환은 계속 보류한다. 작업 성공을 기억의 본문이나 유효한 서명만으로 판정하지 않는다.
