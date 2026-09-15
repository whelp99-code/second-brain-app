# M10 한글 검색 평가셋 — Claude 큐레이션본 (2026-09-15)

**상태: CLAUDE-CURATED — 사용자 승인 전.** `M10-GOLD-DRAFT-2026-09-15.json`을 리뷰어 관점에서 검토·수정한 결과가
`M10-GOLD-CURATED-2026-09-15.json`이다. `dataset_origin`은 스키마 enum(`synthetic`|`user_curated`)상
정직한 값인 `synthetic`을 유지했고, 최상위에 다음을 달았다.

```
"curation_note": "Claude-curated from real vault excerpts 2026-09-15; not user-curated"
```

모든 case에는 `"curation": "claude_curated"`가 있다.

## 1. 출처와 읽기 범위

- 세대 심링크: `/home/jm/.local/share/second-brain/vault` (읽기 전용)
- 데이터셋 작성 시점의 해석 결과: `sbgen:v1:d55ac3acaef3795c08448749437c9509cd4bb208aad5785356156c82dd86efe8`
- 읽은 범위: `wiki/`, `wiki/_proposed/`, `daily/`만. `raw/`, `inbox/`, `conflicts/`는 읽지 않았다.
- 자격증명·키·토큰은 포함하지 않았다. `[REDACTED_EMAIL]`은 원본 페이지에 이미 마스킹돼 있고,
  `postgresql://unified:unified@localhost:5433/unified`는 프로젝트 문서에 이미 공개된 로컬 개발용 문자열이다
  (그래도 빼고 싶으면 `wiki/me-projects-unified-db`, `wiki/me-projects-blro-os` 본문에서 해당 문장만 제거하면 된다).

## 2. 초안 대비 변경 (counts)

### 문서

| 항목 | 초안 | 큐레이션본 |
|---|---|---|
| documents | 41 | 40 |
| gold | 36 | 34 |
| distractor | 5 | 6 |

- **삭제 1건**: `wiki/inbox-ops-contract-summary`. 원본 페이지
  `inbox-2026-09-09t130927692351-…-7c4748df.md`가 현재 세대에 더 이상 존재하지 않는다. 이 페이지를 쓰던 case 3건
  (`fact-018`, `proc-017`, `cmp-011`)은 같은 내용을 담은 계약 전문 페이지 `wiki/inbox-ops-contract-full`로 옮겼다.
- **역할 변경 1건**: `wiki/me-index`를 gold → **distractor**로 바꿨다. 이 페이지를 정답으로 쓰는 case가 없었고,
  주제가 다른 gold 페이지와 겹쳐 실질적인 오답 유인 역할이 더 적절하다. 초안의 약점(“distractor가 전부 빈 템플릿”)을
  일부 보완한다.
- **본문 40건 전부 재작성.** 두 가지 이유다.
  1. **정본성**: 초안 본문 중 61개 줄이 실제 페이지 문장과 일치하지 않았다(요약·재작성). 큐레이션본은 현재 세대
     페이지에서 **문장을 그대로 복사**하고 각주 마커·마크다운 장식만 제거했다.
  2. **하네스 제약**: `korean-search-acceptance.py`는 각 fixture 페이지 본문 끝에 각주 마커 하나만 붙인다.
     `sb/memory_records.py`의 레코드 분할 규칙상 이때 생성되는 레코드는 **본문의 마지막 줄 하나뿐**이다.
     초안처럼 본문이 여러 줄이면 (a) 검색이 마지막 줄만 매칭하고 (b) gold 페이지가 회수될 경우
     `answer_span`이 레코드에 없다며 실행 전체가 `ValueError: gold answer absent from selected record`로 죽는다.
     그래서 모든 본문을 **한 줄**(문장들을 공백으로 이은 발췌문)로 만들었다. 최대 815자 / 1,536바이트.

### 케이스

