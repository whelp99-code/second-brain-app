# 대기 inbox 세대 복사 안전성 — 2026-09-09

발견: copy_pending_inbox는 is_file/is_symlink로 목록을 고른 뒤 Path.read_bytes로 읽었다. 하드링크가 단일 링크 일반 파일로 복제되어 세대에 들어갔다. 수정 전 하드링크 거부 회귀가 실패했고 정상 복사는 통과했다.

수정: inbox 기준 디렉터리 descriptor로 각 상위 경로를 O_NOFOLLOW로 열고, 최종 파일은 O_NOFOLLOW/O_NONBLOCK으로 연다. fstat으로 regular·현재 UID·같은 장치·단일 링크를 확인한다. 읽기 크기를 최초 크기+1로 제한하고 크기/mtime/ctime/link 수 변화 시 GENERATION_SOURCE_UNSAFE로 거부한다. 모든 파일 읽기와 삭제 재유입 검사를 마친 뒤 destination에 복사한다. 실패 시 원본은 수정하지 않는다.

검증: 관련 11개 테스트 통과(4.87초). 하드링크 거부, 정상 nested 파일 복사, .done/.requests 제외, 목록 수집 후 symlink/FIFO/상위 디렉터리 symlink 교체를 결정적으로 재현했다. Ruff import 정리 후 통과, basedpyright 오류·경고 0. 실제 TLS/gateway/MCP/CLI 자비스 통합 4경로도 통과했다. 정상 완료와 새 로그인·독립2클라이언트 회수, 철회/만료 차단 유지.

한계: 이 수정은 선택된 대기 파일의 읽기 경계를 보강한다. inbox에 동시에 새 파일이 추가되는 경우의 목록 완전성, inbox 루트 이전의 경로 교체 및 전체 수집 예산을 증명하지 않는다. 원래 제외되던 심볼릭 링크를 목록 단계에서 새 오류로 바꾸지는 않았다. 별도의 inode 소유권/재개 정책과 전체 세대 전환 인수는 남는다. 통합 데이터·identity·시각은 fixture이며 운영 활성화나 실제 모델 요청을 실행하지 않았다.
