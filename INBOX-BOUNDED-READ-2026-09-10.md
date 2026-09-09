# 받은편지함 특수 파일·교체 중 읽기 보강

inbox_documents의 stat→read_bytes 경로는 FIFO에서 대기하거나 stat 이후 커진 파일을 제한 없이 읽을 수 있었다. O_NONBLOCK/O_NOFOLLOW로 파일을 열고 실제 descriptor가 일반 파일이며 최초stat의 device/inode/mode/size/mtime/ctime과 일치하는지 검사한다. 최대10MiB+1만 읽고 길이와 descriptor/path identity를 다시 검사한다. 변경/특수파일은 unreadable로 건너뛰며 다음 scan에서 다시 검사한다. acknowledge의 내용 확인에도 같은 읽기를 적용했다.

실제 FIFO를 writer 없이 독립 Python 프로세스에서 scan:10초 timeout 안에 정상종료/skip, 같은cursor재개중복0. 일반파일을 read직전 다른inode로 교체하는 결정적 검사:그회차skip/다음scan새본문회수. 기존 파서·done이동·pending inbox·walking skeleton 포함20passed/3.78초. Ruff전체/변경모듈타입0오류0경고/diff통과.

한계: path 부모 디렉터리 교체 및 acknowledge 검증 뒤 rename 직전 경합까지 descriptor기반으로 닫은 것은 아니다. 읽은 내용의검증과 이동의원자적동일성은 다른 조건이다. 후속으로 정확히읽은inode만이동/변경된입력보존을 검토해야 한다. 운영데이터변경없음, 전체M1–M14유지.
