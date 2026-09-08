# 실제 native 세션 연결 검증과 원문 보존 문제

이전 [영구 전달 원장](REFERENCE-DELIVERY-JOURNAL-ACCEPTANCE-2026-09-08.md)은 합성 adapter session
ID를 사용했다. 이번에는 native Codex가 발급한 실제 세션 ID를 먼저 관측하고 같은 ID로 기억을
전달했다. 자비스 제품은 `6e101fc`를 유지하며 SB 작업공간의 검증 도구를 `94ea45a`로 확장했다.
[상세 기계 증거](NATIVE-SESSION-ACCEPTANCE-2026-09-08.json)를 함께 보존했다.

**실제 세션 식별·재개·원장 차단을 검증했다. 일반 사용자 Codex 세션에 기억을 자동 저장하는
제품 연결은 원문 보존·삭제 경로가 준비될 때까지 보류한다.** 전체 중앙 기억 완성이나 자비스
실제 앱 채택·운영 배포의 완료가 아니다.

## 1. 실제 요청 경로 대조

현재 JARVIS `src/task-execution-runtime.ts`와 `src/claude-task-provider.ts`의 작업 실행 경로는
Claude 단발 후보 생성이다. `src/cli-memory-reference.ts`는 bounded memory context를 출력하며
모델 전달까지 수행하지 않는다. 별도 Codex adapter를 기존 작업 실행 권한의 대체물로 넣지 않았다.

설치된 `codex-cli 0.153.4`의 CLI 도움말 및 로컬 생성 protocol을 확인했다. `codex app-server`는
`--ignore-user-config`를 거부했고, exec/resume은 지원했다. 사용자 설정·인증·MCP를 일괄 상속하는
새 app-server를 바로 실행하는 경로는 보류했다. 외부 공식 문서나 최신 버전을 재조사한 결과는
아니며 이번에 설치된 바이너리의 관측이다.

## 2. 확인한 결함과 수정

| 발견 | 실제 영향 | 이번 대응 |
|---|---|---|
| `exec resume --ephemeral`에도 기존 rollout에 새 입력 기록 | 옵션 이름만으로 기억 원문 비보존을 보장할 수 없음 | 무해한 합성 canary로 재현. 제품 native 자동 연결 보류 |
| 설치 npm launcher와 native 바이너리의 그룹 쓰기 권한 | 파일 경로만으로 고정 실행체를 증명하기 어려움 | 원본 chmod/교체 없이 native binary 두 개를 fixture로 복사, 0500, 원본/사본 SHA 대조 |
| native rollout 파일이 기본 umask에서 0664로 생성 | 디렉터리 밖으로 복사할 때 파일 권한 자체가 과도함 | native spawn 동안만 umask 0077, 성공/실패 모두 부모 umask 복원 |
| 알 수 없는 native event를 기존 감사기가 무시 | 향후 approval/tool/failure 이벤트가 성공처럼 처리될 수 있음 | 허용 event 종류 외 전부 거부, exact resumed thread ID 검증 추가 |
| provider에서 삭제해도 native transcript에 원문 잔류 | SB 삭제와 소비자 사본 삭제는 별개 | 실제 잔류 검출과 fixture native-state 폐기 도구 추가. 모델/모든 로그 삭제 주장 금지 |

초기 native lifecycle 실행은 실행 파일 권한 검사에서 모델 호출 전 중단됐다. 그 실패는 성공
증거로 포함하지 않았다. 권한 검사를 완화하지 않고 설치된 native 실행체의 별도 사본을 사용했다.
이 설치의 경로 구성에 맞춘 Linux x64 인수 도구이며 일반적인 Codex 배포 방식 지원을 뜻하지 않는다.

## 3. 검증용 파일시스템과 인증 경계

`scripts/reference_native_session.mjs`는 다음 방식으로 실행한다.

1. root `0700`의 fixture에 native 실행체, 빈 client cwd, Codex state, 임시 경로를 준비한다.
2. bubblewrap에서 호스트 root를 읽기 전용으로 두고 기존 `~/.codex` 위치에 fixture state를
   겹쳐 연결한다. `HOME`·`CODEX_HOME` 값을 다른 경로로 바꾸지 않는다.
3. 원래 `auth.json`만 읽기 전용으로 연결한다. 자격증명 내용을 복사·출력하지 않는다.
   내부 preflight에서 regular file/nlink 1/readable/not-writable과 auth-only 초기 목록을 확인한다.
4. 전달 환경은 기존 HOME/PATH/LANG/TZ 값만 허용한다. 빈 cwd, ignore-user-config, read-only
   sandbox 설정, shell/apps/multi_agent/web 비활성화를 두 요청 모두에 적용한다.
5. 원장 claim 뒤 exact UUID를 지정한 resume을 실행하고 전체 JSONL·종료 코드·thread ID를 검사한다.

