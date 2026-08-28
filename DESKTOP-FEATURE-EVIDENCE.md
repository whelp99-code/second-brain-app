# Second Brain macOS 데스크톱 기능 검증 증거

검증일: 2026-08-28  
검증 호스트: Ubuntu  
브랜치: `release/second-brain-1.0.0`  
현재 Python 패키지 버전: `1.0.0`  
상태: Ubuntu 릴리스 검증 및 macOS 네이티브 빌드·서명·설치·실행 검증 완료

## 1. 필수 기능 구현 현황

| 필수 기능 | 구현 위치 | Ubuntu 자동 검증 | 실제 macOS 인증 |
| --- | --- | --- | --- |
| 맥 파일 드래그 앤 드롭 업로드 | SwiftUI 앱, 웹 drop zone, `POST /api/uploads` | 통과 | 앱 빌드 통과, 서버 연결 후 실파일 전송 검증 필요 |
| 폴더 자동 동기화 | 보안 범위 북마크, DispatchSource, 주기 스캔, manifest | 소스·계약 통과 | Swift 6 단위 테스트 통과 |
| 메뉴바 아이콘 | SwiftUI `MenuBarExtra` | 소스·계약 통과 | 설치 앱 프로세스 실행 확인 |
| 알림센터 브리핑 | `/api/briefing/latest`, `UNUserNotificationCenter` | API·소스 계약 통과 | 컴파일 통과, 사용자 권한 승인 후 실알림 검증 필요 |
| 네이티브 macOS 앱 | Swift Package, AppKit·SwiftUI, `.app` 빌드 스크립트 | 소스·bundle 계약 통과 | Swift 6.3 테스트·release 빌드·서명·설치·실행 통과 |
| MCP 즉시 `sb run` | MCP `sb_run` → 기존 `run_all` lock | 단위·통합 통과 | 서버 계약 통과, 실제 AI 클라이언트 호출 권장 |

## 2. 구현된 서버 계약

### 파일 업로드

```text
POST /api/uploads
```

검증 항목:

- 최대 원본 10MiB
- 지원 확장자 allowlist
- base64 유효성
- 상대경로 탈출 방지
- NUL·절대경로·`..` 거부
- 선택적 SHA-256 일치 검증
- 0600 원자적 저장
- `device + relative path + content hash` 기반 중복 방지
- 처리 전 재시도: `already-queued`
- inbox 처리 후 재시도: `already-ingested`

### 즉시 처리

```text
POST /api/run
MCP sb_run
```

웹·MCP·CLI 모두 `Config.configured_source_ids`를 사용한다. 설정에 inbox만 있으면 다른 기본 소스를 임의로 스캔하지 않는다. 모든 실행은 동일한 `run.lock`과 `run_all()`을 사용한다.

### 브리핑·기능 조회

```text
GET /api/briefing/latest
GET /api/capabilities
```

브리핑 응답은 page ID, 전체 본문, frontmatter, SHA-256을 제공한다. 맥 앱은 SHA-256이 변경된 브리핑만 알림센터에 전달한다.

## 3. 네이티브 macOS 앱 구조

```text
clients/macos/SecondBrainMac/
├── Package.swift
├── Sources/SecondBrainCore/
│   ├── Models.swift
│   ├── APIClient.swift
│   └── FolderSync.swift
├── Sources/SecondBrainMac/
│   ├── AppSettings.swift
│   ├── SystemServices.swift
│   ├── AppModel.swift
│   └── SecondBrainMacApp.swift
├── Tests/SecondBrainCoreTests/
├── Resources/Info.plist
└── Scripts/
    ├── build-app.sh
    └── install-app.sh
```

보안·운영 특성:

- API token: macOS Keychain
- SSH: `/usr/bin/ssh`를 인자 배열로 실행, shell 미사용
- 서버 노출: Ubuntu `127.0.0.1:8765`
- 맥 로컬 포워딩: `127.0.0.1:18765` → Ubuntu `127.0.0.1:8765`
- 연결: 맥 SSH local forwarding
- 폴더 접근: 사용자가 직접 선택한 bookmark
- 동기화: Mac → Ubuntu 단방향
- 삭제 전파: 없음
- 파일 무결성: Swift CryptoKit SHA-256 → 서버 재검증
- symlink descendant가 선택 폴더 실경로 밖으로 해석되면 동기화 제외
- 알림센터 브리핑은 기본 비활성이고 사용자가 명시적으로 켬
- 로그인 실행: `SMAppService.mainApp`

## 4. Ubuntu 자동 검증 결과

### 정적 검사

