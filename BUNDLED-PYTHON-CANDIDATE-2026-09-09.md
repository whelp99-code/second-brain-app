# Provider Python 런타임 내부 포함 — 2026-09-09

기존 provider .venv의 실행기 링크는 외부 uv Python 설치를 가리켰다. JARVIS 정본 manifest의 내부 상대 링크 조건에 맞추기 위해 prepare-release가 로컬 uv-managed Python3.12 런타임을 후보의 runtime/python에 복사하고 그 실행기로 venv를 만들도록 개선했다. 자동 다운로드는 끈다. venv 실행기 링크는 내부 상대 링크로 교체하고 표준 라이브러리와 설치 의존성의 bytecode를 사전 생성한다.

bundle_python_runtime helper는 파일 수20,000·일반 파일 합계1GiB를 넘으면 거부한다. 외부/절대 링크, 끊어진 링크, FIFO 등 특수 파일은 복사 전에 거부한다. 기존 설치본 전체를 복사하므로 Python LICENSE.txt와 배포본 내 pip/vendor license 파일도 유지된다. 원본 Python 설치는 재구성하거나 제거하지 않았다. 신뢰된 정지 상태의 로컬 배포본을 복사하는 도구이며 복사 도중 악의적 원본 교체를 막는 기능은 아니다.

후보: `/var/tmp/sb-contained-python-w2d7tar3/releases/16c2c6248a07c8abccd76725acb0a520d5b17b20`.

검증:

- 원본 runtime 일반파일3,772개·105,084,713bytes, symlink1,048개·외부/절대0개 확인.
- 완성 후보 전체 symlink1,052개가 모두 내부 상대 경로. 실제 sys.base_prefix가 후보 내부 runtime/python. 실제 SSL·SQLite·SHA256 실행 성공.
- 실제 설치본 + JARVIS e6984ad의 TLS/gateway/CLI/MCP 4경로 통과, 후보 전후 내용 일치. 실제 설치 MCP4프로파일 초기화 통과.
- 관련19개 통과, 이후 helper의 파일 예산 검사를 순회 중 조기 거부로 바꾼 뒤 관련5개 재통과. Ruff/helper·테스트 및 diff check 통과. 5개는19개와 중복이다.
- [검증 결과](BUNDLED-PYTHON-CANDIDATE-2026-09-09.json).

이 후보는 source abb67b3의 git archive에서 앱을 빌드했고 이번 작업 중 수정한 준비 도구로 런타임을 포함했다. 완전한 빌드 provenance·재현성 receipt·정본 manifest 작성은 남는다. 현재 release_id는 기존 wheel/requirements 식별자이므로 같은 ID만으로 전체 런타임 동일성을 주장하지 않는다. OS 동적 라이브러리·Node·시스템 설정까지 묶은 완전 독립 환경도 아니다. 운영 current/DB/서비스 및 실제 계정/에이전트 상태를 변경하지 않았다.
