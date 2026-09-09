# 세대 공개 직후 배치 강제 종료·재시작 검증

기존 generation activation barrier를 사용해 관리형 run_all의 두 지점에서 실제 자식 프로세스를 SIGKILL했다: pointer_rename(포인터 교체 직후), activation_verify(활성화 원장 갱신 직후). 제품 activation 로직은 바꾸지 않고 자식 검증 프로세스에서 barrier를 주입했다.

각 지점에서 새 active 세대와 완료 batch를 관측한 뒤 종료했다. 새 서비스 인스턴스에서 maintain을 두 번 호출했다. active는 공개된 새 세대를 유지했고 같은 batch ID/상태/시각이 남았으며 이전 세대가 처분됐다. 대기 원본1건의 바이트도 유지됐다. 원래 run_all을 재호출하지 않고 복구했으므로 새 배치를 만들어 성공으로 덮지 않았다.

관련 managed/ordinary batch crash 및 runtime reliability **8 passed / 7.93초**, Ruff/diff 통과. 별도 스크립트에서도 두 강제 종료 지점을 다시 실행해 같은 조건을 확인했다. [실제 프로세스 결과](PUBLISHED-BATCH-CRASH-2026-09-10.json).

검증은 합성 원본이 있는 임시 저장소이며 sources=[]로 원본 처리 없이 publication 경계를 검사했다. 모델 호출, 외부 부수 효과의 재실행 방지, 실제 업무 내용의 검색 품질은 이번 범위가 아니다. SIGKILL은 프로세스 종료이며 호스트 전원 차단이나 저장장치 write-cache 유실을 재현한 것은 아니다. pointer_rename 이전/이후 모든 내부 명령 위치의 완전한 종료 행렬이라고 주장하지 않는다.

이번 커밋은 회귀 테스트와 증거를 추가한다. 실제 검증 자식들만 종료했으며 운영 서비스·데이터 변경 없음. 공개 전 버려진 batch의 별도 영속 감사, 최신 설치 반영, 실제 업무/다른 에이전트 공유·운영 및 M1–M14 인수는 남는다.
