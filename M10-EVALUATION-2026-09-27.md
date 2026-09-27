# M10 한글 검색 평가 (2026-09-27)

측정만 기록한다. 코드와 `IMPLEMENTATION-STATUS.md`는 수정하지 않았다.

## 실행

- HEAD: `2e9f2cd288511ec4f30f882763fbed9fa666b103` (branch `master`)
- 데이터셋: `M10-GOLD-CURATED-2026-09-15.json`
- 데이터셋 sha256: `e751ce6acf971fd5d46763edc9d8483c20532b39fc2784b7198b4d258b741c10`
- 문서 40 / 케이스 131 / limit 5 / `state: measured` / `completed_cases: 131`
- 증거 JSON의 `commit`, `dataset_sha256`은 위와 같다.
- `selected_record_checks`: 34
- `gold_answer_checks`: 26
- `sealed_files_unchanged`: true
- 운영 vault(`/home/jm/.local/share/second-brain`)는 사용하지 않았다. fixture는 `TMPDIR` 아래 `mkdtemp`였다.

`scripts/korean_search_evaluation.py`는 라이브러리 모듈이다. `docs/MANUAL.md` §12.2와 `M10-GOLD-CURATED-2026-09-15.md` §5가 지정한 실행 진입점은 `scripts/korean-search-acceptance.py`다. 그 스크립트 docstring의 `uv run` 형태를 썼다. `--hybrid`, `--min-similarity`는 문서가 실행하지 말라고 한 선택지라 주지 않았다.

```bash
cd /home/jm/orca/projects/second-brain-app
TMPDIR=/var/tmp/m10-eval-20260927-st01a0e292 uv run python scripts/korean-search-acceptance.py \
  --dataset M10-GOLD-CURATED-2026-09-15.json
```

- exit code: **0**
- stdout: `Evidence directory: /var/tmp/m10-eval-20260927-st01a0e292/sb-korean-search-d_yzr97l` 및 `Completed 20/131` … `Completed 120/131` (131은 20의 배수가 아니라 진행 줄이 없다). stderr 비어 있음.
- 원본 측정 JSON: `M10-EVALUATION-2026-09-27.json` (`evidence.json` 복사). 임시 디렉터리는 이 파일 작성 후 삭제했다.

## 측정값 (스크립트 `metrics` 그대로)

### overall

| 지표 | CLI | MCP |
|---|---|---|
| positive_cases | 115 | 115 |
| negative_cases | 16 | 16 |
| hit_at_1 | 0.20869565217391303 | 0.2 |
| recall_at_5 | 0.23478260869565218 | 0.22608695652173913 |
| mrr_at_5 | 0.2217391304347826 | 0.21304347826086956 |
| negative_empty_rate | 1.0 | 1.0 |
| forbidden_labeled_cases | 2 | 2 |
| forbidden_exposure_at_5 | 0.0 | 0.0 |

### by_kind recall_at_5 (CLI / MCP)

| kind | positive / negative | CLI recall_at_5 | MCP recall_at_5 |
|---|---|---|---|
| exact_phrase | 9 / 0 | 0.6666666666666666 | 0.6666666666666666 |
| keyword | 23 / 0 | 0.8260869565217391 | 0.782608695652174 |
| reordered_terms | 2 / 0 | 1.0 | 1.0 |
| natural_question | 66 / 0 | 0.0 | 0.0 |
| paraphrase | 13 / 0 | 0.0 | 0.0 |
| stale_decision | 2 / 0 | 0.0 | 0.0 |
| no_answer | 0 / 16 | (negative_empty_rate 1.0) | (negative_empty_rate 1.0) |

keyword hit_at_1 / mrr_at_5: CLI 0.6956521739130435 / 0.7608695652173914, MCP 0.6521739130434783 / 0.717391304347826.
exact_phrase·reordered_terms는 hit_at_1 = recall_at_5 = mrr_at_5.
natural_question·paraphrase·stale_decision은 hit_at_1 = recall_at_5 = mrr_at_5 = 0.0.
stale_decision forbidden_exposure_at_5 = 0.0 (양쪽).

