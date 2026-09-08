# 실제 임베딩 실행 경계와 한국어 평가 진행

제품 `0834e86`, 평가 도구 `6b32416`. [구조화된 증거](REAL-EMBEDDING-PROCESS-2026-09-08.json).

**후속 완료:** 아래 진행 중이던 100질문 평가는 exit 0으로 종료했다. 정답 회수 90/90,
무정답 빈 결과 0/10과 후속 최소 유사도 구현·도전 평가 결과는
[실제 의미 검색 비교](SEMANTIC-RELEVANCE-2026-09-08.md)를 우선한다. 이 문서의 진행 상태는 작성 시점 이력이다.

## 이번 동작 판정

실제 BGE-M3 모델을 기존 코드에 고정된 revision으로 준비하고, 변경 코드의 실제 CLI와 stdio MCP에서 한국어 자연어·의역 질문의 올바른 근거 회수를 확인했다. **무정답에도 후보가 반환되는 문제와 약 6초의 검색 지연이 확인되어 운영 hybrid 활성화는 계속 보류한다.**

합성 encoder 검증 이후 처음으로 이 코드의 실제 BGE-M3 실행 경계를 검사한 결과다. 이 보고서는 실제 사용자 질문 100–300개 품질 인수나 운영 배포 완료를 의미하지 않는다.

## 재현한 결함과 수정

| 결함 | 영향 | 수정 |
|---|---|---|
| `resolve_encoder`는 캐시 디렉터리 존재만 확인하고 자식은 기본 온라인 모델 로딩 사용 | 불완전한 캐시에서 검색/세대 생성 중 예상하지 않은 다운로드·대기 가능 | 인코딩 자식의 `SentenceTransformer` 생성에 `local_files_only=True`. 다운로드는 명시적 warmup 경로로 유지 |
| 모델 자식 프로세스 실행에 timeout 없음 | 멈춘 모델이 검색이나 writer를 계속 점유할 수 있음 | 인코딩 subprocess에 60초 timeout. 명시적 다운로드 warmup은 600초. TimeoutExpired/OSError를 기존 EmbeddingUnavailable로 정규화 |
| stdout의 숫자가 아닌 진단 문자열에서 ValueError 전파 | 기존 lexical fallback/깨끗한 disabled successor 처리에 진입하지 못함 | 잘못된 숫자 출력도 EmbeddingUnavailable로 정규화 |

동일 테스트의 수정 전 **4 failed**, 수정 후 집중 **54 passed/1 skipped, 11.41초**. 전체 **897 passed/2 skipped, 119.83초**, Ruff 통과, 변경 파일 타입 오류·경고 0. 모델 생성자 경계와 잘못된 출력은 실제 자식 프로세스로, timeout/실행 실패 변환은 주입 검사로 확인했다. 집중 skip은 별도 opt-in live smoke이고 실제 모델 사용은 아래 독립 실행으로 검증했다.

60초는 자식 인코딩 호출의 한도다. 요청 전체 예산·MCP transport timeout·여러 batch 합계가 60초라는 뜻은 아니다. 모델을 상주시키거나 새 서버/queue를 추가한 변경도 아니다. 과도하게 긴 batch는 비활성 벡터 세대로 전환될 수 있으므로 모델/배치 지연의 운영 조정이 남는다.

## 실제 모델 준비와 고정

