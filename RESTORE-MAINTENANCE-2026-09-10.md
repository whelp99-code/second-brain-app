# 명시적 복원 작업공간 유지관리

기준 4870665. `sb maintain --once --restore-workspace PATH`를 추가했다. 기존 세대/export 유지관리가 끝나고 해당 service를 닫은 뒤, 명시한 복원 작업공간만 기존 디렉터리 잠금·안전 검사·관리 이름 정책으로 정리한다. 세대 잠금을 가진 채 작업공간 잠금을 기다리지 않는다. 잠금 사용 중이면 성공 응답에 restore_workspace_busy=true와 disposed_restore_workspaces=0을 반환한다. unsafe/missing 경로는 오류 종료하며 성공한 정리로 보고하지 않는다. 옵션 미지정 시 기존 출력·대상 범위 유지.

기존 restore_workspace에서 잠금과 정리를 _clean_locked로 분리해 sanitizer와 유지관리가 같은 구현을 사용한다. 새 임시 폴더를 만들기 위해 복원을 실행할 필요가 없다. 알려지지 않은 이름/구형 복구 자료는 보존하며 현재 관리 이름의 symlink는 거부한다.

검증: 관련 CLI generation/runtime·restore·workspace·실제 SIGKILL 재시도 **26 passed in 39.23s**, Ruff sb/tests 및 basedpyright cli/restore_workspace 0오류0경고, diff 통과. 새로운 실제 독립 CLI 검사는 살아 있는 restore의 파일 보존/busy, 별도 worker SIGKILL=-9 후 잔류 확인, CLI 정리1건/작업공간 비움, 다시 실행0건을 검증한다. 테스트용 키/본문과 격리 경로이며 운영 서비스는 변경하지 않았다.

직전 전체1698통과는 f45a1a1 기준이며 이번 제품 변경의 전체 재검증 수치가 아니다. 이번 변경은 실제 CLI 검증을 포함한 관련26개 결과로 보고한다.

운영 timer에 임의 경로를 자동 추가하지 않았다. 실제 sanitizer 작업공간 경로와 구버전 writer 종료를 확인하고 서비스 쓰기 허용 경로를 맞춘 운영 연결이 남는다. 잠금 미참여 구버전과 혼합 실행은 보류다. 이 명령은 폴더 연결부이며 원장 소실 DR·과거 고정 이름 처분·전체 사용자 업무/다중 모델 인수 완료가 아니다. 전체 M1–M14 목표 유지, push 없음.