**이 구성은 Codex state 교체와 호스트 쓰기 제한이다. 호스트 파일을 전부 읽지 못하게 하는
기밀성 sandbox는 아니다.** system/managed policy가 전혀 없다는 증거도 아니다. 합성 자료 검증에
한정하며 실제 사용자 기억의 제품 연결에는 보존 경로·관리 정책·권한 조건을 추가해야 한다.

## 4. 실제 세션 수명 검증

bootstrap에는 기억을 제공하지 않고 no_data 응답을 요구한다. 성공 종료와 전체 이벤트를 검증한
뒤 `thread.started` UUID를 저장한다. 그런 다음 read→submitInSession→exact resume 순서로 호출한다.
초기 epoch는 `initial` 하나이며 compaction을 관측하지 않고 epoch를 증가시키지 않는다.

| 시나리오 | 검증 범위 |
|---|---|
| 빈 기억 | native bootstrap 뒤 같은 UUID 재개, no_data |
| 최초 기억 | 임의 128-bit 확인값과 정확한 record/source/generation 반환 |
| 정정 후 새 세션 | 새 native UUID에서 새 값 회수, 이전 준비 객체는 callback 전 차단 |
| 삭제 전 원문을 받은 모델 | native 완료 후 callback 반환 전에 실제 삭제를 수행하고 결과 반환 차단 |
| 삭제 후 새 세션 | 새 native UUID로 no_data |
| 이미 제출한 같은 session/epoch | 새 reference 객체여도 callback 0회 |
| 무효화한 최초 native UUID | 새 reference로도 callback 0회, 세션 재개 거부 |

삭제 검사는 **native 모델 완료 후, 제출 callback이 반환되기 전**에 실행한다. 실행 중 모델과
동시에 삭제한 테스트나 DB commit→외부 송신 경합을 원천 차단한 테스트가 아니다.
출처 일치도는 전송·출력 상관관계의 증거이며 모델 내부 사고 과정의 증명으로 표현하지 않는다.

## 5. 잔류 사본과 보류 결정

첫 완료 run에서 provider의 최종 record는 0개였지만 native rollout에는 최초 확인값을 담은
세션 1개와 정정 값을 담은 세션 2개가 남았다. 원장의 invalidated 상태만으로 외부 transcript가
지워지지 않는다는 직접 증거다. 파일들은 상위 0700 디렉터리 안에 있었으나 자체 mode는 0664였다.

파일 권한을 보강한 후 새 run으로 다시 검증했다. storage 감사는 알려진 fixture의 nativeHome
전체 디렉터리·파일을 한도 내에서 순회해 합성 확인값의 잔류 여부·파일 권한을 기록한다.
5개 native rollout은 정확한 파일명/UUID 및 bootstrap/resume 쌍과 별도로 대조한다. `--dispose-native-state`는 그
fixture의 native-codex 디렉터리만 제거하고 부재를 확인한다. prompt/모델 이벤트/검증 보고서에는
합성 데이터가 남으므로 전체 fixture plaintext 또는 원격 모델 보존 데이터 삭제를 뜻하지 않는다.

다음은 계속 보류·미완료다.

- 운영 Codex 세션으로 전역 자동 주입: 관리형 native state/폐기/백업 정책 연결 전 보류.
- 기존 자비스 task 실행기에 Codex 기억 경로 추가: 실행 권한·프로젝트 범위와 별도 조율 필요.
- native compaction·장기 재개·선택적 record 무효화: 실제 이벤트/수신 fence 계약 필요.
- DB→외부 송신의 전역 원자성, 모델 사본 삭제, 오래된 백업 복원 이후 세션 재개: 미완료.
- Claude/기타 앱의 자동 수집·주입: 각 클라이언트의 실제 인수 필요.

다음 제품 작업은 이미 있는 JARVIS managed surface/보존 경로가 native 상태를 소유하도록
연결하는 설계와 실제 앱의 명시적 기억 질의 경로다. 별도 기억 정본이나 모델 Proxy는 추가하지 않는다.


## 6. 추가 native 상태 조사와 의도적 보류

기본 기능을 유지한 v3는 nativeHome에 플러그인 자산도 내려받았다. 실제 관측은 2,295개 객체,
64,834,064 bytes, group/world 권한 객체 1,473개였다. 원문 rollout 자체는 umask 보강으로
600이었지만 `apps=false`만으로 플러그인 다운로드가 꺼지지 않았다.

설치된 기능 목록을 확인해 plugins/remote_plugin/hooks/skill_search/skill_mcp_dependency_install을
명시적으로 false로 설정했다. 개발 중인 skip_host_skill_discovery는 오류 item을 발생시켜
엄격한 event 감사에서 거부됐으므로 제외했다. 오류를 무시하도록 parser를 완화하지 않았다.
이후 v5 실제 수명 인수는 성공했고 nativeHome은 112개 객체·1,445,219 bytes로 관측됐다.
이 수치는 한 fixture run의 값이며 제품 성능 벤치마크가 아니다.

