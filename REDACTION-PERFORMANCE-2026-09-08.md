# 반복 보호 처리의 결과 보존 최적화

2026-09-08. 자비스·여러 에이전트의 공통 기억을 SB에 유지하는 인계 방향에 따라,
기존 쓰기 프로파일에서 확인한 반복 문자열 검사 비용을 줄였다. 제품 커밋 `b6d9875`.
별도 기억 저장소나 서버는 추가하지 않았다.

## 변경과 보존 조건

`sb/security.py`와 `sb/normalize.py`의 정규식에 반드시 포함되는 리터럴이 없을 때만 해당
치환을 생략한다. 예를 들어 이메일 패턴은 `@`, 비밀값 할당 패턴은 `=` 또는 `:`, AWS 키는
`AKIA`가 없으면 일치할 수 없다. 각 조건은 앞선 치환을 마친 문자열에 적용하여 겹치는 값의
처리 순서를 보존한다. 대소문자 무시 패턴을 ASCII 전용 검사로 대체하지 않았다.

정규식·치환값·source별 allow/deny/local-only·민감도 정책과 검사 대상 unit 수는 동일하다.
원문 정규화는 기존처럼 연락 이메일/전화를 보존하며, 기존 LLM 전송 사본의 이메일 masking은
유지한다. unit ID·normalizer version·출처·봉인 계약은 바꾸지 않았다.

## 같은 대용량 입력의 관측

기준 제품 `fe21016`과 개선 제품을 완료된 합성 fixture
`/var/tmp/sb-write-cycles-ynvxjoyu`의 별도 사본에서 각각 실행했다. 실제 CLI remember/run과
신규 기억 검색이 성공했으며, 각 실행 후 source 5,101개/unit 100,101개로 정확히 하나씩 증가했다.

| 관측 | 기준 | 개선 |
|---|---:|---:|
| remember 전체 | 12.24초 | 12.52초 |
| run 전체 | 96.83초 | 74.07초 |
| mask_sensitive 201,202회 누적 | 22.93초 | 2.68초 |
| protect_units 2회 누적 | 25.97초 | 5.57초 |
| normalize의 _redact 5,102회 누적 | 4.65초 | 0.27초 |
| 전체 regex sub 호출 | 831,521회 | 203,405회 |
| _load_units 누적 | 24.95초 | 20.78초 |

함수 누적 시간은 서로 포함되므로 합산하지 않는다. run 전체는 이 관측에서 약 23.5% 줄었다.
각 버전 단일 cProfile 실행이며 deterministic LLM과 profiler 비용을 포함한다. 자체 전체 회귀와
MCP 인수는 프로파일 종료 후 실행했다. 공유 호스트에서 별도 자비스 vitest 실행이 관측되어
호스트 부하가 완전히 통제된 벤치마크는 아니다. 운영 p95나 실제 모델 품질 결과로 해석하지 않는다.

- 기준: `/var/tmp/sb-write-profile-zkqjgivw/result.json`.
- 개선: `/var/tmp/sb-write-profile-xtqmv091/result.json`.
- 원시 프로파일·CLI stdout/stderr·검색 결과는 각 디렉터리에 보존했다.
- [수치와 함수별 호출 통계](REDACTION-PERFORMANCE-2026-09-08.json).
- 개선 제품 sb 소스 SHA256: `53aec50887980f2ffb8839b22b0fb705c498c69ad53858a4a2886f58ad905c2c`.

## 검증

`tests/test_redaction_equivalence.py`에 변경 전 정규식/처리 순서를 독립적으로 고정했다.
Unicode 특수 대소문자·공백·CRLF·NUL·잘못된 접두사·짧은 키·중첩 치환·미종결 PEM과
고정 seed 2,000개 조합에서 두 함수의 결과 전체를 대조한다. 저장 연락처 보존과 전송 사본의
기존 보호 차이도 명시했다. 기존 구현에서 관련 72개 테스트 통과 후 변경을 적용했고,
개선 구현에서도 72개 모두 통과했다. 이는 기존 동작 동등성 검사이며 새 결함 재현 수치가 아니다.

- 집중 72 passed: `/var/tmp/sb-redaction-focused.log`. Ruff 통과, 변경 파일 타입 검사
  0 errors/0 warnings. 전체 **860 passed/2 skipped, 201.04초**:
  `/var/tmp/sb-redaction-full.log` (`--ignore=tests/test_embeddings.py`, 리포 기본 회귀 범위).
- 실제 CLI 3회 remember/run·두 MCP reader·무변경 replay·백업 복원 통과:
  `/var/tmp/sb-write-cycles-3nnhf2to/evidence.json`, `/var/tmp/sb-redaction-native.log`.
  검색/페이지 읽기 각 706회, 복원 후 신규 기억 3개 회수, CAS 8개 보호·orphan/invalid 0.
  이 작은 인수는 전체 회귀와 함께 실행했으며, 그 지연을 대용량 성능 표에 섞지 않았다.

## 남은 수정·개선·고도화

1. **P1 원본 재정규화:** 여전히 모든 기존 source를 읽고 unit을 다시 만든다. 캐시를 도입하려면
   parser/normalizer/source identity와 정정·삭제·복원 수명을 먼저 결합해야 한다.
2. **P1 compile 중복 처리:** 완료된 자료도 정책 검사와 그룹화를 반복한다. 완료/실패 재시도·cap·
   정책 차단 시점의 동등성을 검증하기 전까지 검사 자체를 건너뛰는 변경은 보류한다.
3. **P1 conflict/briefing 비용:** 기존 전체 corpus의 후보 선정·페이지 읽기·토큰화 비용이 남는다.
   신규 기억과 과거 결정의 충돌 회수율을 보존하는 증분 처리 검증이 필요하다.
4. **P1 빠른 기록:** remember 약 12초는 계속 개선 대상이다. 별도 queue/inbox 경로로 이동하여
   기존 generation 결합·기록 응답 의미를 바꾸는 우회는 보류한다.
5. **P1 보호 처리 최악 입력:** 필수 문자가 실제 있는 긴 문자열은 기존 regex 비용이 남는다.
   이번 조건문을 입력 크기 제한이나 모든 악성 입력의 시간 상한으로 주장하지 않는다.
6. **통합 미완료:** 자비스 세션 전달·compaction·삭제/범위, 봉인 의미 검색의 세대/삭제 수명,
   실제 한글 질문·모델·GUI, 운영 전환/DR은 기존 B4~B8 완료 조건으로 유지한다.

운영 서비스 재시작·운영 DB migration·실제 vault 변경·push는 실행하지 않았다.
