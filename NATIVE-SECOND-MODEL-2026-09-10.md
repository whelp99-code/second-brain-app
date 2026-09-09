# 두 번째 native 모델의 공통 기억 조회

기준0c96446. 기존 live 검색 acceptance에 --model 선택과 모델 관측 증거를 추가했다. 실제 system init 모델과 assistant 응답 모델 목록, client version을 각 결과에 기록한다. 모델 비교는 event 근거가 있는 --live에서만 허용한다.

이전 성공 실행의 init event는 claude-opus-5[1m]/Claude Code2.1.261이었다. 이번 --model sonnet 실행은 init/응답 모두 claude-sonnet-5, client2.1.261을 확인했다. 제품·provider·질의·세대·검색 결과는 같은 합성 fixture다.

첫 Sonnet 실행은 의미상21일을 답했으나 value에 '은하 백업 보관 기간은 21일이다.'를 넣어 정확한 필드값 검사2건 실패/보류1건 통과, exit1이었다. 이를 사실 오류나 성공으로 바꾸지 않았다. gold 문자열 비교는 그대로 두고 prompt에서 value는 요청한 값/단위만 담도록 명시했다. gold값 자체를 prompt에 추가하지 않았다.

최종 /var/tmp/sb-native-search-answer-929WZ7 실행exit0. 각 질문마다 실제 sb_search1회/성공 응답1개/완료1개, generation 및 전체 검색 결과가 기준과 동일. current/current-natural은 supported/21일, absent는 insufficient_evidence/null. [실패·최종 결과와 모델 식별](NATIVE-SECOND-MODEL-2026-09-10.json).

Node 구문/diff 통과. 응답 validator와 제품 코드 변경이 없어 기존6검사를 반복하지 않았다. 총 Sonnet6호출(첫3+최종3). 기존 Opus 실행은 출력 지침 보강 전이므로 같은 prompt를 쓴 모델간 통제 벤치마크로 보고하지 않는다.

두 모델 변형이 같은 기억을 조회한 근거이며 서로 다른 agent 제품·제공자·사용자 업무의 자동 수집/쓰기/주입 인수가 아니다. trusted-owner fixture, live provider MCP이며 JARVIS 인증/scoped 전달 경계는 별도다. hybrid 기본 활성화·운영 전환 보류 유지, 전체 M1–M14 미완료. 운영 DB/서비스·타 리포·push 없음.
