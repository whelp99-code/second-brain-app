# P16 — 기존 수집원 보강: AI 세션·Unified DB·Hermes/Markdown·Mac 폴더·문서 형식

명세 등록 / 구현·시험 NOT_RUN. Refs #3, #35. 선행 P01 #20, P02 #21, P03 #22, 모델 연결 전 P10 #29. R1 (제안) / Capture·Core·Client / 6~9인일(추정치, 확정 아님). 기준: 09-23 계획 13·14·16·17·18.

## 목표
SB2 P03은 새 life 입력 adapter만 다룬다. 운영 중인 기존 커넥터의 root 분리, 늦은 수정·삭제 포착, 폴더 동기화 영수증, 문서 추출 한도는 어느 명세에도 없다. 기존 커넥터(`sessions_*`, `unified_db`, `markdown_vault`, `*_documents`)와 Mac 폴더 업로드는 있지만 계획이 요구한 보강은 코드로 확인하지 않았다(미측정). 새 수집기 없이 기존 adapter·cursor·receipt를 고친다.

## 구현 체크리스트
- [ ] 13 AI 세션: Claude/Codex/OMO/OpenCode/GJC의 실제 존재하는 root만 manifest에 등록하고 없는 client는 unavailable로 두며 전체 수집으로 세지 않는다.
- [ ] 13: config 예시와 설치 설정 생성기를 분리하고 raw terminal 전체·credential·probe 잡음을 거른다. 결정·실행 시도·테스트·커밋·배포 사실을 구분한다. 여러 root를 한 source ID나 legacy cursor로 합치지 않는다.
- [ ] 14 Unified DB: immutable change sequence 제공 여부를 먼저 본다. 없으면 PK·내용 hash를 bounded segment로 비교하고 진행 위치는 SB ledger에 둔다.
- [ ] 14: 같은 occurred_at/PK 수정과 뒤늦은 삽입은 K1 새 revision이다. 사라진 row는 완료된 full reconciliation에서만 source_deleted 후보가 된다. 두 read-only flag가 on일 때 SELECT만 실행하고 cap·disabled를 삭제로 읽지 않는다.
- [ ] 16 Hermes·Markdown: `hermes` markdown root와 기억 파일 범위를 manifest에 고정하고 config/plugins/skills를 일기로 오인하지 않는다.
- [ ] 16: `records_project`/`records_orca` export schema와 byte cursor를 K1/K2로 연결한다. dev-wiki는 개발 기억 정본이라 생활 데이터와 별도 source/scope다. 본문 속 코드 지침은 실행하지 않는다.
- [ ] 17 Mac 폴더: 파일별 성공 receipt를 durable manifest에 남겨 중간 실패에도 수락된 파일을 잃지 않는다. rename/change/disappear는 명시적 observation이다.
- [ ] 17 제외: 단방향이며 로컬 삭제를 원격 forget으로 바꾸지 않는다. 선택하지 않은 폴더는 읽지 않는다.
- [ ] 18 문서: PDF/DOCX/HWPX/XLSX/MD/TXT/JSON/YAML의 접수 한도 10MiB와 parser 내부 한도를 capabilities에서 구분한다. 페이지/시트/셀/문단 locator, parser/model version, partial_reason을 보존한다.
- [ ] 18 제외: Docling은 선택 worker로 격리하고 실패를 성공한 빈 문서로 숨기지 않는다.

## 코드·API
기존 재사용. `sb/connectors/`의 `sessions_claude.py`, `sessions_codex.py`, `sessions_omo.py`, `sessions_opencode.py`, `sessions_gjc.py`, `session_checkpoint.py`, `discovery.py`, `fs_safety.py`, `unified_db.py`, `unified_db_mapping.py`, `markdown_vault.py`, `records_project.py`, `records_orca.py`, `inbox_documents.py`(`MAX_INBOX_BYTES` 10MiB). `sb/parsers/`의 `__init__.py`, `docling_adapter.py`, `docling_worker.py`, `office.py`, `hwpx.py`, `pdf.py`, `structured.py`(내부 상한 64MiB). `sb/uploads.py`, `sb/store/ledger.py`, `clients/macos/SecondBrainMac/Sources/SecondBrainCore/FolderSync.swift`, `clients/macos/SecondBrainMac/Sources/SecondBrainMac/AppModel.swift`.

신규 후보: `sb/connectors/source_manifest.py`, `sb/connectors/unified_db_reconcile.py`, `sb/parsers/capabilities.py`, `SecondBrainCore/FolderSyncManifest.swift`. registry `__init__.py`는 무조건 고치지 않는다. 쓰기는 `sb.vault` 단일 writer만 거치고 상주 queue·event bus를 새로 두지 않는다.

기존 시험: `tests/`의 `test_connectors_sessions_configured.py`, `test_session_multiple_roots.py`, `integration/test_session_source_isolation.py`, `test_connectors_unified_db.py`, `test_connectors_markdown.py`, `test_connectors_records.py`, `test_macos_client_contract.py`, `test_parsers.py`.

## 인수시험
AC-01: 폴더 재전송·세션 재실행이 사건 1개·receipt 연결. AC-12: absent client, disabled, cap 도달을 장애와 구분. AC-16: 종료·단절 뒤 수락 파일과 cursor 보존. AC-21: flag rollback 뒤 새 수락 자료·삭제 의도 보존. AC-23: symlink·경로 탈출·secret config·확장 폭탄·손상 문서 차단. AC-24: 기존 커넥터 회귀와 공개 계약 유지.

패키지 고유:
- 13: 다섯 fixture family의 증분·재실행·로테이션이 같은 observation set. 잘린 JSONL, 같은 mtime 변경, 모호한 root에서 cursor 손실 0.
- 14: watermark 없는 DB에서 후속 reconciliation이 새 상태를 찾는다. tie/update/delete/backdated insert가 oracle과 일치. read-only off·연결 끊김·부분 조회에서 cursor·삭제 fence 오승격 0.
- 16: markdown 수정과 project closeout revision을 검색에서 구분. 같은 bytes·다른 root는 다른 source identity. 잘못된 schema는 분류된 제외, 원본 수정 0.
- 17: 실제 Mac에서 두 파일 변경이 각각 논리 upload 1개. 첫 성공 뒤 두 번째 실패·재시작·파일 교체에서 중복 effect 0.
- 18: 형식별 실제 fixture를 exact locator로 재열람. OCR 없음·손상·timeout·10MiB 초과는 맞는 reason. partial은 검색·추천에 uncertainty로 전달.

## 적용·중단·완료
보강 flag는 수집원별이며 기본 OFF다. source DB와 원 폴더는 소유자 소유이고 읽기 전용이다. 자격 증명과 DSN 비밀값은 명세·증거에 적지 않는다. rollback은 flag를 꺼 새 접수만 멈추고 receipt·원본·ledger 진행 위치·삭제 의도는 남긴다. 완료 증거는 출처별 입력·보존·격리·처리 수, happy/failure 기록, 실제 fixture·원문 연결, 실제 Mac 실행 기록, 테스트 로그다. 코드 존재만으로 체크하지 않는다. 현 diff는 이 문서 1개이며 구현·시험 모두 NOT_RUN.
