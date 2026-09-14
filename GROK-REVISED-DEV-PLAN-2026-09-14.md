# 잔여 작업 계획 — 2026-09-14 개정

Composer 2.5 적대검증(`COMPOSER-ADVERSARIAL-REVIEW-2026-09-14.md`)과 Grok 원 리스트를 대조한 뒤 **채택한 것만** 남긴다. 원 A–F/M1–M14는 축소하지 않는다. 제품 인수 ≠ 이 문서.

**핀:** SB HEAD `9d2041f` / 제품 `8d1f8cc` / 후보 `2ccf0267…` / JARVIS `64715ba` / 운영 SB `41f0751` / 운영 J `a3cbbbe`.  
**역할:** Grok = 구현·현재핀 자체검증·제출. Codex/Claude = 고정 후보 **1회** 전체 검증. 중간 리뷰 루프 없음.  
**상시 금지(작업 항목 아님):** 전환, auth/config 복사, 실사용자 삭제, 신규 push. `2n`/`phone-history/`/`.bak` 보존. M9 SB Claude 훅 재구현 금지.

---

## 0. 분류 규칙

| 버킷 | 뜻 |
|---|---|
| **코드** | 현재 소스에 원 계약이 없거나, 현재 후보에서 재실행이 실패하면 고친다 |
| **현재핀 재증명** | 구현은 있음. `8d1f8cc`×`64715ba`에서 다시 돌려 로그만 새로 남긴다. 옛 핀 승계 금지 |
| **문서/제출** | 패키지·상태표·지원표 핀을 현재 바이트에 맞춘다 |
| **blocked_deferred** | 목표에 남긴다. 이번 라운드 실행·이전 금지 |
| **blocked_external** | 사용자 입력/허가 전 시작하지 않는다 |

---

## 1. 코드 (실패가 확인된 것만)

1. **JARVIS artifact hygiene** — `/var/tmp/jarvis-artifact-64715ba/runtime` → `78e7307/runtime`. 64715ba 바이트와 다시 맞춘다. 게이트 전.
2. **N1 JARVIS 공개 경로** — `cli-gjc-commands.ts`는 compaction 이벤트 없음(355–357), 기본 `RecordingModelTransport`(378). Claude 훅으로 대체 금지. 공개 dispatch에 실제 consumer transport + per-attempt `known_not_sent` / explicit negative / unknown이 **64715ba에 없으면** 구현. 있으면 재증명만.
3. **Cursor 인계 §10 네 결손** — 반례가 현재 코드에서 살아 있으면 수정. 이미 막혀 있으면 현재핀 테스트 1회만.  
   - OpenCode DB descriptor 교체  
   - inbox `stat→unlink`  
   - 프로세스 RSS ≠ 스냅샷 한도(한도 상향 금지, 측정)  
   - source-id/cursor 마이그레이션 × 삭제 정책
4. **타입** — 변경 파일 basedpyright **error 0**. 기존 24 warning을 일괄 청소하지 않는다. EXIT1은 제출물에 한계로 적는다.

**A managed compile은 코드 1순위가 아니다.** `test_managed_compile_keeps_uncommitted_human_edit`가 `USER_EDIT_KEEP_THIS`를 이미 단언한다. Composer의 6FB150B 인용은 STALE. 현재 후보에서 그 테스트가 실패할 때만 코드.

---

## 2. 현재핀 재증명 (`f7c1945`/`e13cd3b`/`1672626`/`harness-36`/`7d97af7` 승계 금지)

실패하면 §1로 올린다. 통과하면 새 로그·JSON만 제출물에 연결한다.

| 순서 | 항목 | 한 줄 |
|---|---|---|
| R1 | **A** | 후보 CLI로 managed compile 보존/무수정 정정/중단 재시작 |
| R2 | **B** | 철회 store 유실·symlink·복원 후 fresh stdio 2개. 보류 수명 분기는 실행하지 않음 |
| R3 | **M6** | 이전 writer 실배제 + 실패 cutover 복구. 큐0 ≠ 배제 |
| R4 | **M12** | cold 원본, provider/control 유실, `init_vault` legacy, 같은 런타임 복원→scoped→high-water→재유입 차단→새 쓰기, RPO/RTO |
| R5 | **M7** | CLI/MCP/web/scoped에서 제목·snippet·score·원문·벡터·관계 불허 0 |
| R6 | **M11** | pinned-read 중 publish + 현재 후보 MCP p50/p95/RSS |
| R7 | **M13** | 격리 브라우저 실패→수정→성공, 정정/삭제/원문/영수증. 삭제경합은 deferred |
| R8 | **3게이트** | `prepare-release`(바이트 불일치일 때만) + maintenance/integration/`--work` **새 로그**. 개발 아님 |

---

## 3. 문서 / 제출 (최종 검증 요청 조건)

1. `GROK-FINAL-ACCEPTANCE-PACKAGE.md/.json`을 `8d1f8cc` × `64715ba` × `9d2041f`로 재작성.
2. `IMPLEMENTATION-STATUS` 상단 표를 같은 핀으로. F행의 `e13cd3b`/`f7c1945`를 현재와 섞지 않음.
3. `GROK-CLIENT-CONNECTION-READINESS` 핀을 8d1f8cc / Claude **2.1.270**으로 갱신. 수집기 ≠ 주입기. 없는 이벤트는 미지원.
4. M9 JARVIS: “compaction 이벤트 없음”을 문서+회귀로 고정. 허구 이벤트 없음.
5. M5: 관리 사본 vs 클라이언트 소유 한계 표. 빈 HOME ≠ 미지원.
6. M2/M4: 기존 REAL-WORK 계보로 **증거 항목표**만 준비. 합성 업무를 사용자 업무로 바꾸지 않음.
7. A–F/M1–M14를 `verified` / `implemented_unverified` / `blocked_external` / `blocked_deferred` / `not_implemented`로만.

---

## 4. 목표에 남기고 이번엔 안 함

| ID | 상태 | 이유 |
|---|---|---|
| M3 열린연결·옛설정/백업 수명, 보안경계, symlink/FIFO, 삭제경합, 삭제전 백업 | `blocked_deferred` | 실행 보류. 목표 삭제 아님. 재시도·이전 금지 |
| M1 운영 로그인 | `blocked_external` | 실세션 |
| M2/M4 실사용자 1건 | `blocked_external` | task ID 또는 원문 경로 |
| M10 | `blocked_external` | 한글 100–300 + 근거 |
| F/M6 운영 전환 | `blocked_external` | 중단·writer 배제 허가 |
| M9 native `/compact` | `blocked_external` | 절차는 `/var/tmp/sb-native-probe-8d1f8cc` |
| M5/M13 실사용자 처분 | `blocked_external` | 대상+허가 |
| M14 | `not_implemented` | 고정 질문 비용 측정만. 새 그래프 없음. 핵심 다음 |

---

## 5. 실행 순서 (사용자 입력 없이)

1. JARVIS runtime 정합 → (필요 시) N1/§10 소스 확인 후 좁게 수정  
2. R1–R8 현재핀 재증명, 실패만 코드  
3. §3 제출물  
4. Codex/Claude 최종 검증 요청  

원 핸드오프의 M1/M2 우선은 **입력이 오는 즉시** R 시퀀스보다 앞선다. 입력이 없으면 기다리지 않고 1–4를 한다.

M9 SB Claude 훅, 옛 게이트 로그 이름 바꾸기, 6FB150B를 현재 A 버그로 재구현, Composer 재검증 루프 — 하지 않음.
