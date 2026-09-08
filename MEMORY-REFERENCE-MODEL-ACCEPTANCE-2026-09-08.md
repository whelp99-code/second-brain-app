# 실제 모델의 공통 참고 기억 소비 인수

상태: **격리 합성 기억을 실제 Codex 모델 요청에 넣고 정확한 답·근거를 회수했다. 제품 자동 주입·세션 이력·운영 인수 완료는 아니다.**

[자비스 CLI 연결](MEMORY-REFERENCE-READ-2026-09-08.md)의 실제 출력이 모델 요청에서 사용할 수 있는지
검증했다. native client 자체가 MCP를 호출했던 [앞선 두 클라이언트 인수](AGENT-CLIENT-MEMORY-ACCEPTANCE-2026-09-08.md)와 달리,
이번 경로는 **SB 저장→자비스 CLI의 정책·세대 검사→reference JSON→도구 없는 모델 요청→답·출처 대조**다.
별도 기억 서비스나 모델 Proxy를 제품에 추가하지 않았다.

## 변경과 실측

- `tests/fixtures/jarvis_memory_provider.py`의 격리 seed에 선택적 합성 본문을 추가했다. frozen
  fixture 기본값은 유지하며 변경 본문의 request digest를 기존 canonical 규칙으로 계산한다.
- `scripts/jarvis-reference-model-acceptance.mjs`는 실행마다 128-bit 무작위 확인값을 생성해
  격리 provider에 저장한다. 질문 지시문과 출력 schema에는 확인값이 없고 reference 본문에만 있다.
  이 값은 비밀키나 운영 자료가 아닌 검증용 합성 문자열이다.
- 실제 `codex-cli 0.153.4` / `gpt-5.6-sol`로 서로 독립된 ephemeral 요청 두 번을 실행했다.
  사용자 config를 제외하고 앱·쉘·웹·하위 agent 기능을 끄는 명시적 설정이며 native 도구 호출은 0건이다. 별도 격리 cwd와
  stdin을 사용하고 네트워크 전송 내용은 이 검증에서 생성한 합성 reference다.
- 기억 없는 대조 요청: **6645ms**, `no_data`, 답·근거 필드 전부 null.
- 기억 있는 요청: **13815ms**, 확인값과 record_id/record_digest/text_digest/
  source_identity_full/generation_id 모두 실제 CLI 결과와 정확히 일치.
- 모델 완료 시점에 원 reference가 만료되지 않았음을 검사했다. 그 뒤 실제 CLI로 다시 조회해
  provider 세대·record binding·본문 digest가 동일한지 확인했다.

위 지연은 모델/CLI 시작을 포함한 각 1회 실행값이며 검색 p95나 모델 품질 통계가 아니다.
정답·출처가 맞는 두 사례를 자연어 검색·충돌 판단·실제 업무 정확도 전체로 확대하지 않는다.

## 완료 이벤트 감사

`scripts/reference_model_events.mjs`는 exit 0만으로 통과시키지 않는다. 단일 native thread/turn의
시작→정확히 한 답변→turn.completed 순서를 요구한다. 시작만 한 도구, 완료 도구, item 오류,
turn 실패, 누락·중복 완료와 답변, 잘못된 JSON, no_data의 추측 답변을 거부한다.
모델은 이 인수에서 기억을 찾는 도구를 사용하지 않고 전달된 JSON만 소비한다.

`scripts/reference_model_events.test.mjs`: **14 passed**. MCP 계약·프로필·walking skeleton의
관련 Python 회귀 **12 passed / 11.13초**. 이 회귀는 새 모델의 품질 검사 수에 합산하지 않는다.
전체 Ruff와 Node 구문 검사를 통과했다. seed 선택 인자 추가 후 기존 실제 CLI의 5시나리오도
재검증했다(`/var/tmp/jarvis-reference-cli-seed-compatibility.log`). 변경은 SB 테스트/인수 도구이며 자비스 제품 소스는 이번 단위에서 수정하지 않았다.

## 증거와 재현

