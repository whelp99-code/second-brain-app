# 야간 독립 검토 — d564688 미통과

작성자: **기존 Codex 감시 작업에 위임된 야간 독립 검증자** (`term_6bf51058-3b29-40e2-a25b-b751fab0c24e`). 원래 Codex가 직접 실행한 검토가 아니다. 제품 소스/테스트는 수정하지 않았으며 격리 harness와 이 보고서/조정 기록만 작성했다.

**제품 후보 인수 미통과. 운영 완료/인수 아님.** 이전 V2와 V4의 특정 실패는 개선됐지만, 실행 가능한 N1–N4가 남아 있다. 기존 A–F/R1–R7/M1–M14의 의미와 완료 기준을 유지한다. 운영 허가나 인증 부재는 아래 결함의 차단 사유가 아니다.

## 고정 대상과 증거

- 제출 `d5646882708055134b64ce14be890cac772727d6`, SB source `bda08041771859e129ec59c325d7fe259560ed4d`.
- 후보 `/var/tmp/sb-candidate-bda0804/releases/48686de7744355ac51fa7a91807ce3160860b4d5`.
- wheel SHA-256 `23025b89dd82d3022d291088d915f0eb6ad69fea21f3cd649c011ddcd7fb8c7b`.
- JARVIS `635b4b5`, `/var/tmp/jarvis-artifact-635b4b5/source/dist`.
- JARVIS 설치 inventory `827217404a053390408d0284bbc76cef003997ef69dda223ce17e252cdedf17d`, 34776개.
- 독립 증거 `/var/tmp/codex-night-d564688-crclh2ha`; 기계 판독 결과 `CODEX-NIGHT-REVIEW-d564688.json`.

SB Python 182개는 제출의 git archive 소스·wheel·설치물 바이트가 모두 일치했다. JARVIS src/tests 1132개는 제출 git 소스와 일치했고, 별도 출력 경로에 TypeScript를 재컴파일한 src JS 584개도 제출 dist와 모두 일치했다. 검토 중 `4ef0334`는 야간 ACK/상태/control 문서만 바꿨다. 이 검토 결과는 고정 d564688 후보에 한정한다.

## 직접 통과한 범위

- 관련 회귀 **123 passed / 23.10s**. `focused-pytest.log`.
- Ruff `sb tests` EXIT 0. Python 변경 네 모듈 타입 검사 **0 errors, 7 warnings, EXIT 1**. JARVIS TypeScript 컴파일/타입 검사 EXIT 0. 경고를 통과 0개로 바꾸어 표시하지 않는다.
- 설치 표준·`--work`·유지보수 모두 **EXIT 0**. `installed-pair-fixed.log`, `installed-work.log`, `installed-maintenance.log`. 실제 격리 TLS/CLI/MCP를 사용하며 신원/시계는 fixture다. native 실사용 인수가 아니다.
- R1 관리형 compile: 무수정 정상 정정과 미커밋/커밋 손편집·사람 본문 보존 네 조합 통과.
- R2 기존 철회 후 scoped/cancellation 키 제거와 store 유실 거부 통과. R3 정상/빈/디렉터리/symlink store의 구버전 rollback 거부 통과. 실제 운영 전환 진입점 강제 연결을 통과로 확대하지 않는다.
- V2: cap=1, 실패 문서4개에서 실제 calls=1/capped=true. 실패→성공, 성공→실패, 정상 성공과 후속 재시도도 각각 설정 cap 내 호출. 기존 보안/deny 로컬 경로 관련 회귀 포함.
- V4: dangling/기존 symlink·디렉터리 marker는 거부하며 외부 파일 생성/변경 없음. marker 유실/초기화 중단 뒤 기존 store가 남으면 철회 키를 계속 읽었다. 손상된 store의 별도 결함은 N3.
- R5 기존 Unicode/줄바꿈/구문 일치 사례 및 이전 한 번 언급 긴 문서 vs 세 번 언급 짧은 문서의 순위 재현 통과. 더 일반적인 순위는 N2.
- R4 helper의 baseline/만료/untrusted/예전 과대 예산 사례 통과. 예전 과대 요청은 6268/8000바이트. 실제 세션 연결 증거는 N1.

전체 **1823 passed, 2 skipped / 604.65s**는 Grok 원본 `/var/tmp/sb-full-pytest-bda0804.log` 확인 수치다. 이번 검증자가 전체 회귀를 실행한 수치가 아니다. 핵심 인수 실패가 재현되어 같은 트리 전체 회귀를 불필요하게 반복하지 않았다.

