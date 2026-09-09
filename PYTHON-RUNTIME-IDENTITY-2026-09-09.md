# Python 런타임 입력 식별 — 2026-09-09

기존 release_id는 wheel과 requirements만 결합해 외부 Python 버전/내용 차이를 구분하지 못했다. 런타임 내부 포함 이후에도 같은 빈틈이 남아 있었다.

준비 단계에서 먼저 런타임을 private staging에 복사하고, 경로별 내용·권한·내부 링크의 inventory를 sb-python-runtime-v1 도메인으로 해시한다. staging 절대 경로는 포함하지 않는다. wheel/requirements 해시와 runtime 해시를 sb-release-inputs-v2 도메인으로 결합한40자리 ID를 사용한다. manifest에 release_id_scheme과 python_runtime_input_sha256을 기록한다. 목적지 이동/복사 후 digest를 다시 대조한 뒤 bytecode 생성과 설치를 진행한다.

검증: 관련20개 통과/0.33초, Ruff(helper/tests) 및 diff check 통과. 같은 runtime을 다른 위치로 복사해도 digest가 같고 내용 변경 시 digest와 release_id가 달라지는 회귀를 확인했다.

실제 준비 도구를 서로 다른 두 임시 app root에서 실행했다. 둘 다 **18e9d889f90cc595533f1f5317b140e95cec9e14** 및 같은 runtime 입력 해시를 생성했다. 첫 후보의 실제 TLS/gateway/CLI/MCP4경로 및 후보 전후 동일성 검사 exit0. [원시 결과](PYTHON-RUNTIME-IDENTITY-2026-09-09.json).

전체 설치 inventory도 비교했으며 **5,395항목 차이**를 확인했다. 입력 ID 일치가 최종 산출물의 바이트 단위 재현성을 입증하지 않는다. pyc와 실행 경로 등 설치 산출물 차이는 JSON에 분리 기록했다. 해당 차이를 검사에서 제외하거나 정본 reproducibility receipt를 성공으로 만들지 않았다. 최종 정본 manifest/봉인·재현성·운영 전환 및 실제 사용자/에이전트 인수는 미완료다. 운영 current/DB/서비스 변경 없음.
