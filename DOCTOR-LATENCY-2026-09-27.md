# `sb doctor` 지연 측정 (2026-09-27)

JARVIS 준비 상태 프로브의 제한은 `src/second-brain-readiness-runtime.ts`의 `PROBE_TIMEOUT_MS = 5_000`(5초)이다. 배포판 1.0.7의 `SB_CONFIG=~/.config/second-brain/config.toml ~/.local/state/second-brain/app/current/bin/sb doctor --json` 실행 시간은 제공된 실측값 6.1초이며, JARVIS `/api/v1/health`는 `second_brain operational=unavailable`, `reason=doctor_timeout`을 보고했다. 배포판은 수정하지 않았다.

동일한 설정을 읽어 개발 코드의 `sb.ops.doctor(load_config())`를 검사별 호출 직후 계측했다. 단위는 ms(벽시계), 두 측정 모두 12개 검사, 검사 결과 모두 `pass`였다.

| 검사 | 수정 전 | 수정 후 |
| --- | ---: | ---: |
| python | 1.66 | 1.66 |
| git | 0.17 | 0.20 |
| vault | 0.03 | 0.03 |
| git-repository | 0.02 | 0.03 |
| ledger | 34.17 | 34.38 |
| citations | 5360.19 | 1812.99 |
| source:hermes | 0.08 | 0.07 |
| source:unified-db-journal | 0.01 | 0.01 |
| generation | 533.32 | 521.86 |
| activation-orphans | 0.33 | 0.48 |
| llm-cli | 0.08 | 0.09 |
| scheduler-assets | 0.07 | 0.07 |
| 합계 | 5930.15 | 2371.89 |

원인: `audit_citations`가 8,592개 Markdown 페이지를 읽은 뒤 각 페이지의 검증된 `SourceCite.sid`를 알아내려고 `read_page_spec`로 다시 읽고 Python YAML 로더로 파싱했다. 별도 분해 계측에서 citations 5471.05ms 중 `read_page_spec` 8,592회가 4708.89ms였다. 해결: 첫 번째 읽기의 텍스트를 같은 `read_page_spec`에 전달하고, 동일한 안전한 YAML 형식의 C 로더가 있는 경우 사용한다(없으면 기존 안전 로더). 페이지 존재/경로 검사, 전체 spec 유효성 검사, CAS 검사, 미해결 인용 검사 및 모든 doctor 검사는 유지한다. 회귀 테스트는 페이지 읽기가 2회에서 1회가 되는 것을 실패 우선으로 확인했다.

개발 CLI `SB_CONFIG=/home/jm/.config/second-brain/config.toml uv run sb doctor --json` 벽시계 3회: **2.618초, 2.499초, 2.508초**, 모두 exit 0 (CLI는 `read_config`로 세대 루트에 고정하므로 직접 `doctor(load_config())`의 generation 및 activation-orphans 검사와 달리 CLI 결과는 10개 검사이다). 관련 pytest 151개 통과(exit 0), `uv run ruff check sb tests` 통과(exit 0). 커밋: `99b496694556022b71d7b2b86932d6cafab10e29` (`fix(ops): reuse rendered pages in doctor citation audit`). 이 문서는 커밋에 포함하지 않았다.

계측/검증 기록: Orca-JARVIS `.omo/evidence/ulw/mass-20260927/c5/`의 `before-per-check.txt`, `before-citation-breakdown.txt`, `loader-experiment.txt`, `red-test.txt`, `after-per-check.txt`, `after-cli-three-runs.txt`, `pytest.txt`, `ruff.txt`. 주의: dev CLI 자체는 종료 시 `record_command`로 설정된 vault의 `.sb/metrics.jsonl`에 자동으로 명령 지표를 기록하며 `read_config`가 reader pin을 사용한다. 프로파일러의 직접 `sb.ops.doctor(load_config())` 호출은 해당 CLI 종료 경로를 거치지 않았다. 배포판, 설정 파일, 서비스 및 vault를 수동 변경하거나 되돌리지 않았다.
