# Second Brain for macOS

네이티브 SwiftUI 메뉴바 앱이다. Ubuntu의 Second Brain 웹 API와 연결해 다음 기능을 제공한다.

- Finder 파일 드래그 앤 드롭 업로드
- 선택 폴더 자동 동기화
- 메뉴바 상태 아이콘과 즉시 실행
- 최신 일일 브리핑의 macOS 알림센터 전달
- 빠른 기억 입력과 지식 검색
- SSH 로컬 포워딩 자동 실행
- 로그인 시 자동 실행

## 요구 환경

- macOS 14 이상
- Xcode 15 이상 또는 동등한 Xcode Command Line Tools
- Ubuntu에서 실행 중인 `sb web`
- 맥의 `~/.ssh/config`에 접속 가능한 SSH Host 별칭

권장 SSH 설정:

```sshconfig
Host second-brain-web
    HostName <UBUNTU_SERVER_IP>
    User jm
    IdentityFile ~/.ssh/id_ed25519
    AddKeysToAgent yes
    UseKeychain yes
    ServerAliveInterval 30
    ServerAliveCountMax 3
```

앱은 기본적으로 다음 터널을 직접 실행한다.

```text
127.0.0.1:8765 → Ubuntu 127.0.0.1:8765
```

Ubuntu 웹 서비스는 외부 주소에 노출할 필요가 없다.

## 빌드 및 설치

저장소를 맥에 체크아웃한 뒤:

```bash
cd clients/macos/SecondBrainMac
./Scripts/build-app.sh
./Scripts/install-app.sh
```

기본 설치 위치는 `~/Applications/Second Brain.app`이다. 시스템 `/Applications`에 설치하려면:

```bash
./Scripts/install-app.sh /Applications
```

첫 실행 시 알림 권한을 허용한다. 선택 폴더 자동 동기화를 사용할 때는 앱 설정에서 폴더를 추가한다. 보안 범위 북마크가 저장되므로 앱을 재시작해도 선택이 유지된다.

## 최초 설정

1. 메뉴바의 뇌 아이콘을 클릭한다.
2. **설정**을 연다.
3. 서버 URL을 `http://127.0.0.1:8765`로 둔다.
4. Ubuntu 웹 서비스에 `SB_WEB_TOKEN`을 사용한다면 같은 토큰을 입력한다. 토큰은 macOS Keychain에 저장된다.
5. SSH Host 별칭을 입력하고 **연결 다시 시작**을 누른다.
6. **동기화 폴더 추가**로 Finder 폴더를 선택한다.
7. **업로드 후 즉시 처리**와 **새 브리핑 알림**을 켠다.

## 동기화 원칙

- 맥에서 Ubuntu 방향의 단방향 업로드다.
- 서버 파일을 맥 폴더로 되돌려 쓰지 않는다.
- 지원 문서만 업로드한다: PDF, DOCX, HWPX, XLSX, Markdown, TXT, JSON, YAML.
- 파일 경로와 크기·수정시각을 로컬 manifest에 기록한다.
- 폴더 이벤트와 주기적 전체 스캔을 함께 사용한다.
- 동일 파일 재전송은 서버의 upload identity로 중복 저장되지 않는다.
- 심볼릭 링크, 빈 파일, 숨김 파일, 10MiB 초과 파일은 건너뛴다.

## 알림센터 브리핑

앱은 `/api/briefing/latest`를 확인하고 마지막으로 알린 SHA-256과 다른 브리핑만 알린다. 전체 브리핑은 앱 창에서 읽을 수 있고, 알림 본문에는 Markdown을 제거한 짧은 요약만 표시한다.

## 운영 보안

- Ubuntu 웹 서버는 `127.0.0.1`에 바인딩한다.
- 맥 앱은 `/usr/bin/ssh`를 인자 배열로 직접 실행하며 셸을 사용하지 않는다.
- API 토큰은 UserDefaults가 아닌 Keychain에 저장한다.
- 폴더 접근은 사용자가 직접 선택한 보안 범위 북마크로 제한한다.
- 자동 동기화는 서버의 기존 `inbox-documents` 수집 경로만 사용한다.

## macOS 인증 게이트

릴리스 전 실제 맥에서 다음을 모두 확인해야 한다.

```bash
swift test
./Scripts/build-app.sh
/usr/bin/codesign --verify --deep --strict "dist/Second Brain.app"
open "dist/Second Brain.app"
```

그 후 실제 UI에서 파일 드롭, 폴더 변경 감지, 재부팅 후 북마크 복원, 로그인 항목, SSH 재연결, 알림센터 브리핑을 검증한다.
