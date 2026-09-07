# Second Brain 개선 완료 보고서

2026-09-07, Linux 운영 환경에서 검증했다. 최초 진단은 `AUDIT-2026-09-07.md`에 보존한다. 이 문서가 개선 후 상태다.

**판정: 핵심 기억 저장·처리·검색 기능은 실제 운영 환경에서 동작한다.** 소스 수정만 한 상태가 아니라 CLI, 웹, MCP, 자동 실행과 백업에 수정 배포본을 적용했다. 자비스의 실제 기본 transport를 사용해 신규 운영 기록을 검색하고 인용 페이지를 읽었다.

운영 릴리스: `41f0751aca8906d612961e704bc60dd0855fdabd`. 이는 검증한 wheel과 잠금된 의존성의 내용 기반 식별자다. 미커밋 작업을 Git 릴리스 커밋으로 위장하지 않는다. `release-manifest.json`에 원본 HEAD와 dirty 상태를 별도로 기록한다.

## 수정 내용과 의미

| 발견 문제 | 개선 | 검증 |
|---|---|---|
| MCP 누락 함수·기본 설정 때문에 서버 구성 실패 | 기존 프로필과 schema 4 구현을 복구하고 desktop `sb_run` 경로를 분리 | 프로필·계약 회귀 검사, 실제 자비스 transport 연결 |
| 소스·uv 설치·provider 릴리스가 서로 다른 코드 실행 | CLI·웹·provider launcher를 `app/current` 릴리스로 통일 | 실제 응답의 provider release 확인 |
| launcher가 자비스의 SB_CONFIG를 강제로 덮어씀 | 전달된 설정을 존중하고 임시 monkeypatch 제거 | 자비스 기본 경로에서 계약 검증·검색·페이지 읽기 성공 |
| vault symlink가 실제 세대 경로로 일찍 해석되어 쓰기 경로 불일치 | 안정된 활성 경로 보존, 상태·share·요청·export 경로 명시 | 운영 설정 일치와 generation 검증 |
| sealed 세대를 일반 가변 저장소처럼 처리 | pipeline·웹 쓰기와 CLI 재시도·해결·정리를 세대 변경 경로로 연결 | 세대 통합·장애 복구 테스트 |
| 검색이 sealed 인덱스를 수정하거나 기본 scope 때문에 결과를 숨김 | 읽기 전용 인덱스 조회, 세대 바인딩 검증, 명시적인 reference 조회 | 검색 전후 인덱스 해시 일치 |
| 한국어 두 글자 검색 누락 | 짧은 문자열의 매개변수화된 부분 문자열 검색 추가 | 실제 ‘업무’와 신규 기록 검색 |
| 검색 항목과 기억 record의 내용·인용 span 불일치 | 실제 record text로 일치 항목 선택, 다중 인용 span 계산 수정 | 기존 17개 페이지 파싱 검증과 계약 회귀 검사 |
| LLM 실패가 성공처럼 보일 수 있음 | 실패 파생물·오류 개수·비정상 종료 상태를 기록 | 합성 LLM 장애 테스트, 운영 중 실패 확인 후 재처리 |
| 브리핑이 잘못된 인용을 생성하면 바로 실패 | 허용 인용 검증과 제한된 교정 재시도; 운영 최대 3회 | 기존 브리핑 테스트 및 실제 신규 브리핑 생성 |
| 상태 조회 후 SQLite 연결이 남아 세대 정리 실패 | 연결을 명시적으로 close | GC를 끈 상태에서 readiness 조회 후 다음 저장 성공 |
| 처음 생성된 세대에 운영 원장 스키마가 없을 수 있음 | staging 단계에서 원장 스키마 준비 | 최초 저장·상태 조회·다음 저장 회귀 검사 |
| 정기 서비스가 Codex 실행기를 중단시킴 | Node 실행에 필요한 메모리 실행 옵션과 Codex 상태 쓰기 경로 조정 | 기존 옵션에서 Node 중단 재현, 수정 후 실제 compile·brief 성공 |
| 백업 권한·busy 오류와 백업/maintenance 이름 혼동 | 세대·요청 잠금 아래 WAL 포함 스냅샷, 상태·요청 원장 포함, 서비스 분리 | 실제 systemd 백업 성공과 독립 복원 |
| `/health`만으로 준비 상태를 판단 | `/ready`에 초기화·스키마·검색 바인딩·마지막 실행·최근 백업 검사 추가 | 최종 모든 readiness 검사 true |
| 테스트가 사용자 설정에 영향받고 fixture/import가 깨짐 | SB_CONFIG·XDG 격리 및 fixture/import 수정, 유의미한 통합 회귀 검사 추가 | 517개 테스트 통과 |

## 운영에서 실제로 확인한 흐름

