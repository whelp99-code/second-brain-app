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
