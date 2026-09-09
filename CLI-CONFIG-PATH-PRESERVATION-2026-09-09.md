# 독자 설정의 상대 경로 보존 — 2026-09-09

`read_config`는 vault_root를 고정하면서 Config를 새로 만들었으나 base_dir/source_path를 전달하지 않았다. 설정 파일 위치 대신 실행 프로세스의 작업 디렉터리를 기준으로 상대 경로를 해석했다. status/search/sources/retention/metrics/doctor 및 일부 dry-run 공통 경로에 영향을 줄 수 있다. 개별 명령 모두에서 잘못된 결과가 발생했다고 주장하지는 않는다.

수정 전 회귀 2개 실패:

- 설정의 knowledge_registry="registry.json"이 settings/registry.json에서 실행 디렉터리의 registry.json으로 바뀜.
- 실제 별도 `python -m sb.cli doctor --json`을 설정 디렉터리 밖에서 실행하면 존재하는 settings/notes를 다른 경로의 notes로 검사해 fail 반환.

dataclasses.replace로 vault_root만 교체해 raw의 다른 값·base_dir·source_path를 유지했다. 원래 config는 불변이다. 설정의 상대 경로 처리 규칙을 새로 정의하지 않고 이미 로드한 Config의 의미를 보존한다.

검증: 새 회귀 + CLI + CLI generation **55 passed / 5.19초**. 별도 CLI doctor에서 실제 원본 폴더의 정확한 경로와 pass를 확인했다. Ruff sb/tests 통과, basedpyright runtime_access 오류0/경고0, diff check 통과. 임시 vault/config만 사용했고 운영 파일은 변경하지 않았다. 실제 managed generation 전환 자체의 새로운 종합 인수를 뜻하지 않는다.

추가 관찰: source_policy_snapshot은 raw source root를 직접 읽는 별도 경로를 갖는다. 이 수정만으로 모든 진단 표면의 상대 경로 일관성이 완성됐다고 보지 않는다. 운영 배포·실제 계정/에이전트 인수도 남는다.
