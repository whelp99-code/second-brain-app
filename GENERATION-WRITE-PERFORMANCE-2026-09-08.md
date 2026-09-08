# 세대 쓰기의 실제 병목과 복사·동기화 개선

상태: **제품 구현·전체 회귀·대용량 CLI 프로파일·실제 MCP/복원 인수 통과.**
제품 커밋 `fe21016`, 제품 source SHA-256
`40ba38a260cf329cb7ba950f25bbca7db0d278b0a0189f41b8d05ed28196052f`.
[100회 쓰기 인수](WRITE-CYCLE-ACCEPTANCE-2026-09-08.md)에서 관측한 높은 capture/run 지연의 후속이다.

## 프로파일과 개선 결과

완료된 합성 대용량 fixture의 share/state/requests를 별도 디렉터리에 복사해 실제 CLI remember와
run을 cProfile로 실행했다. 기준 source/unit는 5,100/100,100이며 각 실행 후 5,101/100,101과
새 기억 검색을 확인했다. baseline source 원본은 읽기만 하며 운영 vault나 기존 인수 자료는 바꾸지 않는다.

| 측정 | 기준 코드 | 개선 코드 |
|---|---:|---:|
| 실제 CLI remember 전체 | 33.52초 | 12.24초 |
| 실제 CLI run 전체 | 120.06초 | 96.83초 |
| remember의 파일 복사 누적 | 18.67초 | 1.50초 |
| remember의 content manifest 생성 | 5.12초 | 0.92초 |
| remember의 relative_to 호출 | 71,861회 | 11,102회 |
| remember의 fsync 호출 | 32,811회 | 16,608회 |
| remember의 fsync 누적 | 14.97초 | 0.09초 |

각각 단일 프로파일이므로 p95나 운영 SLO가 아니다. 같은 완료 fixture에서 새 사본을 만든 순차
측정이고 cProfile 비용을 포함한다. 다른 reader 부하가 있던 100회 쓰기의 p95와 직접 비교하지
않는다. 최초 개선 측정에 전체 회귀가 잠시 겹쳐, 그 회귀를 중단하고 최종 프로파일은 분리 실행했다.
초기 개선 관측 12.70/98.89초를 최종 표에 섞지 않았다.

- 기준 `/var/tmp/sb-write-profile-uazbt7kq`, `/var/tmp/sb-write-profile-before.log`.
- 최종 `/var/tmp/sb-write-profile-zkqjgivw`, `/var/tmp/sb-write-profile-after-final.log`.
- [요약과 함수별 실제 통계](GENERATION-WRITE-PERFORMANCE-2026-09-08.json).
- 재현 도구 `scripts/write-profile.py <완료된 synthetic full fixture 경로>`.
  source hash 전후 불변·정확히 한 원본/unit 증가·실제 기억 회수를 검사한다.

## 무엇을 변경했는가

기존 코드는 .git와 .sb를 rglob로 모두 순회한 다음 각 경로를 제외했다. 신규
`sb/generation_walk.py`는 최상위 제외 디렉터리에 들어가지 않고 절대/상대 경로를 함께 전달한다.
파일 순서는 기존 전체 경로 사전순을 유지한다. 중첩된 일반 .git 이름, generation.json이라는
디렉터리의 내부 파일과 실제 generation.json 파일 제외 의미도 기존과 같다. 포함 경로의
심볼릭 링크·hardlink·소유자/장치 검증은 기존 copier가 계속 담당한다.

복사한 파일마다 즉시 실행하던 중복 fsync를 제거했다. 최종 파생 DB와 manifest를 만든 뒤
`_fsync_tree`가 모든 파일/디렉터리를 동기화하고, 그 다음 봉인 세대를 게시하는 순서는 유지한다.
파일 쓰기를 모은 뒤 최종 봉인 경계에서 동기화하여 호출 수와 작은 동기 쓰기의 비용을 줄인다.
최종 파일 fsync가 실패하면 게시하지 않고 이전 세대와 원문을 유지하며 준비 사본을 정리한다.
단일 writer·reader pin·삭제/복원·활성 포인터 계약을 바꾸거나 queue/별도 기억 DB를 추가하지 않았다.

