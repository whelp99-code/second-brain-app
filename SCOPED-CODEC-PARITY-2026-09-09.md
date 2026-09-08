# 자비스 v4 영속 자료 codec·양쪽 검증 대조

2026-09-09. 직전 복구 수정은 전체 검사·커밋으로 진전했다. 이번 자비스 제품 `9bc5976`은 승인 소비·outbox 확정의 선행 조건인 v4 요청 자료의 독립 검증 경계를 추가하고 기존 생성기에 연결했다.

현재 outbox의 control dispatch redemption·원본 요청 재구성 규칙을 확인했다. 범위 검토를 기존 confirmation으로 위장하거나 candidate UNIQUE를 해제하는 접근은 보류한다. codec만으로 승인 소비/저장 확정을 완료했다고 보고하지 않는다.

## 구현과 검증

- 자비스 `src/memory-scoped-write-codec.ts`: canonical JSON 32,768 bytes 제한, 정확한 필드, 원본 v3 재검사, provider/작성자/프로젝트/본문/준비값/만료/idempotency/digest 결합. JSON 중복 키·비정규 bytes는 거부한다. 파싱된 자료는 깊게 freeze한다.
- 생성기 반환 전 독립 검증을 수행하며 기존 원본 권한·현재 정책·승인 검토 검사를 유지한다. 실제 한국어 CRLF 원문을 쓰는 integration 경로에도 연결했고 DB 행 수 불변을 확인했다.
- 초기 TS 반환 타입 순환 참조와 lint의 제어문자 regex 오류를 수정했다. 최종 Vitest **18 passed / 5.38초**, backend 타입/변경 파일 ESLint/격리 emit 통과. 마지막 public type export 후 타입 검사를 다시 통과했다.
- SB 기존 codec **29 passed / 0.22초**, 인수 helper Ruff·양쪽 diff 검사 통과.
- `scripts/scoped-codec-parity-acceptance.py <격리 JARVIS build 경로>`: 실제 컴파일 Node와 Python provider를 별도 프로세스로 대조한다. 같은 fixture의 **정상1·변조12** 판정 일치와 정상 canonical bytes 일치를 확인했다. 변조 요청은 외부 request hash를 다시 계산해 단순 최외곽 hash 불일치만으로 거부되는 검사가 되지 않도록 했다.
- [실행 결과 JSON](SCOPED-CODEC-PARITY-2026-09-09.json). 시험용 fixture이며 provider 호출0·승인 소비false다. 읽은 자료를 최신 운영 상태나 실제 모델 인수로 취급하지 않는다.

## 다음 필수 연결

v4 자료를 기존 outbox에 결합하는 명시적 버전 전환과 승인 단일 소비, 종료/재시작에서 동일 요청의 재사용, 실제 provider 권한 검증, 공개 MCP/자비스 완료 영수증 계약이 남아 있다. 이 codec은 재생·쓰기 권한을 주지 않는다. 전체 M1~M14, 실제 에이전트·운영 인수 목표는 유지한다. 이번에는 전체 Python/JARVIS 검사를 재실행하거나 운영 서비스·DB·설정을 변경하지 않았다.
