# 명시적 source ID별 세션 분리 검증 — 2026-09-09

## 기존 구현 대조와 정정

`sb/pipeline.py::_select_adapters`는 설정의 각 id를 고유성 검사한 뒤, 한 source row만 담은 Config로 커넥터를 재생성한다. 원장은 adapter.source_id별 cursor를 저장한다. 이전 보고서의 “서로 다른 설정 id만으로 해결되지 않는다”는 설명은 이 파이프라인 확장을 놓친 것으로 정정했다. registry나 source ID 형식을 변경할 필요가 없었다.

## 지원되는 신규 설정 예시

```toml
[[sources]]
id = "claude-agent-a"
adapter = "claude-sessions"
root = "/absolute/path/to/agent-a"

[[sources]]
id = "claude-agent-b"
adapter = "claude-sessions"
root = "/absolute/path/to/agent-b"
```

각 root는 하나의 source id에 대응한다. 이 예시는 신규 설정용이며 기존 운영 ID를 바꾸라는 의미가 아니다. 다른 지원 adapter는 codex-sessions, omo-sessions, gjc-sessions다. 명시적 id가 없는 자동 다중 root나 직접 생성한 복수 root adapter는 기존 보류 정책을 유지한다.

## 실제 프로세스·원장 검증

`tests/integration/test_session_source_isolation.py` 추가. 네 형식마다 실제 `python -m sb.cli ingest`를 독립 프로세스로 3회 실행했다(총 12회). 동일 파일명·동일 메시지 ID·동일 내용의 두 폴더를 사용했다.

1. 처음에는 동일 상대 URI의 SourceItem이 서로 다른 source_id로 2개 보존되고 커서도 2개 저장된다.
2. 프로세스를 재시작해 다시 수집해도 원장 항목과 커서 위치가 변하지 않는다.
3. 첫 폴더에 메시지를 추가하면 항목은 3개가 되고 첫 source 커서만 변한다. 두 번째 source 커서는 보존된다.

결과 `4 passed in 12.31s`. 첫 시도에서는 검증 코드가 봉인된 원장을 writable Ledger로 열어 readonly 오류가 났다. 제품 수집 실패가 아니라 검사 방법 오류였으며, 기존 읽기용 load_ledger_tables로 수정해 재실행했다. 운영 데이터·설정은 사용하거나 변경하지 않았다. LLM 요약/네이티브 앱 자동 업로드/실제 계정 권한을 검증한 테스트는 아니다.

## 미완료 범위

명시적 ID를 가진 신규 다중 폴더 수집 경로는 검증됐다. 기존에 합쳐진 출처의 분리, 같은 ID의 root 교체·이동·삭제 기록 보존, ID 없는 자동 탐색의 다중 root는 여전히 미완료다. 기존 기억을 추측으로 분리하거나 자동 재수집하지 않는다.