| 분류 | 초안 | 큐레이션본 | 신규 | 그대로 유지 | 수정 |
|---|---|---|---|---|---|
| fact (사실 확인) | 21 | 26 | 5 | 2 | 19 |
| date (날짜·일정) | 21 | 22 | 1 | 1 | 20 |
| decision (결정 사유) | 21 | 22 | 1 | 0 | 21 |
| procedure (절차·명령) | 21 | 24 | 3 | 2 | 19 |
| comparison (비교) | 21 | 21 | 0 | 0 | 21 |
| no_data (정답 없음) | 15 | 16 | 1 | 3 | 12 |
| **합계** | **120** | **131** | **11** | **8** | **112** |

- 정답 있는 case **115건**, `no_answer` **16건** (요구 최소치 100 + 10 충족).
- **case ID 삭제는 0건**이지만, 질문이 근거와 맞지 않던 **10건은 사실상 폐기·교체**했다(같은 ID에 새 질문).
  해당 case에는 `curation_note`를 달았다: `dec-009`, `dec-014`, `dec-018`, `dec-019`, `dec-020`, `dec-021`,
  `date-010`, `date-018`, `cmp-015`, `cmp-017`.
  가장 흔한 패턴은 **문서에 없는 “이유”를 묻고 근거 문장은 절차·정의를 가리키는 경우**였다(초안 `dec-018`~`dec-021`).
  이런 질문은 “정답이 있다”고 표시된 채로는 영원히 틀리므로, 문서가 실제로 답하는 형태로 질문을 바꿨다.
- 초안의 애매한 다문서 추론 case 3건(초안 `cmp-015` agentgauge vs jarvis-ai, `cmp-017` 09-10 vs 09-11 조건 충족,
  `cmp-019` 점수 9·6·9·7·6의 항목명)은 **근거가 한 페이지에 없어 폐기**하고 다른 질문으로 대체했다.
- 초안 `neg-009`(“이모지 허용 예외가 있나요?”)는 문서가 “이모지는 쓰지 않는다”로 사실상 답하므로
  `no_answer`로 부적절하다고 보아 폐기하고, 검증된 부재 주제 2건(사업자등록번호, Postgres 이미지 태그)으로 대체했다.
- `no_answer` 16건은 전부 현재 세대 `wiki/`+`daily/` 전문 검색으로 부재를 확인했다
  (`매출액`, `헬스장`, `사업자등록`, `출시일`, `백업 주기`, `이미지`, `디자이너`, `버전 번호` 모두 0건;
  `파트너사`는 가격 원칙의 상대 유형으로만 등장하고 회사 목록은 없다).

### expected_page_ids 확장 (임의 축소 금지 규칙 적용)

근접 중복 로그가 여러 개인 주제는 정당하게 답하는 페이지를 **모두** 정답으로 넣었다. 5건이다.

| case | 정답 페이지 수 | 페이지 |
|---|---|---|
| `proc-013` Windows 카톡 작업 순서 | 2 | `inbox-kakao-order`, `daily-2026-09-10` |
| `cmp-017` seven_day_complete 상태 | 3 | `morning-afternoon-hold`, `evening-collab`, `hold-2130` |
| `cmp-018` 15:12 일에이엔 혼입 발송 | 4 | 위 3건 + `daily-2026-09-11` |
| `cmp-019` 윤비서 세 루틴 마지막 실행 | 2 | `evening-collab`, `hold-2130` |
| `cmp-020` mail-unread-event 마지막 실행 | 2 | `mail-tick-0043`, `mail-tick-0126` |

**확장이 5건에 그친 이유(중요).** 하네스는 회수된 gold 페이지마다
`answer_span`이 그 페이지의 레코드 본문에 있어야 한다고 강제한다. 즉 정답 페이지를 여러 개 두려면
**모든 정답 페이지에 똑같은 문자열이 그대로 들어 있어야** 한다. 예컨대 “7일 홀드 시작 시각”은
`inbox-hold-launchagent`(“홀드 시작은 2026-09-11 00:00이다.”)와 `inbox-hold-matrix`
(“…2026-09-11 00:00 KST부터 true이며…”)가 둘 다 답하지만 공통 부분 문자열이 없어 확장할 수 없었다.
이건 스키마의 제약이지 판단상 축소가 아니다.
또한 `recall_at_5`는 **top-5 안에 든 gold 비율**이라, 확장한 case는 상한이 구조적으로 낮아진다
(`cmp-018`은 5칸 중 4칸을 요구한다). 아래 수치를 읽을 때 감안해야 한다.

