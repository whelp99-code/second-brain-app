# P15 — 업무·약속 projection·기한·추천 정책

명세 등록 / 구현·시험 NOT_RUN. Refs #3, #34. 선행 P01 #20, P02 #21, P07 #26, P10 #29. R2 (제안) / Core·Client·QA / 7~11인일 추정(범위, 확정 일정 아님). 기준: 2026-09-23 계획 31~36·44, K3/K4/D05.

## 목표
원본의 약속·할 일·결정을 근거와 함께 업무 projection으로 유지하고, 기한은 원래 정밀도로 저장하며, 상태는 revision 순서로만 바꾼다. 추천은 결정적 선택이 먼저고 모델은 표현만 한다. SB2 명세에는 할 일·약속·기한 모델과 추천 선택 정책이 없다. P07은 사실 카드 브리핑, P08은 빈칸 질문만 다룬다. 현재 `sb/obligations.py`, `sb/obligation_time.py`, `sb/reminder_evaluation.py`는 없고 사건 타입, `life_workflow` 상태, 기대 revision 정정만 있다.

## 구현 체크리스트
- [ ] (31) K3 ObligationV1/EventV1을 additive migration으로 만든다. 근거가 모호하면 proposed. obligation·occurrence마다 origin/span/revision.
- [ ] (31) 명확히 같은 source event만 deterministic upsert한다. 회사 obligation은 namespace를 지키고 deny/private는 규칙 추출·로컬 표현만 쓴다.
- [ ] (32) Asia/Seoul owner clock과 due_kind 적용. 문맥상 due 분리, 상대 날짜는 원본 발생 시각 기준, original_timezone/precision 보존.
- [ ] (32) 반복 일정은 occurrence로 나누고 한 회차 완료를 전파하지 않는다.
- [ ] (33) event reducer·receipt. 사용자 confirm/complete/cancel/snooze/reopen과 JARVIS 결과 근거 구분, expected_revision CAS, action_sequence high-water, 중복 event, pending change suppression, 충돌은 `OBLIGATION_REVISION_CONFLICT`.
- [ ] (34) `sb evaluate-reminders --once`와 선택 user timer. frozen context 하나로 수집·선택·render, fingerprint가 같으면 no-op, 수집 0이어도 due clock이 지나면 평가.
- [ ] (35) K4 eligibility를 먼저 계산하고 모델은 선택 근거만 인용해 0~5개를 쓴다. open/conflicted/proposed/blocked 구분, freshness/coverage 부족 설명.
- [ ] (36) 정책 schema에 D05(09:00 digest, 22~08 quiet, 하루 3묶음)·cap·slot·snooze, active revision을 증거에 기록. 추천 100 case와 suppress oracle 독립 작성.
- [ ] (44) Mac/PWA 버튼이 expected revision·인증 actor·eventID로 K3 event를 보내고, applied receipt 뒤에만 성공 표시.

제외: confidence·compiled approval·완료 문자열·`proved`·`processed_complete`·`delivered`만으로 완료/확정 금지. 날짜만 있는 기한의 임의 UTC midnight, DST·모호한 상대 날짜의 확정 금지(review로 남김). 늦은 과거 event로 완료 뒤집기 금지, dismiss는 취소가 아니다. tick마다 LLM 호출, 모델 대기 중 별도 Vault writer, 추천 3개 채우기, 이전 brief를 근거로 쓰기, 자동 fine-tuning·정책 변경 금지. P20 relay·원장과 P19 채널은 범위 밖.

## 코드·API
재사용: `sb/store/ledger.py`, `sb/store/life.py`, `sb/life_contracts.py`, `sb/life_workflow.py`, `sb/memory_records.py`, `sb/company_memory.py`, `sb/request_store.py`(`journal.db`에 정본 `obligation_events`·`completion_high_water`), `sb/scoped_request_status.py`, `sb/generation_runtime.py`, `sb/pipeline.py`, `sb/vault.py`, `sb/life_delivery.py`, `sb/briefing.py`, `sb/life_model_policy.py`, `sb/security.py`, `sb/cli.py`, `systemd/user/`, `clients/macos/SecondBrainMac/Sources/SecondBrainMac/AppModel.swift`. 시험: `tests/test_briefing.py`, `tests/test_cli.py`, `tests/test_life_store.py`, `tests/test_life_workflow_http.py`, `scripts/korean_search_evaluation.py`.

신규 후보: `sb/obligations.py`, `sb/obligation_values.py`, `sb/obligation_time.py`, `sb/reminder_evaluation.py`, `sb/recommendation_selection.py`, `tests/test_recommendation_evaluation.py`, additive migration. 추천 ID는 owner/namespace/obligation/occurrence/reason/slot digest라 문장이 바뀌어도 유지된다.

## 인수시험
AC-01: 10회 재전송에 obligation 1개, replay는 같은 receipt. AC-02: 같은 문장·다른 날짜는 별도 occurrence. AC-03: 예정 기한과 실제 완료 분리. AC-04: 자정·hostTZ·윤년·DST·상대 날짜·반복 fixture 100%. AC-09: 완료·정정 후 추천·브리핑·Obsidian 일치. AC-10: timeout·잘못된 인용은 축소·기권. AC-11: 같은 slot 추천 1개. AC-12: OFF·장애와 빈 입력 구분. AC-13: quiet와 하루 3묶음 frozen clock 100%. AC-15: 범위 밖·회사 누출 0, deny/private 외부 LLM 0. AC-16: 재시작·clock reversal에 중복 slot 0. AC-18: 삭제 업무 추천·부활 0. AC-23: injection 승격 0. AC-24: 기존 회귀 통과.

고유: 가정·부정·타인 발언·인용의 약속 승격 0. complete, 중복, newer reopen, reschedule 재현. failed attempt·unknown result에서 허위 완료 0. gold precision≥95%, 금지 상태 추천 0, 선택마다 reason/evidence/state revision. cap 초과·잘못된 policy는 fail. 두 기기 같은 revision 충돌은 표시하고 덮어쓰지 않는다.

## 적용·중단·완료
신규 flag 기본 OFF. projection 읽기, `--once` 수동 평가, 선택 timer 순으로 켠다. rollback은 flag OFF로 추출·평가·추천만 멈추고 journal 사건·high-water·삭제 의도는 보존한다. ledger projection은 파생이라 현재 journal과 대조해 재구축한다. 불변: `sb.vault` 단일 writer, 새 상주 queue/event bus 금지, 원본 DB는 소유자 소유·읽기 전용, 자격증명은 명세에 쓰지 않는다. 증거: 계획 31~36·44 happy/failure JSON, frozen clock fixture, gold·oracle, policy·코드·모델 revision, requested/run/pass/fail/skip/not-run. 44 종단은 P19/P20과 실기기가 없으면 BLOCKED. 현 diff는 이 문서 1개이며 구현·시험 모두 NOT_RUN.
