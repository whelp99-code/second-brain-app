# 제한 MCP의 실행 중 정책·키 철회 반영

2026-09-09 제품 `867d65b`. 기존 `31d9ab1`의 시작 시 정책 snapshot 한계를 보완했다.

## 구현

Config는 실제 로드한 파일 경로를 보존한다. 제한 MCP는 이 고정 경로를 매 요청 전후 다시 읽어 정책 revision과 허용 공개키를 대조한다. 실행 중 SB_CONFIG 환경 변수가 바뀌어도 다른 정책 파일로 넘어가지 않는다. 파일이 없거나 손상됐거나 scoped 설정/허용 키가 사라지면 이전 정책이나 legacy 모드로 되돌아가지 않고 거부한다.

처음 연결의 principal/agent/session과 provider·vault/state/share/request 경로를 보존한다. 변경된 설정으로 기존 연결의 신원이나 저장소를 다시 연결하지 않는다. 이런 변경은 새 연결에서 적용해야 한다. 정책 revision 및 키 철회는 기존 연결에서 반영된다.

본문 반환 전 정책·키가 같은지, 삭제 high-water와 활성 세대가 같은지 다시 확인한다. 서명/fence의 현재 시간 유효성도 재검사하여 조회 중 만료된 claim의 응답을 거부한다. 파일 없이 직접 생성한 Config는 제공된 설정 객체를 재조회하며 외부 설정 경로를 추측하지 않는다.

## 검증

- 최종 집중 **30 passed, 4.31초**: 정책 로더, scoped MCP, 기존 MCP, claim.
- 고정 경로·정책 변경·키 철회·다른 세션/저장소·잘못된 TOML·설정 삭제·복원 검사. 실제 MCP handler에서 읽는 도중 키 철회 및 claim 만료도 결과 반환 없이 거부했다. 시간 검사에 sleep을 사용하지 않았다.
- Ruff·diff 통과, 변경 제품 모듈 basedpyright 0 오류/0 경고.
- 실제 프로세스 최종 `/var/tmp/page-access-acceptance-015mp1o4/scoped-mcp-result.json`: JARVIS 실제 issuer와 별도 stdio MCP, record2. 같은 연결에서 키 철회/정책 변경/손상/파일 삭제 각각 거부, 유효한 설정 복원 후 동일 응답. 새 MCP 프로세스에서도 반복했다.
- 이전 전체1,136통과는 `31d9ab1`의 기록이며 이번 최종 전체 검사로 표기하지 않는다. 초기에 존재하지 않는 tests/test_config.py를 지정한 명령은 0개 실행으로 종료했으며 검사 수치에 포함하지 않는다.

## 범위와 남은 일

이번 자동 반영은 제한된 record 조회 연결에 적용한다. 기존 owner 프로필 전체에 적용된 것이 아니다. 운영 scope resolver, 검색·쓰기·status·resolve·export·restore·context 전체 검사가 남는다.

원본 분류의 policy revision과 현재 정책이 다르면 거부하며 자동 재분류하지 않는다. 유효한 설정을 복원하면 다시 허용되는 동작을 확인했지만, 이 구현이 과거 정책 파일 복구를 단조적으로 차단하는 정책 이력 원장은 아니다. 정책 rollback과 복구 인수는 기존 전체 목표에 남긴다. 요청 전후 검사만으로 모든 외부 writer에 대한 전역 원자성을 주장하지 않는다.

실제 인수는 합성 기억·fake LLM·테스트 authority/scope·고정 시각을 사용했다. 운영 사용자 인증, native 세션 수명, 실제 앱 전체 순환, 여러 writer 배제, 검색/GUI/DR 등 전체 목표는 유지한다. 운영 서비스 재시작·배포·실 vault/config 변경·push는 수행하지 않았다.
