# 참고 문맥 제출 재검사 — 구현과 실제 모델 인수

자비스 제품 `8e233c7802511fff13b9571ed182f1c7b547cf74`, SB 인수 도구
`4e3a8de876480ed1e4bb4007a4bd8cf44e32daf0`. [이전 사본 재전송 재현](REFERENCE-MODEL-LIFECYCLE-2026-09-08.md)의
후속 구현이다. [상세 증거 JSON](REFERENCE-SUBMISSION-ACCEPTANCE-2026-09-08.json)을 함께 보존했다.

**자비스 reader가 발급한 문맥을 한 번 제출하고, 제출 직전과 callback 완료 뒤에 재검사하는
경로를 구현했다. 영구 전달 영수증·세션 전체 중복 억제·compaction은 아직 미완료다.**

## 1. 바뀐 동작

`MemoryReferenceReader.read()`의 기존 결과와 wire 계약을 유지하고 같은 reader의 `submit()`을
추가했다. 호출자는 같은 runtime 안에서 read→submit을 연결한다. 기존 `memory context` CLI의
JSON을 따로 보관했다가 직접 모델에 보내는 행위는 이 보호 경로를 거치지 않는다.

| 입력/상황 | 새 동작 |
|---|---|
| reader가 발급한 원래 객체 | 내부에 보관한 직렬화 본문과 generation/privacy snapshot을 사용 |
| 객체 복사·다른 reader·본문 변조 | `MEMORY_REFERENCE_SUBMISSION_INVALID`, callback 미호출 |
| 같은 객체의 동시 제출·재시도 | 첫 await 전에 한 번 소비. 두 번째 호출 거부 |
| 준비 후 정정·삭제·개인정보 변경·키 철회 | provider와 로컬 상태를 재검사하여 제출 거부 |
| callback 실패 | `MEMORY_REFERENCE_SUBMISSION_UNCONFIRMED`, 같은 객체 재제출 불가 |
| callback 완료 전후 정정·삭제·만료 | 후속 재검사에서 실패하여 callback 결과를 반환하지 않음 |
| 빈 결과 또는 전체 항목 생략 | checked_at 이후 최대 60초. no_data/record의 더 짧은 만료도 적용 |

상태는 WeakMap으로 해당 객체 수명에 결합하며 새 원문 DB·MCP 도구·migration을 추가하지 않았다.
호출 중 SQLite transaction을 열어 두지 않고, 검증된 본문 문자열만 callback에 준다.
이미 제출한 본문·callback 내부 로그·모델 서비스의 데이터를 되돌리거나 지운다는 기능은 아니다.

최대 60초는 이 제출 경로의 유효 기간이다. 긴 모델 요청이 이를 넘으면 결과를 제공하지 않는다.
provider status 관측과 로컬 처리 사이에 전역 원자적 잠금이 없으므로, 관측 직후 다른 프로세스의
변경까지 원천 차단했다고 주장하지 않는다. 장기 세션은 별도 수명/전달 원장 계약을 필요로 한다.

## 2. 실제 모델 인수

새 격리 자비스 빌드의 production reader→실제 SB MCP→native Codex 모델을 연결했다.
각 모델 요청은 합성 자료를 사용하는 독립 ephemeral 세션이고 도구 호출은 비활성화했다.
이번 guarded 모드는 CLI 출력 경로가 아니라 production reader의 동일 runtime을 사용한다.

| 인수 | 관측 결과 |
|---|---|
| 빈 결과 정상 제출 | 실제 모델 `no_data` |
| 최초 기억 정상 제출 | 임의 확인값과 정확한 record/source/generation 회수 |
| 준비 후 정정 | 이전 미제출 객체 거부. 해당 prompt/model 로그 파일이 생성되지 않음 |
| 정정된 기억 정상 제출 | 새 값과 새 출처 회수 |
| 모델 callback 중 삭제 | 모델은 삭제 이전 문맥으로 응답했지만, 삭제 proved 후 guard가 결과 반환을 거부 |
| 삭제 후 새 조회·제출 | record 0개, 실제 모델 `no_data` |
| 이미 제출한 최초 객체 재전송 | 재전송 거부. 추가 prompt/model 로그 파일 미생성 |