```text
Ruff: PASS
BasedPyright: 0 errors, 0 warnings
```

### Python 테스트

```text
362 passed
3 skipped
```

예상된 skip:

```text
SB_LIVE_DB!=1
optional live embedding model smoke
optional live LLM smoke
```

### 배포 자산

```text
bash -n: PASS
systemd-analyze verify: PASS
isolated installer --dry-run: PASS
```

활성화 대상 및 실운영 결과:

```text
second-brain 1.0.0 user tool install: PASS
second-brain-web.service: active (running), restart 0
127.0.0.1:8765 /health: {"status":"ok"}
second-brain.timer: enabled
second-brain-backup.timer: enabled
```

user systemd가 capability drop을 허용하지 않는 환경에서 실패하던 `ProtectControlGroups`, `ProtectKernelModules`, `ProtectKernelTunables`는 제거했다. `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`, 쓰기 경로 제한은 유지한다.

### 패키지 빌드

```text
second_brain-1.0.0-py3-none-any.whl
second_brain-1.0.0.tar.gz
```

Wheel 포함 확인:

```text
sb/uploads.py
sb/web.py
sb/mcp.py
sb/pipeline.py
sb/prompts/compile.md
sb/prompts/conflict.md
```

### 실제 macOS 네이티브 검증

```text
Apple Swift 6.3.3 / Xcode 26.6
swift test: 6 passed, 0 failed
release build: PASS
ad-hoc codesign verification: PASS
Info.plist lint: PASS
install: ~/Applications/Second Brain.app
process launch: PASS
screen capture: macOS Screen Recording 권한 미허용으로 증거 이미지 미생성
```

실기 과정에서 Swift Core import 누락, SwiftUI 색상 타입 불일치, 기존 AgentCat의 로컬 `8765` 점유를 발견해 수정했다. macOS 앱은 로컬 `18765`를 사용하고 Ubuntu 웹 서비스는 원격 `8765`를 유지한다.

## 5. 설치형 데스크톱 API E2E

새 Python 3.12 가상환경에 freshly built Wheel을 설치한 뒤, 기존 사용자 Vault가 아닌 격리 Vault에서 실행했다.

실행 흐름:

```text
sb init
→ 인증된 파일 업로드
→ POST /api/run
→ inbox ingest
→ CAS 저장
→ cited Wiki 생성
→ 한글 검색
→ daily briefing 조회
→ 동일 파일 재업로드
→ sb doctor
```

결과:

```text
upload state: queued
run status: ok
run exit_code: 0
pages: 1
errors: 0
Korean search results: 2
briefing: daily/2026-08-28
duplicate state: already-ingested
doctor exit_code: 0
```

검증 중 발견하고 수정한 실제 결함:

```text
웹/MCP 즉시 실행이 명시된 inbox 이외의 기본 소스까지 스캔해
성공한 compile·briefing에도 최종 API 결과를 failed로 반환하던 문제
```

수정 후 CLI·웹·MCP가 동일한 명시적 source selection을 공유한다.

## 6. Ubuntu에서 인증할 수 없는 항목

현재 Ubuntu 작업 호스트에는 다음 실행기가 없다.

```text
swift
xcodebuild
AppKit runtime
Notification Center
macOS Keychain runtime
SMAppService runtime
```

따라서 다음은 구현 완료와 별개로 실제 맥 인증이 남아 있다.

- `swift test`
- release Swift build
- `.app` bundle 생성·서명 검증
- 메뉴바 아이콘 표시
- Finder 실제 drop
- security-scoped folder bookmark 재시작 복원
- 하위 폴더 변경 자동 감지
- Notification Center 1회 알림
- SSH 단절·재연결
- 로그인 항목 재로그인 실행

## 7. 실제 맥 최종 인증 명령

```bash
cd clients/macos/SecondBrainMac
swift test
./Scripts/build-app.sh
/usr/bin/codesign --verify --deep --strict "dist/Second Brain.app"
/usr/bin/plutil -lint "dist/Second Brain.app/Contents/Info.plist"
open "dist/Second Brain.app"
```

실기 인수 기준은 `MACOS-DESKTOP.md`의 **macOS 릴리스 인수시험**을 따른다.

## 8. 현재 판정

### Ubuntu 서버·API·MCP

**PASS**

### 네이티브 macOS 구현 소스·프로토콜·배포 구조

**PASS**

### 실제 macOS 앱 런타임 인증

**PENDING — 실제 macOS/Xcode 환경 필요**

실제 맥 인증이 끝나기 전에는 macOS 앱을 정식 출시 완료로 표시하지 않는다.
