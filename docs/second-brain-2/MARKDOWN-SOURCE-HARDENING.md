# P16 Markdown 수집원 보강

Refs #35, #61. 이번 증분은 Markdown만 대상으로 한다. 운영 배포·실제 원본 수집 설정 변경은 포함하지 않는다.

## 이용 범위

허용한 Markdown 원본을 접수한 뒤 중단하거나 다시 실행해도 이미 접수한 revision은 중복 생성하지 않는다. 같은 mtime·크기라도 내용이 바뀌면 새 revision으로 보존하며, 원본과 이전 CAS 내용을 지우지 않는다. 손상된 인코딩은 검색 가능한 성공으로 세지 않고 격리 수로 기록한다.

출처별 K2 스캔 영수증과 커서는 같은 원장 트랜잭션으로 기록된다. 빈 폴더의 빈 커서와 탭·개행 파일명의 불투명 커서도 관찰 본문 텍스트로 검증하지 않는다. root가 끊기거나 scan이 실패하면 커서가 유지되고 해당 수집원만 unavailable이다.

## 선택적 삭제 관찰

기존 `[[sources]]` Markdown row에 `deletion_observations = "v1"`을 지정하면 정상적으로 끝난 전체 scan에서 사라진 파일을 `source-deleted` 후보로 기록한다. 기본값은 `"off"`다. root 단절·scan 실패·차단된 하위 경로는 삭제 근거가 아니다.

후보는 원천 파일·보존 CAS·페이지·인용의 삭제 명령이 아니다. `"off"`로 되돌려도 기존 영수증·커서·후보 기록을 지우지 않는다. 다시 나타난 파일은 내용 revision으로 재접수한다. root는 실제 설정에서 해석하며 새 호스트·포트를 고정하지 않는다.

## 어디까지 접수됐는지 보기

`GET /api/sources`의 `coverage.accepted`는 스캔에서 접수한 누적 revision 수다. `coverage.last_scan`은 최신 K2 영수증의 ID·상태·접수/변경 없음/제외/격리/보류/오류 수와 전후 커서 해시다. 원문·파일명·upstream 증거를 응답에 넣지 않는다. unavailable은 실제 scan 진행 0건이며 전후 커서가 같다.

`stage_counts_measured=false`이면 기존 captured/parsed/published/searchable/eligible 숫자의 0은 단계 측정값이 아니다. 스캔 접수와 게시·검색 증거를 혼동하지 않는다. `exhausted=false`는 upstream 끝이 확인됐다는 뜻이 아니다. 실제 검색은 `GET /api/search?q=<검색어>&scope=all`에서 게시된 페이지를 확인한다. 동일 페이지의 여러 section 결과는 접수 중복과 다르다.

이 adapter의 K2 영수증을 수동 K1 접수용 `/api/source-observations` 영수증으로 부르지 않는다. 두 경로의 계약과 증명은 별개다.

## 검증과 정확한 잔여

Markdown adapter 시험과 `tests/integration/test_markdown_source_hardening.py`는 실제 설정·CLI 재시작·원장 영수증·CAS·커밋된 검색을 사용한다. cap 뒤 재시작, 후수정·후삭제, 단절, 손상 문서, 빈 폴더, 특수 파일명, 차단 경로에서 오삭제가 없음을 검사한다. HTTP 실측은 별도 임시 원본·vault에서 수행하며 운영 자료의 인수가 아니다.

남은 P16 범위는 AI 세션별 실제 manifest/루트·회전·부분 JSONL 인수, Unified DB 실제 읽기 전용·후수정/삽입/삭제 재대조 인수, project/orca 실제 export·scope 인수, 실제 Mac 파일별 동기화 영수증·재시작 인수, 다른 문서 형식별 locator/partial/worker 인수다. 코드가 이미 있는 경로도 이번 증분에서 완료로 세지 않는다. 회사/개인 회상·AI 문맥·알림·JARVIS·전사·위치·건강·예측도 별도 단계다.
