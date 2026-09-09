# 릴리스 입력 ID에 준비 절차 결합 — 2026-09-09

sb-release-inputs-v2는 wheel/requirements/Python runtime을 구분했으나 준비 도구 변경은 구분하지 않았다. uv 앱 설치를 pip로 바꾸거나 bytecode 방식을 바꿔도 같은 ID가 나올 수 있었다.

v3는 prepare-release.py, bundle_python_runtime.py, check-release-contents.py의 실제 파일 SHA256을 정렬된 JSON으로 결합한 preparation_recipe_sha256을 추가한다. 각 파일 해시와 결합 해시를 release-manifest.json에도 기록한다. 기존 v2 후보를 덮어쓰거나 새 방식으로 검증됐다고 소급 표기하지 않는다.

검증: 관련20개 통과/0.34초, Ruff(helper/tests)·diff check 통과. runtime 동일/recipe 변경 시 ID가 달라지는 회귀를 확인했다. 실제 새 후보의 기록된 도구 해시3개와 현재 바이트를 직접 비교했다. 실제 설치본 TLS/gateway/CLI/MCP4경로 및 전후 후보 내용 동일성 검사 통과. [실측 결과](RELEASE-RECIPE-IDENTITY-2026-09-09.json).

후보: `/var/tmp/sb-recipe-bound-13p4j7ow/releases/bbc398e8b6e64965922028ee1bb5028b9087454d`.

이 ID는 명시된 빌드 입력 식별자다. uv/OS 전체 공급망·호스트 간 재현성·정본 봉인·실제 운영 인수를 모두 증명하는 식별자가 아니다. 준비 중 실행 소스가 바뀌지 않는다는 전제가 있으며 악의적인 동시 소스 변경 방지는 별도다. 현재 source archive는 c94958b, 준비 도구는 이번 변경 바이트를 사용했다. 운영 current/DB/서비스 변경 없음.
