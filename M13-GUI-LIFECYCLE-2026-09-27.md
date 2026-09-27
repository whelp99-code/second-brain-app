# M13 GUI 수명 — 2026-09-27

판정: **미통과.** 운영 웹 GUI에 기억 본문을 고치는 정정 흐름이 없다. 컴파일된 시험 페이지는 GUI로 삭제됐지만, 같은 GUI 처리가 오늘 브리핑에 센티널을 남겼고 그 줄을 지울 GUI 정정이 없어 검색 건수는 0이 아니다. CLI로 정정하거나 삭제하지 않았다. `IMPLEMENTATION-STATUS.md`는 바꾸지 않았고 커밋하지 않았다.

## 대상

- 운영 웹: `http://127.0.0.1:8765` (`second-brain-web.service` active, 릴리스 `1e7a7fefb93c88c81fb1de67555f39936675c2e9`)
- `[web] token`은 `~/.config/second-brain/config.toml`에 없다. 토큰을 넣지 않았다.
- 브라우저: owned engine (`connectPipe`, `/opt/google/chrome/chrome`, `--headless=new`, 작업용 `/tmp/omowright-m13-*` 프로필). 사용자 본 프로필을 쓰지 않았고 쿠키를 지우지 않았다. 세션은 모두 `browser.close()`로 닫혔고 해당 프로필 프로세스는 남아 있지 않다.
- 센티널: `M13SENT0cced706`
- 본문 시작: `[M13-TEST 2026-09-27]`
- 만든 기억: 1건. 두 번째 remember는 하지 않았다.

## 문서에서 확인한 GUI

`docs/MANUAL.md` §7.6과 운영 HTML(`sb/web.py` 내장 콘솔, 라이브 `/` 13071바이트)의 버튼은 기억하기, 지금 처리, 영수증 삭제, 검색, 전체 열기, 페이지 삭제, 해결 기록, 7일 변경 조회, 상태 조회다. `정정`/`correct`/`correction`/`수정` 문자열은 없다.

`IMPLEMENTATION-STATUS.md`의 H3/H4는 GUI 버튼이 아니다. H3는 삭제 경합 격리, H4는 삭제 전 백업 수명 격리이고, M13 행은 `blocked_external`(실사용자 처분, H3/H4 격리는 배포됨)이다. 이 파일은 수정하지 않았다.

## 한 일

1. 빈 내용으로 기억하기. GUI가 `content is required`를 보였다. 이어서 같은 칸에 시험 문장을 넣고 기억하기로 복구했다.
2. GUI 기억하기가 세대 변이를 끝내기 전에 20초 폴링이 끊겼다. 서버는 그 클릭의 POST를 마쳤고 inbox 파일 1개만 생겼다. `inbox/2026-09-27T114501963748-m13-test-m13sent0cced706.md`. 본문은 `[M13-TEST 2026-09-27] M13SENT0cced706`로 시작한다.
3. GUI `지금 처리`. `run_id=a124da30ed1242028499792bf219103c`, `status=ok`, `pages=1`, `conflicts=0`, `errors=0`, `exit_code=0`, `already_running=false`.
4. 검색이 컴파일 페이지 `wiki/inbox-2026-09-27t114501963748-m13-test-m13sent0cced706-03328480`를 찾았다. 같은 처리의 브리핑이 `daily/2026-09-27` 「오늘의 추천」에도 센티널 한 줄을 넣었다.
5. `전체 열기` 원문에 센티널과 각주 `inbox:2026-09-27T114501963748-m13-test-m13sent0cced706.md`가 있었다.
6. 영수증은 콘솔 라벨 `영수증 경로`다. 첫 세션은 성공 JSON을 그리기 전에 폴링이 끝났다. 이어진 세션에서 그 inbox 경로를 영수증 칸에 표시했다. 별도 영수증 문서 화면은 없다.
7. 정정 컨트롤을 라이브 DOM에서 다시 세었다. 제목은 API 토큰, 운영 준비 상태, 처리 실패, 최근 단계 실행 이력, 기억 추가, 파일 업로드, 처리 결과, 검색, 열린 충돌, 최근 변경, 소스·보존. 버튼은 저장, 기억하기, 지금 처리, 영수증 삭제, 파일 선택, 업로드 후 지금 처리, 검색, 전체 열기, 페이지 삭제, 새로고침, 해결 기록, 7일 변경 조회, 상태 조회. 정정에 해당하는 항목은 0개다. `해결 기록`은 충돌 결정이지 본문 교체가 아니다. CLI 정정으로 넘어가지 않았다.
8. 없는 페이지 `wiki/m13-stale-not-a-page`를 GUI에서 삭제해 `compiled page missing`을 봤다. 시험 페이지를 다시 열었고 센티널이 그대로였다.
9. 페이지 ID가 센티널을 포함하고 본문에도 센티널이 있는 그 위키 페이지만 `페이지 삭제`했다. GUI 결과: `forgotten=wiki/inbox-2026-09-27t114501963748-m13-test-m13sent0cced706-03328480`, `commit=ad21d09cb78cf64ca3203cea589338c7d58584b3`. 현재 세대에 그 위키 파일은 없다. `daily/2026-09-27`은 다른 브리핑이 있으므로 삭제하지 않았다.

