# 내부 v4 수락→실행→봉인→처리 영수증 연결

2026-09-09. 이전 수락 조합·검증·커밋은 진전이었다. 이번에는 기존 provider 실행기를 통해 v4 기억을 실제 처리하는 내부 경로를 구현했다.

## 구현

`RequestExecutor`에 명시적 `scoped_authority` callback을 추가했다. 제공된 경우에만 v4 원장을 열고 v4 파일을 claim한다. 기본값은 None이며 기존 1/2/3 경로를 유지한다. 운영 CLI/MCP 구성에는 아직 연결하지 않았다.

`load_scoped_execution`은 private 파일을 bounded/O_NOFOLLOW/inode/link 검사로 읽고 봉투를 검증한다. v4 request identity 전체와 수락 원장 identity, 최초 accepted_at, 재계산한 수락 result와 file digest가 일치해야 한다. 원본 v3는 최초 수락 시각으로 해석하되 이것을 새로운 권한으로 취급하지 않는다.

기존 remember stage·CAS·Vault·generation mutation·단계 전환·proof 기록을 재사용한다. 원본 프로젝트 분류를 `materialize_remember(source_access=...)`로 전달하고, mutation ID와 proof ID는 바깥 v4 요청 ID를 사용한다. v4 artifact proof에는 request digest·scope digest·provider도 결합한다. 기존 v1/v3 proof 구조는 유지한다.

실행 시작·materialization·세대 전환 직전에 명시적 권한 callback이 정확히 True여야 한다. 아직 활성화되지 않은 만료 요청은 callback이 True여도 거부한다. 이미 활성화된 단계의 역사적 복구와 새 쓰기를 구분하며, 구체적 권한/철회 처리 전체 인수는 아래 남은 조건을 따른다.

## 검증

- 초기 신규 테스트3개는 apply_once의 keyword-only 인자를 잘못 호출하여 실패했다. worker=로 수정했고 제품 검증을 완화하지 않았다.
- scoped execution/v3/admission/walking skeleton **42 passed / 7.77초**, 전체 Ruff 및 helper Ruff·diff 검사 통과. 최종 전체 Python 검사는 **1,208 passed / 2 skipped / 217.08초**다. 기존 gate대로 optional `tests/test_embeddings.py`는 제외했고 JARVIS 전체 검사를 포함하지 않는다.
- 정상 proved·scope/request digest proof 결합·4records·다른 프로젝트 거부, 변조 봉투/권한 철회 거부, 만료 시작 거부, sealed manifest 뒤 권한 철회 시 활성화 차단을 확인했다.
- 실제 별도 Python 프로세스7개: accept→execute→독립 reader2개와 불허 reader1개→재수락→재실행. `PROVIDER_PROVED`, v4 처리 영수증의 요청 일치, records4/4, 다른 프로젝트 거부, replayed=true, 재실행 idle, pending 파일0을 확인했다.
- [실행 JSON](SCOPED-REQUEST-EXECUTION-2026-09-09.json), `scripts/scoped-request-execution-acceptance.py`로 재현한다. fixture 권한·합성 요청·임시 provider이며 종료 후 정리했다.

## 보류와 다음 완료 조건

fixture의 True 권한 callback을 운영에 연결하는 방식은 채택하지 않았다. 실제 authenticated transport·현재 정책·자비스의 소비된 범위 검토 증거를 확인하는 검증기가 필요하다. v4 MCP contract/수락 노출과 자비스 outbox·승인 단일 소비·처리 영수증 소비도 아직 미완료다. 여기서 생성한 v4 proof는 내부 provider 증거이며 구형 클라이언트에 호환된다고 주장하지 않는다.

운영 전에는 활성화 후 중단·철회·만료의 재개, v4 정정/삭제/복구·legacy import 혼합 구성, 실제 에이전트 인증 세션 회수까지 인수해야 한다. 기본 실행기의 schema 제한을 풀어 우회하지 않는다. 전체 M1~M14와 운영 목표를 이번 내부 실행 성공으로 축소하지 않는다.
