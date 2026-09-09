# 최신 자비스 설치 후보 연동 검증

자비스 커밋 `195b1a7d4588a8386def5e7dce2067a141942708`을 git archive로 새 디렉터리에 추출하고 TypeScript를 컴파일했습니다. 소스 archive SHA256은 `40e0ed0fccaa10d549e8945a6113be7c42676344b70c2a969c49c65231e8d333`입니다. 의존성은 기존 검증 후보에서 복사했고 네트워크 설치는 수행하지 않았습니다. 후보 `/var/tmp/jarvis-current-pair-_mq15nmd/source`의 링크 32개는 모두 내부를 가리킵니다.

정본 manifest가 있는 SB d7373ab 설치본과 `deploy/check-release-integration.py`를 실행해 exit 0을 확인했습니다. 실제 TLS·gateway·별도 Python·CLI·MCP를 거치는 4개 경로에서 정상 쓰기/조회, 접수 중 철회, 실행 전 철회, 실행 전 만료 처리가 통과했습니다. 정상 경로는 provider proved, 자비스 settled, control completed이며 settlement/attempt 각각 1개입니다. 새 로그인 후 독립 stdio 클라이언트 2개가 각각 기억 2개를 조회했고 reader 철회 후 403이 확인됐습니다. 모든 경로의 외래 키 오류는 0입니다.

검증 전후 provider 18,457개 항목, 자비스 19,588개 항목 및 Node 실행 파일이 동일했습니다. 전체 구조화 결과와 소스 증거는 동명 JSON에 기록했습니다.

한계: 신원 전달·업무·시각은 fixture이고 native 모델 호출은 0입니다. 서로 다른 실제 모델의 사용자 업무 기억 인수로 간주하지 않습니다. SB 후보는 d7373ab이며 후속 복원 수정 cef3a56/1b62d2e는 포함하지 않습니다. 이 결과는 최신 자비스 소비자 코드와 기존 정본 provider 후보의 호환성 증거입니다. 최신 provider 재빌드, 자비스 정본 manifest/재현성 및 운영 배포 인수는 남습니다. 운영 서비스·DB·설정은 변경하지 않았습니다.
