# M5 native 사본 점검 (2026-09-27)

## 격리 인수

`/var/tmp/sb-m5-THYLFs8f` 아래 별도 HOME, 설정 및 새 vault를 만들고 설치된 `sb init`을 실행했다. 실제 Claude Code 2.1.283에 OAuth 인증 파일 **한 개만** 임시 HOME으로 복사해 MCP 기억 저장을 시도했다. 모델 호출 1회는 `Failed to authenticate: OAuth session expired and could not be refreshed`로 실패했다. 원본 인증 파일의 refresh 만료 시각도 현재 시각 이전이었다. 원본 HOME에서 모델을 실행하지 않았다.

로그인 상태인 Codex CLI 0.157.0도 인증 파일만 임시 HOME에 복사해 `codex exec`을 2회 실행했다. 첫 호출은 MCP 도구 승인이 `never`여서 거절되었고, 두 번째 호출에서는 도구가 실패했다. 별도 설치 `sb remember` 명령은 격리 inbox에 fixture 한 건을 기록했으나, native 저장·회수·provider 삭제·새 세션·`--resume`·재색인·백업 복원 검증은 이루어지지 않았다. 모델 호출 총 3회. 격리 실행 프로세스가 없음을 확인하고 임시 디렉터리를 제거했다. **격리 인수는 미통과**이며 부활 0이라는 주장을 할 수 없다.

## 후속 격리 재시도 (같은 날, 별도 환경)

