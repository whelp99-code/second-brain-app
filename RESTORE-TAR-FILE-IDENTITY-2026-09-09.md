# tar 복원 입력 식별 고정

기존 tarfile.open(path)는 symlink 및 hardlink 입력을 허용하고 읽기 도중 원본 변경 여부를 확인하지 않았습니다. 실제 tar의 링크2종과 extractall 직후 바이트 추가1종에서 수정 전 거부 회귀가 모두 실패했습니다.

입력을 lstat로 일반파일/nlink1인지 검사하고 O_NOFOLLOW|O_NONBLOCK으로 한 번 엽니다. descriptor metadata를 검사한 뒤 fileobj를 tar 파서에 전달합니다. 정상 처리 종료 시 descriptor와 원래 경로의 device/inode/mode/nlink/size/mtime_ns/ctime_ns가 초기 값과 같은지 다시 검사합니다. 열기·파싱 실패를 포함해 descriptor는 닫습니다. 기존 tar member 목록/크기/경로 검사도 유지합니다.

검증: 새3개 포함 archive18개 및 서명 복원/권한/재유입 전체28 passed(12.79초), Ruff sb/tests, restore 정적검사0오류0경고. 링크 입력은 출력 전에 거부됩니다. 처리 도중 변경은 읽기를 마친 후 실패하며 직접 _extract 호출의 임시 출력이 이미 생길 수 있습니다. 공개 sanitize 경로의 예외 staging 정리가 그 자료를 처리합니다. 이번 테스트가 임시 추출 중 다른 프로세스의 관측까지 방지한다고 주장하지 않습니다.

이것은 읽기 전후 파일 식별 검사이며 악의적 원본 변경의 모든 형태나 tar 내부 파서의 CPU/메모리 격리를 입증하지 않습니다. 운영 서비스와 DB는 변경하지 않았습니다.
