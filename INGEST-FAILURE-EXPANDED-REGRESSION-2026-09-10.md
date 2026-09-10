# 수집 실패 처리 확대 회귀

제품 df5d822까지의 읽기 실패/재유입 검증 불능 상태 변경을 기존 기능과 함께 검증했다. 두 검사 집합은 테스트 파일이 겹치지 않는다.

- 수집 읽기/재유입 오류, 단위 예산, source 선택, inbox ack, web, readiness, 배치 crash/managed crash, 실제 배치 읽기 실패 상태, session source isolation: **69 passed / 59.33초**.
- inbox connector, fs_safety runtime, web run failure, generation pending inbox: **28 passed / 3.11초**.

누적97개에서 기존 원문 보존·오류 응답·배치 중단/재시작·출처 분리와 충돌하는 회귀는 확인되지 않았다. 두 명령의 실행 시간이 일부 겹쳤으며 성능 벤치마크가 아니다.

추가 정리: pipeline._register_compiled의 registry.put 반환값을 `_ =`로 명시하여 기존 basedpyright 미사용 반환값 경고를 제거했다. 호출과 저장 동작은 유지한다. 그 뒤 walking-skeleton 통합 게이트 **2 passed / 3.99초**, pipeline basedpyright **0 errors / 0 warnings**, 캐시 없는 전체 sb/tests Ruff 통과.

확대 회귀97개는 반환값 표기 정리 전 제품 기준, walking-skeleton2개·정적 검사는 정리 후 기준이다. 전체 pytest와 새 설치물 자비스 인수는 이번에 재실행하지 않았다. 최신 전체1,767통과 및 설치 인수의 기준은13cab77이며, 이후 변경은 각 집중·실제 CLI/HTTP 검증 기록으로 구분한다. 운영 전환과 실제 사용자 업무/native 세션의 전체 수명 및 M1–M14는 미완료다.