## 3. 평가 결과

`korean_search_evaluation.py`는 라이브러리 모듈이라 `--help`가 아무것도 출력하지 않는다(CLI 진입점 없음, exit 0).
실행 진입점은 `scripts/korean-search-acceptance.py`이며, 이 도구가 데이터셋의 `documents`로 **격리된 fixture vault와
레지스트리를 `mkdtemp`로 새로 만들어** CLI(`python -m sb.cli search`)와 stdio MCP(`sb_search`/`sb_read_page`) 두
표면을 동시에 측정한다. 운영 vault·레지스트리는 건드리지 않는다.

### 3.1 격리 fixture 실행 (기본 측정)

- 데이터셋 sha256 `7b159a77…`, 앱 커밋 `a5c4159`, 문서 40 / 케이스 131, limit 5, 전 케이스 완료(`state: measured`).
- 증거 디렉터리 `/var/tmp/sb-korean-search-bvl8s2vj` → 요약 JSON
  `/var/tmp/claude-night-e53dd66-GBr0la/m10/eval-curated.json`

**overall (스크립트가 보고한 그대로)**

| 지표 | CLI | MCP |
|---|---|---|
| positive_cases | 115 | 115 |
| negative_cases | 16 | 16 |
| hit_at_1 | 0.22608695652173913 | 0.21739130434782608 |
| recall_at_5 | 0.22608695652173913 | 0.21739130434782608 |
| mrr_at_5 | 0.22608695652173913 | 0.21739130434782608 |
| negative_empty_rate (no_answer 정밀도) | 1.0 | 1.0 |
| forbidden_labeled_cases | 2 | 2 |
| forbidden_exposure_at_5 | 0.0 | 0.0 |

**by_kind (CLI / MCP의 recall_at_5)**

| kind | 건수 | CLI | MCP |
|---|---|---|---|
| exact_phrase | 9 | 0.6666666666666666 | 0.6666666666666666 |
| keyword | 23 | 0.782608695652174 | 0.7391304347826086 |
| reordered_terms | 2 | 1.0 | 1.0 |
| natural_question | 66 | **0.0** | **0.0** |
| paraphrase | 13 | **0.0** | **0.0** |
| stale_decision | 2 | 0.0 | 0.0 |
| no_answer | 16 | (negative_empty_rate 1.0) | (negative_empty_rate 1.0) |

지연(진단용): CLI search p50 270.5ms / p95 286.7ms, MCP search p50 42.0ms / p95 55.1ms.
`selected_record_checks` 32, `gold_answer_checks` 29, `sealed_files_unchanged` true.

### 3.2 운영 릴리스 CLI 대상 읽기 전용 프로브 (보조 측정)

같은 131개 질의를 운영 릴리스 바이너리
`~/.local/state/second-brain/app/current/bin/sb search … --json --limit 5`(릴리스
`8ea65a7d968fdcf99560f449b2a1ad656a99a2e9`)로 실행하고, `documents_origin_map`의 슬러그를 각 원본 파일의
프론트매터 `id`로 되돌려 같은 `summarize()`로 채점했다. 실패·오류 0건. 결과
`/var/tmp/claude-night-e53dd66-GBr0la/m10/eval-ops-live.json`.

| 지표 | 값 |
|---|---|
| positive_cases / negative_cases | 115 / 16 |
| hit_at_1 | 0.20869565217391303 |
| recall_at_5 | 0.24130434782608695 |
| mrr_at_5 | 0.222463768115942 |
| negative_empty_rate | 1.0 |
| forbidden_exposure_at_5 | 0.0 |
| exact_phrase / keyword recall@5 | 0.7777777777777778 / 0.8152173913043478 |
| natural_question / paraphrase recall@5 | 0.0 / 0.0 |

