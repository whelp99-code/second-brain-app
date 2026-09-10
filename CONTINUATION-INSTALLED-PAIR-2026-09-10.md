# 인계 이후 설치 후보 paired 인수 — 25d49b4

인계서 8-B에 따라 현재 HEAD를 새 임시 app root에 설치하고 격리 JARVIS 빌드와 연결해 인수를 다시 실행했다. 운영 `current`는 전환하지 않았다.

## 설치 후보

- 준비 명령: `python deploy/prepare-release.py /var/tmp/sb-cursor-candidate-d4cbdda --offline` (exit 0).
- 소스 커밋 `d4cbdda68932b788f91b462d283249b84779e344`, tree `6cfe774c0d9d4ea1f33e01e6e244f3d6449eb2a1`, 재료화 `git-archive`.
- 릴리스 `25d49b4367945c8fa01ea71f2d83932d8da934d8`, wheel SHA-256 `aa6fad5fc76ebda509ad3ac616b4e94b538bad2ae2161c83b86158a09a886dcf`, 계약 profile `task32-schema4`.
- 준비 시 작업공간에는 기존 미추적 파일이 있어 manifest의 `working_tree_modified`는 true다. 커밋된 트리만 설치했고 미추적 자료는 산출물에 들어가지 않았다.

## paired 검사

- `python deploy/check-release-integration.py <release> /var/tmp/jarvis-current-pair-_mq15nmd/source/dist` → **exit 0**.
  - 사용한 JARVIS 빌드의 원 소스 커밋은 `195b1a7d4588a8386def5e7dce2067a141942708`이며, 이는 이번에 확인한 Orca-JARVIS 작업공간 HEAD와 같은 커밋이다. 이번에 JARVIS를 새로 빌드하지는 않았다.
  - harness는 후보 커밋 `d4cbdda…`의 자료로 고정됐다(`harness_commit`).
  - 접수 표면 mcp, 실행 표면 cli, 실제 검증 TLS·별도 verifier 자식·live gateway 세션. 신원과 clock은 fixture다.
  - 시나리오 4종 통과: `valid`, `revoke_during_accept`, `revoke_before_execute`, `expire_before_execute`. 철회/만료 경로는 accepted row 없이 거부되거나 failed로 남고 active generation이 없다. FK 오류 0.
  - 검사 전후 inventory 불변: provider 18,474항목 `9e8efe49380fe383ff74af9dc539b9a536f0a660fa5daa3bd79fcf4a61a29fa7`, JARVIS 19,588항목 `8b3ebc1901256636f33c6218adee47d6e294355afd64b569af343ea7676b8d10`, node 실행파일 `bc17c508ffeed0ec622934f9b7fa72f8e78da65350e63c3eceb56fa688aa5e12`.
  - `production_activated: false`.
- `python deploy/check-release-maintenance.py <release>` → **exit 0**.
  - 살아 있는 복원 workspace는 보존(`restore_workspace_busy` 검사 3회), worker SIGKILL(-9) 후 폐기 1·재실행 0.
  - 유지 기억 불변: generation `sbgen:v1:5830a7b9…`, body `d7ab82bf…`, ledger `6ba1e59d…`, high-water `[0, sha256:7fb694c8…]`, 회수 record 1.

원본 출력은 [연동 JSON](CONTINUATION-INSTALLED-PAIR-2026-09-10.json)과 [유지보수 JSON](CONTINUATION-INSTALLED-MAINTENANCE-2026-09-10.json)에 보존했다.

## 한계

- 이 인수의 신원·업무·clock은 fixture이며 native 모델 호출은 0이다. 실제 사용자 업무 계보와 각 제품의 자동 수집·주입 인수는 여전히 남아 있다.
- 운영 `current`, 운영 DB, 운영 서비스는 변경하지 않았다. 운영 전환의 보류 조건은 [운영 재확인](OPS-RECHECK-2026-09-10-0140.md)을 따른다.
- 같은 시간대에 전체 회귀가 실행 중이었으므로 실행 시간은 성능 기준이 아니다.
