# W3.2 설치 후보 `14a6ed7`

운영 app root를 쓰지 않았다. `current`를 바꾸지 않았다.

```bash
TMPDIR=/var/tmp python deploy/prepare-release.py /var/tmp/sb-candidate-8de4c6b --offline
```

EXIT 0. 로그 `/var/tmp/sb-candidate-8de4c6b-build.log`.

| 핀 | 값 |
|---|---|
| 경로 | `/var/tmp/sb-candidate-8de4c6b/releases/14a6ed7ce284fa24a4e8157b97302f5d5786a275` |
| release_id | `14a6ed7ce284fa24a4e8157b97302f5d5786a275` |
| wheel SHA-256 | `1db842dc4aec6bd5ec222f8bb96d9a4037e648938909faeee81e51feb52d04a5` |
| source_commit | `8de4c6b0862f00ed00b33828f082aef1a9096fa3` |
| source_tree | `33a8bcdbb30ec274ef87796f33c0120277d9b264` |
| materialization | `git-archive` |
| recipe SHA-256 | `4742bcc1cbc897082e1e44a5f7fdf7580767ba42aaa46405fbd8058b334ab775` |

이전 비교 기준 `c04dee1` / wheel `ac8fcd16…`는 그대로 둔다. 이 후보 wheel의 site-packages에 `activation-orphans`, `_divert_to_proposed`, `revoked_keys.py`가 있다. `bin/sb --help` exit 0.

`working_tree_modified: true`는 준비 시점 작업 트리에 미추적 bak이 있어서다. 재료는 git-archive HEAD다.

JARVIS 의존성 artifact·`check-release-integration`·유지보수 인수는 아직이다. 전환 대상 링크를 이 후보로 덮지 않았다.