다섯 native 모델 요청이 완료됐고 전체 인수 프로세스 exit 0이었다. 정정·삭제는 기존 자비스
V2 target/chain/request와 실제 SB executor를 사용했으며 proof/observation 검증도 유지했다.
owner 확인은 synthetic fixture이므로 실제 승인 화면·운영 Control Plane 전체 인수는 아니다.
`during-delete`의 모델 출력은 인수 증거용으로만 관측했으며 guard의 정상 반환 결과가 아니다.

원시 결과 `/var/tmp/sb-reference-model-89azeB/result.json`, 로그
`/var/tmp/sb-reference-model-guarded.log`. 새 빌드는 `/var/tmp/sb-reference-submit-build-verified`다.
빌드 기준 HEAD `8efb2b4`에 현재 제품 소스를 포함했고 tsc 재컴파일의 산출물 동일성 및 실제 실행
중 SB Python/자비스 compiled JS의 해시 불변을 확인했다. 마지막 경계 테스트 추가는 제품 소스를
바꾸지 않았다. 사용자 작업의 운영 문서 커밋은 보존했다.

```bash
cd /home/jm/orca/projects/second-brain-app
TMPDIR=/var/tmp node scripts/jarvis-reference-model-acceptance.mjs /var/tmp/sb-reference-submit-build-verified --guarded
```

## 3. 회귀와 독립 검토

- reader 제출·기존 읽기·reference 본문 3개 파일: **70 passed**, 28.86초.
- Node native event 감사기 **14 passed**, 수정 스크립트 syntax 통과.
- 자비스 backend tsc 및 변경 reader/test ESLint 통과. 전체 backend/GUI 테스트 통과 주장 아님.
- 저장소의 구현/검토 모델 분리 규칙에 따라 `gpt-5.6-sol`이 read-only 검토했다.
  빈 결과 만료 누락, 변조 객체의 잘못된 오류 분류/transaction 내부 getter 실행을 지적했고 수정했다.
- 중간 수정에서 current outcome에 없는 fresh_until 필드를 읽은 타입 오류와 회귀 실패가 있었다.
  조건 분기와 유한 60초 한도로 고쳤으며 최종 70개 통과만 완료 증거로 사용한다.
- 최종 독립 재검토는 actionable finding 없음을 확인했다. 추가 권고인 전체 항목 생략 결과의
  정확한 60초 경계 검사도 반영했다. reviewer가 테스트를 실행한 것으로 보고하지 않는다.

## 4. 이어서 필요한 구현

이번 결과는 [전달 수명 계약](REFERENCE-DELIVERY-LIFECYCLE-CONTRACT-2026-09-08.md)의 제출 전후
검사와 객체 단위 한 번 시도에 해당한다. 다음 항목은 아직 없다.

1. 같은 세션/epoch의 여러 객체·프로세스·재시작을 묶는 영구 전송 claim과 native 확인 영수증.
2. 실제 client session/turn/compaction 관측과 확인 후 중복 억제, 불확실 전송의 복구.
3. 기존 context/projection에 전달 계보를 결합하고 삭제된 세션의 후속 사용을 차단하는 처리.
4. CLI 외 실제 앱 요청 경로의 guard 채택, 범위 분류·원본 차단·운영/DR의 전체 인수.

자비스의 해당 세 context/projection 테이블은 이번 인수에서도 0행이다. WeakMap은 그 영구
원장을 대신하지 않는다. 전역 자동 주입·장기 세션 공유·자동 task 수집은 관련 선행 조건이
완성되기 전까지 보류한다. 실제 사용자 질문과 검색 지연·GUI·운영 전환의 기존 목표도 유지한다.
