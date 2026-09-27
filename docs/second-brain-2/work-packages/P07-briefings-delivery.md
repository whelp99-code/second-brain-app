# P07 — 아침·저녁 브리핑과 전달

명세 등록 / 구현·발송·스케줄 등록·시험 NOT_RUN. Refs #3. 선행 P05 #9, **모델 연결 전 P10 완료**. R1 기본/R2 전달 고도화. REQ-04·REQ-08 / Core+Client / 5–7인일 추정. 기준: 개발계획 8·12·13장.

## 목표
기존 briefing 입력 보호·인용·PageSpec 생성기를 재사용해 아침 준비와 저녁 회고를 구분한다. 생성됐다는 사실과 실제 전달·열람을 동일하게 표시하지 않는다.

## 출력 계약
Morning은 오늘 일정/만날 사람의 과거 맥락/현재 결정/미완료/수집 상태에서 최대 5개 핵심 근거 카드를 만든다. Evening은 오늘의 실제·미확인 사건/새 결정/변경·취소/내일 필요한 기억을 정리한다. Maintenance 기술 로그는 생활 브리핑과 별도 표시한다. 기록 없는 건강·감정·참석을 만들어내지 않는다.

## 구현 체크리스트
- [ ] frozen input snapshot에 day/slot/timezone/input_version/evidence를 고정하고 순수 생성기와 I/O를 분리한다.
- [ ] 기존 `daily/{day}`와 충돌하지 않는 slot별 결과 계약과 통합 Daily projection을 정의한다.
- [ ] 허용 citation ID/digest/scope 검증, 길이·호출·재검증 예산, 무근거/모델 실패 시 축소/실패 상태를 구현한다.
- [ ] 단일 writer와 day+slot+input_version으로 생성 중복을 차단하고 동일 입력은 불필요하게 재생성하지 않는다.
- [ ] 외부 스케줄러가 기존 run surface를 호출하게 한다. 코어 상주 queue/worker를 추가하지 않는다.
- [ ] 재시작 후 놓친 slot은 정책상 유효한 범위에서 한 번 보정하고 과거 알림을 몰아서 발송하지 않는다.
- [ ] generated/published/delivery_attempted/transport_accepted/opened를 원장에 분리한다. opened는 실제 신호가 있을 때만 설정한다.
- [ ] 기존 승인된 채널의 중복키/메시지 ID/수락 조회를 연결한다. 공급자 멱등성이 없고 응답 유실이면 delivery_unknown을 표시하고 무조건 재발송해 중복을 만들지 않는다.
- [ ] 잠금 화면 기본 알림은 '브리핑 준비됨' 등 최소 정보만 표시한다. 민감 본문은 인증 후 조회한다.
- [ ] 정정/삭제 발생 시 최신 브리핑의 근거와 본문을 재검증하고 이전 알림/외부 사본의 삭제 한계를 표시한다.

## 설정
08:00/21:30 KST는 초기 제안값이며 사용자 기상/취침 사실이나 이미 생성된 자동화가 아니다. timezone/quiet hours/휴일/catch-up TTL을 설정으로 둔다. schedule의 실제 등록은 운영 승인과 P11 gate 이후다.

## 코드·계약
기존 `sb/briefing.py`, `sb/pipeline.py`, config와 전달 helper를 재사용한다. 새 `life_briefing` 순수 함수와 slot 모델은 후보. GET briefings는 input snapshot/근거/전달 상태를 반환하고 `web_push.py` payload만으로 실제 배달 성공을 인증하지 않는다.

## 인수시험
AC-10: 모델 timeout/없는 인용/잘못된 인용의 실패·축소를 정직하게 표시. AC-11: 같은 slot 동시 실행/재시도/응답 유실/재부팅에서 중복 억제와 상태 구분. AC-03/09: 취소·정정 후 오래된 사실을 현재 추천에 사용하지 않음. AC-15: scope 밖 내용을 생성기/알림/캐시에 전달하지 않음. 사용자 timezone·quiet hours·서버 날짜 차이를 시험한다.

## 적용·롤백·증거
`life_briefing`과 채널 전달을 단계적으로 활성화한다. 장애 시 발송을 멈추고 근거/게시본은 보존하되 stale를 표시한다. 운영·읽음 상태를 과장하지 않는다. 실제 revision, 입력 snapshot, 사용 모델/비용, 인용 검증 로그, channel ID/응답, 정상·실패·중복 시나리오와 독립 검토가 필요하다. 현재 명세 파일만 추가, 모든 제품 시험 NOT_RUN.
