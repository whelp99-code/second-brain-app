# P18 — 회사·개인 회상 분리와 AI 클라이언트 자동 문맥

명세 등록 / 구현·시험 NOT_RUN. Refs #3, #37. 선행 P09 #28, P10 #29. R2 (제안) / Core+Client+QA / 5~8인일 (추정이며 확정 일정 아님). 기준: 2026-09-23 계획 작업 28·30, 대조 문서 3절. 계획상 선행 작업 19(메일 개인·회사 분리), 25~27(P09 회상 보강), 29(P05 인용 ID)도 따른다.

## 목표
회사 기억과 개인 기억을 사용자가 고른 namespace로만 조회한다. 같은 질문이라도 source와 receipt가 섞이지 않는다. Claude, Codex, OMO, OpenCode, GJC가 실제로 문맥을 받는 경로를 matrix로 고정하고, 지원하지 않는 경로를 자동 연결로 광고하지 않는다.

SB2 P09는 개인 life 기억 회상만 다룬다. `sb-company` 수신·처리와 MCP 검색은 이미 있지만, 분리된 회사 조회와 클라이언트별 문맥 연결 측정은 없다. 이 묶음이 그 빈칸을 맡는다.

## 구현 체크리스트
- [ ] (계획 28) `sb-company`에 서명된 authorized query와 record 상태 조회 operation을 추가한다. 기존 authority 검증을 그대로 거친다.
- [ ] (계획 28) JARVIS namespace selector에서 회사/개인을 명시 선택으로만 연결한다. 선택이 없으면 조회하지 않는다.
- [ ] (계획 28) candidate/accepted/processed 상태와 verified business fact를 응답에서 구분한다. 후보를 확정 사실로 말하지 않는다.
- [ ] (계획 28) wrong workspace, stale deletion fence, unsigned request, 개인 DB 경로 지정은 fail closed로 내용 0건을 반환한다.
- [ ] (계획 30) Claude hook 경로와 Codex/OMO/OpenCode/GJC의 지원되는 MCP·시작 문맥 경로를 client matrix로 고정한다. 각 칸에 supported/unsupported와 근거를 남긴다.
- [ ] (계획 30) 한 세션에서 같은 근거를 두 번 주입하지 않는다. 빈 query나 무관한 query에는 문맥을 넣지 않는다.
- [ ] (계획 30) broken pipe나 잘린 출력은 delivered로 기록하지 않는다. stale generation과 empty search는 명시 상태로 돌려준다.
- [ ] (계획 30) gold 5 domain과 negative case를 독립 검증한 뒤 client별 설치된 surface에서 실행한다.

제외(계획 Must NOT do): 회사 결과를 개인 inbox나 개인 Vault에 저장하지 않는다. 회사+개인 전체 union 검색을 만들지 않는다. unsupported event를 자동 연결로 광고하지 않는다. 회사 DB와 원천 DB는 소유자 것이며 읽기 전용으로만 연다. 새 상주 queue/event bus를 두지 않으며 쓰기는 `sb.vault` 단일 writer를 유지한다. 인증 키와 토큰 값은 명세·fixture·로그에 적지 않는다.

## 코드·API
재사용: `sb/company_memory.py`(candidate/accepted/processed_complete 상태), `sb/company_memory_authority.py`(workspace·서명 검증), `sb/company_memory_cli.py`(`sb-company` 진입점, `pyproject.toml`), `sb/scoped_search.py`, `sb/scoped_read_policy.py`, `sb/scoped_surfaces.py`, `sb/mcp.py`, `sb/mcp_contract.py`, `sb/memory_access.py`, `sb/memory_records.py`, `sb/life_recall.py`, `sb/life_model_policy.py`, `sb/postcompact_hook.py`, `sb/cli.py`. 계약 문서는 `docs/core5/COMPANY-MEMORY-DONOR-CONTRACT.md`, `docs/core5/COMPANY-MEMORY-PRODUCT-DESIGN.md`. 시험은 `tests/test_company_memory_product.py`, `tests/test_postcompact_hook.py`, `scripts/korean-search-acceptance.py`, `tests/fixtures/korean_search_v1.json`, `tests/fixtures/korean_abstention_v1.json`.

신규 후보: `sb/company_recall.py`(namespace 고정 회사 조회), `sb/client_context_matrix.py`(client별 경로·상태 표), `tests/test_company_recall_scope.py`, `tests/test_client_context_matrix.py`, `tests/fixtures/client_context_gold_v1.json`. P09의 공개 `recall` 표면이 생기면 거기에 namespace 인자만 더하고 별도 검색 서버는 만들지 않는다.

## 인수시험
AC-05: 회사와 개인에 같은 이름·같은 문장이 있어도 namespace별 source/receipt가 독립이다. AC-09: 정정 뒤 회사·개인 회상과 hook 주입에 옛 사실이 없다. AC-10: 모델 timeout이나 잘못된 인용은 축소 상태로 표시한다. AC-11: 같은 세션 중복 주입 0건, generated와 delivered 분리. AC-12: 회사 수집 OFF와 조회 장애를 구분한다. AC-14: 과거 A/현재 B 결정을 client 문맥에서도 구분한다. AC-15: 범위 밖 제목·snippet·노드·모델 입력 누출 0건. AC-18: 삭제 fence가 지난 회사 기록은 복원 뒤에도 반환하지 않는다. AC-23: 근거 본문의 지시문이 client 명령으로 바뀌지 않는다. AC-24: 기존 `sb-company` receive와 MCP 검색 계약 회귀.

패키지 전용: cross-workspace, 개인 DB 경로, scope 혼합 요청에서 내용 0건. 빈/무관 query 주입 0건. broken output은 delivered 아님. 전체 Recall@5 90% 이상, domain별 85% 이상, 근거 없는 확정 답 0건. 새 agent session이 올바른 근거를 한 번만 받는지 client별로 확인한다.

## 적용·중단·완료
`company_recall`과 `client_context` flag는 따로 두고 기본 OFF다. 한 client, 한 workspace에서 시작한다. rollback은 두 flag를 끄는 것으로 끝나며 회사 DB, receipt, 삭제 fence, 기존 hook 동작은 그대로 둔다. 품질이 기준에 못 미치면 해당 client 칸을 unsupported로 되돌리고 그렇게 표시한다.

완료 증거는 client matrix 원본, client·코드 revision, 설치 surface별 실행 로그, gold/negative 결과표, fail-closed 응답 기록, 독립 검토다. 수치를 채워 넣거나 정답셋을 바꿔 통과시키지 않는다. 현 diff는 이 문서 1개이며 구현·시험 모두 NOT_RUN.