운영 복구 사실을 설명하는 기록 1건을 실제 inbox에 저장했다. 최초 시도에서 SQLite 연결 정리 문제와 서비스의 Codex 실행 제한을 발견했고, 수정 후 실패 작업을 재처리했다. 그 결과 compile 1건·brief 1건 모두 성공했고 각 단계 오류는 0이었다. 이 과정의 실패 이력은 삭제하지 않았다.

이후 자비스 리포의 `dist/src/second-brain-transport.js`를 기본 경로·기본 설정 그대로 실행했다. `sb_generation_status`, `sb_search`, `sb_read_page`가 실제 MCP 프로세스와 통신했다. 신규 기록에 대한 record ID를 포함한 검색 결과 1건과 인용 페이지 조회가 반환됐다. 테스트용 transport나 가짜 검색 응답을 사용하지 않았다.

최종 관측값:

- 웹 서비스 active, readiness `ready`
- wiki 18개, daily 2개, conflicts 0개
- 현재 pending/running 파생물 0개; 완료 파생물 91개
- 마지막 실행 `ok`; 정기 refresh 서비스와 실제 backup 서비스 `Result=success`
- 요청 path watcher active, 요청 처리기 `NO_PENDING_REQUEST`, maintenance 정상
- 매시간 inbox 갱신, 매일 실제 백업, 별도 maintenance 일정 활성화

`oneshot` 작업이 끝난 뒤 refresh·backup 서비스가 `inactive/dead`인 것은 정상이다. 성공 여부는 `Result=success`와 종료 코드, 다음 timer 일정을 함께 본다.

## 검증 결과

| 검증 | 결과 |
|---|---|
| `uv run pytest -q --ignore=tests/test_embeddings.py` | 517 passed, 2 skipped; multiprocessing 관련 경고 1개 |
| `uv run ruff check sb tests` | 통과 |
| `uv run basedpyright sb tests` | 오류 0개, 경고 60개 |
| 자비스 계약·transport·outbox saga·동시성 검사 | 정본 테스트 파일 4개, 30개 테스트 통과 |
| 신규 기억 저장 → 실제 LLM 처리 → 자비스 검색 → 인용 조회 | 통과 |
| 실제 backup 서비스 → 별도 디렉터리 복원 | 통과 |

선택적 embeddings extra는 설치·성능 검증 대상에 넣지 않았다. 저장소 안의 별도 미추적 `phone-history/` 프로젝트는 이번 Second Brain 검사 범위에 포함하지 않았다. 그 디렉터리까지 포함하는 무인자 basedpyright 결과를 Second Brain 오류 수로 혼합하지 않았다.

## 사용 가능 범위와 남겨둔 사실

1. **자비스의 중앙 기억 저장소로 연결할 수 있는 상태다.** 실제 통신·계약·저장·검색은 검증했다. 운영 자비스의 사용자 승인 candidate → outbox → settled 이벤트가 이미 발생했다고 주장하지는 않는다. 운영 request journal은 비어 있으며, 이 경로의 saga·중복·장애 복구는 별도 통합 테스트로 검증했다.
2. 기존 9월 5일의 브리핑 인용 실패 5건은 과거 이력으로 남아 있다. 현재 처리 중 작업이나 이번 재처리의 실패가 아니다. 오류 통계를 보기 좋게 만들기 위해 삭제하지 않았다.
3. 세대 변경 중에는 읽기가 잠금을 기다릴 수 있다. 이번 실제 갱신은 수십 초였다. 고빈도 동시 서비스에는 별도 읽기 가용성·부하 측정이 필요하다.
4. Hermes 및 외부 프로젝트의 수집 범위·민감도 정책은 기존 설정을 유지했다. 이번 수정이 모든 외부 프로젝트 자료를 자동 수집하게 만든 것은 아니다. 정기 갱신 대상은 inbox다.
5. 백업에는 기억 데이터와 제어 원장을 포함한다. 호스트 설정·서명 키의 외부 보관, 실제 장애 시 운영 재활성화와 tombstone 대조는 별도 복구 절차다. 오래된 백업을 활성 경로에 직접 덮어쓰는 위험한 경로는 차단했다.
6. 설치본 doctor의 `scheduler-assets` 경고는 Python wheel 옆에 배포 템플릿이 없다는 의미다. 실제 설치된 timer·service는 별도로 확인했고 정상이다. 타입 경고와 선택적 검색 고도화는 기능 성공 판정과 구분한다.

운영 경로, 재시도, 배포, 백업·복원 명령은 `OPERATIONS-RECOVERY.md`에 정리했다. 기존 staged 변경을 유지했으며 Git push는 하지 않았다. 증거 로그와 변경 전 설정·패치는 `/var/tmp/sb-remediation-20260907/`에 보관했다. 이 임시 경로를 영구 백업으로 간주하지 않는다. 실제 백업은 `~/.local/state/second-brain/backups/`에 있다.