최종 artifact: `/var/tmp/sb-reference-model-4ObTZl`. 격리 DB: `/var/tmp/jarvis-task27-memory-PAaqaj`.
각 요청의 `.cli.stdout`, `.cli.stderr`, `.prompt.json`, `.model.jsonl`, `.model.stderr`와 result.json을
보존했다. 실제 모델 실행 로그는 `/var/tmp/jarvis-reference-model-acceptance-final.log`다.

- 참고 기억 JSON digest: `sha256:96768966d257efe7242e08352947ccbaa2c082ba4a73c96a54dca2411ed7f9e0`.
- 실제 답 JSON digest: `sha256:5fbc4afaf8394c193c120f4c639d3ab7f78af1fda358bcd6c303a68cc354df88`.
- native 모델 완료 확인 수준: `native_turn_completed_and_exact_answer_with_provenance`.
- 모델 요청 후 실제 관측한 personal_context_snapshots / personal_context_memory_evidence /
  memory_projection_dependencies는 각각 **0행**이다. `context-storage-observation.json`.
  따라서 이 인수 artifact를 기존 제품 DB의 전달 영수증이나 session 중복 억제 구현으로 주장하지 않는다.

자비스 `63bdd02` 이후 제품 소스를 별도 outDir에 빌드하고 contracts/migrations를 포함한 뒤:

```bash
TMPDIR=/var/tmp node scripts/jarvis-reference-model-acceptance.mjs <jarvis-build-root>
node --test scripts/reference_model_events.test.mjs
```

실제 client 로그인과 모델 사용량이 필요한 opt-in 인수다. 기본 pytest에서 모델을 호출하지 않는다.
운영 설정·서비스·원문·키는 수정하지 않는다. `--ephemeral`은 client 로컬 session 파일에 대한
설정이지 원격 모델 사업자의 보존 정책이나 삭제 완료 증거가 아니다.

## 다음 구현 경계와 보류 판정

| 대조 대상 | 이번에 확인한 현재 구현 | 후속 작업/판정 |
|---|---|---|
| 자비스 실제 작업 prompt | `src/task-candidate-provider.ts:56`은 TaskSpec/plan/source_files를 조립 | 기억 JSON을 자동으로 덧붙이면 현재 승인된 plan과 실제 전송 입력의 관계를 새로 정의해야 함. 승인 원형에 없는 기억의 무조건 주입 보류 |
| 세션 수명 | `src/claude-task-provider.ts:11`의 `--no-session-persistence`, `:78`의 stdin 전송 | 이 호출을 persistent session/compaction 확인으로 사용할 수 없음. 실제 client session identity·epoch와 확인 수준을 연결해야 함 |
| 기존 context 저장 | `src/personal-context-store.ts:123`은 추천용 snapshot을 기존 projection에 결합 | reference-only 본문과 모델 수신 확인을 같은 의미로 저장하지 않음. 계약 버전과 원문 최소 전달 메타데이터 필요 |
| 삭제 추적 | 기존 projection kind와 legacy suppression 원장 존재; 새 CLI는 surface/legacy 판정 공통화 | reference record membership→기존 projection→session 전달의 정정·삭제 연결과 즉시 차단을 검증해야 함 |
| 공유 범위 | 현재 owner fence; 검증된 프로젝트 분류 미연결 | 임의 session/project 문자열로 접근 권한을 발급하거나 범위를 넓히는 방식 보류 |

C1의 실제 모델 소비 증거는 추가됐지만 C6/C7/C8은 계속 미완료다. 전송 실패·수신 불확실·확인 후
중복 억제, 새 session/compaction 재공급, 준비/전송 중/후 정정·삭제·정책 변경, 실제 tokenizer,
앱별 운영 인수를 이어서 구현해야 한다. 단순 stdout 완료를 전달 영수증으로 저장하는 우회는 하지 않는다.

B7 대규모 100회 쓰기는 이번 관측 시점 **71회**까지 같은 실행으로 진행 중이다. SB 제품 SHA-256은
`387d6c7f5b9c1b9db98c31d53c224181757d4eddba5aaf8cfba0641176cb53c4`로 시작값과 일치한다.
대기 검색/복구 세 커밋은 이 실행이 terminal에 도달한 뒤 병합한다. B4 수집/범위·B5 세션·B6 운영·
B7 최종 인수/실제 질문·B8 품질을 포함한 전체 목표는 유지한다.
