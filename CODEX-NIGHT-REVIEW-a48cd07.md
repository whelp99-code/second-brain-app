# 고정 후보 독립 검토 — a48cd07

작성자: 지정된 기존 감시 Codex `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`. 갱신 UTC 2026-09-13T05:40:02.814644+00:00. 원래 Codex는 조정만 했고 이번 검토/테스트를 중복 실행하지 않았다는 전달을 기록한다.

**판정: 일반 M9 연결 및 현재 후보 준비 미통과. 전체 제품·운영 인수도 미완료.** 네 일반 잔여를 아래 하나의 통합 지시로 기존 Grok에 전달한다. 새 제품 진입점과 기본 합성 검사는 동작하지만 공개 이벤트의 실제 문맥 소비 계약·배포 실행 구성·record/예산·제출 산출물이 충분하지 않다. 인증 대기만으로 분류할 수 없는 잔여다.

기준은 `GROK-COMPLETION-CONTINUATION-2026-09-13.md`, `CODEX-REMAINING-TRIAGE-2026-09-13.md`, `CODEX-PROGRESS-CONTROL-2026-09-13.md/.json` 및 원 A–F/M1–M14다. 보류는 콘텐츠 안내 후 원래 Codex의 조정 결정이며 사용자 목표 축소가 아니다. 발생 검사는 원인 미확정이다. 보류 보안/삭제/경합/복원 수명 분기는 실행·수정·이전하지 않았다.

## 고정 바이트와 증거

원본 `/var/tmp/codex-night-a48cd07-eif_t0ak`. 이전 검토 harness/로그는 보존했다. 별도 git archive 복사본·합성 fixture·`TMPDIR=/var/tmp`에서 실행했으며 제품 체크아웃은 수정하지 않았다.

- 제출 HEAD `a48cd07bc7147e890512d7be7b182bac607f3be8`, SB source `611083036f342f3590627723693d729898c25a0c`, archive SHA256 `3334b28cebd7531957db952020bb2237d2640e63ecb1e5bce7576858ba5023a9`.
- SB 후보 `/var/tmp/sb-candidate-6110830/releases/2cc28b41fa0bb848cd551ed7b20e683857c05d85`, wheel `50417180cd8f9a79d537b2f4774a8d96ff94c28c0370e7da8fce2b2df05be2c6`. **183 Python 파일 source/wheel/installed 불일치0**. manifest의 working_tree_modified=true만으로 제품 오염/구휠을 단정하지 않는다. 실제 archive와 바이트를 대조했다.
- JARVIS `f6757ce44c539ff4147880072886bdec0600cc8c`, archive SHA256 `34fe9ec3afe1dbdc46e66ddfcc83309e1b4d4edc8c01c57fb9c6566ebce03a6e`. 제출 `/var/tmp/jarvis-artifact-f6757ce/source`와 추출 파일 불일치0. **제출 dist 없음**.
- 검토용 JARVIS 복사본은 lockfile이 같은 로컬 node_modules를 참조했다. 새 backend 빌드를 검토 디렉터리에 생성했다. artifact 1215파일, 81 migrations, digest `sha256:5157f53bb0e76d98f9669e3ecc3e6e71e62a4d8cb4c19ceee7c844d267a7bc7f`. archive이므로 build metadata source_head/dirty는null이다. 이 빌드의 출처는 identity.json의 archive/file hashes로 묶었다. **Grok 제출 dist 또는 운영 artifact라고 이름 바꾸지 않는다.** frontend 전체 빌드는 이번 변경 범위 검사가 아니다.
- 검토 후 source/test/scripts/deploy와 실제 체크아웃 불일치0 (`post-source-check.json`). 고정 후보를 바꿔서 판정하지 않았다. 초기 설치 경로 탐색 StopIteration은 검토 스크립트의 `.venv` 경로 정정으로 해결했으며 제품 결함 아님.

## 직접 실행과 한정 통과

