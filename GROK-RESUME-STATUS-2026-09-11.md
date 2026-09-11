# Grok 재개 상태

시각: 2026-09-11. **status=running**

deny compile 로컬 페이지 수정 후 복원 dest `ingest`+`compile` EXIT 0, sealed 기본 검색 `wiki/inbox-…after-restore-d77cfc33`. 휠 `dc493f1`에는 아직 이 compile 변경이 없다.

2970cc3 이후 미완료 작업 재개, R4/R6/R7 원인 해결 진행.

`dc493f1`/`512a4c7` × JARVIS `6ce2356` 게이트 EXIT 0 증거는 보존. ready_for_final_review 아님. 전환·인증 복사·push 없음.

## 원인 (2970cc3 재개 시 원문)

복원 dest compile:
```
SB_CONFIG=/var/tmp/sb-dr-genlayout/config.toml TMPDIR=/var/tmp/sb-dr-genlayout
uv run python -c 'Config(raw=toml); run_compile(cfg, llm_mode="cli")'
```
결과: `exit_code=1` `errors=1` `pages=0` `failure="SecurityPolicyError: source inbox: LLM egress denied by source policy"` (`run_id=3d984b61e5e643e995fec7948d4de367`). config `llm_policy = "deny"`인데 compile이 LLM을 호출한다.

sealed 검색 0: `share/vault`는 generation.json이 있어 sealed FTS만 본다. 바늘은 `inbox/2026-09-11T070302501061-after-restore.md`에만 있다. wiki 컴파일 페이지가 없다. `scope=all` 1건은 generation.json을 지운 복사본에 wiki로 옮긴 뒤의 결과이며 sealed 기본 검색 성공이 아니다.