## 삭제 뒤 확인

- GUI 검색: 결과 2건, 페이지 ID는 `daily/2026-09-27`뿐. 위키 페이지 ID는 없다. 센티널 문자열은 「오늘의 추천」에 남아 있다. 건수 0이 아니다.
- GUI `전체 열기`는 `Failed to fetch`다. 없는 페이지 GET은 HTTP 응답 없이 연결이 끊긴다. 서버 로그는 `PageNotFoundError: page not found` 뒤에 `read_root` 종료 중 `TypeError: super(type, obj): obj must be an instance or subtype of type`이다. 있는 페이지 `daily/2026-09-27`은 HTTP 200이다. 삭제 뒤 원문 화면은 `page not found`를 보여 주지 않는다.
- 삭제 영수증: GUI가 보여 준 것은 위 `forgotten`/`commit` JSON이다. 삭제 상태로 바뀌는 별도 영수증 화면은 없다. inbox 파일은 현재 세대 inbox에 없다.
- 읽기 전용 CLI: `SB_CONFIG=~/.config/second-brain/config.toml ~/.local/state/second-brain/app/current/bin/sb search M13SENT0cced706` exit 0. 위키 페이지는 없고 `daily/2026-09-27`만 나온다. 건수 0이 아니다. 요약: `.omo/evidence/ulw/mass-20260927/m13/cli-search-summary.txt`.

## 운영 타이머

GUI 상태, 단계 이력, 소스·보존(metrics 포함)에 timer, OnCalendar, systemd가 없다. `systemctl --user list-timers` (기록 시각 약 20:49 KST):

| 유닛 | NEXT | LAST |
|---|---|---|
| `jm-second-brain-maintenance.timer` | 2026-09-27 21:00:00 KST | 2026-09-27 20:00:02 KST |
| `jm-second-brain-refresh.timer` | 2026-09-27 21:00:53 KST | 2026-09-27 20:00:42 KST |
| `second-brain-backup.timer` | 2026-09-28 03:24:08 KST | 2026-09-27 03:17:59 KST |

전체 출력: `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13/systemd-timers.txt`. refresh/requests 유닛은 이번에 시작하지 않았다. 처리는 GUI `지금 처리`로 했다.

## 스크린샷

너비 1440은 CSS viewport 1440x900 PNG다. 390은 `16c-search-390.png` (390x844, `innerWidth=390`). `16-search-after-390.png`는 deviceScaleFactor 3 캡처라 1170x2532이고 390 증거로 쓰지 않는다. `16b`는 빈 clip이라 쓰지 않는다.

| 단계 | 경로 |
|---|---|
| 콘솔 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13/01-console-1440.png` |
| 상태 로드 후 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13/01b-console-status-1440.png` |
| 실패 목록 자리 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13/02-status-failures-1440.png` |
| 빈 기억 오류 `content is required` | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13/03-empty-remember-error-1440.png` |
| 처리 결과 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13/05-run-result-1440.png` |
| 검색 히트 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13/06-search-1440.png` |
| 원문 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13/07-original-page-1440.png` |
| 영수증 경로 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13/08-receipt-1440.png` |
| 정정 컨트롤 없음 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13/09-no-correction-control-1440.png` |
| 없는 페이지 삭제 오류 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13/10-stale-forget-error-1440.png` |
| 오류 뒤 원문 재확인 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13/11-recovery-reread-1440.png` |
| 페이지 삭제 결과 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13/12-forget-result-1440.png` |
| 삭제 후 검색 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13/13-search-after-delete-1440.png` |
| 삭제 후 검색 재확인 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13/13b-search-after-retry-1440.png` |
| 삭제 후 원문 `Failed to fetch` | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13/14-page-after-delete-1440.png` |
| 같은 오류 재확인 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13/14b-page-missing-1440.png` |
| 소스·보존·metrics | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13/15-metrics-governance-1440.png` |
| 390 검색 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13/16c-search-390.png` |

행동 기록: `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13/action-log.jsonl`.

## 남는 것

- GUI 정정 흐름이 없다. 그래서 M13을 통과로 적지 않는다.
- `daily/2026-09-27` 「오늘의 추천」에 시험 문장 한 줄이 남는다. GUI `지금 처리`의 브리핑이 넣었다. 그 페이지를 지우면 다른 브리핑이 같이 지워지므로 지우지 않았다. 정정 GUI가 없어 그 줄만 되돌리지 못했다.

## R2 (배포 13ff2cf3)

판정: **미통과.** 운영 콘솔에 정정 컨트롤은 있다. 시험 문장 1건을 골라 정정 저장을 한 번 눌렀고, GUI는 `ManagedInspectionError`를 돌려줬다. 그 클릭은 서버에서 끝나 있었고 처리 중이 아니었다. 활성 페이지는 바뀌지 않았고 센티널 검색은 0이 아니다. 같은 영수증을 다시 제출하지 않았다. 새 시험 기억은 만들지 않았다. `verified`로 적지 않는다.

### 대상