## 통합 미충족

| ID | 우선순위 | 직접 근거·영향 | 완료 기준 |
|---|---|---|---|
| N1 / V1 / R4 | P1 | JARVIS `src/authority-progress-store.ts:29`의 `persistAssembledContextSnapshot`은 여전히 production 호출자가 없다. `src/personal-context-persistence.ts:55`는 고정 `RecordingModelTransport.record`에 먼저 기록한 뒤 실제 evidence 검증/저장으로 넘어간다. 제출 dist의 public helper를 호출한 독립 probe에서 **record=1, send=0**, `PERSONAL_CONTEXT_MEMORY_EVIDENCE_CONFLICT`가 난 뒤에도 본문 capture가 남았다. 새 테스트도 이 예외를 삼킨다. | 실제 제품/세션 진입점이 기억 선택→검증→요청 생성→주입 가능한 transport.send를 수행하게 한다. 그 진입점에서 정상·거부·새 세션·compaction·철회·만료·no_data와 전체 직렬화 예산을 검증한다. 거부된 입력의 recording을 성공 전달로 세지 않는다. 현재 재현은 내부 recording이며 외부 유출/실제 전송을 주장하지 않는다. |
| N2 / V3 / R5 | P2 | `sb/search_query.py:96`은 본문 길이를 고려하지 않은 term 횟수만 정렬한다. 긴 문서30개에 각각 `quartz`4회, 짧은 핵심 문서에3회를 넣으면 핵심은 **top5에서 제외**된다. 핵심 경로를 a/z 양쪽으로 바꾸어도 같고, 같은 DB의 BM25 기준선은 양쪽 모두 핵심1위다. 반환 score는 계속0이다. | Unicode/줄바꿈 parity를 유지하면서 길이·반복·경로/제목 변경에 견디는 관련도 순위를 회복한다. 특정 fixture 빈도만 조정하지 않는다. 충분한 corpus의 실제 MCP 지연과 기존 기억 정정/옛 버전 제외를 별도로 검증한다. |
| N3 / R2 / B·M3 | P1 | `sb/revoked_keys.py:28`은 이미 초기화한 store가 빈 일반 파일로 잘려도 빈 집합으로 받아들인다. 격리 fixture에서 `key:test` 철회→marker 유지→store를 빈 파일로 만드는 손상 재현 후 **활성 scoped policy keys에 key:test가 다시 포함**됐다. marker symlink 수정과 별개의 fail-closed 결손이다. | 최초 미초기화와 기존 store의 절단/파손/잘못된 형식을 구분한다. 신뢰 가능한 복구 이전에는 기존 권한을 다시 활성화하지 않는다. marker/store 초기화 중단·재시작·복원 및 새 유효 키 정상 경로까지 검증한다. 실제 무허가 사용자 기록을 읽었다는 주장은 아니다. |
| N4 / V5 / R6 | P1 | 제출 browser harness 재실행은 `run_body_status=ok`를 출력했지만 **같은 Chrome DOM의 runResult는 status=failed, exit_code=1, pages=0**이었다. 원인은 `SafeSourceFilesystemError: source mutation observed: .`다. `scripts/isolated-browser-fail-recover.py:57`은 최종 batch/run 대신 최신 성공 하위 stage를 고른다. 별도 Playwright로 정상 폼 title/content 입력→기억하기→지금 처리→재시도해도 두 번 모두 같은 실제 실패가 났다. | 성공은 실제 사용자 요청의 batch/run ID 및 결과와 연결한다. 실패 원인을 조사하고 실제 UI에서 입력/설정 정정→동일 경로 재실행→성공한 실제 작업/조회까지 검증한다. 실패 이력은 유지한다. `sb/web.py:164`의 테스트 전용 `#fix=`/`#run` 숨은 동작을 정상 제품 UI 인수로 대체하거나 filesystem 검사를 우회하지 않는다. |

N4의 정상 UI probe는 별도 격리 fixture의 과거 실패만 만들고 성공 stage는 주입하지 않았다. 정상 폼의 성공 응답 수신 후 실행 버튼을 눌렀고, 네트워크 응답과 렌더링된 실패 화면/이력을 함께 보존했다. 실패를 승인이나 인증 문제로 확대 해석하지 않는다.

## 원래 A–F / M1–M14 상태 유지

