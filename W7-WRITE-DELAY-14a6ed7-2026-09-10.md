# W7 쓰기 지연 표본 — 후보 `14a6ed7`

운영 불변. fsync를 제거하지 않았다. 클라이언트 timeout 목표를 달성했다고 보지 않는다.

writecost 랩을 복사해 설정 경로만 바꿨다. 17,343파일 / 36.5MB에서 `sb remember` **21.54s, exit 0**. 이전 후보 `c04dee1` 단일 표본 21.36s와 같은 자리다. 반복 1회, cold/warm 구분 없음, MCP p50/p95 없음.

빈 `sb init` 뒤 remember 3회는 `WRITE_REQUEST_INBOX_UNSAFE`로 실패했다. 2000파일 부분 복제는 세대/요청함이 안전하지 않아 쓰지 않는다.

고아 journal 자동 `proved`는 추가하지 않았다. 지연을 timeout 아래로 내렸다고 쓰지 않는다.
