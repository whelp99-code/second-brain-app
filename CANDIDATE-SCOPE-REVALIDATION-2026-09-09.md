# 후보 범위 제안 재검증

2026-09-09. JARVIS 제품 `be2c012`.

## 변경과 이유

기존 범위 제안은 생성 시점의 후보 digest에 결합됐지만 저장된 제안을 나중에 검토할 때 사용할 재검증 함수가 없었다. 또한 격리된 후보와 후보 생성 이전 시각을 제안 생성에서 차단하지 않았다. 기존 삭제·격리 원장을 재사용해 두 경우를 차단했다.

`validateMemoryCandidateScopeProposal`은 입력 필드·시각·현재 후보의 무결성·격리 상태를 확인하고 현재 후보에서 재구성한 제안과 전체 canonical bytes를 비교한다. 프로젝트·분류·출처·만료·authorization·추가 필드가 달라진 제안을 거부하며 반환값은 동결된 새 객체다. 입력 DB와 저장된 v1 분류를 변경하지 않는다.

이는 제안의 무결성과 현재 후보 상태 검사다. 현재 프로젝트 정책을 승인하거나 작업 성공 증거의 유효성을 다시 발급하는 기능은 아니다. 유효한 제안도 `authorization=not_granted`이며 새 프로젝트로 새 제안을 만드는 행위 자체를 권한으로 취급하지 않는다. 이후 실제 승인과 dispatch는 후보의 현재 작업 근거·정책·동일 제안 digest를 다시 결합해야 한다.

## 실제 실행 검증

- 집중 테스트 2 passed / 3.61초. 신규 경계: 직렬화 왕복, 프로젝트/authorization/추가 필드 변조, 만료, 미래 시각, 후보 생성 전 시각, 제안 이후 격리.
- TypeScript noEmit·격리 outDir emit, 변경 파일 ESLint, JS 구문·diff 검사 통과.
- 격리 DB에 검증된 fixture 후보를 저장하고 컴파일된 제품 코드를 별도 Node 프로세스 3개에서 실행했다. 같은 DB를 새로 여는 정상 제안 수락, 프로젝트 변경 거부, DB 격리 반영 후 기존 제안 거부를 확인했다. 검증 전후 테이블 행 수 불변.
- 최초 실행은 SB cwd에서 fixture 상대 정책 파일을 찾지 못해 실패했다. fixture가 요구하는 JARVIS cwd에서 다시 실행해 성공했으며 helper 주석과 아래 재현 명령에 이를 명시했다.
- [기계 판독 결과](CANDIDATE-SCOPE-REVALIDATION-2026-09-09.json), [재현 helper](scripts/candidate-scope-acceptance.mjs).

```bash
cd /home/jm/orca/projects/Orca-JARVIS
TMPDIR=/var/tmp node /home/jm/orca/projects/second-brain-app/scripts/candidate-scope-acceptance.mjs "$(cat /var/tmp/cancellation-material-build-path.txt)"
```

marker는 검증 시 사용한 임시 격리 build 위치다. 다른 환경에서는 같은 제품 커밋을 별도 outDir로 컴파일한 경로를 직접 전달한다. 운영 dist/DB를 사용하지 않는다. 실제 사용 방식의 제품 API·프로세스·DB 검증이며 실제 모델/운영 로그인/HTTP 저장/영수증 인수는 아니다.

## 보류 및 다음 구현

`memory.confirm`의 기존 확인 family·receipt·dispatch identity에 프로젝트 필드만 덧붙이는 방식은 보류한다. 기존 승인의 의미와 provider idempotency를 바꾸고 이전 승인을 다른 범위에 재사용할 여지가 있다. 기존 control plane의 버전 계약을 확장하고, 같은 proposal digest가 승인→요청→불변 source 분류→완료 영수증에 연결되도록 구현해야 한다. 새 별도 승인 엔진은 도입하지 않는다.

이번 API는 아직 CLI/HTTP 승인 진입점에 연결되지 않았다. capabilities의 writes_supported=false를 유지하며 scoped 쓰기 전체 목표를 완료 처리하지 않는다. 운영 설정·서비스·데이터 변경 및 push는 하지 않았다.
