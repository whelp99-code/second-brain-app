# 자비스 발행/취소와 실제 MCP 접수의 두 경계 인수

2026-09-09. 인수 코드 `fd5e9b5`. JARVIS 제품 `ea076ae`/테스트 `30cf131`, SB 제품 `9e30115` 유지.

## 실제 연결과 결과

기존 686f6e8은 별도 Python 프로세스의 접수 잠금 경합을 검증했다. 이번 인수는 실제 JARVIS MemoryCorrectionSaga·MemoryCorrectionCancellationIssuer·bounded write adapter·Node transport·Python MCP를 연결한다. 같은 시나리오의 DB와 요청 식별자를 끝까지 사용한다.

| 경계 | 자비스·MCP 실측 | provider 실행과 커밋 |
|---|---|---|
| 원 요청 접수 응답을 받은 직후, saga의 로컬 응답 기록 전 | Node763553/MCP763731. 실제 sb_write_request1회. suppression 요청을 적용한 뒤 취소를 시도하면 dispatch fence/미전송 검증이 MEMORY_CANCELLATION_UNSENT_UNPROVED로 거부. 취소 의향0개/MCP 취소 호출0회. cursor1 | 정정 proved·다음 실행 idle. 이전 내용 부재, 정정 내용 존재 |
| 유효한 suppression 근거로 취소 의향을 저장하고 MCP 제출을 시작한 동안 원 요청 dispatch 재시도 | Node763523/MCP763729·763749. 원 요청 writer0회/MCP 쓰기0회. 취소 의향1개. provider 접수 commit 직후 exit77로 응답 유실, 명시적 transport 재시작과 같은 의향 재접수. 취소 MCP 호출 총2회. cursor0 유지 | 실제 CLI 취소 적용, 원 요청 행 없음·다음 executor idle. 이전 내용과 정정 내용 모두 부재 |

[기계 증거](CANCELLATION-JARVIS-MCP-RACE-2026-09-09.json).
원본은 `/var/tmp/cancellation-submit-acceptance-eh4dmaff/race-result.json`, `/var/tmp/cancellation-submit-acceptance-i2ga1k2x/race-result.json`이다.

취소 우선 시나리오의 queued/cursor0은 이 인수가 취소 접수와 provider 처분까지 검사하기 때문이다. 취소 settlement/cursor1→후속 seq2 settled·명령 completed의 전체 연결은 이전 [최종 완료 인수](CANCELLATION-FOLLOWUP-SETTLED-ACCEPTANCE-2026-09-09.md)를 따른다.

## 실패에서 수정한 인수 구성

첫 원 요청 실행은 Node read fence가 테스트 MCP 시계보다1초 미래여서 provider stale로 거부됐다. race mode에서 양쪽 고정 시계를 맞췄고 제품 시간 검증은 유지했다.
취소 시제품은 suppression 이벤트 발행 전 barrier와 단순 quarantine을 의향 근거로 사용해 MEMORY_CANCELLATION_SUPPRESSION_UNPROVED로 거부됐다. 기존 cancellationDatabaseFixture의 검증된 suppression 경로로 바꿨다. 이벤트/증거를 직접 조작하거나 issuer 조건을 완화하지 않았다. 단순 quarantine을 유효한 취소 근거로 사용하는 경로는 보류한다.

## 검사와 재현

최종 두 모드는 각자 독립 임시 저장소에서 실제 Node/Python 실행을 완료했다. 실제 MCP 메서드 호출 횟수·PID·원장·실행 상태·git HEAD 본문을 검증한다. 접수/취소 응답은 대역이 아니다. 준비된 후보·승인·억제 증거 및 키와 기억 내용은 테스트 fixture이며 시계는 2026-08-28 고정이다.

- `TMPDIR=/var/tmp .venv/bin/python scripts/cancellation-submit-acceptance.py ISOLATED_JARVIS_BUILD --race-request`
- 같은 명령의 `--race-cancellation`.
- 관련 Python 새 원 요청 경합·일반 writer 경합·취소 executor **14 passed / 15.13초**.
- 전체 sb/tests Ruff, Node syntax, Python AST, git diff check 통과.
- 제품 소스/계약/migration 수정 없음. 전체 제품 테스트 및 운영 배포 인수는 재실행하지 않았다.

## 전체 목표에 대한 판정

선택한 자비스 발행 경계 두 곳에서 실제 MCP 전송까지 연결된 단일 효과를 인수했다. 이는 같은 자비스 프로세스의 결정적 async 경계 검사이며 임의의 여러 자비스 runtime·직접 DB 작성자를 모두 배제했다는 증거는 아니다. 기존 별도 provider 프로세스 잠금 경합 검증과 범위를 구분한다.

다음 P0는 사용자/프로젝트 ACL과 원작업→기억 계보, 관리형 native 세션/SQLite WAL/백업 수명, 다중 runtime·직접 writer 및 root inode 변경, 실제 앱 새 세션 재사용이다. 자동 수집/주입·한국어 검색 평가·GUI·운영 복구 조건을 유지한다. 운영 서비스·DB·설정·배포·push는 변경하지 않았다.