- 운영 웹: `http://127.0.0.1:8765` (`second-brain-web.service` active, MainPID 2231615, 릴리스 `13ff2cf32660677b35e9e96cd1db3fd04234a3a2`). 유닛은 2026-09-27 22:04:33 KST에 시작됐다. NRestarts=0.
- 릴리스 매니페스트 `source_commit`은 `fbccedb0a519976414cd398c8babd82e9290106a`다. 그 커밋은 `7e84605` 다음 문서 커밋이다. 배포된 `sb/web.py`에는 `정정 저장`과 `correctPageButton`이 있다.
- `[web] token`은 없다. 토큰을 넣지 않았다.
- 브라우저: owned engine (`connectPipe`, `/opt/google/chrome/chrome`, `--headless=new`, `/tmp/omowright-m13-r2-a4drXx`). 사용자 프로필을 쓰지 않았다. 세션은 `browser.close()`로 닫혔고 그 프로필 프로세스는 남지 않았다.
- 지우려던 센티널: `M13SENT0cced706`. 페이지 삭제는 누르지 않았다.

### 단계

| 단계 | 판정 | 사실 |
|---|---|---|
| GUI 검색 | 통과 | 결과 2건. page_id는 `daily/2026-09-27`뿐. |
| 전체 열기·영수증 | 통과 | `page_content_digest=sha256:01552f1339d27f0aa2b2da9b2bf602609071f6ac3615155029794ca5bb8b137e`. 문장 6개 중 센티널 문장 1개. |
| 문장 선택 | 통과 | 선택지 6개 중 센티널을 포함한 선택지 1개. 본문 48자. |
| 정정 저장 | 실패 | 22:15:18 KST 클릭, 22:15:59 KST GUI `ManagedInspectionError`. HTTP 본문은 예외 클래스 이름만이다. |
| 검색 0 | 실패 | 읽기 전용 CLI `sb search M13SENT0cced706` exit 0, 센티널 1, page_id `daily/2026-09-27`. |
| 다른 브리핑 유지 | 통과(활성 페이지 불변) | 아래 건수. 활성 파일을 고치지 않았다. |
| 새 수명주기 1건 | 실행 안 함 | 같은 정정·삭제 경로가 백업 검사에서 닫힌다. 두 번째 센티널을 남기지 않으려고 기억하기를 하지 않았다. |
| 빈 정정·낡은 영수증 409 | 실행 안 함 | 미완료 영수증이 있다. 두 번째 effect는 우회다. |
| 삭제 후 404 | 실행 안 함 | 삭제를 누르지 않았다. |
| 390 화면 | 없음 | 정정 응답 뒤 검색 대기에서 클라이언트 관찰이 끊겨 390 캡처 전에 세션이 닫혔다. |

활성 `daily/2026-09-27`은 정정 전과 같다. 바이트 2566, 줄 43, 시험 표지 줄 4, 그 외 줄 39, 센티널 정확 일치 2. GUI가 연 본문만 따로 세면 문자 1406, 줄 25, 시험 표지 줄 3, 그 외 줄 22, 센티널 정확 일치 2다. 다른 브리핑 문장은 인용하지 않는다.

### 서버는 처리 중이 아니었다

정정 클릭의 응답은 약 41초 뒤에 왔다. 그 다음 GUI 검색이 3분 넘도록 안 바뀐 것은 클라이언트 관찰기다. 같은 검색 JSON이라 결과 칸이 다시 안 그려졌고, 서버 대기가 아니다. 확인 시각에 웹 프로세스는 `poll_schedule_timeout`이고 `/health`는 HTTP 200이다. `journalctl --user -u second-brain-web`의 22:14:50–22:17:30 KST 창은 0줄이다. 핸들러가 트레이스를 남기지 않는다.

영수증 `owner-effects/9e7fde4ef2abba379fe0e6fed128f93f2498ea23514208c1ac0fd19429421e72.json`:

- `operation=correct`, `page_id=daily/2026-09-27`, `result=null`.
- `result_generation_id=sbgen:v1:bbfa04a9c54f88c03c3b893320a4b1181e38d79235e4cba4ac54905e6cb3ee05`. 이 세대는 디스크에 있으나 `vault` current가 아니다.
- 대체 본문 14자가 남아 있다. 성공 뒤 지우는 스크럽이 실행되지 않았다.
- 요청 저널 `tombstone_replica` 1행, sequence 1, 같은 request_id, `effective_at=2026-09-27T13:15:21.881Z`. `managed_copy_disposals` 0행. `requests` 0행. `pending`·`processing` 파일 0.
- current는 여전히 `sbgen:v1:ce3a9b2d2188f4995855cfff1839479b4ff23f8ebc7f9b57c3eb194f36880bc7`.

활성화되지 않은 후속 세대의 `daily/2026-09-27`은 바이트 2605, 줄 44, 시험 표지 줄 1, 그 외 줄 43, 센티널 정확 일치 1이다. 운영 검색은 이 세대를 보지 않는다.