격리 fixture(40개 발췌 페이지)와 운영 인덱스(현재 세대 전체)가 **거의 같은 수치**를 낸다.
즉 이 데이터셋의 결론은 fixture 축소 때문에 생긴 것이 아니다.

### 3.3 읽어야 할 결론

- **자연어 질문·패러프레이즈 회수율이 정확히 0이다(79건).** `sb/search_query.py`의 매칭은 질의를 공백으로 쪼갠
  뒤 **모든 토큰이 문서에 그대로(공백 무시, casefold) 들어 있어야** 하는 AND 부분 문자열 방식이다.
  한국어는 조사·어미가 붙으므로 “`unified-db의`”, “`며칠인가요?`” 같은 토큰이 문서에 그대로 있을 수 없다.
  형태소 분석·n-gram·의미 검색 중 하나가 없으면 이 79건은 데이터셋을 어떻게 고쳐도 0이다.
- **키워드/정확 구절은 0.67–0.82로 이미 쓸 만하다.** 문제는 매칭 엔진의 질의 정규화이지 색인 자체가 아니다.
- **no_answer 정밀도 1.0, forbidden 노출 0.0.** 없는 것을 지어내지 않고, stale로 지정한 페이지도 top-5에
  올리지 않았다. 다만 `stale_decision` 2건은 **정답 페이지도 못 찾았으므로**(recall 0.0) 이 0.0은
  “잘 배제했다”기보다 “둘 다 안 나왔다”에 가깝다. 과대 해석 금지.
- 격리 실행에서 `hit_at_1 == recall_at_5 == mrr_at_5`인 것은 우연이 아니다. 맞힌 case는 전부 1위로 맞혔고,
  1위에 없으면 2–5위에도 없었다.

## 4. 사용자가 다시 봐야 할 가장 약한 10건

| # | case | 무엇이 미심쩍은가 |
|---|---|---|
| 1 | `dec-007` | `wiki/inbox-release-verification`을 `forbidden`으로 지정했다. 정정 전 판단이라 배제한다는 뜻인데, 이력 추적용으로는 검색에 나와도 되는 문서일 수 있다. 정책 판단이 필요하다. |
| 2 | `cmp-006` | 같은 forbidden 판단의 두 번째 사례. 게다가 질문이 “어느 쪽이 최신 판단인가”라는 **메타 질문**이라 실사용 질의로는 부자연스러울 수 있다. |
| 3 | `cmp-018` | 정답 페이지 4개. top-5 중 4칸을 요구해 `recall_at_5` 상한이 구조적으로 불리하다. 4개를 다 인정하는 게 맞는지 확인 필요. |
| 4 | `cmp-017` | 정답 페이지 3개(같은 이유). |
| 5 | `cmp-019` | 정답 2개인데 `answer_span`이 `09:05:47`이라는 짧은 시각 문자열이다. 우연 일치 위험이 있다. |
| 6 | `cmp-020` | 정답 2개, `answer_span`이 “메일 봇 mail-unread-event의 마지막 실행은”으로 **문장 중간에서 끊긴다**(두 페이지에 공통으로 존재하는 최장 문자열이라 불가피했다). |
| 7 | `date-018` | 질의어(`브리핑 회귀 1,785 passed 2 skipped`)의 숫자가 정답 문서(09-10 브리핑) 본문에 없다. 회귀 수치는 `inbox-release-verification`에만 있다. 질의를 브리핑용으로 바꾸거나 정답 페이지를 바꿔야 할 수 있다. |
| 8 | `cmp-009` | “실행 간격이 얼마나 들쭉날쭉했나”의 근거가 “85·59·43분으로 불규칙하다” 한 문장이다. 검색이 아니라 독해를 평가하는 쪽에 가깝다. |
| 9 | `cmp-013` | “어떤 보고가 24시간을 넘겼나”의 근거 문장에 세 값이 모두 들어 있어, 답을 고르는 추론이 필요하다. |
| 10 | `neg-009` | “T3로 분류된 실제 파일 목록”. 목록이 없는 건 맞지만, T3는 애초에 어떤 에이전트도 읽지 않는 등급이라 “검색이 비어야 정상”인 것이 정답 부재 때문인지 정책 때문인지 모호하다. |