v5의 비공개 권한 예외는 `installation_id` 하나였다. 내용은 설치 UUID 메타데이터이고 기억
본문이 아니다. 초기 mode 600으로 미리 만들어도 CLI가 644로 변경했으며, 읽기 전용 bind로
막으면 초기화가 EROFS로 실패했다. 일반 설치를 수정하거나 오류를 숨기지 않았고 그 우회는
제거했다. 저장 감사는 `nonprivate_native_file_modes`와 비정상 종료를 유지하며, 전체 nativeHome
삭제 성공을 검사 통과로 덮어쓰지 않는다. 상위 root/nativeHome은 700이고 rollout은 600이다.

원문은 rollout 외에도 native 상태에 존재할 수 있으므로 감사기는 canary가 들어간 파일의
안전한 상대 경로와 크기·권한만 기록한다. 파일 내용·인증 비밀은 출력하지 않는다. 이 추가
표면까지 관리형 보존에 편입하기 전에는 제품 연결을 완료로 판정하지 않는다.


## 7. 최종 검증 결과와 재현

최종 v6의 원시 결과는 `/var/tmp/sb-reference-model-mPVh78/result.json`이며 인수 프로세스
exit 0이었다. native 실행은 **5개 실제 UUID, bootstrap 5회 + exact resume 5회 = 모델 10회**다.
모든 resume에서 UUID가 일치하고 원장은 invalidated 4 / callback_completed 1행이었다.
동일 reference 집합 재전송과 무효화된 실제 UUID 재개는 추가 callback 없이 거부됐다.

저장 감사는 **112개 객체, 1,445,186 bytes**를 검사했다. 최종 provider record 0개인데도
원래 값은 rollout 1개, 정정 값은 rollout 2개에 남았고, **`thread_history_1.sqlite`에도 두 값이
모두 남아 있었다.** 해당 SQLite 파일은 114,688 bytes이며 private mode였다. 이 파일을
포함한 canary 검출 4개 파일의 상대 경로·크기·권한은 JSON 증거에 보존했다.

원문 rollout 5개는 모두 private mode였으나 native 상태 전체에는 비공개가 아닌 객체 1개가
남았다. 따라서 감사 결과는 `nonprivate_native_file_modes`, **exit 1**이다. 정상 native 수명
인수와 전체 파일 권한 감사의 결과를 혼동하지 않는다. 앞선 v5/시작 검사는 그 권한 예외를
installation_id로 식별했으며 이 메타데이터는 원문 canary가 없는 36-byte UUID였다.

`native_state_disposed=true`는 최종 run의 nativeHome 경로 제거·부재 확인이며 모든 fixture
원문 또는 원격 모델의 보존 데이터 삭제가 아니다. 감사 후에도 prompt와 native event 증거는
해당 합성 fixture root에 남는다. 경로 부재만으로 외부 열린 FD·원격 보존까지 검증했다고
주장하지 않는다. 초기 CLI 동작 재현은 일반 Codex home에 무해한 bootstrap/canary 세션을
생성했으며, 실제 SB 기억을 전달한 lifecycle run은 별도의 nativeHome에서 수행했다.
운영 SB vault·JARVIS DB·배포·서비스 재시작은 변경하지 않았다.

회귀는 Node event/umask **20 passed**, Python MCP 계약·프로파일·기억 수명 **12 passed**,
변경 JavaScript syntax 및 git diff 검사 통과다. JARVIS 제품 변경이 없으므로 전체 backend/GUI
또는 SB 전체 931개를 이번에 다시 실행했다는 주장은 하지 않는다. 독립 모델 검토의 실행체
식별·전체 nativeHome 감사·추가 canary 표면 식별 지적을 반영했다. reviewer는 테스트를 실행하지 않았다.

```bash
TMPDIR=/var/tmp node scripts/jarvis-reference-model-acceptance.mjs /var/tmp/sb-delivery-journal-build --native-session
# 위 명령이 출력한 result.json 경로를 지정한다. 권한 예외가 있으면 audit는 exit 1이다.
TMPDIR=/var/tmp node scripts/audit-native-reference-storage.mjs /path/to/result.json --dispose-native-state
TMPDIR=/var/tmp node --test scripts/reference_model_events.test.mjs scripts/reference_native_session.test.mjs
```

사용한 `codex-cli 0.153.4`의 두 native 실행체 SHA, source metadata, 허용 환경 키,
요청별 UUID와 응답 digest는 JSON에 있다. 다른 설치 버전/레이아웃의 호환성을 보장하지 않는다.
다음 제품 작업의 완료 기준에는 rollout뿐 아니라 thread_history SQLite·부속 파일·백업의
관리형 보존, native session 폐기, 실제 앱의 보호 경로 채택이 반드시 포함돼야 한다.
