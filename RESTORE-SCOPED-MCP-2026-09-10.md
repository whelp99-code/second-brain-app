# 복원 세대의 서명된 MCP 조회 검증

기준 제품 5838b77. 이전 목표 턴은 접근 제한 복원 구현·전체 1,674통과·커밋까지 수행한 진척이다. 이번에는 실제 sanitizer가 만든 후보 세대를 격리된 fixture GenerationStore.activate로 활성화하고, scoped-record-read-v5 MCP Client에서 서명된 요청으로 조회했다. 운영 저장소 활성화나 배포는 하지 않았다.

원본 백업 작성→실제 삭제→정제 복원→지식 및 접근 분류 재생성→봉인/활성화→MCP 조회의 연속 경로다. 최신 tombstone high water를 read fence에 결합하고 해당 페이지·세션·사용자·프로젝트·정책에 대한 access claim을 사용한다. 정상 응답의 기억 본문과 완전한 접근 projection을 확인했다. 다른 사용자·프로젝트·정책, 만료된 claim은 오류이며 본문이 포함되지 않는다. 정상 요청 뒤 설정에서 키를 철회하고 같은 요청을 재시도해 본문 반환 없이 거부되는 것도 확인했다.

이 검증은 MCP 라이브러리 Client와 실제 provider server를 같은 프로세스에서 연결한다. 키는 고정된 테스트 키이고 시계도 fixture 시간이다. 따라서 실제 JARVIS DB에서 발급한 권한, HTTPS/stdio 별도 프로세스, native 에이전트 로그인, 사용자 실업무의 인수 증거는 아니다. 이미 별도 항목에서 검증한 transport 동작을 이 복원 시나리오와 합치는 일은 남는다.

검증: restore integration 단독 **3 passed / 8.00초**. 이어서 기존 scoped MCP v1–v5 회귀와 복원을 합쳐 **13 passed / 17.12초**, Ruff 전체·diff 검사 통과. 제품 코드 변경은 없으며 전체 suite는 이전 5838b77 기준 1,674통과 기록을 유지한다. 이번 새 테스트를 포함한 전체 suite는 재실행하지 않았다.

테스트 helper: tests/restore_scoped_mcp.py. 활성화는 sanitizer의 후보 생성과 기존 active pointer 유지 검증이 끝난 다음, 명시적으로 테스트용 store에서만 수행한다. 운영 DB·서비스·공용 registry 및 다른 리포 변경·push 없음. 실제 JARVIS 연결/현재 정책 조합·DR·운영 및 M1–M14 전체 목표는 미완료다.
