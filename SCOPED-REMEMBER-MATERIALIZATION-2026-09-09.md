# 요청 기억의 프로젝트 분류를 봉인 세대에 보존

2026-09-09. M2 범위 쓰기 완료를 위한 저장 측 구현이다. 이전 단계 `2d11e7e`는 준비값 codec·실제 교차 언어 검증과 커밋으로 진전했다.

## 확인한 결손과 수정

`materialize_remember`는 CAS 원문·인용·페이지를 만들지만 source_item/source_access/page_access를 결합하지 않았다. 따라서 프로젝트 분류를 전달할 수 있어도 봉인된 scoped reader가 새 기억을 완전한 출처로 읽을 수 없었다.

기존 함수에 명시적 `source_access: SourceAccess | None` 인자를 추가했다. 분류가 있을 때만 기존 Ledger transaction에서 정확한 candidate/content 버전의 원본을 등록하고 불변 분류를 결합한다. Vault만 페이지를 기록하며, 실제 렌더링된 페이지 bytes의 SHA-256과 모든 원본 요구 범위를 page_access에 결합한다. 분류를 생략한 기존 일반 경로는 유지한다.

동일 원본/내용의 같은 분류 재시도는 유지되고 다른 프로젝트로 재분류하면 `SOURCE_ACCESS_RECLASSIFICATION_REQUIRED`로 거부한다. 분류 충돌 검사는 페이지 기록 전에 수행한다. 함수는 generation mutation이 소유한 비공개 staging에서 실행해야 하며, 파일·DB의 전체 원자성은 기존 봉인/활성화 경계를 따른다. 활성 vault를 직접 수정하는 API로 사용하지 않는다.

## 검증

- remember/scoped remember/page access 관련 **14 passed / 1.64초**. 한국어 CRLF 원문 보존, 봉인 후 4개 record, 허용 분류 수락, 다른 프로젝트 거부, 같은 요청 재시도와 다른 분류 rollback을 확인했다.
- import 순서 lint를 수정한 뒤 전체 Ruff 통과. 최종 전체 Python 검사 **1,169 passed / 2 skipped / 220.91초**. `tests/test_embeddings.py` optional extra는 기존 gate대로 제외했으며 JARVIS 전체 검사는 포함하지 않는다.
- 실제 JARVIS CLI→서명 검토→준비 API에서 만든 합성 데이터를 독립 Python 실행으로 검증하고, 새 GenerationStore에서 저장·봉인·활성화했다. 서로 다른 reader 프로세스 3개에서 허용2회 **records4/같은 page digest/같은 source ref**, 다른 프로젝트 **MEMORY_ACCESS_DENIED**를 확인했다. 원문 **51 bytes**.
- [구조화 실 실행 결과](SCOPED-REMEMBER-MATERIALIZATION-2026-09-09.json), 재현 스크립트 `scripts/scoped-remember-materialization-acceptance.py`. 사용한 임시 세대/DB는 정리했다.

## 남은 완료 조건과 보류

이번 인자는 내부 staging에 검증된 분류를 전달하는 수단이다. 현재 `RequestExecutor._remember`는 아직 이 인자를 전달하지 않는다. 공개 요청 계약에 범위와 권한 증거가 없으므로 body/frontmatter/config 기본값으로 범위를 추측하는 연결은 보류했다. 준비값의 digest만으로 쓰기 권한을 허용하지 않는다.

다음에는 자비스의 현재 권한/정책 검증과 범위 검토 단일 소비, 버전이 구분된 요청·영수증, provider 수락 원장의 불변 분류를 연결해야 한다. 이후 실제 MCP 요청→처리→완료 영수증→새 agent 인증 세션 회수를 통과해야 범위 쓰기 완료로 판단할 수 있다. 이번 프로세스 인수는 서버 내부 저장/봉인/읽기 검증이며 실제 Codex/Claude 또는 운영 배포 검증이 아니다. 전체 M1~M14 목표는 계속 남는다.

## 다음 수락 구현에서 확인된 제약

자비스 migration057의 `memory_outbox.candidate_id`는 UNIQUE이고 `insertOrReplay`는 candidate ID 또는 idempotency key가 일치하는 기존 saga를 조회한다. 따라서 프로젝트를 바꾼 idempotency key만 만들면 여러 저장이 가능하다고 가정할 수 없다. 현재 원본 분류도 같은 candidate/content의 재분류를 거부한다. 기존 기억의 범위 변경을 추가 저장으로 우회하거나 UNIQUE 제약을 제거하는 변경은 채택하지 않았다. 후속 요청 계약은 동일 후보의 재시도와 범위 변경/정정을 명확히 구분해야 한다.

기존 `control_command_redemptions`도 request ID와 receipt ID를 단일 소비 키로 가진다. 범위 검토용 receipt를 일반 실행기의 lease로 임의 소비하면 승인 조회가 더 이상 통과하지 않는다. outbox와 검토 소비를 하나의 transaction에 결합하고 역사적 재조회와 새 쓰기 권한 검증을 구분하는 구현이 필요하다.
