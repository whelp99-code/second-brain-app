# 고정 제출 a47f2a9 독립 검토 (Claude 야간)

작성자: **Claude Fable 5.1 야간 세션**. 2026-09-13T12:56:35.179488+00:00.

**판정: 미인수.** 핵심 결함 B5: hook의 질의 선택이 all-terms(AND)라서 실제 다중 단어 compaction 요약·사용자 프롬프트에서는 record가 하나도 선택되지 않아 **실세션 기준 M9 hook 경로 전체가 no_data**다. 이는 PostCompact 도입 시점부터의 결함이며 이전 후보 a41b70d에서도 동일 재현했다(이전 검토들은 단일 단어 fixture만 사용). B2b: in-turn 제외 집합이 세션 내 누적돼 두 번째 compaction부터 재주입되지 않는다. 문서 잔여 D2/D3/constraint.

## 고정과 바이트
- 제출 `a47f2a9`, 제품 `5680155`, 후보 `/var/tmp/sb-candidate-5680155/releases/64274fd223c84bde58cde3c9029d3515062e4a40` wheel `c79ebc0bbd5c0dbb2ed158c59d21f265c57bf1fc450755942100371e22c7223c`. source/wheel/installed **183 파일 일치**. 원본 `/var/tmp/claude-night-e53dd66-GBr0la`.
- 직접 실행: pytest hook 파일 **21 passed / 1.57s EXIT0**, Ruff EXIT0, basedpyright 0 errors / 13 warnings / EXIT1. 합성 probe 17 assertion 중 10 통과 / 7 실패 (`inturn-probe-5680155.json`; 기준선 `inturn-probe-baseline-a41b70d.json`).

## 통과 범위
- a47f2a9 archive: source/wheel/installed 183 files identical; manifest source_commit 5680155; wheel sha matches
- documented SessionStart(compact) input without summary no longer exits 2; missing last_query -> {} exit 0; source!=compact -> {} exit 0 (probe s0,s2 pass)
- PostCompact excludes in-turn delivered record_id+version within an epoch (probe s7 pass)
- UserPromptSubmit records bounded last_query; D1 fixed (SB_CONFIG row removed, config.py:184-192 order, absolute path); not_complete keeps M9_native_session
- 21 hook tests, Ruff clean

## 잔여 — 한 번의 통합 후속

### B5 (blocking) — `sb/postcompact_hook.py select_search_query + _serialize/_matching_records; sb/search_query.py LexicalQuery.matches_record (all-terms by design)`
select_search_query keeps up to 32 whitespace tokens of the summary/prompt and the hook then requires EVERY token to appear in a record (index predicate AND + matches_record all()). Frozen candidate: PostCompact compact_summary 'Session summary: the user asked about OmegaInturnTarget in the notes and we reviewed it; next step is to continue the write-up.' -> stage empty, next UserPromptSubmit {} (r1/r2). UserPromptSubmit prompt 'Can you remind me what the notes say about OmegaInturnTarget before I continue?' then SessionStart(compact) -> {} (r3/r4). Even 'OmegaInturnTarget please' -> {} (s3). Unit tests pass only because fixtures use single-token or repeated-token summaries (e.g. 'OmegaCompiledBody '*400 dedupes to one group). Same result on prior candidate a41b70d. Effective real-session behaviour of the whole M9 hook path is no_data.

**완료조건:** Hook-level selection must tolerate natural text without changing the sb search contract: e.g. derive candidate terms (drop very short/stop tokens, keep bounded count), search per term or per small term group, aggregate records by number of matched terms then engine relevance, bounded by MAX_ITEMS/budget; keep record identity/version/source_ref/dedupe/budget. Tests and probes must use multi-word summaries and prompts (assertions r1-r4, s3 in probe-inturn.py).

### B2b (blocking) — `sb/postcompact_hook.py confirm_delivery/_write_stage delivered_in_turn`
delivered_in_turn is carried forward on every stage write and appended on every confirm; it is never reset. After a later compaction the same still-relevant record is excluded forever in the session, so SessionStart(compact) #2 and its PostCompact inject nothing (probe s8 -> {} with last_query present; also depends on B5).

**완료조건:** Scope the exclusion set to one compaction epoch: SessionStart(compact) starts a new epoch (delivered_in_turn := records delivered now, not prior+now); PostCompact of that epoch excludes only that set; UserPromptSubmit confirm may add within the epoch. Probe: second_compaction_new_epoch_reinjects_last_query.

### A-D2 (ordinary) — `GROK-CURRENT-OPERATIONS-REVIEW-2026-09-13.md:55-56`
ops review :55-56 still lists states keys gjc_runtime/gjc_intents/gjc_intent_leases/gjc_microloop_leases and counts unexpired_lease_rows/invalid_lease_rows which do not exist in deploy/check-jarvis-pending-state.py (STATES: memory_outbox, memory_outbox_attempts, memory_candidate_dispatch_publications, collaboration_bridge_outbox, pre_gjc_report_outbox, outbox; COUNTS: cursor_rows, active_cursor_rows, gjc_lease_rows, microloop_lease_rows; leases: gjc_runtime_leases, microloop_leases with unexpired/expired/invalid)

**완료조건:** replace with real keys; state/outcome value classification rule; {table: []} vs count>0

### A-D3 (ordinary) — `GROK-CURRENT-OPERATIONS-REVIEW-2026-09-13.md:68-72`
slots RESTORED_ROOT/VERIFY_CONFIG present; VERIFY_STATE_ROOT/VERIFY_REQUEST_ROOT/VERIFY_QUERY missing; mapping table vault_root->RESTORED_ROOT, state_root/request_root->independent slots missing

**완료조건:** add the three slots and mapping table; keep doctor/search examples

### B4-doc (ordinary) — `GROK-M9-SESSION-COMPACTION-CONSTRAINT-2026-09-13.md`
GROK-M9-SESSION-COMPACTION-CONSTRAINT: JARVIS consumer (JARVIS_MODEL_TRANSPORT_CMD exit0 accepted; FileModelTransport not consumer), event digest lifetime, and stdout-failure/no-ACK sections were deleted although still true; PostCompact additionalContext-ignored fact and prompt-based query limitation (summary reselection lands at next prompt) not stated; SessionStart registration example lacks matcher compact

**완료조건:** restore the three sections; add the two facts; add matcher

## 재검증
`/var/tmp/claude-night-e53dd66-GBr0la/probe-inturn.py <bin/sb>` 17 assertion 전부 통과, `check-docs.py` 10 통과, hook pytest/Ruff/타입. 검색 계약(`sb search`, MCP `sb_search`)의 all-terms 의미는 바꾸지 않는다(M7 일관성). native 로그인 세션·운영 전환·보류 분기 재시도 없음.