| 검사 | 직접 결과 | 원본 |
|---|---|---|
| SB 제출 훅 테스트 | 4 passed / 4.18s | sb-tests.log |
| SB 변경 파일 Ruff | EXIT0 | sb-ruff.log |
| SB 변경 CLI/훅/테스트 타입 | 0 errors / 3 warnings / EXIT1 | sb-types.log |
| JARVIS 제출 postcompact | 5 passed / 총7.17s | jarvis-tests.log |
| 기존 명시 dispatch 정상·중복키·동일키 동시 호출 | 3 passed, 선택 제외21 / 총4.74s | dispatch-normal.log; 보류 관련 검사는 선택하지 않음 |
| JARVIS 변경 파일 lint | 1 error / EXIT1 | jarvis-lint.log |
| JARVIS backend build (TypeScript 포함) | EXIT0, wall9.67s | jarvis-build.log 및 build metadata |

JARVIS lint는 `src/cli-gjc-commands.ts:366`의 `_ignoredFence` unused다. 해당 문장은 이전1672626에도 있으므로 새 훅이 만든 신규 오류로 세지 않는다(`lint-baseline-evidence.json`). 그렇다고 필수 lint가 통과했다고 쓰지도 않는다. 타입 경고를 완전 통과로 숨기지 않는다. 별도 전체 regression/DR/native/실모델은 실행하지 않았다. 위 수치를 과거4/5pass 주장·86회귀·f7c1945 게이트와 합산하지 않는다. 자체 검증 문서에는 명령/요약이 있으나 이번 수치는 위 독립 로그에서 얻었다.

`probe-jarvis.mjs`는 새 검토 빌드의 공개 `execute(['memory','postcompact',...], dependencies)`→control handler→재선택→session transport를 실행했다. 합성 provider/transport를 주입한 **실제 제품 dispatcher** 범위에서 session1/2, 본문·source_id·version digest, 최종420bytes(실제 JSON420bytes)를 확인했다. 제출 helper 직접호출보다 넓지만 공개 native 이벤트 등록이나 실모델 수신은 아니다. 알려진 transport 실패→성공2회, 계속 실패→오류는 제출 테스트를 독립 실행해 확인했다.

`probe-sb.py`는 합성 vault와 새 **설치 후보 bin/sb**를 사용했다. 정상 본문 출력 EXIT0, 검색 없음은 header-only additionalContext EXIT0, 긴 일반 요약은 SEARCH_QUERY_TOO_LARGE/EXIT1이었다. no_data가 실제 세션에서 올바르게 소비되는지까지 인수하지 않는다.

## N1 — 공개 PostCompact를 문맥 주입 계약으로 간주함 (P1)

