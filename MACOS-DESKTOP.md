# macOS 데스크톱 사용·운영 가이드

## 1. 목표 사용자 경험

Second Brain은 Ubuntu에서 지식 엔진을 운영하고 macOS에서 네이티브 앱으로 사용하는 구조를 기본으로 한다.

```text
macOS Second Brain.app
├── Finder 파일 드래그 앤 드롭
├── 선택 폴더 자동 동기화
├── 메뉴바 상태·동기화·즉시 실행
├── 빠른 기억 입력·검색
├── Notification Center 브리핑
└── SSH loopback 터널
          ↓
Ubuntu 127.0.0.1:8765
├── /api/uploads
├── /api/run
├── /api/briefing/latest
├── /api/search
└── 기존 inbox → CAS → Wiki 파이프라인
```

맥 파일은 Ubuntu로 단방향 업로드된다. 서버가 사용자의 맥 폴더를 수정하거나 삭제하지 않는다.

## 2. Ubuntu 준비

### 2.1 프로그램과 설정

```bash
cd /home/jm/orca/projects/second-brain-app
uv tool install --force .
mkdir -p ~/.config/second-brain
install -m 0600 config.example.toml ~/.config/second-brain/config.toml
```

설정 파일에 inbox 소스를 명시한다.

```toml
vault_root = "../../.local/share/second-brain/vault"

[[sources]]
id = "inbox"
adapter = "inbox-documents"
llm_policy = "allow"
sensitive = "mask"
```

초기화와 진단:

```bash
SB_CONFIG=~/.config/second-brain/config.toml sb init
SB_CONFIG=~/.config/second-brain/config.toml sb doctor
```

### 2.2 자동 처리·백업·웹 API

```bash
cd /home/jm/orca/projects/second-brain-app
./deploy/install-systemd-user.sh
```

이 설치는 다음을 활성화한다.

- `second-brain-web.service`: Ubuntu loopback 웹 API
- `second-brain.timer`: 매시간 지식 처리
- `second-brain-backup.timer`: 매일 백업

확인:

```bash
systemctl --user status second-brain-web.service
systemctl --user list-timers --all 'second-brain*'
curl http://127.0.0.1:8765/health
```

### 2.3 선택적 API 토큰

SSH 터널만 사용하면 웹 서비스는 loopback 밖에 노출되지 않는다. 추가 인증을 사용하려면:

```bash
TOKEN=$(openssl rand -hex 32)
printf 'SB_WEB_TOKEN=%s\n' "$TOKEN" > ~/.config/second-brain/environment
chmod 600 ~/.config/second-brain/environment
systemctl --user restart second-brain-web.service
printf '%s\n' "$TOKEN"
```

출력된 토큰을 맥 앱 설정에 한 번 입력한다. 앱은 토큰을 macOS Keychain에 저장한다.

## 3. 맥 SSH 설정

`~/.ssh/config`:

```sshconfig
Host second-brain-web
    HostName <UBUNTU_IP_OR_HOSTNAME>
    User jm
    IdentityFile ~/.ssh/id_ed25519
    AddKeysToAgent yes
    UseKeychain yes
    ServerAliveInterval 30
    ServerAliveCountMax 3
```

연결 확인:

```bash
ssh -T second-brain-web 'curl -fsS http://127.0.0.1:8765/health'
```

앱은 이 Host 별칭으로 `/usr/bin/ssh -N -L ...`을 직접 실행한다. 셸 문자열을 실행하지 않는다.

## 4. macOS 앱 빌드·설치

맥에 저장소를 체크아웃한 뒤:

```bash
cd clients/macos/SecondBrainMac
./Scripts/build-app.sh
./Scripts/install-app.sh
```

기본 위치:

```text
~/Applications/Second Brain.app
```

시스템 Applications에 설치:

```bash
./Scripts/install-app.sh /Applications
```

앱은 macOS 14 이상, Xcode 15 이상을 대상으로 한다.

## 5. 최초 앱 설정

1. 메뉴바의 뇌 아이콘을 클릭한다.
2. **설정**을 연다.
3. 서버 URL을 `http://127.0.0.1:8765`로 둔다.
4. SSH Host 별칭을 `second-brain-web`로 둔다.
5. API 토큰을 사용한다면 입력한다.
6. **SSH 터널 자동 연결**을 켠다.
7. **동기화 폴더 추가**로 Finder 폴더를 선택한다.
8. **업로드 후 즉시 처리**를 켠다.
9. **새 브리핑을 알림센터에 표시**를 켜고 권한을 허용한다.
10. 필요하면 **로그인 시 Second Brain 실행**을 켠다.