읽기 전용으로 백업 루트 108개 파일을 같은 검사기에 넣었다. `.tar.gz` 40개가 모두 `MANAGED_ARCHIVE_UNSUPPORTED`다. 일치 0. 정정 활성화는 이 검사 뒤에서 멈춘다. GUI는 코드 문자열이 아니라 클래스 이름만 보여 준다. 백업 파일은 지우거나 고치지 않았다.

### 운영 타이머

`systemctl --user list-timers` (기록 시각 약 22:24 KST, `XDG_RUNTIME_DIR=/run/user/1000`):

| 유닛 | NEXT | LAST |
|---|---|---|
| `jm-second-brain-maintenance.timer` | 2026-09-27 23:00:00 KST | 2026-09-27 22:00:03 KST |
| `jm-second-brain-refresh.timer` | 2026-09-27 23:00:12 KST | 2026-09-27 22:00:30 KST |
| `second-brain-backup.timer` | 2026-09-28 03:28:42 KST | 2026-09-27 03:17:59 KST |

전체 출력: `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13-r2/systemd-timers.txt`. refresh/maintenance 유닛은 이번에 시작하지 않았다.

### 스크린샷

너비 1440은 CSS viewport 1440x900 PNG다. 390 캡처는 없다.

| 단계 | 경로 |
|---|---|
| 콘솔 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13-r2/01-console-1440.png` |
| 정정 전 검색 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13-r2/02-search-before-1440.png` |
| 원문·영수증 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13-r2/03-original-receipt-1440.png` |
| 문장 선택 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13-r2/04-correction-ready-1440.png` |
| `ManagedInspectionError` | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13-r2/05-correction-result-1440.png` |
| 실패 후 화면 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13-r2/99-cleanup-failure-1440.png` |

행동 기록: `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13-r2/action-log.jsonl`. 서버 상태: 같은 디렉터리의 `server-state.json`.

### 준비 상태

(a) 이 세션은 `second-brain-web`을 재시작하지 않았고, 위 복구 지시 전에는 `sb backup`을 실행하지 않았다. 웹 `ActiveEnterTimestamp`는 2026-09-27 22:04:33 KST, `NRestarts=0`이다. 그 시각 저널은 옛 릴리스 `1e7a7fef`의 PID 1732103을 멈추고 현재 유닛을 시작했다. 타이머와 path 유닛도 같이 재시작됐다. 배포 쪽 재시작이지 이 세션의 `systemctl restart`가 아니다. `second-brain-backup.service`의 마지막 실행은 03:17:59 KST다. `second-brain-20260927T220247+0900.tar.gz`는 22:02:54 KST에 만들어졌고 22:03:49 KST에 검증 영수증이 붙었다. 이 세션의 첫 CLI 검색은 22:15:10 KST다.

22:03:17과 22:03:47의 `sqlite3.OperationalError: database is locked`는 옛 웹 PID 1732103의 `do_GET` → `initialize_cancellations` `BEGIN IMMEDIATE`다. 같은 분에 MCP `sb_generation_status`와 `second-brain-cli-broker`도 같은 잠금으로 실패했다. 이 세션의 CLI와 웹이 겹친 기록이 아니다.

(b) `/ready` degraded는 백업 폐기가 아니다. `managed_copy_disposals`는 0행이고 `220247` 아카이브와 `.verified.json`은 그대로다. 결함이다. 검증 영수증의 tombstone은 sequence 0, `sha256:7fb694c8abb7c9a4477aa38381c49446493bc4da1c01b50690c1db5b2c20b9d3`다. 활성 세대 `generation.json`도 sequence 0이다. 요청 저널과 `/ready`의 `tombstone_high_water`는 정정 클릭이 남긴 sequence 1, `sha256:20c5fadd19f18ea81861e7a4cabeedab3a22d2545207387866c4923eb916e193`다. 세대는 활성화되지 않았는데 high-water만 올라갔다. 그래서 있는 검증 백업이 `BACKUP_TOMBSTONE_OR_PROVIDER_MISMATCH`다. 기대된 삭제 의미(사본 폐기 후 새 백업)와 다르다.

복구 전 `/ready`: HTTP 503, `status=degraded`, reasons `VERIFIED_BACKUP_UNAVAILABLE`, `LATEST_BACKUP_UNVERIFIED`, `backup_error=BACKUP_TOMBSTONE_OR_PROVIDER_MISMATCH`, `latest_backup=second-brain-20260927T220247+0900.tar.gz`. 저장: `m13-r2/ready-before.json`.

(c) 문서 경로만 사용했다. 백업 파일을 손으로 지우지 않았다. `sb verify-backup` `second-brain-20260927T220247+0900.tar.gz`는 exit 1, `BACKUP_TOMBSTONE_OR_PROVIDER_MISMATCH`. 이어서 `sb backup` 1회도 exit 1, 같은 코드다. 새 아카이브 `second-brain-20260927T222918+0900.tar.gz`와 `.sha256`만 남고 `.verified.json`은 없다. 활성 세대 sequence 0을 담은 아카이브가 저널 sequence 1과 맞지 않는다. 복구 후 `/ready`는 여전히 HTTP 503, `degraded`, 같은 두 reason이다. `latest_backup`은 `second-brain-20260927T222918+0900.tar.gz`, `backup_error=BACKUP_VERIFICATION_MISSING`으로 바뀌었다. `ready`로 되돌리지 못했다. 저장: `m13-r2/ready-after.json`, `verify-backup-latest.txt`, `sb-backup.txt`.

