# 디렉터리 복원 원본 파일 식별 고정

기존 복원은 lstat 검사 후 Path.open으로 읽어, 그 사이 파일이 바뀌면 검사한 파일과 다른 내용을 복사했습니다. 같은8바이트 일반파일 교체 및 외부 symlink 교체를 실제 파일시스템에서 결정적으로 주입해 수정 전2개 실패를 재현했습니다.

사전 목록에 파일 metadata를 보관하고 복사 직전에도 동일성을 확인합니다. 일반파일은 O_NOFOLLOW|O_NONBLOCK으로 열고 fstat의 device/inode/mode/nlink/size/mtime_ns/ctime_ns를 검사 당시 값과 비교합니다. 최대 읽기 크기를 유지하며 읽기 후 열린 descriptor를 다시 검사하고, 크기 불일치도 거부합니다. descriptor는 예외 시에도 닫습니다. 경로를 다시 열어서 읽지 않습니다.

같은크기 교체/외부symlink/FIFO 교체3경우 모두 RESTORE_ARCHIVE_UNSAFE로 거부하고 대상 파일을 만들지 않았습니다. FIFO의 경우 입력을 기다리지 않음을 확인했습니다. 외부 원본 내용도 보존됐습니다. 기존 tar/서명복원 포함24개 통과(13.38초), FIFO 추가 후 archive15개 통과(0.35초), Ruff sb/tests 및 restore 정적검사0오류0경고입니다. 실행은 중복되어 합산하지 않습니다.

범위는 디렉터리 원본의 파일 읽기 식별입니다. tar 입력 descriptor 고정, 전체 파일시스템의 적대적 동시 변경, 아카이브 전체 snapshot 원자성까지 입증한 것은 아닙니다. 운영 DB·서비스·기존 사용자 파일을 변경하지 않았습니다.
