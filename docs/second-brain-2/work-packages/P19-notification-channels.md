# P19 — 알림 채널: Web Push·iPhone 홈 화면 웹앱·Mac 알림

명세 등록 / 구현·시험 NOT_RUN. Refs #3, #38. 선행 P07 #26, P10 #29; JARVIS 저장소(계획 37·40, P20 #39 선행). R2 (제안) / Client·Core·QA / 6~10인일 추정(신규 추정, 확정 일정 아님). 기준: 2026-09-23 계획 38, 39, 41, 42와 대조 문서 3절.

## 목표
P07의 전달 상태·중복 억제를 실제 채널에 잇는다. 구독은 인증된 owner와 기기에 묶고, 불확실한 전송 결과는 그대로 남긴다. iPhone 웹앱과 Mac 알림은 같은 stable delivery ID를 쓴다. 잠금 화면엔 최소 정보만, 본문은 인증 후 재검증해서 연다. P07은 구독 관리, 실제 채널, 웹앱 화면, Mac delivery ID를 다루지 않는다. 현재 `sb/web_push.py`는 payload 생성만, `sb/life_delivery.py`는 HTTPS 전송과 unknown 처리만 한다.

## 구현 체크리스트
### 계획 38. 구독·회전·폐기
- [ ] JARVIS `push-subscriptions` route·store와 `web-push@3.6.7`. 기존 session/CSRF/owner namespace 검사를 거친다.
- [ ] endpoint는 HTTPS·허용 provider만. host/IP·DNS rebinding 방어, p256dh/auth 길이 검증, device binding.
- [ ] 등록/갱신/로그아웃/해지/404·410 반영. VAPID key 보관·rotation. key와 endpoint 토큰은 log/UI/cache에 남기지 않는다.
- [ ] 제외: 임의 URL POST proxy로 만들지 않는다.

### 계획 39. 서버 전송과 불확실한 결과
- [ ] K6 TTL/timeout/topic/Retry-After 적용, sender는 JARVIS supervised command. 새 상주 queue·event bus 없음.
- [ ] 전송 직전 권한·완료·삭제 재검사, generic payload. 응답 유실과 5xx/429/401/410을 구분하고 모호하면 `delivery_unknown`, blind replay 없음.
- [ ] 제외: 만료된 recommendation 재전송, provider 2xx를 기기 수신으로 기록. transport evidence와 수신 event는 따로 둔다.

### 계획 41. iPhone 홈 화면 웹앱
- [ ] JARVIS dashboard `/memory` route, manifest/icons, service worker, 구독 UI, notificationclick deep link.
- [ ] SW 캐시는 shell asset만. 민감 본문·토큰은 persist하지 않는다. deep link를 열 때 state를 재검증하고 invalidated 내용은 열지 않는다.
- [ ] 중복 delivery는 UI upsert, offline/expired/denied 명시.
- [ ] 제외: 한 번 탭한 열람을 완료로 처리.

### 계획 42. Mac 알림
- [ ] `AppModel`의 `last-notified-briefing-sha` dedupe를 K6 delivery ID·device event로 보완하고 기존 브리핑 열람은 유지한다.
- [ ] provider 접수·OS enqueue·opened를 따로 기록. 알림센터는 generic, 상세는 authenticated fetch. settings에 D05·수신 권한·last sync.
- [ ] 제외: permission denied를 성공으로 표시. 알림이 막혀도 검색·수집 UI는 동작한다.

### 공통
- [ ] `sb.vault` 단일 writer 유지, 채널은 전달 사실만 SB에 돌려준다. 원천 DB는 owner 소유·읽기 전용. 자격 증명은 명세·이슈·evidence에 적지 않는다.
- [ ] JARVIS(`whelp99-code/Orca-JARVIS`) 변경은 별도 이슈로 연결한다.

## 코드·API
재사용: `sb/web_push.py`, `sb/life_delivery.py`(`prepare`/`finish`/`send_notification`), `sb/life_config.py`, `tests/test_life_transport_runtime.py`, `clients/macos/SecondBrainMac/Sources/SecondBrainMac/AppModel.swift`, `clients/macos/SecondBrainMac/Sources/SecondBrainMac/SystemServices.swift`(`BriefingNotificationService`), `clients/macos/SecondBrainMac/Sources/SecondBrainMac/AppSettings.swift`, `clients/macos/SecondBrainMac/Sources/SecondBrainCore/APIClient.swift`.

신규 후보: JARVIS 구독 route·store와 sender command, `/memory` PWA·service worker, Mac delivery ID·device event 기록, `notification_channels` flag, `tests/test_web_push_channels.py`. JARVIS 참조 파일은 이 저장소 밖이라 확인하지 않았다. 브라우저에는 SB token/key/8765 주소를 두지 않는다.

## 인수시험
AC-11: 재시도·두 기기·문장 수정·재시작에도 delivery ID 하나, accepted/opened 분리, 폭주 0. AC-15: 잠금 화면·SW 캐시·log에 범위 밖 본문·토큰 0. AC-09/18: 정정·삭제 뒤 deep link 차단, 재접속은 tombstone 우선. AC-12: 권한 거부·만료·장애를 OFF와 구분. AC-16: sender kill 뒤 전달 사실 보존. AC-21: rollback 뒤 해지 의도·원장 보존. AC-22: 알림 권한 거부·재허용. AC-23: internal IP/rebind, 변조 key, CSRF, 타인 기기 차단. AC-24: 기존 브리핑·Mac 알림 회귀 없음. AC-06 실기기 종단은 계획 43(P11/P04).

고유(A 38~42): 실제 browser 구독 바인딩. 암호화 payload와 transport receipt, sender kill·429·410·state race에서 잘못된 수신 0. browser driver로 설치·구독·click·근거 열람, iPhone narrow·desktop screenshot, stale SW에서 원문 cache 0. Mac AX driver로 수신·열람, 터널 끊김·enqueue 실패에서 retry identity 유지. 증거 `$E/T38`~`$E/T42`.

## 적용·중단·완료
`notification_channels`와 JARVIS 채널 flag는 기본 OFF, Mac `notificationBriefings`도 false 유지. 한 기기·한 채널에서 시작한다. 중단은 flag OFF로 새 전송만 멈추고 해지 의도·원장·unknown 상태를 보존한다. 과거 알림은 몰아서 보내지 않는다. 완료 증거: SB·JARVIS·Mac revision, key를 뺀 전송·수신 로그, QA evidence, 실기기 증거(조건 없으면 BLOCKED, simulator만으로 PASS 금지), 독립 검토. 현 diff는 이 문서 1개이며 구현·시험 모두 NOT_RUN.