추가로, 내가 질문을 바꾼 `dec-018`·`dec-019`·`dec-020`·`dec-021` 4건은 원래 사용자가 의도한 질문이 따로 있었을 수
있다(초안은 모두 문서에 없는 “이유”를 묻고 있었다). 의도가 있었다면 해당 근거를 vault에 먼저 추가하는 편이 맞다.

## 5. 정확한 재현 명령

```bash
# (1) 큐레이션본 생성 — 운영 vault를 읽기 전용으로 읽어 본문을 원문 그대로 다시 채운다
cd /home/jm/orca/projects/second-brain-app
TMPDIR=/var/tmp .venv/bin/python /var/tmp/claude-night-e53dd66-GBr0la/m10/build.py

# (2) 스키마 검증
cd /home/jm/orca/projects/second-brain-app
TMPDIR=/var/tmp PYTHONPATH=scripts .venv/bin/python -c \
  "import json;from korean_search_evaluation import load_dataset;print(load_dataset(json.load(open('M10-GOLD-CURATED-2026-09-15.json'))).id)"

# (3) CLI 확인 — 이 모듈은 라이브러리라 --help가 비어 있다(정상, exit 0)
cd /home/jm/orca/projects/second-brain-app
TMPDIR=/var/tmp .venv/bin/python scripts/korean_search_evaluation.py --help
TMPDIR=/var/tmp .venv/bin/python scripts/korean-search-acceptance.py --help

# (4) 본 평가 — 격리 fixture vault를 mkdtemp로 새로 만들어 CLI/MCP 두 표면을 측정
cd /home/jm/orca/projects/second-brain-app
TMPDIR=/var/tmp .venv/bin/python scripts/korean-search-acceptance.py \
  --dataset M10-GOLD-CURATED-2026-09-15.json
# 증거: /var/tmp/sb-korean-search-bvl8s2vj/{evidence,dataset}.json, cli.jsonl, mcp.jsonl, rankings.jsonl
# 요약 사본: /var/tmp/claude-night-e53dd66-GBr0la/m10/eval-curated.json

# (5) 보조 — 운영 릴리스 CLI에 같은 질의를 읽기 전용으로 던지는 프로브
cd /home/jm/orca/projects/second-brain-app
TMPDIR=/var/tmp .venv/bin/python /var/tmp/claude-night-e53dd66-GBr0la/m10/ops_probe.py
# 결과: /var/tmp/claude-night-e53dd66-GBr0la/m10/eval-ops-live.json
```

실행하지 않은 선택지: `--hybrid`(모든 문서에 대해 활성화된 생성 벡터를 요구한다. fixture vault에는 임베딩이 없어
`real hybrid evaluation requires enabled cited vectors for every document`로 실패한다),
`--min-similarity`(의미 후보의 코사인 하한).

## 6. 남은 제약과 주의

1. **`dataset_origin`은 여전히 `synthetic`이다.** 본문은 실제 vault 원문이지만 사용자가 검토하지 않았으므로
   enum상 `user_curated`라고 쓸 수 없다. 사용자가 승인하면 `user_curated`로 바꾸고 `curation_note`를 지우면 된다.
2. **세대가 계속 회전한다.** 데이터셋 작성 시점 세대는 `d55ac3ac…`였고, 운영 프로브 시점에는 `4a2f9ea2…`였다
   (계약 페이지 자신이 “현재 세대 이름은 매번 바뀐다”고 적고 있다). 페이지 내용은 같았지만,
   `source_generation_root`는 스냅샷 값으로 봐야 한다.
3. **page_id는 여전히 fixture 슬러그다.** 스키마 정규식(`wiki/[a-z0-9][a-z0-9-]*`)이 한글 파일명을 허용하지 않는다.
   운영 page_id와의 매핑은 `documents_origin_map`과 `eval-ops-live.json`의 `page_id_mapping`에 있다.