## 검증

초기 재현은 제외된 디렉터리까지 순회함과 복사 단계의 조기 fsync 두 건 실패, 기존 안전성
대조 네 건 통과다. `/var/tmp/sb-generation-walk-before.log`.

- 관련 집중 **49 passed (16.02초)**. 제외 경로 비순회, 심볼릭 링크 파일/디렉터리 및 hardlink
  거부, 순서/제외 의미, 최종 fsync 실패 시 기존 세대 보존·staging 정리를 검사했다.
- 표준 전체 **821 passed / 2 skipped (190.95초)**, `/var/tmp/sb-generation-walk-full-final.log`.
  집중 검사와 중복이며 합산하지 않는다.
- 변경 소스/테스트/도구 타입 **0 errors / 0 warnings**, 전체 Ruff와 diff check 통과.
- 기준 커밋 c16c2e3과 새 코드로 같은 고정 입력을 봉인했을 때 generation manifest 전체가
  일치했다. `/var/tmp/sb-generation-walk-manifest-oracle.json`. 이는 파일 순서나 digest 계산을
  성능 개선 과정에서 바꾸지 않았다는 고정 사례의 증거다.
- 실제 3회 remember/run, 두 MCP reader, 무변경 replay, 백업/복원 통과. 검색/페이지 읽기
  각 777회, 복원 회수 3개, CAS 8개 보호·orphan/invalid 0. `/var/tmp/sb-generation-walk-native.log`,
  `/var/tmp/sb-write-cycles-v5mpzdfm/evidence.json`.
  이 작은 기능 인수의 지연을 대용량 성능 수치로 사용하지 않는다.

## 다음 성능 개선과 보류

기준 run 120초 중 compile stage는 73.76초였다. 기존 원본 5,102회 materialize/normalize,
100,101 units의 load 재생성에 25.32초, 두 protect_units 호출의 200,202회 보호 처리에
26.16초가 들었다. conflict 검사 누적 24.63초에는 보호 처리와 lexical 후보 선정 비용이
포함되므로 이 시간들을 서로 독립적인 비용처럼 합산하지 않는다.

| 우선순위 | 후속 | 완료 기준 또는 보류 이유 |
|---|---|---|
| P1 | 보호 문자열 처리 비용 | 기존 모든 credential/민감도 정책 결과와 Unicode 경계가 동일한 빠른 경로를 검증하고 실측 |
| P1 | 이미 완료된 compile 자료의 중복 처리 | 실제 전송 대상·정책 실패·derivation 재시도/만료를 먼저 구분하여 기존 차단을 우회하지 않음 |
| P1 | 정규화 결과 재사용 | parser/normalizer/source identity와 삭제·정정 수명을 묶어야 함; 원문 사본 cache를 무조건 추가하는 방식은 보류 |
| P1 | conflict/briefing의 전체 corpus 비용 | 신규 기억의 충돌 회수를 잃지 않는 증분/정확성 oracle과 최악 질의 측정 필요 |
| P1 | 빠른 capture 응답 | 현재 모든 content writer의 generation 결합을 유지해야 함; 별도 inbox/queue로 옮겨 기존 쓰기 응답 계약을 우회하는 변경은 보류 |

기록 12초와 처리 97초는 여전히 대화형 사용에 느리다. 이번은 복사·순회·동기화 단위의 개선이며
전체 성능 목표의 완료가 아니다. 봉인 의미 검색, 자비스 session 전달/compaction/삭제·범위,
실제 질문/모델/GUI, 운영 전환/DR의 기존 미완료 조건을 그대로 유지한다. 운영 서비스·DB migration·push는 하지 않았다.