### 지연 (진단용, 게이트 아님)

| 구간 | count | p50_ms | p95_ms | max_ms |
|---|---|---|---|---|
| cli_search | 131 | 289.15979200974107 | 326.0792111977935 | 472.76208689436316 |
| mcp_search | 131 | 47.00449202209711 | 70.19013864919543 | 135.79545775428414 |
| mcp_read | 34 | 44.684331864118576 | 66.03198917582631 | 87.13772473856807 |

## 문서 수치와 비교

하네스는 품질 미스를 실패로 보지 않는다 (`Quality misses are measurements`). 숫자 하한 게이트는 `korean-search-acceptance.py`와 MANUAL §12에 없다. exit 0은 전송·증거·fixture 오류가 없었다는 뜻이다.

아래 pass/fail은 **보고된 숫자와 이번 측정이 같은지**만 뜻한다. 반올림 4자리 일치는 별도 열.

### §3.1 (사용자 검토 전 격리 fixture, 앱 커밋 `a5c4159`)

| 지표 | §3.1 CLI | 이번 CLI | 일치 | §3.1 MCP | 이번 MCP | 일치 |
|---|---|---|---|---|---|---|
| hit_at_1 | 0.22608695652173913 | 0.20869565217391303 | fail | 0.21739130434782608 | 0.2 | fail |
| recall_at_5 | 0.22608695652173913 | 0.23478260869565218 | fail | 0.21739130434782608 | 0.22608695652173913 | fail |
| mrr_at_5 | 0.22608695652173913 | 0.2217391304347826 | fail | 0.21739130434782608 | 0.21304347826086956 | fail |
| negative_empty_rate | 1.0 | 1.0 | pass | 1.0 | 1.0 | pass |
| forbidden_exposure_at_5 | 0.0 | 0.0 | pass | 0.0 | 0.0 | pass |
| exact_phrase recall_at_5 | 0.6666666666666666 | 0.6666666666666666 | pass | 0.6666666666666666 | 0.6666666666666666 | pass |
| keyword recall_at_5 | 0.782608695652174 | 0.8260869565217391 | fail | 0.7391304347826086 | 0.782608695652174 | fail |
| reordered_terms recall_at_5 | 1.0 | 1.0 | pass | 1.0 | 1.0 | pass |
| natural_question recall_at_5 | 0.0 | 0.0 | pass | 0.0 | 0.0 | pass |
| paraphrase recall_at_5 | 0.0 | 0.0 | pass | 0.0 | 0.0 | pass |
| stale_decision recall_at_5 | 0.0 | 0.0 | pass | 0.0 | 0.0 | pass |

§3.1과 overall hit/recall/MRR, keyword recall이 다르다. 데이터셋 JSON `status`는 검토 후 `user_reviewed`다. §3.1은 검토 전 측정이다.

### §7 재평가 (검토 후, 같은 파일의 나중 표)

보고값은 소수 4자리. 이번 값을 같은 자리로 반올림하면 전부 같다.

| 표면 | 지표 | §7 | 이번 | 4자리 일치 |
|---|---|---|---|---|
| CLI | hit@1 | 0.2087 | 0.20869565217391303 | pass |
| CLI | recall@5 | 0.2348 | 0.23478260869565218 | pass |
| CLI | MRR@5 | 0.2217 | 0.2217391304347826 | pass |
| CLI | negative_empty | 1.0 | 1.0 | pass |
| CLI | forbidden_exposure@5 | 0.0 | 0.0 | pass |
| MCP | hit@1 | 0.2000 | 0.2 | pass |
| MCP | recall@5 | 0.2261 | 0.22608695652173913 | pass |
| MCP | MRR@5 | 0.2130 | 0.21304347826086956 | pass |
| MCP | negative_empty | 1.0 | 1.0 | pass |
| MCP | forbidden_exposure@5 | 0.0 | 0.0 | pass |

운영 릴리스 프로브(§3.2, §7 마지막 행)는 실행하지 않았다. 그 프로브는 운영 CLI를 호출하고 요청 저널 mtime을 바꾼다고 §6.6이 적는다.
