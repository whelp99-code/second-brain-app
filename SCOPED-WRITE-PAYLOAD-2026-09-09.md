# 범위 검토와 후보 본문 결합

2026-09-09. 현재 후보의 제목·본문을 승인된 범위 식별자에 결합하는 `prepareMemoryScopedWritePayload`를 추가했다. 기존 범위 식별자만으로 호출자가 보낸 본문까지 검증됐다고 판단하지 않는다.

같은 read transaction에서 현재 서명 검토·범위 identity와 persisted candidate를 읽는다. approved/remember 후보만 준비하며 plain-text-v1 검증 후 제목·본문 각각의 domain hash를 후보의 저장된 digest와 비교한다. purpose·sensitivity·retention_days도 호출자 값이 아닌 후보에서 가져온다. 준비 결과 전체는 별도 preparation domain으로 해시한다. 저장된 v1 후보나 일반 remember 계약을 변경하지 않는다.

## 검증

- 관련 JARVIS 2 passed/3.64초. 정상 후보 본문 일치, 제목 바꿔치기·본문 바꿔치기·NUL 본문 거부, DB 행 불변을 확인했다.
- TypeScript noEmit·격리 emit·변경 파일 ESLint, Python helper Ruff, JS 구문·diff 검사 통과. Python helper의 import 순서 경고 1건은 수정 후 재검사했다.
- fixture DB에서 실제 owner 키로 서명한 범위 검토를 사용해 컴파일된 제품 API로 본문을 준비했다. 다른 작업 결과 본문은 MEMORY_SCOPED_PAYLOAD_INVALID로 거부됐다.
- Python에서 준비된 제목·본문 digest와 preparation digest를 독립적으로 재계산해 모두 일치했다. 기존 scope identity/idempotency 일치 및 독립 Node 7개에서 실행 거부·승인 보존·범위/철회/격리 검사도 통과했다. [결과 JSON](SCOPED-WRITE-PAYLOAD-2026-09-09.json).

## 남은 구현

준비 결과의 profile은 scoped-remember-preparation-v1이고 writes_authorized=false다. 이는 네트워크 요청 codec이나 승인 소비 완료가 아니며 아직 inbox/outbox를 만들지 않는다. scoped 쓰기 실행에는 현재 작업 근거·프로젝트 정책 재검사, 승인 영수증 단일 소비와 outbox 삽입, provider의 요청별 source 분류 및 완료 영수증을 연결해야 한다. 준비 시 검증한 값을 실행 시 검증 대신 사용하는 방식은 보류한다.

이번 검증은 합성 작업 근거·fixture 키/시계와 실제 제품 코드/DB를 사용했다. 실제 모델·운영 로그인·HTTP 쓰기·새 agent 회수 또는 현재 전체 스위트 완료를 뜻하지 않는다. 운영 서비스/DB/설정과 provider 쓰기 표면은 변경하지 않았다.
