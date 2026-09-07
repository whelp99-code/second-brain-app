# 기억 유효기간과 조회 응답 시간 계약

상태: R4 소스 구현·검증. 운영 전환은 미실행. Second Brain schema 4의 기존 record 필드 및 자비스의 소비 모델을 사용한다. JSON schema·도구 목록·canonical digest 계산을 완화하거나 교체하지 않는다.

## 해결하는 문제

기존 provider는 모든 기억을 updated 날짜의 UTC 자정부터 하루만 유효하게 만들었다. 자비스는 종료된 기록을 ID 손상으로 거부하고 페이지 작성일로도 일괄 만료시켰다. 날짜 없는 provider 기록은 읽는 시각이 바뀌면 ID도 바뀌었다. 장기 보존 기록이 정상적으로 조회되지 않는 원인이었다.

## 저장된 주장과 응답의 구분

1. record의 `valid_from`/`valid_until`은 반개구간 `[from, until)`이다. 현재 시각이 구간 안에 있어야 현재 사용 가능한 기억이다.
2. 내부 frontmatter의 명시적 날짜는 정확한 24자 `YYYY-MM-DDTHH:mm:ss.sssZ`로 검증한다. 잘못된 날짜·역전·같은 시작/끝을 기본값으로 은폐하지 않는다. 명시적 시작이 없으면 유효한 updated 날짜를 기존과 같이 날짜 단위 기준으로 사용한다. 이는 정확한 사건 발생 시각을 새로 추론했다는 뜻이 아니다.
3. 시작 정보도 없으면 `0001-01-01T00:00:00.000Z`를 **알려지지 않은 열린 시작**으로, 종료 정보가 없으면 `9999-12-31T23:59:59.000Z`를 **명시적 종료 없음**으로 사용한다. 실제 사실의 시작·끝 날짜나 관측일을 주장하는 값이 아니다. sealed generation의 Git commit 날짜는 재현성을 위해 2000년으로 고정되므로 관측 시각으로 사용할 수 없다.
4. 기록의 ID/digest는 원문·출처·span·위 시간 정보를 그대로 포함한다. 호출 시각은 ID에 영향을 주지 않는다. 바뀐 날짜나 본문은 새 digest를 필요로 한다. 날짜를 변조하고 예전 digest를 재사용하면 거부한다.
5. `observed_at`은 이번 조회 시각이다. 현재 구간의 응답은 `fresh_until = min(checkedAt + max_age_ms, valid_until)`, `expires_at = min(checkedAt + expiry_ms, valid_until)`이다. 열린 종료가 응답 캐시를 영구 유효하게 만들지 않는다.
6. 구간 이전·종료 시각과 이후는 `stale`이고 응답의 freshness/expiry 경계는 checkedAt이다. 재조회 없이 미래의 시작일까지 기다렸다가 기존 stale 응답을 current로 재사용할 수 없다. 정상적인 시간 경과를 `RECORD_IDENTITY_INVALID`로 표현하지 않는다.
7. `fresh`/`current`는 해당 시각 provider에서 읽은 사용 가능한 저장 기록이라는 뜻이다. 사실을 현실에서 다시 검증했다는 뜻은 아니다. `trust=untrusted`, `authority=none`을 유지한다. 실행 결과 검증은 자비스 책임이며 요약이나 최신 조회로 성공·승인 상태를 승격하지 않는다.
8. schema 3의 인용 기반 legacy 응답은 기존 페이지 만료 규칙을 유지한다. 기존 클라이언트에 새로운 도구나 필드를 조용히 추가하지 않는다.

보존·삭제 정책은 별개다. 열린 종료가 사용자 삭제 요청·정정·retention·재유입 억제를 무효화하지 않는다. record target의 짧은 resolved_at/expires_at 및 요청·승인 TTL도 그대로다. 기억 유형별 재검토일과 특정 날짜 기준 검색은 B5/G1/G4 후속 범위다. 이번에 내부 날짜 해석을 추가한 것으로 모든 입력 UI가 기간 편집을 지원한다고 표시하지 않는다.

## 업그레이드 경계

기존 하루 기본값을 사용하던 기록의 ID/digest는 새 정책에서 바뀐다. 같은 generation을 구형·신형 provider로 동시에 읽는 동안 서로 다른 record 선택이 생성될 수 있으므로 **운영 실행 파일만 먼저 바꾸지 않는다.**

- 소비자 변경을 먼저 검증하고 배포한다. 이 소비자는 구형 유한 구간과 신형 열린 구간을 모두 검증한다.
- 실제 provider 전환은 읽기/쓰기 진입을 유지보수 경계로 묶고, 기존 미완료 요청·reader·target 상태를 점검한 후 새 provider_release_sha를 가진 generation과 실행 파일을 함께 전환해야 한다. 경계 해제 전에 검색→페이지→target의 일치와 readiness를 검사한다.
- 구형 selection/target은 새 generation에서 다시 조회한다. 이전 요청의 digest·서명·target을 자동 치환하거나 실패한 요청을 임의로 완료 처리하지 않는다.
- 이미 접수한 요청과 deletion/tombstone journal의 처리 상태를 보존한다. 재시도·완료·재접수 여부는 기존 상태기계로 판단한다. 롤백도 활성 generation·journal과 함께 검증해야 한다.
- 이번 소스 프로브는 별도 MCP 프로세스에서 운영 자료를 읽었다. 서비스 실행 파일·active 포인터·저장 기록을 전환하지 않았다. 완전한 배포/롤백 인수는 B6에 남는다.

## 검증

- Python: 날짜 없는/오래된 기록의 시계 독립 ID, 명시적 유효기간, 잘못된 구간 거부, 실제 sealed 두 세대에서 ID·기간 보존, target 응답의 5분 만료.
- 자비스: 오래된 durable 기록, 명시적 종료 상한, 종료 시각 경계, 과거·미래 기록의 stale, 날짜 변조와 extended-year 거부, legacy 만료 유지.
- 실프로세스: 운영 자료를 소스 MCP와 실제 자비스 adapter로 검색. 현재/다음 날/35일 후의 주입 시계에서 같은 10개 record와 bounded expiry 확인. 미래 시계 검사는 실제 35일 운영 증거가 아니다.
- 전체 검사 결과·커밋은 [구현 원장](IMPLEMENTATION-STATUS.md)에 기록한다.