A의 R1 주요 사례와 B의 기존 철회 거부는 개선됐다. B는 N3, C는 N1/N2, E는 N4 및 실제 성능·DR 통합 인수가 남는다. D의 설치 fixture 계보 통과는 실사용자/제품 세션 인수가 아니다. F의 설치물 일치는 확인했지만 실제 writer 배제·전환/rollback 강제 적용과 복구안은 별도다.

| 요구 | 남은 상태 |
|---|---|
| M1 신원/권한 | fixture만 통과, 실로그인 외부 조건 |
| M2 실제 업무 공유 계보 | 설치 --work 통과, 실제 사용자/다른 제품 세션 인수 남음 |
| M3 철회 | N3 및 전체 복구/초기화 계약 남음 |
| M4 검증 결과 원계보 | fixture 통과를 원업무 인수로 확대하지 않음 |
| M5 native 사본 수명 | 실제 사본/처분 입력과 격리 가능한 검사 구분, 미인수 |
| M6 단일작성자·전환복구 | 유지보수 통과, writer 배제 및 rollback 진입점 남음 |
| M7 전체 읽기 범위 | 기존 fixture 거부 통과, N3와 전체 표면/오래된 권한 대조 유지 |
| M8 제품별 공유연결 | 실제 native와 N1 연결 미충족 |
| M9 문맥·compaction | helper 예산 통과, N1 실제 세션 수명 남음 |
| M10 검색품질 | N2; 사용자 질문100–300개/정답은 외부 조건 |
| M11 성능 | V2 개선, 순위 변경 후 MCP 지연·기존 기억 정정/옛 버전 제외 인수 남음 |
| M12 DR | 유지보수 일부 통과, 원장/원본 소실·high-water·새 쓰기·회수·RPO/RTO 통합 인수 남음 |
| M13 GUI | N4 미충족; 운영 timer는 별도 |
| M14 관계검색 | 기존 보류 유지, 핵심 인수를 대신하는 신규 확장 금지 |

## 재현과 후속 실행

독립 harness는 `/var/tmp/codex-night-d564688-crclh2ha`에 있으며 이전 원본 두 디렉터리는 변경하지 않았다. 고정 source는 그 아래 `source/`다.

```bash
TMPDIR=/var/tmp PYTHONPATH=/var/tmp/codex-night-d564688-crclh2ha/source /home/jm/orca/projects/second-brain-app/.venv/bin/python /var/tmp/codex-night-d564688-crclh2ha/extended.py
node /var/tmp/codex-night-d564688-crclh2ha/transport-entry.mjs
TMPDIR=/var/tmp PYTHONPATH=/var/tmp/codex-night-d564688-crclh2ha/source /home/jm/orca/projects/second-brain-app/.venv/bin/python /var/tmp/codex-night-d564688-crclh2ha/normal-browser.py
```

재현 시 새 증거 경로를 사용해 이번 출력은 보존한다. 최초 설치 표준 검사는 git archive 위치에서 git 메타데이터를 찾지 못해 `CANDIDATE_SOURCE_COMMIT_INVALID`가 났다. 원본 log를 보존하고 실제 저장소의 동일 스크립트로 후보 commit에 고정된 harness를 추출해 재실행하여 EXIT0을 확인했다. 이는 검토 실행 위치의 오류이며 제품 결함으로 세지 않았다.

Grok는 이 검토를 기존 통합 목표에 병합하고 **N1–N4와 관련 전체 계약을 한 번에 구현·자체 검증**한다. 현재 승인된 native 구현 목표를 공식 기능으로 재개한다. 옛 W4 운영 blocked 목표로 되돌리거나 내부 goal JSON을 수정하지 않는다. 중간 커밋 후 running인 채 최종 응답하지 말고 다음 독립 작업으로 이어간다. 고정된 새 소스/설치물/로그 한 조합으로 다음 패키지를 제출한다.

실제 외부 입력은 로그인·업무/공유 프로젝트·native 세션/사본 범위·사용자 질문·운영 drain 허가다. 정확한 대상·준비된 절차·복구안과 함께 오전 보고로 모은다. 사용자에게 야간 반복 승인을 묻지 않는다. 운영 current의 읽기 관측은 `41f0751aca8906d612961e704bc60dd0855fdabd`이며 전환·인증 복사·사용자 기록 삭제·push는 수행/승인하지 않았다. 30분 감시는 유지한다.
