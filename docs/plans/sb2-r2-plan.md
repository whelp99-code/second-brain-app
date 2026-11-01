# SB 2단계: 무엇을 먼저 만들고, 끝나면 무엇을 할 수 있나

**추천: 수집 신뢰성 → 회사/개인 분리 → 업무·약속 → AI 문맥 → JARVIS → 알림 → 통화 전사. 위치·건강·예측은 보류.**
2026-10-09 / 계획만, 구현 시작 전 재민 확인 필요. S=한 범위 보강, M=여러 경로 연결, L=데이터·다른 제품·기기까지 연결하는 상대 규모이며 일정·비용 확정값이 아니다.

## 현재 출발점과 착수 조건

- **이미 있다:** 일일 브리핑 추천, 수집 커넥터, 회사기억 수신·단건 읽기·메일 후보 목록/count. 새로 필요한 것은 업무/기한별 상태에 따른 추천 정책과 분리된 회상·실제 클라이언트 연결이다.
- **부분 코드와 사용 완료는 다르다:** 원천 DB 후수정/삭제 재대조, 위치·건강·예측 코드는 있다. 설치된 수집원·실기기·운영 인수는 별도 확인하며 “미구현”으로 뭉뚱그리지 않는다.
- **착수 게이트:** 기존 계약·영속 접수/정정/삭제·인용·회상·모델 정책(P01/P02/P05/P09/P10)의 관련 인수 근거와 실제 source manifest를 확인한다. 미통과 경로는 해당 단계만 차단하고 독립 단계는 진행한다. 소스 DB는 각 소유자에게 남기고 SB는 읽기·관찰·인용만 한다.

## 단계별 한 장 계획

