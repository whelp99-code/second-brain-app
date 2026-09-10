# JSONL 세션 파서의 FIFO 교체 대기 방지

세션 checkpoint는 먼저 file_revision으로 일반 파일을 확인하지만 네 파서는 이후 별도 path.open('rb')를 호출했다. 그 사이 파일이 FIFO로 교체되면 외부 writer가 올 때까지 대기할 수 있다. Codex adapter.scan을 실제 별도 Python 프로세스로 실행하고 revision 확인 직후 os.mkfifo로 교체하자 10초 timeout으로 실패했다. subprocess.run이 시간 초과 자식을 종료·회수했다.

session_checkpoint에 공통 open_session_file을 추가했다. O_NONBLOCK/O_NOFOLLOW로 열고 열린 descriptor가 일반 파일인지 fstat으로 확인한 뒤만 binary stream을 제공한다. 정상/예외 모두 wrapper와 descriptor를 닫는다. Claude·Codex·OMO·GJC JSONL reader가 이를 사용한다. checkpoint의 읽기 오류 보고·이전 cursor 보존 및 기존 전체 파일 revision 검사는 유지한다.

네 adapter 각각 실제 자식 프로세스와 FIFO 교체로 검증: 대기 없이 unreadable-session-file 1개를 반환하고 cursor0 유지. 기존 파일 교체/재개/native Claude/export 회귀 포함 **50 passed / 0.60초**. Ruff sb/tests·변경5모듈 basedpyright **0 errors / 0 warnings**, diff 통과. 최초 정적 검사에서 테스트 subprocess의 명시적 check 인자 누락을 찾아 기본과 같은 check=False로 정리했다.

이 변경은 최종 파일 구성요소의 symlink/특수 파일 교체 대기를 닫는다. 모든 상위 경로 교체, 무제한 큰 파일·전체 세션 수집 예산, 다른 형식의 reader까지 해결했다고 주장하지 않는다. 실제 운영 계정 세션·서비스를 변경하지 않았으며 합성 파일로 실제 adapter 프로세스를 검사했다. 앞선 전체 회귀/설치 후보 이후 제품 변경이고, 사용자 업무/운영·M1–M14 전체 인수는 유지한다.
