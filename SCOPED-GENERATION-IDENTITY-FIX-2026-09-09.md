# 접근 분류를 봉인 세대 identity에 결합

2026-09-09. [P0 재현](SCOPED-GENERATION-IDENTITY-AUDIT-2026-09-09.md)의 동일 본문·다른 프로젝트가 같은 generation ID를 생성하던 결함을 수정했다.

## 변경

`sb/generation_access.py`가 canonical source_access/page_access 행을 정렬해 기존 ledger 논리 digest와 함께 `access-bound-ledger-v1` 프로필로 해시한다. 원본 분류의 digest와 PageAccess 인코딩도 검증한다. `GenerationStore.build`는 이 값을 ledger_manifest_digest에 넣으므로 최종 generation identity에도 접근 분류가 결합된다. 공개 manifest 필드나 schema 번호는 추가하지 않았다.

`load_verified_manifest`는 파생 파일 inventory 검증 후, 봉인된 records 목록과 실제 분류 행에서 같은 ledger digest를 재계산한다. 분류/페이지 요구사항을 바꾸거나 전체 분류를 제거하고 inventory 파일 해시까지 재계산해도 generation의 ledger digest와 다르면 거부한다.

분류 행이 없는 기존 세대는 기존 ledger digest를 유지한다. 분류 행은 있으나 해시에 결합되지 않은 **옛 scoped 세대는 새 검증에서 거부**한다. 이를 검증된 새 세대로 자동 간주하거나 읽기 검사를 완화하지 않는다. 운영 적용 전에 원본·승인된 분류에서 재생성하는 전환 절차와 실제 운영 자료 인수가 필요하다. manifest 외형이 같아도 옛 reader가 새 검사를 수행하는 것은 아니므로 모든 관련 reader 버전과 배포 준비 상태를 확인해야 한다.

## 회귀 중 발견·수정

첫 구현이 실제 Markdown 파일을 직접 읽어 기존 cancellation의 오류 코드가 달라졌고 FIFO 교체 사례에서 멈췄다. 테스트 프로세스의 `wait_for_partner` 대기를 확인한 뒤 SIGINT로 중단했다(2 failed / 101 passed). 이 결과를 통과로 집계하지 않았다.

manifest 재계산은 writer가 실제 페이지에서 만든 records 목록을 사용하도록 바꿨다. 실제 페이지/inode 검사는 기존 전용 경로가 맡아 `EFFECT_TARGET_INVALID` 동작을 유지한다. 파일 이름 정렬도 writer의 `.md` 경로 순서와 일치시켰다. 추가로 manifest·파생 파일 open에 O_NONBLOCK을 사용해 FIFO를 열 때 멈추지 않고 regular-file 검사에서 거부한다.

## 검증

- 초기 관련52통과, 회귀 수정 후 관련42통과, FIFO/정렬/옛 세대 검사 포함 집중36통과. 중복 검사이므로 합산하지 않는다.
- 새 모듈 basedpyright 0 errors / 0 warnings, 전체 sb/tests Ruff 통과.
- 최종 전체 검사: `uv run pytest -q --ignore=tests/test_embeddings.py` → **1,222 passed / 2 skipped / 204.85초**. optional embeddings는 제외했다.
- 전체 Ruff 통과, 새 모듈 정적검사 0 errors / 0 warnings. 최종 독립 인수는 이 제품 코드로 재실행했다.

독립 reader4개에서 project:a/b 세대 ID가 서로 달라졌고 각각 허용 프로젝트만 records1을 반환했다. 별도 JARVIS/Python 인수8프로세스는 새 세대의 수락→내부 proved→독립 manifest 검증→자비스 proof 대조를 통과했다. 다른 generation head 거부와 수락 이벤트1 보존도 확인했다. [최종 실행 증거](SCOPED-GENERATION-IDENTITY-FIX-2026-09-09.json).

## 한계·다음 단계

generation identity 결합을 고쳤지만 hash가 발신자 인증이나 현재 읽기 권한을 대신하지 않는다. 공개 v4 계약/운영 verifier, 독립 scoped artifact·완료 기록, old scoped 세대 전환/복구, 실제 에이전트·검색 규모 인수는 남는다. records·분류 재계산의 대규모 비용은 M11에서 실측한다. fixture authority이며 운영 서비스나 native 모델 세션 인수로 확대하지 않는다.

이번에는 운영 배포·서비스 재시작·운영 자료 재생성·push를 수행하지 않았다. 전체 M1~M14 목표를 유지한다.
