# 효과 상태 재결합 경계의 실제 SIGKILL 복구

기준 제품 de542d2. 제품 변경 없이 실제 자식 프로세스 강제 종료 통합 테스트를 추가했다.

## 두 종료 지점

1. erasure가 끝나고 bound knowledge를 기록하기 직전. 원장 transaction은 열려 있으나 새 상태는 아직 쓰지 않았다.
2. 상태 재결합 함수가 완료되어 staging 원장 commit까지 끝났으나 새 generation 봉인/publication 전.

multiprocessing spawn으로 독립 Python 프로세스를 실행한다. 자식은 실제 RequestExecutor로 접수된 forget 요청을 처리한다. Event로 목표 지점 도달을 확인하고 살아 있는 자식만 Process.kill로 종료한다. join 후 exitcode=-SIGKILL을 확인한다. sleep이나 실행 시간 추측으로 종료 시점을 선택하지 않는다. 죽인 프로세스가 기다리던 Event는 재사용하지 않는다.

## 복구 결과

두 경우 모두 종료 뒤 원래 활성 generation ID와 원문은 유지된다. 새 RequestExecutor가 원장을 다시 열고 lease 만료 이후 같은 request ID를 재처리해 proved로 완료한다. tombstone sequence/set root는 중복 증가하지 않는다. 새 세대로 전환되고 삭제 대상은 reference 검색에 없으며 남은 사실은 active VERIFIED로 회수된다. 인용 검사 통과 및 abandoned staging 제거도 확인했다.

초기 두 기록/승인 상태는 fixture에서 실제 materializer·CAS·원장·publication으로 만들었다. 따라서 초기 기억 생성은 native 모델 인수가 아니다. 이후 effect 접수·삭제·DB/세대 복구는 실제 경로이며 예외를 던지는 모사만으로 대체하지 않았다.

## 검증

`TMPDIR=/var/tmp uv run pytest -q tests/integration/test_effect_knowledge_sigkill.py tests/test_effect_knowledge.py tests/integration/test_memory_crash_recovery.py --tb=short`: **13 passed / 9.22초**. 실제 SIGKILL 두 경우와 기존 rollback/장애 회귀를 포함한다. Ruff 전체·diff 통과.

전원 손실/fsync 장치 장애, pointer 전환 이후 새 지식 상태의 SIGKILL, 정정/취소 경쟁, 복원 상태, scoped 접근, 실제 사용자 업무·최신 설치/운영 및 M1–M14는 남는다. 이번 테스트 추가 후 전체 suite를 다시 실행하지 않았다. 운영 프로세스는 종료하지 않았으며 운영 DB·서비스·공용 registry 변경과 push 없음.
