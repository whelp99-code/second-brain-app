# 동일 정정 요청 접수와 취소 접수의 프로세스 경합

2026-09-09. 테스트 커밋 `686f6e8`. SB 제품 `9e30115`, JARVIS 제품 `ea076ae` 유지.

## 새로 검증한 경계

기존 test_cancellation_admission_race.py는 일반 generation writer와 취소의 경합을 검증했다. 이번 test_cancellation_request_publication_race.py는 같은 서명된 정정 요청의 accept_effect_request와 해당 요청의 accept_correction_cancellation을 별도 spawn 프로세스에서 실행한다.

각 프로세스는 독립 RequestExecutor/SQLite 연결을 갖는다. 원 요청은 실제 _publish 직전, 취소는 실제 target 검증 직전의 공통 pending-directory 잠금을 보유한 위치에서 Event로 멈춘다. 다른 프로세스가 접수에 진입한 뒤 첫 프로세스를 풀어 두 잠금 획득 순서를 결정적으로 검증한다. 실제 잠금·파일 저장·서명/대상 검증·원장 변경은 제품 코드를 사용하며 sleep은 없다.

| 시나리오 | 접수 결과 | 재시작 후 실행·검증 |
|---|---|---|
| 원 요청 선행 | 정정 접수 성공, 취소 MEMORY_CANCELLATION_ALREADY_RECEIVED | 동일 요청 replayed, 실제 executor proved, 다음 실행 idle. 커밋에서 이전 내용 부재·정정 내용 존재 |
| 취소 선행 | 취소 접수 성공, 정정 MEMORY_REQUEST_CANCELLED | 동일 의향 replayed, 취소 generation_active, 원 요청 행 없음·다음 executor idle. 커밋에서 이전 내용과 정정 내용 모두 부재 |
| 요청 파일 저장 후 원장 commit 전 종료 | 별도 프로세스 exit77. pending 파일 존재/원 요청 행 없음/high-water0 | 취소를 이미 접수됨으로 거부. 같은 요청 접수로 원장을 복구해 high-water1, executor proved, 다음 실행 idle |

첫 두 경합의 부모는 양쪽 프로세스를 종료까지 확인하고 새 executor 연결에서 관측한다. high-water는 양쪽 모두1, cancellation 행은 취소가 먼저인 경우만1이다. 테스트 예외와 timeout은 성공으로 바꾸지 않는다.

## 검증 결과

- 최초 관련 묶음: 새 경합3개+기존 일반 writer 경합2개+취소 executor9개, **14 passed / 14.86초**.
- 이후 커밋 본문 확인을 추가한 최종 새 경합 검사: **3 passed / 6.75초**. 위14개와 중복이므로 합산하지 않는다.
- 전체 sb/tests Ruff, git diff check 통과. 최초 Ruff import 정렬 오류는 수정 후 재검사했다.
- 재현: `TMPDIR=/var/tmp .venv/bin/pytest -q tests/test_cancellation_request_publication_race.py`.

## 판단과 남는 범위

이 경계에서 제품 결함은 재현되지 않아 잠금이나 접수 계약을 수정하지 않았다. 제품 변경 없이 기존 공통 잠금·고아 파일 보수적 판정·원장 복구의 실제 실행 증거를 추가했다.

이는 테스트 키·합성 기억·임시 저장소를 쓰는 별도 프로세스의 제품 API 인수다. Node MCP 전송 및 JARVIS cursor claim/취소 issuer부터의 통합 경합은 포함하지 않는다. 따라서 외부 전송과 취소의 전체 경합 항목을 완료로 닫지 않는다. 다음 검증은 JARVIS 발행 전후 경계와 두 MCP 접수 경로를 같은 요청 식별자로 연결하는 것이다.

이전 seq1 취소→정상 seq2 settled·명령 completed 인수는 유지한다. 사용자/프로젝트 ACL, 원작업 계보, native 세션/직접 DB 작성자 및 root 정체성, 실제 앱 새 세션 사용, 수집·주입·검색·GUI·운영 복구 목표는 남는다. 운영 데이터·설정·서비스·배포·push는 변경하지 않았다.
