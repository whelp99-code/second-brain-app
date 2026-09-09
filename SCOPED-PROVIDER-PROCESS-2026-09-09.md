# Scoped provider 로컬 검증 전송 구현

## 구현과 기존 경로 연결

기존 create_scoped_provider_authority에 전달할 실제 로컬 프로세스 채널 ScopedProviderProcess를 추가했다. 단일 호출마다 새 프로세스와 전용 stdin/stdout을 만든다. 서버 설정의 절대 실행 경로·작업 디렉터리와 복사한 명시적 환경만 사용하며 shell을 실행하지 않는다. 요청 canonical bytes를 stdin으로 전달하고 EOF 후 단일 canonical JSON 판정을 받는다. 기존 sb.effect_values.strict_loads를 재사용해 중복 키·NaN·다중 JSON·비정규 JSON을 거절한다.

- 입력1~32,768바이트, 출력 최대4,096바이트, monotonic 기준 최대20초.
- 파이프 읽기/쓰기를 함께 감시해 큰 입력이나 응답으로 교착하지 않는다.
- 부모 환경을 자동 상속하지 않고 stdin/stdout 외 파일 디스크립터를 닫는다. stderr는 저장·반환하지 않는다.
- 정상 종료 코드0 이후에만 결과를 반환한다. 비정상 종료·시간 초과·출력 초과·잘못된 JSON은 내용 없는 오류 코드로 실패한다.
- 성공/실패/취소 모두 종료 정리 경로를 거치며 프로세스 그룹에 SIGKILL을 보내고 직접 자식을 회수한다. 자식이 유지한 파이프도 timeout에 묶인다.

사용 구성은 서버 코드에서 ScopedProviderProcess → create_scoped_provider_authority → accept_scoped_request 및 RequestExecutor(scoped_authority=...)다. 이 조합을 기존 실제 Python→Node 인수의 수락·실행에 연결했다. Node helper는 현재 JARVIS 생산용 verifier 조합을 호출하고 판정 필드를 정렬해 반환한다. 기존 수락 결과 기록 경로는 유지한다.

## 검증

최종 관련65개 통과(9.10초), 전체 Ruff 및 두 provider 채널 모듈 basedpyright 오류0/경고0. 실제 새 프로세스·환경 비상속·자식 회수·타임아웃·실패 코드·출력 초과·잘못된 JSON·최대 입력과 많은 stderr에서도 교착 없음·실행 파일 없음·잘못된 설정/입력 등을 확인했다. timeout 검사는 sleep 없이 블로킹 select를 사용하는 실제 자식을 종료한다.

[실제 JARVIS/Python 결과](SCOPED-PROVIDER-PROCESS-2026-09-09.json): 정상 저장 proved/현재 권한 검사5회; 수락 중 파일 정책 철회는 검사2회/수락 원장 없음; 실행 전 철회는 검사3회/failed/활성 세대 없음. 세 경우 모두 원래 dispatch attempt1/FK 오류0. 정상은 기존 만료 후 상태 복원과 현재 읽기 철회 거절도 통과했다.

전체1,275통과/2skip은 과거 전체 검사 기록이다. 이번 코드에 전체 검사 수치를 재사용하지 않으며 위65개가 최종 실행 범위다.

## 신뢰 경계와 보류

현재 POSIX 로컬 실행 전용이다. 지정 프로그램·코드·설정·인증 세션 공급자는 서버 운영자가 관리해야 한다. 전용 파이프는 선택한 로컬 프로그램과 응답을 연결하지만 그 프로그램의 정확성이나 원격 발신자를 인증하지 않는다. 요청의 writer 라벨에서 서버 인증 세션을 만드는 구성, 입력으로 실행 명령을 받는 구성, 원격 HTTP에 이 채널을 그대로 적용하는 구성은 보류한다.

인수의 세션과 시계는 fixture다. 실제 전송 코드는 사용했지만 운영 인증 세션 공급과 공개 scoped MCP 쓰기 endpoint를 완료한 것은 아니다. 다음 구현은 운영 서버 소유 세션/검증기 실행 진입점과 공개 쓰기 계약 연결, 실제 에이전트 A 저장→B 새 세션 회수다. 첫 세대 이전 상태 조회·전체 삭제/복원/재유입 억제·클라이언트별 수집/주입·검색 평가·GUI/운영 복구를 포함한 전체 M1–M14를 유지한다.

운영 DB/서비스/vault와 기존 계약·migration은 변경하지 않았고 push/배포는 수행하지 않았다.