### 남는 것

- 활성 `daily/2026-09-27`에 `M13SENT0cced706`이 남는다. 검색 건수는 0이 아니다.
- 미완료 영수증과 접수된 tombstone sequence 1, 활성화되지 않은 후속 세대가 남는다. 다시 정정 저장을 누르지 않았다.
- 새 시험 기억은 없다.
- `/ready`는 `ready`가 아니다. 문서의 `sb backup`은 이 split에서는 검증 영수증을 만들지 못한다.

## 운영 불일치 복구 2026-09-27

판정: **복구 통과.** 2026-09-27 23:55 KST 확인에서 SB `/ready`는 HTTP 200 `ready`,
JARVIS `http://127.0.0.1:4173/api/v1/health`의 `second_brain.readiness`도 `ready`다.
JARVIS 코드·설정·권한·서비스는 바꾸지 않았다. 새 시험 기억은 만들지 않았다.

### 원인과 수정

1. 운영 백업의 외부 형식은 `second-brain-backup-v1` / PAX tar / gzip이다. 사본 검사기가
   `.git/objects/pack/*.idx`를 무조건 거절했고 Git pack도 해석하지 못했다. 실제 아카이브를
   `/var/tmp`로 복사한 재현에서 이 지점이 `MANAGED_ARCHIVE_UNSUPPORTED`의 첫 원인이었다.
   정상 ZIP 원본 외에 UTF-8 대체 문자로 손상된 ZIP 형태의 raw 원본도 있었고,
   옛 app 1.0.0 / ledger schema 2 백업 12개에는 `origin` 필드가 없었다.
2. Git pack은 격리된 자원 제한 Git 프로세스로 검사하고 정상 ZIP도 예산 내에서 해석한다.
   해석할 수 없는 원본을 포함한 백업은 부재라고 판정하지 않는다. 컨테이너의 매니페스트·모든
   파일 해시를 검증한 뒤 제품의 사본 폐기 경로로 통째로 폐기한다. 옛 백업과 중단된 사이드카
   폐기도 재개할 수 있다. 원본 백업은 아래 관리 루트 밖 구조 사본에 보존했다.
3. tombstone 접수는 세대 활성화보다 앞선다. 이를 되감거나 SQLite를 직접 편집하지 않고,
   fsync된 owner 의도를 `sb maintain --once`가 재실행하도록 했다. 미완료 owner 영수증이 있으면
   다른 정정·삭제를 먼저 접수하지 않는다. 완료 영수증의 replacement는 지운다.
4. 같은 daily 페이지의 `origin=... hash=... text=...` 근거 줄도 지운 출처의 사본이므로 제거한다.
   반면 운영 원장의 해시 참조는 본문 사본이 아니다. 기존 광범위 파일 삭제가 원장 전체를
   지우는 결함을 격리 재현에서 발견해, 관련 페이지에만 출처 해시 조건을 적용했다. 원장에 실제
   삭제 대상 본문이 남으면 실패하며, 무관한 원장 행을 지워 성공으로 만들지 않는다.
5. 재실행이 새 sealed 세대를 만들면 옛 sealed 형제 세대가 남아 `GENERATION_CLEANUP_STALLED`가
   됐다. 부모가 이미 폐기되어 활성화할 수 없고 읽기 lease도 없는 세대만 기존 staging 폐기
   경로로 정리한다. rename 직후 중단과 재실행을 테스트했다.
6. JARVIS의 최종 `protocol_incompatible`은 계약 파일 변경이 아니었다. `900f447` 릴리스와
   복구 릴리스의 실제 tools/list·입출력 스키마는 동일했고, JARVIS의 `inspectFrozenSchemas`도
   둘 다 통과했다. 두 릴리스 모두 sequence 1에서 `sb_generation_status({"read_fence": null})`를
   `TOMBSTONE_FENCE_REQUIRED`로 거절했다. sequence 0에서 드러나지 않던 bootstrap 결함이다.
   schema-4의 내용 없는 전역 상태 조회만 허용했다. 본문·검색·개별 요청 proof는 계속 fence를
   요구하고, 명시한 잘못된 fence도 계속 거절한다. 고정 계약과 sidecar SHA-256은 그대로
   `ae2e4b4f41ade29e8781e47e60dad6ddb17ed8cea516b82ccd16454acd5dc3e0`다.

### 보존과 배포

- 최초 변경 전에 `cp -a`로 state/share 전체를
  `/var/tmp/sb-split-rescue-20260927T224450+0900/`에 복사했다. 530,665개 파일,
  11,591,684,425바이트. `manifest.json` SHA-256:
  `5e41819bad3746da65dd17223b675432449216dd4173f36013fa742574f8435d`.
