# 자동 승인 후보의 실제 provider 저장·재조회

2026-09-09. 자동 발행 제품 `aa825f0` 이후 일반 owner 저장 경로의 통합 인수다. 프로젝트 범위가 결합된 쓰기 인수와 구분한다.

## 실행 경로와 결과

새 격리 DB의 검증된 후보 입력을 실제 JARVIS CLI execute로 분류했다. v3 review/dispatch 자동 발행→CLI stage-dispatch→기존 owner 키의 실제 서명 승인→CLI control execute→supervised MCP→SB pending 요청 수락→실제 provider 처리→CLI outbox 확인→기존 명령 완료→독립 MCP 클라이언트 재조회까지 실행했다.

| 확인 항목 | 결과 |
|---|---|
| 후보 발행 | auto_approved_cli, candidate_intake=true, request_schema=3 |
| 수락 직후 | pending; 자비스 명령은 uncertain/reconciling으로 저장 완료와 구분 |
| provider 처리 | proved / PROVIDER_PROVED |
| 자비스 재확인 | outbox=settled, control_state=completed, commands_reconciled=1 |
| 재사용 | 현재 record 4개; 독립 MCP 클라이언트의 record ID 목록과 일치 |
| 중복 요청 | replayed=true, 재처리 idle, redispatched=0, terminal replay=settled |
| 본문 정리 | remaining_review_files=0, cleanup_error=null |
| 범위 | project_scoped_write=false |

[최종 JSON](AUTO-CANDIDATE-PROVIDER-2026-09-09.json)의 요청 ID로 처리 결과를 추적할 수 있다. 첫 연결 시 격리 build에 계약 파일이 없어 CONTRACT_MISMATCH로 중단됐다. helper가 정본 계약 파일 경로를 명시하도록 수정한 뒤 통과했고, 결과 표기 보완 후 다시 실행해 통과했다. 계약 hash 검사 자체는 완화하지 않았다.

## 재현 및 검사

```bash
cd /home/jm/orca/projects/second-brain-app
TMPDIR=/var/tmp JARVIS_ACCEPTANCE_BUILD="$(cat /var/tmp/cancellation-material-build-path.txt)" \
  node scripts/jarvis-memory-acceptance.mjs /home/jm/orca/projects/Orca-JARVIS \
  --auto-candidate --plain-text-v3 --runtime-cli --record-budget
```

helper가 새 fixture DB/vault/MCP launcher를 만들고 종료 시 정리한다. 운영 dist 대신 격리 emit 경로를 사용한다. 기존 owner-confirmed 모드와 별도로 auto-candidate 모드를 추가했다. v3 fixture의 시각을 provider 시험 시각에 맞출 수 있게 했으며 본문/spool은 실제 CLI가 만든다.

관련7통과/7.91초, TypeScript noEmit·격리 emit·변경 fixture lint·JS 구문·diff 검사 통과. 전체 Python/Vitest는 이번에 재실행하지 않았다.

## 남은 범위

실제 CLI/API·서명·MCP·DB·provider 처리·별도 MCP 프로세스를 사용했지만 원본은 합성 검증 결과이며 compile은 결정적 fixture다. 실제 LLM 작업 성공의 자동 검증, 운영 Tailnet/서비스, Codex/Claude 새 모델 세션, 프로젝트 접근 분류가 결합된 쓰기를 증명한 것은 아니다.

일반 owner 저장의 자동 후보 경로는 이번에 끝까지 연결해 검증했다. scoped 요청 codec·범위 승인 단일 소비·outbox 원자화·프로젝트 정책·요청별 source 분류·scoped 완료 영수증과 다른 agent 회수는 계속 P0다. capabilities의 writes_supported=false를 변경하지 않았다. 운영 설정/DB/서비스 변경 및 push는 하지 않았다.
