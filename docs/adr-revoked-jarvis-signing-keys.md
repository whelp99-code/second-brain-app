# ADR: durable Jarvis signing-key revocations

상태: 채택. 정본은 `state_root/revoked-jarvis-signing-key-ids`다. config.toml의 철회 목록은 관측 시 이 파일에 합쳐지며, 설정 복원만으로 옛 키를 되살리지 않는다.

최초 부재는 빈 집합이다. 기존 파일이 symlink·디렉터리·열 수 없으면 `REVOCATION_STORE_UNSAFE`이며 빈 목록으로 바꾸지 않는다. 쓰기는 flock과 고유 임시 파일, fsync, `os.replace`로 직렬화한다.

구버전 `41f0751`은 이 파일을 읽지 않는다. 링크만 되돌리는 자동 rollback은 철회를 보존한다고 보지 않는다.