4. **본문은 한 줄 발췌본이다**(§2 참조). 실제 컴파일 페이지에는 각주·`derivation_key`가 더 있고, 절 구분도 있다.
   각주 유무가 매칭에 주는 영향은 측정하지 않았다.
5. **distractor 6개 중 5개는 여전히 빈 템플릿**이다. `me-index`를 실제 내용 distractor로 추가했지만,
   “주제는 비슷한데 사실이 다른” 강한 오답 유인은 아직 부족하다.
6. **운영 릴리스 프로브는 vault를 전혀 쓰지 않았지만**, `sb` CLI를 호출하면
   `~/.local/state/second-brain/requests/journal.db`의 mtime이 갱신된다(크기 불변). 운영 vault
   (`~/.local/share/second-brain`)와 지식 레지스트리 내용은 실행 전후 바이트 단위로 동일했다.
7. **이 평가는 실사용 인수를 대신하지 못한다.** 하네스 스스로 증거에 기록하는 한계다:
   수집·추출·LLM 답변 평가 없음, 단일 소유자 genesis, 소규모 코퍼스 1회 측정.

## 7. 사용자 검토 반영 (2026-09-15 20:40 KST)

§4의 10건을 사용자가 한 건씩 결정했다(Claude가 선택지 제시). JSON `status`는 `user_reviewed`, 검토 전 사본은 `M10-GOLD-CURATED-2026-09-15.pre-user-review.json`.

| case | 결정 | 반영 |
|---|---|---|
| dec-007 | forbidden 유지 | 변경 없음 |
| cmp-006 | 유지 | 변경 없음 |
| cmp-018 | 브리핑 1개로 축소 | expected = `wiki/daily-2026-09-11` |
| cmp-017 | 가장 나중 관측 1개로 축소 | expected = `wiki/inbox-hold-2130` |
| cmp-019 | 정답 1개 + 완전한 문장 | expected = `wiki/inbox-hold-2130`, span = 세 시각이 든 원문 문장 |
| cmp-020 | 01:26 관측 1개 + 완전한 문장 | expected = `wiki/inbox-mail-tick-0126`, span = 시각·상태·간격이 든 원문 문장 |
| date-018 | 검색어 수정 | query = `릴리스 후보 25d49b4 수정 커밋 인수 검증` (정답 문장의 어절) |
| cmp-009, cmp-013, neg-009 | 유지 | 변경 없음 |
| dec-018~021 | 바뀐 질문 유지 | 변경 없음 |

재평가(131/131, 격리 fixture `korean-search-acceptance.py`, 증거 `/var/tmp/sb-korean-search-4dwlnhc1`):

| 표면 | hit@1 | recall@5 | MRR@5 | negative_empty | forbidden_exposure@5 |
|---|---|---|---|---|---|
| CLI (검토 전) | 0.2261 | 0.2261 | 0.2261 | 1.0 | 0.0 |
| CLI (검토 후) | 0.2087 | 0.2348 | 0.2217 | 1.0 | 0.0 |
| MCP (검토 후) | 0.2000 | 0.2261 | 0.2130 | 1.0 | 0.0 |
| 운영 릴리스 CLI 프로브 (검토 후) | 0.2000 | 0.2348 | 0.2130 | 1.0 | 0.0 |

읽는 법: 정답을 1개로 좁힌 cmp-018·cmp-020은 정답 페이지가 **2위**에 있어 hit@1은 잃고 recall@5는 유지한다(관측 원본이 브리핑보다 먼저 뜬다). date-018은 새 검색어로 09-11 브리핑이 1위, 09-10 브리핑이 2위로 잡혀 recall@5만 얻는다. cmp-017·cmp-019는 자연어 질문이라 여전히 0(§3.3 제품 한계). 결론은 §3.3과 같다: 데이터셋은 확정됐고, 남은 격차는 한국어 조사 처리(형태소/n-gram/의미 검색)라는 제품 항목이다.