코드 `sb/postcompact_hook.py:71–80`과 constraint 문서는 PostCompact 출력의 additionalContext가 같은 세션 다음 요청에 주입된다고 설명한다. 하지만 [공식 hooks reference](https://code.claude.com/docs/en/hooks#postcompact)의 현재 공개 입력/출력 설명과 decision-control 표는 PostCompact를 후속 부수 작업 이벤트로 분류하며, 문맥 추가 지원 이벤트와 구별한다. **“PostCompact hooks have no decision control.”** 입력에 session_id/compact_summary가 있다는 것과 출력 additionalContext를 소비한다는 것은 다른 계약이다. 공개 문서를 읽은 증거는 official-hooks-reference.json. 설치2.1.261의 실제 native 소비를 실행한 것은 아니며, 공개 계약 근거가 없는 상태에서 네 Python 테스트의 JSON 모양으로 소비 성공을 인정할 수 없다.

완료조건: 같은 지원 클라이언트의 **문서화된 문맥 소비/세션 확장 계약**을 특정하고, 공개 등록 callback→제품 진입점→재선택→같은 세션 다음 정상 요청까지 연결한다. 원 이벤트가 전달용이 아니라면 정상 공개 연결 방식을 구체화하고 한계를 정직하게 남긴다. 허구의 hook 출력/helper/Recording-only 성공으로 닫지 않는다. 운영 설정 등록·실모델 호출·보류 검사의 대체 실행을 요청하는 것이 아니다.

## N2 — SB record/예산/중복과 요약 처리 부족 (P1)

`sb/postcompact_hook.py:110–139`는 블록 바이트만 합산하고 header·줄바꿈·JSON envelope를 제외한다. 정상 합성 SearchHit 8개(각 블록2048bytes)로 **additionalContext16458bytes, 최종 JSON16556bytes > 선언16384**를 직접 재현했다. 동일 page ID의 여덟 hit도 그대로 여덟 record로 출력했다. 이는 `_serialize` 경계의 helper 재현이며 설치 CLI의 동일 큰 결과 재현이라고 과장하지 않는다. `sb-probe.json`에 별도로 구분했다.

설치 CLI 정상 조회에서는 source_ref 빈값이 wiki/omega로 대체되고 version은 `2026-09-13`, SearchHit record_id/record_digest는 빈 문자열이었다. 인용 원문 경로는 snippet에 있지만 출력 version을 MemoryRecord 버전이라고 인수할 수 없다. 123행은 digest가 있어도 updated_at을 먼저 선택한다. 원 M9의 본문/근거/record 버전 구분이 필요하다.

공개 compact_summary는 대화 요약인데 전체를 검색 질의로 사용한다(54행). 약5.6KB의 평범한 합성 요약을 설치 CLI에 넣으면 검색4096byte 제한으로 EXIT1/출력 없음이다. 검색 제한 자체를 풀라는 결함이 아니다. 요약→유효한 제한 질의 선택이 없는 정상 연결의 한계이며 실패를 성공으로 출력하지 않는 점은 통과다.

완료조건: 정상 기억 경로의 실제 record/출처/버전을 보존하고 최종 직렬화 후 예산을 지킨다. 같은 기억의 여러 section 및 동일 이벤트 재전달과 새 compaction의 의미를 구별해 중복 주입 정책/증거를 갖춘다. 일반 긴 요약과 빈 검색의 처리·실패 후 정상 복구도 연결한다. 이미 확인한 검색 제한을 약화하거나 보류 삭제/권한 수명 검사를 대신 붙이지 않는다.

## N3 — JARVIS 배포 CLI에는 transport 구성이 연결되지 않음 (P1)

`src/cli-gjc-commands.ts:423–445`는 memoryReferenceOptions와 model_transport, stdin을 주입받아야 한다. `src/cli.ts` 직접 실행은 dependencies 없이 execute를 호출하고 `cli-runtime.mts` 기본값은 빈 객체다. 합성 초기화 DB에 새 검토 dist의 **실제 Node CLI**로 동일 JSON을 입력하면 EXIT2, `MEMORY_REFERENCE_OPTIONS_REQUIRED`다. 실제 사용자 DB/인증을 사용하지 않았다. DI dispatcher 통과와 실행 가능한 배포 등록을 혼동하지 않는다.

동일 JSON/session1을 DI dispatcher로 두 번 보내면 성공2건/transport.send2건, session2를 더하면 세 번째 전송이 발생했다. 세션 ID 전달은 확인됐지만 동일 이벤트 재전달을 구별할 상태/식별 규칙은 확인되지 않는다. 서로 다른 compaction마다 재선택하는 정상 요구를 막아야 한다는 뜻은 아니다. 동일 이벤트와 새로운 compaction을 구분해 검증해야 한다.

완료조건: 공개 callback/호스트 구성에서 실제 선택 세션의 transport와 stdin을 제품 진입점에 연결하는 실행 가능한 adapter/예시를 제출한다. CLI의 필수 options 오류를 단순 로그인 부족으로 이름 바꾸지 않는다. 합성 정상 이벤트를 **그 등록 경로**로 전달하여 session/body/source/version/최종bytes/실패·재시도/중복 의미를 확인한다. 기존 명시 dispatch 정상3건은 보존한다. 이 수정도 실제 native 로그인 인수나 보류 수명 완료는 아니다.

## N4 — 산출물 핀과 운영 판단 자료 미완성 (P1)

인계 본문은 JARVIS f6757ce 변경과 dist 미빌드를 인정하면서 핀 목록은1672626 변경없음으로 남아 있다. client readiness의 현재 실행 예시도 e13cd3b/1672626을 사용한다. 역사적 준비 문서로 보존할 수 있지만 새 M9의 실행 지침으로 사용하면 새 진입점이 없다. 구 dist/f7c1945 게이트에 이번 구현 결과를 붙이지 않는다. backend 빌드는 인증 없이 이번 검토에서 성공했으므로 새 제출 artifact 준비 자체는 외부 입력 차단이 아니다.

현재 operations 문서는 스냅샷/미실행/과거 RSS·DR 한계를 잘 구분했다. 그러나 전환 순서는 점검→doctor→current 교체→런북 참조 수준이다. 현재 SB/JARVIS 조합에 대한 정확한 서비스 중단/재시작·writer 배제 순서, 두 current 및 설정 변경안, 백업 집합/실패 단계별 복구 대상과 성공 조건이 하나의 실행 검토 자료로 연결되지 않았다. 참조 준비 문서도 e13cd3b를 가리킨다. doctor0/서비스active/검색1건만으로 원 F/M6를 승인할 수 없다.

완료조건: 새 JARVIS source-bound dist·검사/manifest를 제출하고 SB/JARVIS/archive/harness/실행 로그를 한 핀 표로 정합화한다. 기존 lint 실패와 타입 경고의 처리를 명시한다. 현재 후보 대상의 정확한 운영 명령/서비스/경로·writer/lease 확인·비밀 없는 설정 diff·중단/성공/실패/복구 절차를 완성하되 **실행하지 않는다**. 전환 직전 값/hash는 당일 점검 대기로 둔다. 구버전 링크만 복원하거나 보류 검증을 통과한 것으로 전제하지 않는다.

## 통합 후속·외부 조건·보존

기존 Grok는 N1–N4의 허용된 **정상 연결·일반 예산/버전/재시도·새 artifact·문서 준비**를 한 묶음으로 마치고 하나의 고정 후보로 제출한다. 부분 수정마다 사용자/원래 Codex 답변을 기다리지 않는다. 콘텐츠 관련 보류 검사를 수행하거나 다른 도구/모델/세션에 맡기라는 요청은 없다. 외부 입력은 지정 실제 업무/프로젝트/공유 제품, 실제 격리 로그인 프로필·세션 호스트, 한글 gold/허용 corpus·지연 목표, 운영 중단·전환/백업/timer 및 RPO/RTO 판단이다. 위 일반 잔여를 이 입력 대기 전체로 돌리지 않는다.

20eff3c의 정상 Alpha/Omega·worker 예외·과거 게이트 출처 및 triage의 A–F/M1–M14별 통과/미완료를 보존한다. M5/M13 전체 수명·기타 보류·M14 가치 판단을 이번 일반 연결로 닫지 않는다. 운영current41f0751/JARVIS a3cbbbe와 production_activated=false는 제출 스냅샷 인용이며 이번 새 운영 점검/전환이 아니다.

공개 화면6027377의 Goal achieved/인계 대기를 읽었다. 직접 전달/공식 목표 재개와 실제 도구 착수는 후속 기록에서 각각 구분한다. 기존30분 자동화 enabled/Asia-Seoul를 공개 show로 확인했고 변경하지 않았다. 새 작업/모델/구현자 생성·제품수정·운영 변경·auth복사·실사용자삭제·push 없음. root가 관리하는 진행 control/야간보고서는 동시 수정하지 않고 이 검토와 증거 디렉터리의 상태에 기록한다.

## 직접 전달 및 공식 목표 재개 확인

UTC 2026-09-13T05:42:22.512541+00:00: 기존 Grok에 이 통합 검토서만 직접 전달했고 accepted:true를 받았다(`delivery-ack.json`). 화면6027441에서 전체 MD/JSON read 도구와 수신 답변을 확인했다. 당시 native footer는 아직 Goal achieved였으므로 공식 `/goal resume`를 전송했다. 이후 화면6027677에서 **Goal active / Status: active / Pursuing goal** 및 SB 훅, JARVIS CLI/dispatcher, 제출 테스트의 실제 read 도구를 확인했다. N1–N4를 하나의 후속으로 처리한다는 명시적 답변도 있었다. 접수·수신·실제 조사 착수·native 자동 지속 상태를 구분해 확인한 것이며 제품 수정 완료나 새 후보 제출/인수는 아니다. 다음은 기존 Grok의 허용된 정상 작업과 정합한 새 산출물 제출이다. 제한 분기 이전·운영 전환·새 구현자 생성은 요청하지 않았다.