| 순서·이슈 | 목표 / 끝나면 재민이 할 수 있는 것 | 선행·진입 조건 | 규모 | 주된 위험 / 완료 증명 |
| --- | --- | --- | --- | --- |
| 1. 수집원 보강 [#35](https://github.com/whelp99-code/second-brain-app/issues/35) | 기존 AI 세션·Unified DB·Markdown·Mac 선택 폴더·문서를 보강한다. **“허용한 원본이 어디까지 들어왔는지 보고, 끊겼다 다시 켜도 누락·중복 없이 이어서 찾는다.”** | 착수 게이트 + P03; 기존 adapter·재대조 코드 재사용, 실제 존재하는 root만 | L | cap/오프라인을 삭제로 오인하거나 원본 훼손. 정상·단절·후수정/후삭제·손상 문서의 원본→receipt→검색을 증명; 삭제는 관찰 후보이며 원본 자동 삭제 아님 |
| 2. 회사/개인 기억 분리 [#37](https://github.com/whelp99-code/second-brain-app/issues/37) | 기존 후보 읽기를 넘어 namespace별 회상을 연결한다. **“같은 질문도 회사와 개인을 따로 찾고, 후보인지 확정 근거인지와 출처를 구분한다.”** | 1의 scope/출처, P09/P10; 기존 회사 권한 재사용 | M | 회사 정보의 개인 inbox·검색·모델 누출. namespace 선택 없는 조회·다른 workspace·오래된 삭제 fence는 내용 0; 같은 질문의 결과/receipt가 독립 |
| 3. 업무·약속·기한 [#34](https://github.com/whelp99-code/second-brain-app/issues/34) | 출처 기반 업무/반복 회차·기한과 선택 정책을 만든다. **“원문 근거와 기한별 업무 목록을 보고, 미정·열림·충돌과 오늘 추천된 이유를 구분한다.”** | 1·2, P07/P10; 기존 브리핑 추천을 대체하지 않고 보강 | L | 상대 날짜·회차 혼동, 후보/전달을 완료로 오인. 수집 0건이어도 기한 평가, 중복/과거 사건이 상태를 뒤집지 않음, 완료·삭제 항목 추천 0. 버튼 종단 인수는 5·6 이후 |
| 4. AI 클라이언트 자동 문맥 [#37](https://github.com/whelp99-code/second-brain-app/issues/37) | Claude·Codex·OMO·OpenCode·GJC의 지원 경로를 연결·측정한다. **“지원되는 AI에서 허용한 관련 기억을 한 번만 받고, 연결 불가·빈 결과는 구분한다.”** | 2, P05/P09/P10; 설치된 client별 지원 matrix | M | 미지원 경로를 자동 연동으로 광고, 중복·무관/삭제 문맥 주입. client별 실제 새 세션 1회, 빈/무관 문맥 0·중복 0·잘린 출력 delivered 아님; 미지원은 완료 제외가 아니라 명시 unavailable |
| 5. JARVIS 연동 [#39](https://github.com/whelp99-code/second-brain-app/issues/39) | 인증된 개인 기억 API·전달 원장·실행 결과 완료 사건을 연결한다. **“JARVIS에서 근거 있는 업무 상태를 보고, 검증된 실행 결과만 완료로 남기며 응답 유실에도 일을 다시 실행하지 않는다.”** | 3, P02/P07; JARVIS 저장소 담당·인증/relay 계약 연결 | L | exit 0/알림 수신/파생 DB를 완료로 착각, 기억 재시도로 업무 재실행. criterion+evidence→applied receipt, 응답 유실 시 business action 1회; 완료 사건은 정본에 남아 복원 후에도 유지 |
| 6. 알림·상태 조작 [#38](https://github.com/whelp99-code/second-brain-app/issues/38), [#34](https://github.com/whelp99-code/second-brain-app/issues/34) | iPhone 홈 화면 웹앱·Mac 채널과 revision 기반 완료/보류/취소를 연결한다. **“허용한 기기에서 필요한 알림을 받고, 눌러 최신 근거를 열거나 업무 상태를 바꾼다.”** | 3·5, P07/P10; 기기/구독 권한 확인; 발송은 실행 단계 별도 승인 | L | 잠금 화면 누출·알림 폭주·허위 수신 성공. stable ID·quiet 22–08·하루 최대 3묶음, provider 접수≠기기 수신≠열람≠업무 완료, 철회·만료·오프라인 및 두 기기 revision 충돌 증명 |
| 7. 통화·녹음 전사 [#36](https://github.com/whelp99-code/second-brain-app/issues/36) | 허용한 음성을 로컬 CPU로 전사하고 시간 구간·원음에 연결한다. **“내가 공유한 녹음에서 발언을 찾아 원음으로 돌아가며, 못 들은 구간은 미확인으로 본다.”** | 1, P03/P10; Phone History 경계·실제 audio·로컬 모델 manifest/라이선스 | M | 원음 외부 전송·오전사 확정·TTL 자동 삭제. 한국어 허용 fixture 실제 전사, 재시작 재사용, worker 외부 전송 0; 모델 없으면 unavailable/cloud fallback 0; 원음은 명시 삭제 전 보존 |
| 보류 A. 위치 [#31](https://github.com/whelp99-code/second-brain-app/issues/31) | **“허용한 위치만 수집하고 방문/이동의 근거와 빈 구간을 구분한다.”** | R2 인수 후 목적·정밀도·보존·철회 선택과 실제 iPhone 배경/오프라인·배터리 측정이 준비되면 재개 | L | 정밀 위치 누출·미관측 방문 확정. 기존 파싱/구간 코드는 재사용하되 실기기·삭제/철회 인수 전 활성화하지 않음 |
| 보류 B. 건강 [#32](https://github.com/whelp99-code/second-brain-app/issues/32) | **“허용한 건강 종류만 보고, 기록 없음·읽기 불가·결측을 구분한다.”** | R2 인수 후 HealthKit 서명/entitlement·종류별 opt-in·실제 기기/표본·철회/재부여 증명 시 재개 | L | 빈 읽기를 0/권한 거부로 단정·건강정보 누출. 기존 bridge/검증/집계 재사용; 진단·치료 권고 금지 |
| 보류 C. 예측 [#33](https://github.com/whelp99-code/second-brain-app/issues/33) | **“결과 전에 고정한 소요시간 예측과 실제 결과·오차를 근거와 함께 비교한다.”** | R2 인수·적격 실제 표본·시간 홀드아웃/기준선 평가 준비 시 재개. 반복 업무 대상이면 위치/건강 불필요; 이동시간 대상만 위치 인수 필요 | M | 사후 정보 유입·부족 표본의 허위 정확도. 기존 cutoff/평가 코드 재사용; 취소/결과 없음 unscored, 기준선 이점 없으면 개인화 OFF |

## 순서·완료 판정

1→2로 원본·scope를 먼저 고정하고 3에서 업무 가치를 만든다. 4는 분리된 회상을 AI에서 먼저 증명한다. 5→6으로 인증·완료/전달 원장 뒤 실제 알림을 붙여 허위 완료와 중복 실행을 막는다. 7은 구현상 1 이후 독립 진행할 수 있지만 **권장 우선순위는 위 순서 하나**다. #35는 R1 보강 선행, #31–33은 R3 보류이며 R2 인수로 묶어 완료 처리하지 않는다.

단계 완료는 표의 재민 문장을 실제 화면/API에서 한 번 재현하고 관련 테스트·타입·lint와 Cursor ACCEPT를 붙였을 때만 판정한다. #37은 2·4, #34는 3·6이 모두 인수된 뒤 닫는다. 운영 반영 시에만 health·실데이터/권한을 확인한다. 이번 PR은 **계획 완료일 뿐 제품 인수·구현 착수 아님**.

근거 기준: [SB2 통합 #3](https://github.com/whelp99-code/second-brain-app/issues/3), 위 아홉 이슈와 [P12–P20 원본 명세](../second-brain-2/work-packages/), source `9a0d1656`의 `briefing.py`, `company_memory_reader.py`, `unified_db_reconcile.py`, `web_push.py`, `life_sensors.py`, `life_health.py`, `life_predictions.py`, `life_documents.py`. 명세의 오래된 NOT_RUN/신규 표시는 최신 코드·인수 근거로 보완한다.

운영 잔여: [PR60 배포 근거](https://github.com/whelp99-code/second-brain-app/issues/30#issuecomment-6074941859)의 jarvis-svc 키 소유권·실UID 검증은 마지막 확인에서 미완료였다. 이는 후보 읽기 수신 준비와 실제 JARVIS 이용의 차이이며, #39 전체 미구현/완료로 대체 해석하지 않는다. 착수 시 최신 소유권·socket 실사용 근거를 다시 확인한다.

범위 밖·운영 영향 없음: 이번 변경은 문서만이며 새 release·DB role·비밀 파일·unit·타이머·포트 없음. 운영 경로는 실제 source manifest/설정으로 해석하고 호스트/IP·포트를 새로 고정하지 않는다. 원본 자동 삭제·원천 DB 쓰기/통합·자동 발송·결제·새 상주 queue/event bus는 범위 밖이다.