- 서비스 정지 뒤 같은 구조 폴더의 `quiesced/`에 활성 세대와 owner/request/control journal을
  추가 복사하고 별도 명세를 남겼다. sequence 1 복구 뒤에도
  `/var/tmp/sb-split-rescue-20260927T232953+0900-consistent/`를 보존했다. 명세 SHA-256:
  `5f1e04a4fbf3a4d433eadd48830690cce660d6baaea2ad31b37bb6eebda9dfe1`.
- 구조 사본에는 삭제 대상 원문도 남아 있다. 관리 루트 밖 0700 복구 자료이며 자동으로 지우지
  않았다. 운영 백업을 손으로 지우지 않았고 JSON·SQLite·vault 포인터도 직접 편집하지 않았다.
- 코드 커밋: `e74a9bf4fb77336a4800beae48b113432bc71d9c`,
  `6da0568f6256e1f6894ab94b9f4fb630843852fe`,
  `3b045534d03f9e91c20e69e0a1db9ad207a664e2` (master, 요청한 두 footer 포함, push 없음).
- 각 후보는 clean tree에서 `python3 deploy/prepare-release.py --offline`으로 빌드했다.
  §10.5의 requests.path·refresh.timer·maintenance.timer·web 정지, `app/current` 원자 교체,
  재시작 순서를 사용했다. 최종 릴리스는 `06ea5e96db0d04f8176ed5279a63343ff0df9b9d`다.
  상태 복구는 제품의 `sb maintain --once`로 수행했다. 롤백은 필요하지 않았다.

### 최종 확인

| 항목 | 측정 결과 |
|---|---|
| 전체 테스트 | 최종 `uv run pytest -q`: exit 0, 2225 passed, 기존 skip 3개 |
| Ruff | `uv run ruff check sb tests`: exit 0 |
| 회귀 순서 | 아카이브·중단 복구·오류 코드·원장 보존·sealed 정리·MCP bootstrap 실패를 먼저 기록한 뒤 수정 |
| 세대·저널 | 활성 `sbgen:v1:35a4ddab383d83a41caa7a9ecb52cb999248b0a231d3c618e591199378c5f0d8`; 둘 다 sequence 1, root `sha256:20c5fadd19f18ea81861e7a4cabeedab3a22d2545207387866c4923eb916e193` |
| 센티널 | CLI `no match`, 웹 검색 `results=[]`, 활성 daily 정확 일치 0 |
| daily 보존 | 이전 43줄 중 비시험 39줄; 이후 43줄 모두 비시험. 기존 37줄은 그대로이고 2줄은 지운 출처의 sid/hash를 새 영수증 출처로 재결속. 무관한 사실 줄은 보존 |
| 파일 보존 | wiki/daily/conflicts/raw 중 34,249개 파일 해시 불변. 해당 daily 1개만 변경, 대상 raw 1개 제거, 정정 출처 raw 1개 추가 |
| 원장 보존 | source_item 8,633, unit 8,207, derivation 8,913, run 1,549, derivation_event 27,436 등 운영 행 누락 0. bound_knowledge는 8,703→8,704 |
| owner 영수증 | `9e7fde4e…`: 완료 result 존재, replacement=null |
| 옛 미활성 세대 | `bbfa04a9…` 제품 경로로 폐기, journal proved, 미완료 activation 0 |
| 백업·검증 | `sb backup`, 이어서 `sb verify-backup`: 모두 exit 0. 최종 백업 `second-brain-20260927T233908+0900.tar.gz`, SHA-256 `006a55ddcaaa38f234e13908538c474149648eee36a68ce94b7d4399329b5fd7` |
| SB 준비 상태 | HTTP 200, status ready, reasons=[] |
| JARVIS 준비 상태 | HTTP 200, second_brain.readiness=ready |
| doctor | exit 0. 필수 항목 PASS; 패키지 설치의 scheduler-assets WARN은 기존 문서상 정상 |
| MCP 계약 | 기존과 실제 tool schemas 동일, JARVIS frozen checker matches=true, status는 sequence 1과 고정 digest 반환 |

근거: `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/sb-split/`.
`production-audit-final.json`, `ready-accepted.json`, `jarvis-health-accepted.json`,
`mcp-comparison.json`, `mcp-comparison-final.json`, 각 red/pytest/build/cutover 로그와 구조 명세 영수증을
남겼다. MCP의 기존 타입 경고 7개와 generation sweep의 기존 Any 경고 4개는 숨기지 않았으며,
새 동작의 타입 오류는 관측되지 않았다. GitHub 조회는 timeout으로 등록 대기이고, 커밋 hook의
engineering-map docs:sync도 rc=1이었다. 커밋·빌드·배포 및 위 실제 검증의 성공과는 구분한다.

## R3 (배포 06ea5e96)

판정: **통과.** 운영 웹 `http://127.0.0.1:8765`, 릴리스 `06ea5e96db0d04f8176ed5279a63343ff0df9b9d` (`source_commit` `3b045534d03f9e91c20e69e0a1db9ad207a664e2`) 위에서 시험 기억 1건의 GUI 수명이 끝났다. 삭제 후 위키·daily 검색과 CLI는 0이고, 없는 페이지는 `404: page not found`를 보였다. `sb backup`과 `sb verify-backup`는 둘 다 exit 0이고, 그 뒤 `/ready`와 JARVIS `second_brain.readiness`는 `ready`다.