`/var/tmp/sb-m5-cWt44Skr`에서 새 HOME, `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, 관리형 vault/state/config를 분리했다. 원본 클라이언트 설정은 복사하지 않았고 Codex `auth.json` 및 Claude `.credentials.json`만 각각의 임시 설정 홈에 복사했다. 설치된 provider 릴리스의 MCP 진입점을 임시 `run-mcp.sh`에서 고정했다. 실험용 기억의 내용은 보고서에 남기지 않고 SHA-256 접두사 `8c7cb003d3b11178`로만 식별한다.

실제 Codex CLI 0.157.0 `codex exec --ignore-user-config -m gpt-6-astra`가 `sb_remember` MCP 쓰기를 완료했다. `sb ingest --source inbox`와 `sb compile --llm fake` 이후 검색 결과 1건, MCP `sb_search` 회수 성공을 확인했다. 설치된 웹 forget 경로와 같은 `mutate_root(EFFECT, Vault.forget_page)`로 해당 페이지를 지웠다. 이후 새 CLI 조회 0건, 재수집·재컴파일 뒤 조회 0건이었다.

삭제 전 임시 Codex 홈에 fixture 내용의 native 사본이 JSONL 2개(각 4행), SQLite 2개(`thread_items.item_json` 4행, `threads` 2행의 title/first_user_message/preview)에 있었다. 열린 대상 fd가 없음을 확인하고 JSONL의 일치 행 8개를 제거했다. SQLite 대상 필드 6행은 같은 치환 문자열로 변경하고 WAL checkpoint 및 VACUUM을 실행했다. JSONL 파싱과 두 DB의 `integrity_check`가 통과했고, Codex 홈의 fixture 바이트 재주사는 0건이었다. digest-only 파일별 영수증 및 원래 일치 행 번호는 `.omo/evidence/ulw/mass-20260927/m5/isolated-disposal-receipt.json`, `isolated-native-inventory.json`에 있다. `codex exec resume --last`의 답은 `UNKNOWN`이며 fixture 출력 0건이었다. 이 과정에서 resume stderr에 `Orphan custom tool call output` 진단 1건이 있었다.

**백업 복원은 통과하지 못했다.** 삭제 이전 격리 백업을 새 격리 목적지에 복원하면 검색 결과 1건으로 삭제된 내용을 되살릴 수 있었다. 삭제 이후 백업을 복원하면 결과 0건이었다. 기존 백업을 현재 provider에 다시 연결하지 않았다. 후속 실행의 모델 호출은 Codex 3회(첫 설정 실패 1회 포함), Claude 1회로 총 4회다. Codex 삭제 후 새 *모델* 세션은 호출 상한 때문에 실행하지 않았고 새 CLI 검색 0건으로만 확인했다. Claude Code 2.1.283은 임시 `CLAUDE_CONFIG_DIR`에서 실제 `-p` 호출 1회가 다시 `Failed to authenticate: OAuth session expired and could not be refreshed`로 실패했다. Claude native 사본 인수는 외부 인증 차단 상태다. 세부 계측은 `isolated-acceptance.json`에 있다.

## 운영 읽기 전용 조사 및 처분

운영 설정 `/home/jm/.config/second-brain/config.toml`의 현재 vault, state 및 requests journal을 SQLite 읽기 전용으로 조사했다. tombstone 0, tombstone 대상 0, correction cancellation 0, reingress 차단 identity 0이다. 현재 vault의 `wiki/memory-*` 페이지 0개이며 해당 경로의 전체 Git 이력에 추가·수정·삭제 이벤트가 각각 0개다. 따라서 이 상태에서 식별 가능한 **이미 삭제·정정된 provider 기억의 내용 sentinel 0개**, native 처분 대상 0개다. 이전 재고 문서에 언급된 릴리스 식별자는 현재 활성 페이지에도 발견되므로 삭제된 기억의 증거로 취급하지 않았다.

정확한 대상 목록 및 경로별 읽기 가능 파일 수는 Orca-JARVIS의 `.omo/evidence/ulw/mass-20260927/m5/targets.json`에 남겼다. `~/.claude` 23,796개, `~/.codex` 6,499개, `~/.omo/agent/sessions` 84개, `~/.grok/sessions` 1,872개, `~/.local/share/claude` 3개의 일반 파일을 읽었다. 읽기 오류 2건(errno 6, 각 경로의 SHA-256 접두사는 JSON에 기록), 심볼릭 링크 16개는 미추적했다. 식별 가능한 삭제·정정 내용 sentinel이 없어 이 파일들에 대한 내용 일치 검사는 실행할 수 없었다. 운영 native 세션을 **수정하거나 삭제하지 않았고**, digest 처분 영수증 대상도 없다. 열린 파일 제외 목록은 수정 대상이 없으므로 공집합이다.

## 잔여 한계

운영의 현재 provider 기록에 식별자가 0이라는 관측은 모든 과거 백업, 외부 provider 또는 비정형 native 압축 사본이 0이라는 증명이 아니다. Claude 인증 실패로 해당 클라이언트 인수를 검증하지 못했다. Codex native 사본 처분 및 재개 조회는 계측됐으나, 삭제 전 백업 복원에서 실제로 부활했고 삭제 후 새 Codex 모델 세션은 실행하지 않았다. 이번 결과는 **운영 대상 목록이 비어 있어 처분을 하지 않은 것**이며 M5 전체의 통과 증거가 아니다.

## 2026-09-27 복원 판정 보정 (개발 저장소 HEAD `900f447`)

**판정: 관측된 1건 재등장은 현재 `sb restore`와 페이지 단위 forget 계약상 예상되는 결과이며, 서명된 삭제 복원 경로의 결함을 증명하지 않는다.** M5의 "백업 복원 미통과"는 오래된 백업까지 삭제를 보장하는 M5 인수 조건이 *미달*이라는 뜻이지, 이 두 경로가 같은 삭제 권한을 사용했는데 제품 보장이 깨졌다는 뜻은 아니다. 오래된 백업을 삭제된 기억이 없는 안전한 백업으로 취급하거나 운영에 재연결해서는 안 된다.

모델 호출 없는 격리 재현(`/var/tmp` 임시 루트, 완료 후 제거): `sb remember` -> `sb ingest --source inbox` -> `sb compile --llm fake` -> `sb backup`(삭제 전) -> 웹 forget과 동일한 `mutate_root(EFFECT, Vault.forget_page)` -> `sb restore <삭제 전 백업> --to <새 디렉터리>` -> `sb search --json`. fake 컴파일러는 입력 본문 대신 `Cited`를 렌더하므로 해당 검색어의 결과 수를 비교했다: 삭제 전 **1**, 삭제 후 **0**, 격리 복원 후 **1**. 출력: Orca-JARVIS `.omo/evidence/ulw/mass-20260927/m5-restore/repro-before.txt`. 관련 기존 테스트 16개 통과: 같은 위치의 `focused-tests.txt` (`test_forget_restore_exclusion.py`는 삭제 전 백업에서 재노출을 명시적으로 확인). 코드 변경/커밋 없음.

경로의 차이: `sb/web.py`의 `/api/pages/<id>/forget`은 `Vault.forget_page`만 호출한다. `sb/vault.py`의 이 메서드는 현재 페이지를 Git 커밋에서 제거하지만 `sb/request_store.py`의 `tombstone_replica`/대상 identity에 삭제를 기록하지 않는다. `sb/cli.py`의 `restore`는 `sb/ops.py::restore_backup`에 격리 목적지만 넘기며, 아카이브 바이트/매니페스트를 검사할 뿐 현재 제어 루트의 tombstone 집합이나 JARVIS fence를 읽어 소거하지 않는다. 관리형 `sb verify-backup`의 현재 high-water 대조(`sb/runtime_backup.py`)는 **검증/준비 상태**의 판정이지 `sb restore`의 복원 필터가 아니다 (`docs/MANUAL.md` 10.4). 반면 9월 10일 삭제 수명 검증은 JARVIS 효과 요청이 `tombstone_sequence`를 올린 뒤 별도 `sb/restore.py::GenerationRestoreSanitizer.sanitize`가 provider 요청 저널의 **검증된 현재 tombstone snapshot**과 JARVIS 서명 fence를 대조해 복원 사본을 정화한 경로였다. 해당 0건 보증을 웹 페이지 forget + `sb restore`에 일반화할 수 없다. 전체 M5 복원 방어와 native 사본 처분은 여전히 인수되지 않았다.
