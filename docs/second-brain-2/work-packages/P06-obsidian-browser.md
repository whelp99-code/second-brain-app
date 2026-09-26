# P06 — Obsidian Human Memory Browser

명세 등록 / 제품 구현·실기기·성능 NOT_RUN. Refs #3. 선행 P02 #6, P05 #9; 실제 R1 흐름은 P04 #8과 통합. **R1 핵심 필수**, R2 관계 패널 고도화. REQ-09·REQ-02 / Client+Core+QA / 8–12인일 추정. 기준: 개발계획 7장 전체·12·13·16·17장. 원문 hash는 #3.

## 목표와 제외
Obsidian을 개인 기억 탐색·근거 확인·내 메모·정정의 주 사용 화면으로 만든다. 기존 core Vault를 iCloud/양방향 sync에 직접 노출하지 않으며 Obsidian 파일을 새 기억 정본으로 삼지 않는다. 현 PR은 이 Markdown만 추가한다.

## 1. 폴더 소유권
전용 `SecondBrain-MemoryView` 안에 Home.md, Auto/Daily·People·Companies·Projects·Places·Events·Decisions·Questions·Evidence·System, MyNotes, Templates를 둔다. Auto는 허용된 projection만 관리하고 MyNotes는 사용자 원본이므로 자동 덮어쓰기·삭제·rollback 대상이 아니다. 파일명은 stable ID, 표시명은 title/aliases로 둔다. 이름 변경/동명이인에도 연결이 유지돼야 한다.

## 2. Daily·관계 화면
- [ ] Daily는 오늘 요점→시간순 사건→결정 변화→내일 필요한 기억→중요한 빈칸→MyNotes 링크/embed→수집 상태 순서로 만든다.
- [ ] 사건→사람/회사/프로젝트/장소→과거 사건→결정→원문으로 탐색 가능하게 한다.
- [ ] flat properties에 object_id/revision/managed/generation/event_state/evidence_state/timezone/evidence_count와 링크 목록을 제공한다. nested metadata는 본문/API로 분리한다.
- [ ] R1은 wikilinks/backlinks/Local Graph를 사용한다. 관계 유형·근거·효력은 코어 relation과 본문 표가 권위를 갖고 기본 Graph를 추론 엔진으로 취급하지 않는다.
- [ ] R2에서는 관계별 필터 패널을 추가한다. 비공개 Graph 내부 API를 덮어쓰거나 새 graph DB를 도입하지 않는다.

## 3. 브리지·manifest 계약
`clients/obsidian/`는 신규 후보다. 기존 인증 API에서 권한이 허용된 projection만 pull한다. 앱 시작/전경 복귀/수동 갱신 시 동작하며 iOS 앱 종료 중 상시 실행을 전제하지 않는다.

- [ ] manifest: generation, object_id, revision, content hash, tombstone, next_cursor를 검증한다.
- [ ] 다운로드 검증→파일별 안전 적용→완료 기록→cursor/ACK 전진 순서로 처리한다. 중간 실패에서 마지막 완료 상태로 재개한다.
- [ ] 마지막 적용 hash와 현 파일이 다르면 사용자 변경본을 보존하고 서버 제안본/충돌을 표시한다. 자동 overwrite하지 않는다.
- [ ] 로컬 읽기-수정-쓰기는 공식 Vault API를 사용하고 최신 API 계약을 구현 시 확인한다. 로컬 원자성과 다기기/다파일 전체 원자성을 혼동하지 않는다.
- [ ] 적용 중/완료 generation/stale를 표시한다. Graph가 중간 파일을 볼 수 있으므로 적용 중 상태를 원자적 최신 그래프로 인증하지 않는다. AI 조회는 완료 세대만 사용한다.
- [ ] 같은 Auto 영역에 복수 동기화 작성자를 겹치지 않는다. 기존 개인 Vault 사용은 sync 제외 검증 후에만 허용한다.

## 4. 메모·근거·정정
- [ ] MyNotes 전체를 자동 업로드하지 않는다. 사용자가 '기억에 저장'한 내용만 기존 inbox로 보낸다. 개인 메모 교차기기 전체 sync는 별도 선택 기능이다.
- [ ] evidence ID로 원문을 열고 인증/scope/민감도/삭제를 서버에서 다시 검사한다. 임의 서버 path나 토큰 포함 URL을 제공하지 않는다.
- [ ] 정정 요청은 target_id, expected_revision, reason, replacement, idempotency_key를 기존 correction adapter에 전달한다.
- [ ] 오래된 revision은 409로 표시하고 최신 근거를 비교한다. 로컬 파일 수정만으로 확정 기억을 갱신하지 않는다.
- [ ] 사용자 변경 보존과 삭제/철회가 충돌하면 접근 차단을 우선하고 남은 로컬 사본 상태를 명시한다. MyNotes를 몰래 삭제하지 않는다.
- [ ] 오프라인 단말은 재접속 시 tombstone부터 적용하며 즉시 물리 회수하지 못한 사본을 pending으로 보고한다.

## 5. 인증·설치·배포
플러그인 설정에 장기 관리자 토큰을 저장하지 않는다. P00에서 기기별 최소 권한·안전한 저장을 확인한다. 안전한 영속 보관이 없으면 세션 자격증명을 사용하고 쓰기 동작을 인증된 Web 화면에 연결할 수 있다. 이 대안도 실제 사용자 흐름을 검증해야 한다. 커뮤니티 등록 승인·유료 sync 구독이 이미 있다고 가정하지 않는다. Mac과 실제 iPhone에서 설치/활성화/업데이트/제거/재로그인/오프라인 읽기를 시험한다.

## 6. 인수시험
|AC|Given/When|Then|
|---|---|---|
|06|실제 Mac/iPhone에서 Daily→사건→사람→근거 클릭|링크와 인증 조회 성공, raw path 노출 없음|
|07|사용자가 Auto 편집 후 서버 새 revision 수신|수정본 보존, 충돌 표시, 무단 overwrite 0|
|08|MyNotes 존재 상태 재생성/삭제/rollback|내용·파일 hash 무단 변화0|
|09|정정 후 5개 surface 조회|같은 개정, 옛 내용을 현재 사실로 미사용|
|15|다른 scope manifest/evidence 요청|제목/노드/본문/edge까지 누출0|
|17|100개 View 적용 중 네트워크·프로세스 중단|완료 cursor만 유지, 재개, 허위 최신 표시0|
|18|삭제 후 오프라인 iPhone 재접속/복원|tombstone 우선, 부활 차단, 남은 사본 상태|
|23|악성 Markdown/URL/path/include/외부 이미지|임의 실행·파일 접근·추적 요청 없음|

초기 성능 제안: 수정 100개·본문합계5MB·안정 LAN·전경 p95≤10초. 모바일 저속망과 cold/warm은 별도 측정한다. 현재 측정값이 아니다.

## 완료·롤백
`obsidian_view` flag로 제한 사용하고 장애 시 새 projection 적용을 멈춰 마지막 정상 세대를 stale로 보여준다. 삭제/철회 처리는 계속하며 MyNotes를 건드리지 않는다. R1 핵심과 R2 관계 패널 완료를 별도로 기록한다. 실제 기기/OS/플러그인 build, 서버 revision, manifest/ACK, hash 전후 비교, 화면, 회귀/독립 검토가 필요하다. 현재 모든 제품 검증 NOT_RUN.