정정·삭제는 관리 백업을 비우므로, 다음 검증 백업 전까지 `/ready`가 degraded다. 이는 이전 split과 다르다. 미완료 영수증이나 pending 요청은 없었고, 백업 디렉터리가 비어 `BACKUP_MISSING`이었다. 확인된 degraded 구간은 아래에 적는다.

### 대상

- 운영 웹 서비스는 시험 전에도 활성이었다. `ActiveEnterTimestamp` 2026-09-27 23:54:47 KST, MainPID 4121999, NRestarts=0. 이 세션은 서비스·설정·릴리스를 바꾸지 않았다.
- `[web] token`은 없다. 토큰을 넣지 않았다.
- 브라우저: owned engine (`connectPipe`, `/opt/google/chrome/chrome`, `--headless=new`, 작업 프로필 `/var/tmp/omowright-m13-r3-*`). 사용자 프로필을 쓰지 않았고 쿠키를 지우지 않았다. 두 세션 모두 `browser.close()`로 닫혔고 프로필은 지웠다.
- 센티널: `M13SENT6c2002e9`. 기억하기 본문은 `[M13-TEST 2026-09-27 R3] M13SENT6c2002e9 meeting is Tuesday.` 정정 본문은 `[M13-TEST 2026-09-27 R3] M13SENT6c2002e9 meeting is Friday.`
- 새 기억은 1건이다. 첫 세션은 기억하기·지금 처리·위키 검색까지 통과한 뒤, 390 화면의 CSS `innerWidth` 단언이 하네스 검사에 걸려 닫혔다. 제품 단계가 아니므로 같은 기억을 이어 열고 정정·삭제했다. 두 번째 기억하기는 없다.

### 단계

| 단계 | 판정 | 사실 |
|---|---|---|
| GUI 기억하기 | 통과 | 00:09:07 KST. `inbox/2026-09-27T150836712587-m13-r3-lifecycle.md`. |
| GUI 지금 처리 | 통과 | 00:09:55 KST. `run_id=75f1c47c964748c896eb8c3d2daf77e7`, `status=ok`, `pages=1`, `conflicts=0`, `errors=0`, `exit_code=0`, `already_running=false`. |
| GUI 검색 | 통과 | 위키 1건. `wiki/inbox-2026-09-27t150836712587-m13-r3-lifecycle-f29ed05b`. 컴파일 문장은 `화요일`로 바뀌었다. daily 검색은 0건. |
| 전체 열기·영수증 | 통과 | `page_content_digest=sha256:149aef41957c6bf093749f67bfb7519f3bbc5b1d30e3ef8ffa532ca891a9fab9`. 센티널 문장 1개. |
| 빈 정정 | 통과 | 00:15:45 KST GUI `CORRECTION_CONTENT_INVALID`. 새 owner 영수증 파일 0. 이어 Friday 문장을 넣고 정정 저장으로 복구했다. |
| GUI 정정 | 통과 | 00:16:42 KST. 서버 영수증 `2f38496c…f506.json`, `operation=correct`, `result.corrected`가 위 위키 페이지, `commit=5cd2fecc5a7bea245883d06e1bf88b6638c5a5d8`, `tombstone_sequence=2`, `replacement=null`. GUI JSON과 영수증 result가 같다. 클릭에서 완료까지 약 57초. 고정 시간 초과로 판정하지 않았다. |
| 정정 후 검색 | 통과 | 위키 스니펫은 Friday 문장만. `Tuesday`·`화요일` 없음. daily는 계속 0. |
| GUI 삭제 | 통과 | 00:17:46 KST. `forgotten`이 같은 위키 페이지. 영수증 `b31d947c…af3.json`, `operation=forget`, `commit=901bca62a788a5c49c17f689c61933b686488e7a`, `tombstone_sequence=3`, `replacement=null`. 완료까지 약 57초. |
| 검색 0 | 통과 | GUI 위키·daily `results=[]`. CLI `sb search M13SENT6c2002e9` exit 0, `no match`. `--kind wiki`·`--kind daily` JSON도 `[]`. |
| 삭제 페이지 | 통과 | GUI `404: page not found: wiki/inbox-2026-09-27t150836712587-m13-r3-lifecycle-f29ed05b`. |
| 운영 타이머 | 통과 | 아래 표. refresh·maintenance·backup 유닛은 이번 시작하지 않았다. |
| 백업·검증 | 통과 | `sb backup` exit 0 (00:18:58–00:20:20 KST). `sb verify-backup` exit 0 (00:20:26–00:21:02 KST). |
| 준비 상태 | 통과 | 백업 후 `/ready` HTTP 200 `ready`. JARVIS `second_brain.readiness=ready`. |

컴파일러가 남긴 원문은 `M13-TEST 2026-09-27 R3에서 M13SENT6c2002e9 미팅은 화요일이다.` 정정은 그 문장을 Friday 문장으로 교체했고, 검색에 옛 문장은 남지 않았다.