- 모델: `BAAI/bge-m3`, revision `5617a9f61b028005a4858fdac845db406aefb181`.
- [해당 revision의 공식 모델 카드](https://huggingface.co/BAAI/bge-m3/blob/5617a9f61b028005a4858fdac845db406aefb181/README.md)는 1,024차원·MIT를 명시한다. 이번에는 기존 프로젝트 기본 모델을 사용했으며 새 모델 선정이나 외부 소스 코드 복사는 하지 않았다.
- 평가 캐시: `/var/tmp/sb-bge-evaluation-hf`. 기존 사용자 모델 캐시와 운영 설정은 변경하지 않았다.
- Hugging Face CLI로 필요한 weight/config/tokenizer/README 11개를 내려받고 원격 checksum 검증을 통과했다. 생략한 ONNX·이미지·sparse/colbert 보조 파일 등 19개는 미다운로드이며 전체 저장소를 받았다고 주장하지 않는다.
- 평가 실행은 `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, CPU thread 2개 설정으로 수행했다. 비공개 원문·인증 토큰을 평가 데이터나 외부 요청에 넣지 않았다.
- 실제 문장 2개 인코딩에서 1,024차원 두 벡터를 확인했다. 최초 14.26초/child peak RSS 2,443,876 KiB, 후속 6.10초/2,456,180 KiB였다. 파일 캐시·동시 부하가 달라 코드 성능 개선으로 계산하지 않는다.

## 실제 CLI·MCP 경계 인수

변경 제품 소스로 기존 20개 합성 문서를 봉인하고, 고정된 기준선에서 자연어/의역/무정답 첫 사례 각 1개를 선택했다. 결과: `/var/tmp/sb-korean-search-ke_0sj7w/evidence.json`.

| 검증 | CLI | MCP |
|---|---|---|
| 자연어 질문 ko-007 | 올바른 원문 1위 | 같은 원문/record 1위 |
| 의역 질문 ko-009 | 올바른 원문 1위 | 같은 원문/record 1위 |
| 무정답 ko-010 | 관련 없는 후보 5개 반환 | 같은 후보 5개 반환 |
| 검색 지연 p50 | 6,462ms | 6,200ms |

3건의 지연 수치는 작은 진단 표본이며 운영 p95가 아니다. 반환한 MCP 후보 15개의 record ID/digest/source identity와 같은 generation의 원문을 검증했고 정답 본문 대조 2건, 읽기 전후 봉인 파일 불변을 확인했다. 모델/벡터 행 수 20개를 확인하며 lexical fallback이 조용히 의미 검색 인수로 계산되지 않도록 평가 도구를 보강했다. 모델 없는 상태의 `--hybrid` 실행은 실제 exit 1로 거부됐다.

## 100개 질문 비교와 진행 중 작업

같은 기존 합성 질문 100개를 사용하는 일반 검색 평가는 완료됐다. `/var/tmp/sb-korean-search-ek7bhffb/evidence.json`:

- CLI/MCP 모두 정답 있는 90개 중 60개 회수, Recall@5 66.67%.
- 자연어 20개·의역 10개는 미회수, 무정답 10개는 모두 빈 결과.
- CLI 검색 p95 234.73ms, MCP 검색 p95 40.19ms. 작은 corpus·단일 실행 결과다.

실제 모델의 100개 CLI/MCP 평가는 **아직 진행 중이며 완료 수치가 없다**. 독립 worktree `/var/tmp/sb-real-hybrid-source-lf3v04aj`, 고정 커밋 `6b32416`, 결과 `/var/tmp/sb-korean-search-kp_nacfr/evidence.json`, 로그 `/var/tmp/sb-korean-real-hybrid-full.log`, 실행 세션 `26716`이다. 현재 작업공간의 후속 수정과 분리되어 있다. 모델 알고리즘은 같지만 이 평가는 위 process 경계 수정 이전 소스이므로 최종 결과에서 구분한다.

재개 시 해당 실행 세션/실제 프로세스와 evidence state를 먼저 확인한다. 관측 시간 만료나 갱신이 느리다는 이유로 동일 평가를 재시작하지 않는다. 이 파일의 진행 표시는 작성 시점 기록이며, 이후 완료 보고서가 있으면 그 증거를 우선한다.

## 다음 필수 개선과 보류

1. 완료된 100개 실제 모델 평가에서 정답 회수·무정답·유형별 품질·지연을 동일 기준선과 비교한다. 합성 질문을 실제 사용자 질문으로 표기하지 않는다.
2. 낮은 관련성 후보의 제외 기준을 실제 distance 분포와 독립 평가로 결정한다. 작은 smoke의 특정 답만 맞추는 임계값을 넣지 않는다. 이 조건 전 운영 hybrid 활성화는 보류한다.
3. 매 query/batch마다 모델을 재로딩하는 약 6초 지연과 2.3GiB 프로세스 비용을 개선한다. 여러 에이전트가 각각 상주 모델을 늘리는 방식도 총메모리 검증 전까지 보류한다.
4. 자비스 session 전달·중복/compaction·정정/삭제 무효화 C6–C8, 프로젝트 접근 범위, 실제 사용자 품질·GUI/운영/DR의 기존 미완료 조건은 유지한다.

모델 평가 자료 준비와 제품 경계 수정만 수행했다. 운영 provider·vault·자비스 소스·DB migration·push는 변경하지 않았다.
