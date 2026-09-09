# HTTP 상태의 세대 일치 — 2026-09-09

`do_GET`은 read_root로 독자 세대를 고정했지만 `/api/status`는 해당 root를 무시하고 context.config의 활성 경로를 다시 조회했다. 세대 전환 시 요청에 고정된 세대와 다른 실패 목록·실행 로그를 반환할 수 있었다.

회귀 테스트는 실제 HTTP 서버에 서로 다른 vault 두 개를 준비하고 read_root가 반환하는 고정 세대 경로를 주입했다. 고정 세대에는 brief 실패1건, 활성 경로에는 실패0건을 두었을 때 수정 전 0건으로 응답해 실패했다. 이후 두 vault의 실행 로그도 다르게 두어 함께 검사했다. 실제 GenerationStore 전환 경합 전체를 새로 검증한 것은 아니며, HTTP handler가 제공받은 pin을 따르는지 검사한 것이다.

수정은 dataclasses.replace로 기존 설정의 base_dir/source_path를 보존하면서 vault_root만 고정 root로 바꾸고, status_snapshot과 read_status 양쪽에 전달한다. 설정 원본과 운영 포인터는 변경하지 않는다.

검증:

- 수정 전 a87a73d 전체 검사: **1,457 passed, 2 skipped / 269.04초**, embeddings 파일 제외. [전체 출력](CURRENT-FULL-REGRESSION-A87A73D-2026-09-09.txt). 새 pin 회귀 테스트는 이 전체 실행에 포함되지 않았다.
- 수정 후 새 HTTP 회귀와 web/ops: **22 passed / 8.36초**. 고정 세대의 실패1건·해당 key·실행 로그가 일치한다.
- Ruff sb/tests 통과, basedpyright sb/web.py 오류0/경고0.

수정 후 전체 스위트 통과로 확대하지 않는다. 운영 배포 및 실제 사용자 공통 기억 인수는 남는다.
