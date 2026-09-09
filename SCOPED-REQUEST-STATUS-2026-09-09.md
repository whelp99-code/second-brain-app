# 범위가 제한된 과거 요청 상태·완료 증명 조회

## 구현 목적과 판정

자비스의 재시작 후 완료 확인을 위해, SB 원장의 scoped-v4 요청을 현재 읽기 범위로 조회하는 내부 경로를 추가했다. 기존 전역 `sb_request_status`를 scoped 사용자에게 그대로 공개하지 않는다. 원래 쓰기 요청이 만료돼도 현재 읽기 권한이 유효하면 과거 완료를 조회할 수 있다. 이 읽기는 쓰기 권한을 갱신하거나 요청을 재실행하지 않는다.

**실제 임시 DB·별도 Python 프로세스에서 완료 증명을 조회하고 JARVIS의 기존 검증기로 대조했다.** 운영 인증된 공개 상태 조회와 자비스의 자동 최종 완료는 아직 연결하지 않았다. 과거 완료 증명은 현재 기억이 삭제·정정되지 않았다는 증거가 아니므로, 기존 현재 artifact/분류/삭제 fence 검증을 대체하지 않는다.

## 변경

- `sb/scoped_request_status.py`: 원래 요청을 역사 시점에 decode하고 전체 journal identity와 수락 기록을 대조한다. 현재 owner/projects/policy 범위를 조회 전후 검사하고 철회·시계 역행을 거절한다. 읽기 범위는 인증된 resolver에서 받아야 하며 요청 본문 자체로 만들면 안 된다.
- 완료된 요청만 proof와 receipt를 반환한다. 본문 바이트 해시, request/provider/scope, 결과 generation, Git head/tree 형식, proof/status 해시와 원장 시간을 검사한다. response는 원장과 분리된 값이다.
- receipt 파일이 없어도 같은 원장 snapshot에서 완료 영수증을 재구성한다. 파일을 만들거나 claim하지 않는다. 호출자가 maintenance-only 원장을 여는 기존 경로를 재사용한다.
- `scripts/scoped-request-status-reader.py`와 기존 실제 권한 인수 도구를 연결했다. 정상 저장 뒤 쓰기 만료 다음 날 새 Python reader로 조회하고, 별도 읽기 정책 파일을 철회한 뒤 재조회 거절을 확인한다.

초기 회귀에서 정상 proof를 거절했다. 원장의 payload digest는 domain을 포함한 JSON 해시인 반면 저장 proof의 content_digest는 UTF-8 본문 바이트 해시다. 기존 JARVIS 검증과 executor 생성 규칙을 대조해 본문 바이트 해시를 사용하도록 수정했다. 기존 해시 계약은 변경하지 않았다.

## 검증 증거

- 신규 상태 조회 11개: 쓰기 만료 후 읽기, receipt 파일 누락, 원장 dump 불변, 응답 수정으로 원장 불변, owner/project/policy 불일치, 최초/최종 철회, 시계 역행, proof/identity/시간 손상, pending의 proof 미노출, 승인된 프로젝트 상위 집합.
- 수락·실행을 포함한 관련 검사: 30 passed / 8.00초.
- 최종 전체 검사: `uv run pytest -q --ignore=tests/test_embeddings.py` → 1,252 passed / 2 skipped / 212.70초. 로그 `/var/tmp/scoped-status-full.out`, exit 0.
- Ruff 전체 sb/tests 및 변경 Python 도구 통과. 새 제품 모듈 basedpyright: 0 errors, 0 warnings.
- 실제 인수 결과: [프로세스 결과](SCOPED-REQUEST-STATUS-2026-09-09.json). 원래 JARVIS 권한 DB/정책을 검사한 저장은 proved. write expiry 이후 receipt 파일 없이 새 reader 조회 성공, 읽기 정책 철회 후 거절, JARVIS `verifySecondBrainScopedProof`는 proof_consistent.
- 기존 인수의 수락 도중 쓰기 정책 철회와 실행 전 쓰기 정책 철회도 다시 통과했다. 각 시나리오 attempt 1개, FK 오류 0, JARVIS 자동 settled 없음.

인수의 인증 세션과 시계, 상태 조회용 읽기 범위 파일은 fixture다. 운영용 인증 결과로 보고하지 않는다. `proof_consistent`는 내부 프로세스에서 공급한 증명의 일관성 결과이며 외부 송신자 인증을 의미하지 않는다.

## 다음 구현과 보류

1. 기존 scoped read v1/v2/v3 계약을 바꾸지 않는 명시적 상태 조회 프로필을 양쪽에 추가한다. 요청 전체/식별자 범위와 claim digest, 도구 허용 목록, 응답 크기 제한을 함께 고정해야 한다.
2. 실제 인증 세션과 현재 정책·삭제 high-water를 검사하는 MCP 경로에서 이 reader를 호출한다. 호출 전후 provider/issuer 정책 철회와 재시작을 검증한다.
3. 자비스에서 원래 수락/attempt와 durable proof, 현재 artifact를 조합한 뒤에만 최종 완료를 기록한다. 현재 active generation이 바뀌었다는 이유만으로 과거 성공을 무효 처리하지 않는다.

공개 전역 status 우회 노출, 만료된 쓰기 승인을 읽기 인증으로 재사용, 해시 일치만으로 자동 settled 처리는 보류한다. 이번에는 배포·운영 DB·서비스·vault를 변경하지 않았다. 전체 M1–M14 목표는 유지한다.
