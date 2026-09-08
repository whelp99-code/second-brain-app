# 완료 proof의 키 유효 시점 누락 수정

2026-09-09. JARVIS 제품 `f7663ca`, SB 제품 `9e30115` 유지.

## 발견·재현·수정

사용자/프로젝트 scope ADR와 기존 candidate·record·신뢰 검증 경로를 대조했다. 원본/요청/record에는 검증된 일반 project 접근 분류가 없고 기존 owner 고정 계약을 그대로 필터 확장으로 바꿀 수 없음을 재확인했다.

그 과정에서 verifyMemoryDispositionProof가 provider 키의 state·provider/release·현재 유효 기간을 확인하지만 proof.completed_at이 키의 유효 기간 안에 있는지는 검사하지 않는 결함을 확인했다. 완료00:00:03.000, 키 valid_from00:00:03.001, 검증00:00:04.000인 올바른 서명 proof가 수정 전 수락됐다. 예상 거부 테스트가 실패했고 두 정상 경계는 통과했다.

키 조회가 현재 시점과 completed_at 양쪽에서 valid_from <= 시각 < valid_until을 요구하도록 수정했다. 기존 현재 철회/만료·provider/release·서명·request binding·시간 순서 조건은 유지한다. 완료 시점부터 정확히 유효한 키는 허용하고1ms 뒤부터 유효한 키는 MEMORY_PROVIDER_PROOF_KEY_INVALID로 거부한다. wire schema·키 DB migration·키 발급 정책은 바꾸지 않았다.

처음 테스트 구성에서 기존 키 유효 기간을 UPDATE하려 했을 때 DB 불변 trigger가 거부했다. 해당 방법을 폐기하고 각각 새 DB에 정상 등록 API로 다른 기간의 키를 등록해 제품 결함을 재현했다. trigger 거부를 proof 결함 재현으로 계산하지 않는다.

## 검증

- 최종 proof 경계3개 및 correction control11개: **14 passed / 40.59초**.
- 기존 control 회귀에는 최종 이벤트 rollback/복구·만료 후 완료·키/서명/fence/철회/취소/바인딩/정리 증거 누락의 완료 거부가 포함된다.
- TypeScript noEmit, 변경 파일 ESLint, 격리 emit, diff check 통과. 운영 dist는 변경하지 않았다.
- 수정된 격리 빌드로 실제 `--dispatch-result` 인수를 다시 실행했다. Node787338→실제 MCP/proof·provider40/guard10→로컬 정리→정정 settled/명령 completed. 독립 Node789026 동일 완료 재생.
- 전체 catalog 기대70/관측70, 누락0/오류0/본문 일치0. 발행1회/cursor2, provider proved·커밋 정정 반영·이전/취소 내용 부재·다음 실행 idle.

[기계 증거](PROOF-KEY-WINDOW-ACCEPTANCE-2026-09-09.json). 원본 `/var/tmp/cancellation-submit-acceptance-e6v6b_c9/result.json`.
요청 `memeff:req:v2:36bbffef2ed1af09cd325ae967ca28f82afb6a2c4fad41942ba4941415683321`.

## 영향과 남는 일

유효 기간 시작 전 완료했다고 주장하는 proof는 새 검증에서 거부된다. 기존 기록을 자동 수정하거나 키 기간을 소급 변경해 통과시키지 않는다. 현재 신뢰된 키를 사용하는 정상 실제 완료 경로는 재인수했다. 과거 전체 데이터의 재감사나 운영 배포를 수행한 결과는 아니다.

**사용자/프로젝트 ACL은 아직 구현 완료가 아니다.** 다음 범위 작업은 기존 SHARED-MEMORY-SCOPE-ADR의 순서대로 자비스 후보/요청의 검증된 원본 분류와 provider record의 분류 바인딩을 함께 버전 확장하는 것이다. 주체·목적·policy revision·원본 분류가 연결되지 않은 project 필터를 권한으로 사용하지 않는다. 과거 무분류 기억은 owner 자료로 유지한다.

원작업→기억 계보, native 세션/WAL/백업 수명, 다중 runtime/직접 DB writer 및 root 정체성, 실제 앱·수집/주입·검색·GUI·운영 복구의 전체 목표를 유지한다. 이번 실사용 검증은 테스트 키·합성 기억·임시 저장소에서 실제 Node/Python/MCP/SQLite/Git를 실행했다. 운영 서비스·설정·DB·배포·push는 변경하지 않았다.
