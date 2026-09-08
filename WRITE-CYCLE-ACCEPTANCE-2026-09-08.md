# 대규모 100회 쓰기·동시 MCP 읽기·복원 인수

상태: **격리 기능 인수 통과. 대기 제품 다섯 커밋 병합 완료. 운영 전환·쓰기 지연 개선은 미완료.**

## 검증한 범위

`/var/tmp/sb-write-cycles-ynvxjoyu`의 실행이 exit 0으로 종료했고 evidence의 state=passed,
completed_cycles=100, restored_recalls=100을 확인했다. [원본 결과 사본](WRITE-CYCLE-ACCEPTANCE-2026-09-08.json).
실행 로그 `/var/tmp/sb-write-cycle-full-fixed.log`와 개별 CLI/MCP 증거는 해당 격리 폴더에 남아 있다.

초기 5,000 sources / 100,000 units / wiki 10,000 / conflicts 1,000에서 실제 CLI remember→run을
100회 수행했다. 두 별도 MCP SDK reader가 쓰는 동안 기존 기억을 검색하고 읽었으며, observer는
매회 새 기억의 원문·record ID/digest·같은 generation을 대조했다. 각 run 안에서 완료한 동시
읽기 수는 최소 4,427회, 최대 6,324회였다. daily 페이지도 같은 schema5 표면으로 회수했다.

최종 source 5,100 / unit 100,100, CAS 5,100개 모두 보호, orphan/invalid 0개다. 추가 무변경 run에서
source/unit이 늘지 않았고, 관리형 백업을 새 경로에 복원한 뒤 신규 기억 100개·검색 결과·CAS
감사가 원본과 일치했다. archive 23,123,998 bytes, SHA-256
`e7d769d21a2101948dc351f09deea9d85fa6c28c0105686b6f3d01cd36e5eced`.

이 실행의 제품 소스 SHA-256은 처음부터 끝까지
`387d6c7f5b9c1b9db98c31d53c224181757d4eddba5aaf8cfba0641176cb53c4`였다.
중간 문서 커밋을 제품 변경으로 오인하지 않도록 sb/*.py 전체의 경로+내용 hash를 검증했다.
최종 성공과 프로세스 종료 확인 후에만 아래 대기 커밋을 병합했다.

## 실제 지연과 증가량

| 측정 | 표본 수 | p50 | p95 | 최대 |
|---|---:|---:|---:|---:|
| MCP 검색 | 312,407 | 49.49ms | 63.14ms | 1,480.14ms |
| MCP 페이지 읽기 | 312,407 | 29.98ms | 42.34ms | 1,473.85ms |
| CLI remember | 100 | 28.32초 | 32.99초 | 36.96초 |
| CLI run | 100 | 102.07초 | 112.66초 | 128.14초 |

MCP 표본은 배경 reader 결과이며 observer의 확인 요청과 합산하지 않았다. 합성 문구·단일 머신의
실측이므로 일반 질의/운영 SLO 보장이 아니다. 기능적으로 쓰기 중 읽기가 유지되지만 기록과
처리는 대화형 사용에 느리다. 이후 성능 수정은 같은 규모에서 측정하며 수집 성공과 지식 정리
완료의 의미를 분명히 유지해야 한다. 기존 단일 writer를 새 queue/서버로 우회하지 않는다.

active 바이트는 174,542,473→175,347,079로 증가했다. 100회 지점 전체 실험 폴더는
1,287,129,192 bytes다. 여기에는 검증 증거·제어 이력 등이 포함되므로 전체 증가를 활성 기억
DB 누수로 단정하지 않는다. 항목별 증가·보존 정책·backup/reader 잠금 비용은 후속 프로파일링 대상이다.

## 대기 커밋 병합

| 격리 커밋 | 원 작업공간 커밋 | 내용 |
|---|---|---|
| d174276 | 1d3d2de | 공통 AND 질의 및 MCP record 선택 |
| 47fa507 | 0fecf0a | 종료된 준비 세대 사본 복구 |
| 9323a6d | f756872 | 정확 문구·경로와 입력 예산 |
| ef3466e | 01f9963 | cosine 후보 필터·현재 본문·출처 |
| 5d25d3a | 49442bc | 실패 시 기존 벡터 DB 보존·대량 SQL |

초기 세 커밋의 상태 문서 충돌은 원 작업공간에 이미 옮긴 보고서와 이후 자비스/검색 진행 기록을
보존하여 해결했다. 제품 소스는 5d25d3a의 sb/와 바이트가 일치했으며 원 작업공간의 추가 자비스
인수 도구·fixture를 유지했다. 병합 후 walking skeleton·검색어·준비 사본·hybrid·vector gate
**69 passed (17.08초)**, `/var/tmp/sb-five-commits-merged-gate.log`.

그 뒤 추가 발견·수정한 [봉인 파일 무결성](GENERATION-INTEGRITY-2026-09-08.md)은 별도 증거다.
그 최신 제품에 이 과거 full100 지연을 그대로 적용하지 않는다.

## 남은 완료 조건

- 실제 LLM 요약·한국어 질문 품질과 실제 앱별 사용, 프로젝트/에이전트 접근 범위.
- 자비스의 자동 문맥 전달 receipt·세션 중복/compaction·전송 후 삭제/정정 수명.
- 운영 백업/독립 runtime 복구·전환·rollback 인수.
- capture/run 지연과 전체 실험/운영 보존 자료의 증가 원인 분석·개선.
- 봉인 vector의 모델/manifest/reader pin/삭제·복원 결합 후 hybrid 활성화 검증.

이번 100회는 결정적 LLM fixture와 합성 자료를 사용했다. 삭제·정책 변경 부하, 실제 모델 처리량,
GUI, 운영 배포의 완료 증거는 아니다. 사용자 운영 vault·서비스·DB migration·push는 변경하지 않았다.
