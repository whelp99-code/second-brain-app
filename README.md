# Second Brain

Second Brain은 원본 보존·출처 추적·충돌 관리·복구 가능성을 우선하는 로컬 개인 지식 엔진이다. Ubuntu에서 엔진과 데이터 저장소를 운영하고, macOS에서는 네이티브 메뉴바 앱으로 기록·파일 업로드·폴더 동기화·검색·브리핑을 사용한다.

## 제공 인터페이스

- CLI: 운영·진단·백업·복원
- MCP: 검색, 페이지 읽기, 최근 변경, 충돌 조회, 기억 추가, 즉시 `sb_run`
- Web: 기억, 드래그 앤 드롭 파일 업로드, 검색, 충돌 해결, 상태·메트릭
- macOS 14+ SwiftUI 앱: 메뉴바, Finder 드롭, 선택 폴더 자동 동기화, Notification Center 브리핑, SSH 터널, Keychain

## Ubuntu 빠른 설치

```bash
cd /home/jm/orca/projects/second-brain-app
uv tool install --force .

mkdir -p ~/.config/second-brain
install -m 0600 config.example.toml ~/.config/second-brain/config.toml

SB_CONFIG=~/.config/second-brain/config.toml sb init
SB_CONFIG=~/.config/second-brain/config.toml sb doctor

./deploy/install-systemd-user.sh
```

활성화되는 사용자 서비스:

```text
second-brain-web.service       127.0.0.1:8765 웹/API
second-brain.timer             매시간 지식 처리
second-brain-backup.timer      매일 백업
```

확인:

```bash
systemctl --user status second-brain-web.service
curl http://127.0.0.1:8765/health
```

## 기본 설정

`~/.config/second-brain/config.toml`:

```toml
vault_root = "../../.local/share/second-brain/vault"

[llm]
argv_template = ["claude", "-p", "{prompt}"]
prompt_version = "v1"
model_id = "claude-cli"
external = true

[search]
hybrid = false

[[sources]]
id = "inbox"
adapter = "inbox-documents"
llm_policy = "allow"
sensitive = "mask"
```

외부 LLM에 보낼 수 없는 소스는 `llm_policy = "deny"` 또는 로컬 모델과 함께 `local-only`로 설정한다.

## macOS 앱

맥에 저장소를 체크아웃한 뒤:

```bash
cd clients/macos/SecondBrainMac
./Scripts/build-app.sh
./Scripts/install-app.sh
```

앱이 제공하는 필수 흐름:

```text
Finder 파일 드롭 → Ubuntu 업로드 → 즉시 sb run → 검색
선택 폴더 변경 → 자동 증분 동기화 → 중복 없는 수집
메뉴바 → 상태·동기화·즉시 실행·앱 열기
새 브리핑 → macOS Notification Center
```

상세 설정과 운영 방법은 [`MACOS-DESKTOP.md`](MACOS-DESKTOP.md)를 따른다.

## 주요 CLI

```bash
export SB_CONFIG="$HOME/.config/second-brain/config.toml"

sb remember "계약서는 수요일에 발송한다." --title "계약 일정"
sb run
sb search "계약서"
sb status --json
sb doctor
sb sources --json
sb retention --json
sb metrics --json
sb backup
sb verify-backup /path/to/second-brain-backup.tar.gz
```

전체 명령:

```text
init, ingest, compile, brief, run, status, rollback, doctor,
mcp, search, remember, retry, backup, verify-backup, restore, migrate,
resolve, web, sources, retention, gc, metrics
```

`sb backup`은 생성 후 임시 저장소로 복원하여 체크섬·원장·인용을 검사하고
`*.tar.gz.verified.json` 검증 기록을 남긴다. 기존 백업은 `verify-backup`으로 검사한다.
검증에는 복원용 추가 디스크 공간이 필요하며 임시 저장소는 검사 후 제거된다.
관리형 검증은 현재 provider·삭제 이력과 다른 백업을 복원 전에 거부한다.
운영 세대 활성화와 복원 권한 검사는 별도다. 출처가 없는 기존 백업은
준비 상태의 정상 근거로 사용하지 않으므로 새 백업을 생성해 검증한다.

웹의 `/health`는 프로세스 생존 여부, `/ready`는 작업·백업·요청 상태를 반환한다.
검증되지 않았거나 변경된 최신 백업, 오래된 성공 실행, 정체된 요청 등은
`/ready`에서 HTTP 503과 `reasons` 코드로 표시한다. 시간 기준은 설정할 수 있다.

```toml
[readiness]
max_run_age_hours = 48
max_backup_age_hours = 48
max_request_age_minutes = 15
failure_window_hours = 48
```

## MCP

도구:

```text
sb_search
sb_read_page
sb_recent_changes
sb_open_conflicts
sb_remember
sb_run
```

Ubuntu 서버에 SSH로 연결하는 맥 MCP 설정 예:

```json
{
  "mcpServers": {
    "second-brain": {
      "command": "/usr/bin/ssh",
      "args": [
        "-T",
        "-o", "ClearAllForwardings=yes",
        "second-brain-web",
        "env",
        "SB_CONFIG=/home/jm/.config/second-brain/config.toml",
        "/home/jm/.local/bin/sb",
        "mcp"
      ]
    }
  }
}
```

즉시 반영이 필요한 AI 흐름:

```text
sb_remember → sb_run → sb_search → sb_read_page
```

## 데이터 구조

```text
vault/
├── wiki/                 생성된 지식 페이지
├── wiki/_proposed/       사람 편집을 보호한 AI 제안본
├── daily/                일일 브리핑
├── conflicts/            충돌과 사람의 해결 기록
├── inbox/                기억·업로드 대기 자료
├── raw/                  SHA-256 CAS 원본
└── .sb/                  SQLite 원장·검색 인덱스·메트릭
```

`raw/`와 `.sb/`는 Vault Git에서 제외되며 백업에는 포함된다.

## 개발 검증

Ubuntu 기본 게이트:

```bash
uv run ruff check sb tests
uv run basedpyright sb tests
uv run pytest -q --ignore=tests/test_embeddings.py
uv build
```

macOS 앱 게이트는 실제 맥에서 수행한다.

```bash
cd clients/macos/SecondBrainMac
swift test
./Scripts/build-app.sh
/usr/bin/codesign --verify --deep --strict "dist/Second Brain.app"
```

현재 Ubuntu 자동 검증은 macOS 앱의 소스·API·보안 계약을 검사한다. AppKit, SwiftUI, Notification Center, Keychain, ServiceManagement의 실제 런타임 인수는 Xcode가 설치된 macOS에서만 완료할 수 있다.

## 운영 원칙

- 단일 사용자·단일 Vault·단일 writer
- 웹 API는 Ubuntu loopback에만 바인딩
- 맥 연결은 SSH loopback 터널 권장
- 업로드는 10MiB 제한, 확장자 allowlist, 상대경로 검증, 원자적 저장
- 맥 폴더 동기화는 서버 방향 단방향이며 삭제를 전파하지 않음
- 자동 conflict 해결과 무승인 원본 삭제 금지
- Push는 명시적 요청 없이 수행하지 않음
