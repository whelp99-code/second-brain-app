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

수집 원본의 owner/project 분류는 선택적인 `[source_access.<source id>]`에 명시한다. 예를 들어 별도로 설정한 `docs` 원본에는 다음을 사용할 수 있다.

```toml
[source_access.docs]
owner = "principal:owner"
projects = ["project:alpha"]
policy_revision = "policy:1"
```

일반 wiki 컴파일은 실제 입력 원본 및 이전 페이지의 요구 분류를 원장 `page_access`에 커밋 본문 해시와 함께 보존한다. 출처가 확인되지 않는 본문이나 미분류 원본이 섞이면 불완전 상태로 남는다. 이는 분류 추적이며 MCP 접근 권한 검사는 아니다. [페이지 출처 구현과 남은 범위](PAGE-ACCESS-PROVENANCE-2026-09-09.md)를 참고한다.


프로젝트 목록은 중복 없이 정렬하며 최대 64개다. 빈 목록은 owner 전용 분류를 뜻한다. 신규 처리 원본의 source ID·URI·내용 해시에 분류를 결합해 원장에 저장한다. 기존 분류를 바꾸면 `SOURCE_ACCESS_RECLASSIFICATION_REQUIRED`로 수집을 거부하며, 과거 무분류 원본을 자동 재분류하지 않는다. **현재 이 설정은 분류 기록 기능이며 MCP/API 접근 제어가 아니다.** 접근 claim·record/page 분류 결합과 범위 검사가 연결되기 전까지 기존 owner 프로필의 조회 범위는 그대로다.

의미 검색은 기본적으로 꺼져 있다. `[search] hybrid = true`와 사용 가능한 임베딩 모델을 설정하면 다음 관리형 세대 생성부터 인용 가능한 기억 레코드의 벡터를 함께 봉인한다. 이미 봉인된 세대는 설정 변경만으로 재색인되지 않는다. 모델이 없거나 맞지 않으면 일반 검색을 유지하며, 큰따옴표 검색은 정확 문구 검색으로 처리한다. 모델 품질·대용량 지연 검증과 운영 활성화 판단은 [의미 검색 인수 보고서](SEALED-VECTOR-ACCEPTANCE-2026-09-08.md)를 따른다.

`[search] min_similarity`로 의미 후보의 최소 cosine 점수를 지정할 수 있다. 범위는 -1부터 1이며 미설정 기본값 -1은 기존 후보를 유지한다. 일반 검색 결과에는 적용하지 않는다. 모델과 자료별 평가로 값을 정해야 하며, 높은 유사도가 원문에 답이 있음을 보장하지는 않는다. [실제 100질문 비교·최소 유사도 검증과 한계](SEMANTIC-RELEVANCE-2026-09-08.md).

수집 예산은 `[caps]`의 `max_new_units_per_run`(신규 고유 unit 수)과 `max_source_items_per_run`(원본 버전 처리 시도 수)으로 나눈다. 기본값은 각각 500이다. 파일 수 키를 생략한 이전 설정은 unit 제한값을 파일 수 상한으로도 계승한다. `sb ingest --limit N`은 파일 수만 조정하며 unit 제한은 그대로 적용한다.

한 원본이 전체 unit 예산을 넘으면 `INGEST_UNIT_BUDGET_EXCEEDED`와 종료 코드 1을 반환하고 원본을 보존한다. 해당 원본의 규모를 확인해 설정을 조정하거나 원본을 나눈 뒤 재실행한다. 잔여 예산에만 맞지 않는 원본은 `capped`로 남고 다음 실행에서 처리한다. [예산 계약과 인수](INGEST-BUDGET-CONTRACT-2026-09-08.md).

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

여러 검색어는 모두 포함된 자료를 찾으며 어순은 달라도 된다. 예를 들어 `sb search "배포 오로라"`는 `오로라 배포는 목요일`을 찾는다. 입력한 문구가 연속으로 있는 결과를 먼저 표시한다. MCP는 모든 검색어가 같은 인용 레코드에 있는 경우만 반환한다. 조사·질문어를 자동으로 제거하거나 의역을 해석하는 검색은 아직 지원하지 않으므로 핵심 검색어를 사용한다.

