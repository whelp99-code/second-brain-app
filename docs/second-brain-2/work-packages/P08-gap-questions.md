# P08 — Memory Gap Detector와 질문 루프

명세 등록 / 구현·질문 발송·시험 NOT_RUN. Refs #3. 선행 P05 #9, P07 #11; 모델 사용 시 P10. R2 / REQ-03 / Core+Client / 5–7인일 추정. 기준: 개발계획 9·12·16장. 원문 식별/hash는 #3.

## 목표
기록의 빈 시간을 창작으로 채우지 않고, 미래 기억에 중요한 불확실성만 사용자에게 확인한다. 수집 장애와 사용자가 기록하지 않기로 한 영역을 생활 질문으로 바꾸지 않는다.

## 누락 분류 계약
- source_disabled: 사용자가 수집 OFF → 질문하지 않음.
- source_failed/late: 연결 장애·지연 batch → 운영 상태 안내, '뭘 했나' 질문 금지.
- occurrence_unknown: 일정만 있고 실제 진행 미확인 → 중요할 때 확인.
- result_missing: 사용자가 미팅을 확인했으나 결과 없음 → 한 문장 결과 질문.
- evidence_conflict: 근거가 서로 다름 → 양쪽 근거를 표시하고 확인.

## 구현 체크리스트
- [ ] source health+covered window+event revision의 frozen snapshot에서 규칙 기반 gap 후보를 생성한다.
- [ ] 기억 중요도→다음 일정 관련성→불확실성→중복/방해 여부의 순서로 후보를 고른다. 미검증 정밀 점수를 사실 확률처럼 표시하지 않는다.
- [ ] daily budget, quiet hours, 동일 사건 cooldown, 사용자 mute/skip을 저장·검사한다.
- [ ] 초기 3개/일, 동일 사건 72시간 억제는 변경 가능한 제안값이다. KST 날짜 경계·여행 시간대·동시 실행에서도 상한을 초과하지 않게 예약/기록을 원자적으로 처리한다.
- [ ] 질문 상태 proposed/presented/answered/skipped/muted/stale를 구분한다. 질문이 참조하는 사건 revision과 근거 snapshot을 고정한다.
- [ ] 사용자 답변은 새 user_asserted 근거로 저장하고 expected_revision을 확인한다. 오래된 질문에는 최신 사건을 대조하고 잘못된 대상을 수정하지 않는다.
- [ ] '건너뛰기'와 '다시 묻지 않기'를 제공하고 재발송·재생성에서 선택을 존중한다.
- [ ] 답변/정정 결과를 검색·타임라인·브리핑·관계·Obsidian으로 전파한다. model confidence만으로 사용자 발언을 덮지 않는다.
- [ ] 질문 전달은 P07 채널/중복 상태를 재사용하고 core에 별도 상주 질문 worker를 만들지 않는다.

## 코드·API
`sb/life_gaps.py` 순수 함수, 기존 ledger의 life_questions, 기존 web의 questions/response adapter가 후보. P06의 Questions projection과 연결한다. 질문 답변은 본문·event ID 모두 비신뢰 입력으로 검사한다. API는 scope·expected revision·idempotency·처리 상태를 포함한다.

## 인수시험
AC-12: OFF/실패/정상 빈 입력 구분; 수집 장애를 사용자 망각으로 취급하지 않음. AC-13: gap10개에도 상한3, quiet hours0, 72시간 cooldown, skip/mute/재부팅/동시 실행 보존. AC-09: 답변 정정 후 5개 surface 일치. 오래된 질문/모호한 답/근거 삭제/timeout을 정상 완료로 처리하지 않는다. 질문 관련성은 실제 사용자 표본 수와 skip 비율을 함께 기록하며 작은 표본을 일반화하지 않는다.

## 적용·중단·완료
R1에는 필요 시 수동 확인 후보만 표시하고 능동 질문은 R2 인수 후 `gap_questions` flag로 켠다. OFF는 새 질문을 중지하되 기존 답변·mute·정정 의도는 보존한다. 의료/감정/관계 점수 추론, 전역 감시, 무제한 질문은 제외한다. 현재 명세 파일만 변경; 모든 제품 시험 NOT_RUN. 실제 로그·버전·정책 설정·사용자 표본·회귀/독립 검토를 요구한다.