이번 `pages=1` 처리는 `daily/2026-09-27`에 센티널·`Tuesday`·`화요일`·inbox 파일명을 넣지 않았다. 파일 정확 일치 0. 그래서 삭제 후 daily 0은 브리핑 줄을 지운 증거가 아니라, 이 항목이 아예 없었다는 관측이다. 위키 원문과 검색·삭제·404는 위 표대로 통과했다.

### 준비 상태 구간

정정 영수증은 00:16:42 KST에 끝났다. 그 시각 백업 디렉터리 mtime은 00:16 KST이고, 00:18:46 KST 확인에서 파일은 0개였다. 삭제 영수증은 00:17:46 KST, tombstone sequence 3, root `sha256:567f53fc1a35573e370faaeb5b8f6d09b5a5d3900526f37527f26342cc545071`. 정정과 삭제 사이의 `/ready`는 따로 찍지 않았다.

00:18:46 KST `/ready`: HTTP 503, `status=degraded`, reasons `VERIFIED_BACKUP_UNAVAILABLE`, `LATEST_BACKUP_UNVERIFIED`, `backup_error=BACKUP_MISSING`, `latest_backup=null`, tombstone high-water 3. 저장: `m13-r3/ready-before-backup.json`.

같은 시각 JARVIS `http://127.0.0.1:4173/api/v1/health`는 HTTP 200, `second_brain.readiness=ready`였다. SB `/ready`와 같지 않았다.

`sb backup`이 만든 아카이브는 `second-brain-20260928T001859+0900.tar.gz`, SHA-256 `a4723c90d9c6f2714f2c790fe3e2f7adca58fc50167042981fc64232aee7ec6d`, 파일 42934, 바이트 149833006. 검증 영수증의 tombstone sequence는 3이고 삭제 영수증과 같은 root다.

00:21:11 KST `/ready`: HTTP 200, `status=ready`, `reasons=[]`, `latest_backup=last_verified_backup=second-brain-20260928T001859+0900.tar.gz`. JARVIS는 00:21:12 KST에도 HTTP 200, `second_brain.readiness=ready`. 확인된 degraded 구간은 00:18:46–00:21:11 KST, 2분 25초다. 백업 디렉터리가 비어 있던 구간은 정정 시각 00:16 KST부터 새 아카이브 00:18:59 KST까지다.

### 운영 타이머

`systemctl --user list-timers` (`XDG_RUNTIME_DIR=/run/user/1000`, 기록 시각 약 00:18 KST):

| 유닛 | NEXT | LAST |
|---|---|---|
| `jm-second-brain-maintenance.timer` | 2026-09-28 01:00:00 KST | 2026-09-28 00:00:02 KST |
| `jm-second-brain-refresh.timer` | 2026-09-28 01:00:26 KST | 2026-09-28 00:00:17 KST |
| `second-brain-backup.timer` | 2026-09-28 03:16:12 KST | 2026-09-27 03:17:59 KST |

전체 출력: `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13-r3/systemd-timers.txt`.

### 390 화면

이는 수명 단계가 아니다. CSS viewport 390, `deviceScaleFactor=1` 캡처의 PNG는 390x844이다. 레이아웃 뷰포트는 435 CSS px이고 `clientWidth`는 390이라 가로로 45px 넘친다.

| 캡처 | PNG | innerWidth | scrollWidth | clientWidth |
|---|---|---|---|---|
| `04b-search-wiki-390.png` | 390x844 | 435 | 미기록 | 미기록 |
| `16-search-390.png` | 390x844 | 435 | 435 | 390 |

1440 단계 캡처는 CSS viewport 1440x900, PNG 1440x900, `devicePixelRatio=1`이다.

### 스크린샷

| 단계 | 경로 |
|---|---|
| 콘솔 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13-r3/01-console-1440.png` |
| 기억하기 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13-r3/02-remember-1440.png` |
| 지금 처리 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13-r3/03-run-1440.png` |
| 위키 검색 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13-r3/04-search-wiki-1440.png` |
| daily 검색 0 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13-r3/05-search-daily-1440.png` |
| 원문·영수증 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13-r3/06-original-receipt-1440.png` |
| 빈 정정 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13-r3/07-empty-correction-1440.png` |
| 정정 영수증 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13-r3/08-correction-receipt-1440.png` |
| 정정 후 위키 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13-r3/09-corrected-wiki-1440.png` |
| 정정 후 daily | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13-r3/10-corrected-daily-1440.png` |
| 삭제 영수증 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13-r3/11-deletion-receipt-1440.png` |
| 삭제 후 위키 0 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13-r3/12-wiki-zero-1440.png` |
| 삭제 후 daily 0 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13-r3/13-daily-zero-1440.png` |
| 404 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13-r3/14-deleted-page-404-1440.png` |
| 390 검색 | `/home/jm/orca/projects/Orca-JARVIS/.omo/evidence/ulw/mass-20260927/m13-r3/16-search-390.png` |

행동 기록: 같은 디렉터리의 `action-log.jsonl`. 백업 전후 준비 상태: `ready-before-backup.json`, `ready-after.json`, `jarvis-after.json`, `sb-backup.txt`, `verify-backup.txt`.