연속된 문구만 찾으려면 검색 내용에 큰따옴표를 포함한다: `sb search '노을 "세 번 실패"'`. 이 예시는 `노을`과 정확한 문구 `세 번 실패`가 모두 있는 근거를 찾는다. 입력 한도는 4,096 UTF-8 bytes·32개 검색 그룹이며, 초과하거나 따옴표가 닫히지 않으면 오류가 반환된다. 큰따옴표 그룹 안의 `\"`는 따옴표 문자, `\\`는 역슬래시 문자로 처리한다.

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

자비스의 일반 여러 줄 기억은 명시적 `remember-schema5` 계약과 V3 요청을 사용한다. 기존 프로필은 유지한다. 새 후보 입력·`JARVIS_SECOND_BRAIN_CONTRACT_PROFILE` 설정·실제 검증과 운영 미배포 범위는 [V3 인수 보고서](REMEMBER-V3-ACCEPTANCE-2026-09-08.md)를 따른다.

일반 stdio 기본 프로필에는 `sb_search`, `sb_read_page`, `sb_recent_changes`, `sb_open_conflicts`, `sb_remember`, `sb_write_request`의 6개 도구가 있다. `remember-schema5`는 이 6개와 `sb_generation_status`, `sb_request_status`, `sb_resolve_memory_target`의 총 9개를 제공한다. `sb_run`은 desktop용 서버 표면에만 있으며 일반 stdio 목록에는 없다.

실제 Codex CLI와 Claude Code의 같은 기억 저장소 양방향 기록·회수는 [에이전트 클라이언트 인수 보고서](AGENT-CLIENT-MEMORY-ACCEPTANCE-2026-09-08.md)를 따른다. 이는 단일 소유자·삭제 이전의 격리 프로필 검증이며 프로젝트 접근 격리·자동 수집/문맥 주입·운영 연결을 보장하지 않는다.

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

기록 후 회수 흐름:

```text
sb_remember → 운영 배치 또는 명시적 CLI 처리 → sb_search → sb_read_page
```

`sb_remember` 응답은 inbox 접수이다. 일반 stdio 클라이언트는 이 응답만으로 검색 반영 완료를 알 수 없다. 명시적 처리에는 서버의 `sb ingest`와 `sb compile`을 사용하며, 실제 compile에는 설정된 LLM이 필요하다. 자비스의 승인된 쓰기·완료 확인 경로는 V3 인수 보고서의 요청/outbox 계약을 따른다.

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

## 범위 제한 record 조회 연결

관리형 vault와 JARVIS 공개키가 설정된 서버에 아래 명시적 설정을 추가하면 `scoped-record-read-v1` 연결로 동작한다. 이 연결은 서명된 `read_fence`와 `access_claim`을 요구하는 `sb_read_page` 하나만 제공하며, 응답은 분류 검증된 records와 세대 정보다. 기존 전체 기능 클라이언트의 대체 프로필은 아니다.

```toml
[mcp_scoped_read]
principal = "principal:owner"
agent = "agent:jarvis"
session = "session:configured-session"
policy_revision = "policy:1"
```

이 값은 서버가 신뢰하는 연결 문맥이며 사용자 요청에서 복사하면 안 된다. 실제 발급기의 인증된 scope resolver와 맞춰야 한다. 현재 서버 설정/공개키는 시작 시 읽으므로 정책·세션·키 철회 설정 변경에는 서버 재구성이 필요하다. 자동 정책 갱신, 전체 검색·쓰기·status·export·restore, 다중 사용자 인증은 아직 연결되지 않았다. [구현과 실제 stdio 인수](SCOPED-MCP-RECORD-READ-2026-09-09.md)를 따른다.
