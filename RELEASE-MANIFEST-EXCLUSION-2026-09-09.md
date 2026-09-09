# 자비스 정본 release manifest 제외 범위 수정 — 2026-09-09

운영 후보를 기존 Personal OS manifest 형식으로 묶기 전에 생성기를 대조했다. walk가 basename이 release.manifest.json인 모든 경로를 제외하고 있었다. 루트 파일1개라는 self_exclusion 선언과 달리 하위 파일·같은 이름 디렉터리의 전체 내용을 해시에서 빠뜨릴 수 있었다. 루트 심볼릭 링크도 제외되어 writeReleaseManifest의 후속 쓰기가 링크를 따라갈 수 있었다.

JARVIS personal-os-release-manifest.ts를 수정해 루트의 일반 manifest 파일만 제외한다. 같은 이름의 하위 항목은 정상 순회·해시하며 루트 제외 대상이 symlink나 일반 파일 아닌 항목이면 거부한다. 동시 교체 공격 전체를 해결한 봉인 도구라는 뜻은 아니다.

검증: 수정 전 nested 파일 누락 회귀 실패, 수정 후 manifest/compatibility **7개 통과**, ESLint 경고0, 별도 /var/tmp TypeScript emit 통과. 빌드된 모듈의 별도 실제 Node 실행에서도 nested/release.manifest.json/payload.js 변경 시 digest 변화, 루트 symlink 거부·대상 내용 보존을 확인했다. 이 실행의 provenance metadata는 합성 fixture이며 운영 manifest를 생성한 것은 아니다.

기존 provider 후보의 외부 Python 실행기 링크는 이 manifest의 내부 링크 전용 조건과 아직 맞지 않는다. 재현성·offline cache 증거 필드도 실제 근거로 채워야 한다. 임의 성공 receipt나 형식 완화로 봉인 처리하지 않는다. 운영 전환 및 전체 공통 기억 인수는 계속 미완료다. 운영 current/DB/서비스 변경 없음.