## 6. 파일 드래그 앤 드롭

앱 창의 **파일 드래그 앤 드롭** 영역에 문서를 놓는다.

지원 형식:

```text
PDF, DOCX, HWPX, XLSX, Markdown, TXT, JSON, YAML
```

처리 순서:

```text
파일 드롭
→ 크기·확장자 검사
→ base64 API 전송
→ 서버 상대경로·digest 검증
→ inbox/uploads 원자적 저장
→ sb run
→ CAS·Wiki·검색 반영
```

동일 device/path/content 재전송은 새 파일을 만들지 않는다.

## 7. 폴더 자동 동기화

앱 설정에서 사용자가 직접 폴더를 선택한다. 앱은 보안 범위 북마크를 저장한다.

동기화는 두 신호를 함께 사용한다.

1. 폴더의 파일 시스템 이벤트
2. 설정된 주기의 전체 재스캔

로컬 manifest에는 상대경로, 크기, 수정시각, 서버 upload ID만 저장한다. 다음은 업로드하지 않는다.

- 심볼릭 링크
- 숨김 파일
- 빈 파일
- 미지원 확장자
- 10MiB 초과 파일

삭제는 전파하지 않는다. 맥에서 파일을 삭제해도 서버 CAS와 지식은 자동 삭제되지 않는다.

## 8. 메뉴바 사용

메뉴바에서 다음을 즉시 실행할 수 있다.

- 연결 상태 확인
- 폴더 동기화
- `sb run` 즉시 처리
- 상태 새로고침
- 최신 브리핑 요약 확인
- 전체 앱 창 열기
- 설정 열기

## 9. Notification Center 브리핑

앱은 `/api/briefing/latest`를 주기적으로 확인한다. 브리핑의 SHA-256이 마지막 알림 값과 다를 때만 새 알림을 전송한다.

- 알림 제목: 브리핑 페이지 제목
- 알림 본문: Markdown과 각주를 제거한 최대 240자 요약
- 전체 내용: 앱의 **최신 브리핑**에서 확인

## 10. MCP 즉시 실행

MCP 도구 집합에 `sb_run`이 포함된다.

권장 AI 흐름:

```text
sb_remember
→ sb_run
→ sb_search
→ sb_read_page
```

`sb_run`은 별도 우회 실행기가 아니다. 웹·CLI와 같은 `run_all()` 및 같은 `run.lock`을 사용한다. 이미 실행 중이면 두 번째 writer를 시작하지 않고 `already_running=true`를 반환한다.

## 11. 장애 대응

### 앱에서 연결 실패

```bash
ssh -T second-brain-web 'systemctl --user status second-brain-web.service --no-pager'
ssh -T second-brain-web 'curl -fsS http://127.0.0.1:8765/health'
```

앱 설정에서 **연결 다시 시작**을 누른다.

### 업로드됐지만 검색되지 않음

메뉴바에서 **지금 처리**를 누르거나 MCP `sb_run`을 호출한다. 이후:

```bash
ssh -T second-brain-web 'SB_CONFIG=$HOME/.config/second-brain/config.toml sb status'
ssh -T second-brain-web 'SB_CONFIG=$HOME/.config/second-brain/config.toml sb doctor'
```

### 폴더 변경이 즉시 감지되지 않음

메뉴바에서 **동기화**를 누른다. 파일 시스템 이벤트가 누락돼도 주기적 전체 스캔이 보완한다.

## 12. macOS 릴리스 인수시험

실제 맥에서 다음을 모두 통과해야 macOS 지원 완료로 판정한다.

1. `swift test`
2. `.app` release build
3. ad-hoc 또는 배포 인증서 서명 검증
4. 앱 실행 후 메뉴바 아이콘 표시
5. 한글 파일 드롭·업로드·즉시 검색
6. 중복 드롭 시 서버 중복 파일 0
7. 선택 폴더 하위 파일 변경 자동 감지
8. 앱 재시작 후 폴더 북마크 복원
9. 새 브리핑 1회만 Notification Center 표시
10. SSH 단절 후 재연결
11. 로그인 항목 활성화 후 재로그인 실행
12. 10MiB 초과·심볼릭 링크·경로 탈출 거부
