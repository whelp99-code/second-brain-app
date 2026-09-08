# 벡터 재생성의 경로 보호·종료 복구와 보류 판정

2026-09-08. SB를 공통 기억 정본으로 유지하는 인계 방향의 B8 선행 수정이다.
관리형 세대의 의미 검색은 아직 비활성 상태이며, 이번은 standalone vectors 재생성 경계다.
제품 커밋 `d152819`. [기계 판독 가능한 인수 결과](VECTOR-RECOVERY-SAFETY-2026-09-08.json).
sb 소스 SHA256: `3cd2e70dcc2b362ef0ebfe029787b30bdb4bc5bbf38994150257b6b9936af08c`.

## 현재 통합 상태 대조

자비스 HEAD `010281c`에서 `memory-reference*`, `personal-context-store.ts`,
`memory-projection-bindings.ts`의 마지막 변경은 `63bdd02`였다. 해당 경로의
`63bdd02..HEAD` 차이는 없었다. 최근 일일 실행/추천 조회 수정과 참고 기억의 세션 전달 수명
완료는 구분한다. 자비스 파일과 운영 DB는 이번에 수정하지 않았다.

SB `generations.py`는 벡터 논리 manifest를 enabled=false/rows=0으로 생성하고,
물리 DB에도 CHECK(enabled=0)을 유지한다. `SearchIndex.search`의 봉인 분기는 lexical이다.
별도 rebuild 성공이나 hybrid 설정만으로 공통 MCP의 의미 검색을 활성화할 수 없다.

## 수정·개선 목록

| 우선순위 | 확인한 문제 | 구현과 결과 |
|---|---|---|
| P1 | `.sb`가 심볼릭 링크인 경우 외부 vectors.db를 덮어쓸 수 있음 | 비공개·동일 소유자 vault 확인, `.sb` O_NOFOLLOW 디렉터리 열기, 외부 marker 보존 |
| P1 | 재생성 중 `.sb`가 교체되면 게시/실패 정리가 바뀐 경로를 사용 | 디렉터리 inode 재확인, 임시 파일 생성·replace·정리를 열린 디렉터리 기준으로 수행 |
| P1 | os._exit/SIGKILL 후 임시 DB와 journal/wal/shm 잔류 | 기존 writer 잠금 아래 예약 이름의 전체 목록 검증 및 조건부 회수. 사용 중/안전하지 않은 파일은 보존; 관측 불가 시 회수 보류 |
| P1 | 사후 SQL 검증 자식에 writer 잠금 descriptor 미전달 | SQL 작성에 더해 사후 검증 프로세스도 descriptor 상속. 부모 종료 후 쓰기/검증 자식의 잠금 수명 유지 |
| P2 | replace 후 directory fsync 실패를 일반 I/O 오류로만 표시 | `vector database replaced; durability unconfirmed`로 이미 교체됐으나 내구성 미확정임을 구분 |
| 호환성 | 내부 `.sb`의 0775를 무조건 거부하면 정상 CLI fixture도 실패 | 상위 vault 0700 경계를 검증하며 기존 inner umask는 허용. vault 자체의 공개 권한은 거부 |

새 파일은 0600이며 생성 당시 inode·단일 link·소유자·권한을 게시 전에 확인한다. 게시된
vectors.db 및 이름이 일치하지 않는 파일은 crash cleanup 대상이 아니다. 정상 실패의 정리는
자신이 만든 임시 파일/sidecar로 한정하며, 디렉터리 교체가 있어도 원래 descriptor를 따른다.
기존 SQLite reader는 이전 파일을 계속 읽고, 새 reader는 완성된 새 파일을 읽는다.

## 자동 회수의 보류 조건

기존 tempfile의 8자 이름과 신규 UUID 32자 이름 및 SQLite sidecar만 예약 영역으로 취급한다.
전체 선택 목록의 regular file·단일 link·소유자·private mode·장치를 먼저 확인하고, 제거 직전
metadata를 다시 대조한다. 도중 unlink가 실패하면 다음 잠금 획득에서 남은 파일만 재시도한다.

이 호스트에는 같은 UID지만 `/proc/<pid>/fd` 관측이 거부되는 프로세스가 실제 존재했다.
**이를 무시하여 안전한 삭제로 보고하지 않는다.** 확인 가능한 사용 중 파일은 재생성을 거부하고,
전체 reader 관측이 불가능하면 임시 파일은 모두 남기며 경고 후 새 재생성만 수행한다.
`/proc`이 없는 환경도 같은 회수 보류 정책이다. root 권한 실행·프로세스 종료·권한 완화는 하지 않았다.

완전한 reader 목록을 주입한 결정적 검사에서는 sidecar 제거·중단 후 재시도가 통과했다.
그러나 아래 실제 CLI에서는 임시 DB 1개가 남았고 `cleanup_complete=false`다.
따라서 **이 호스트의 crash 잔여물 자동 회수 및 물리 삭제 완료는 미완료/보류**다.
관측 이후 외부 프로세스가 임의로 파일을 여는 것까지 막는 별도 권한 체계는 도입하지 않았다.

## 검증 근거

- 최초 경로/회수 보호 7건 실패: `/var/tmp/sb-vector-recovery-before.log`.
  경로 우회는 기존 결함이며 회수·reader 보존은 신규 완료 조건의 기준선이다.
- 기준 커밋 `9ef414f`의 vector_rebuild 모듈을 별도 프로세스에 고정해 최종 경로/디렉터리 교체/
  fsync 상태 검사 3건의 실패도 확인했다. `/var/tmp/sb-vector-recovery-pinned-before.log`.
  현재 제품 파일은 바꾸지 않은 독립 기준 실행이다.
- 최종 집중: **97 passed/1 skipped, 7.29초**.
  `/var/tmp/sb-vector-recovery-focused-final-2.log`. optional sqlite-vec 설치 환경에서 실제 SQLite를
  사용하며 skip은 실제 모델 opt-in smoke다. 모델 품질 검증으로 계산하지 않는다.
- 부모 프로세스 os._exit(17) 뒤 자식이 물려받은 잠금을 유지하는 동안 두 번째 writer가 거부되고,
  파이프 신호로 자식 잠금을 해제한 뒤 재생성이 성공했다. sleep 없는 실제 프로세스 검사다.
- 링크/hardlink/디렉터리/public 잔여물, 열린 임시 파일, 디렉터리 교체, unlink/fsync 실패,
  정상 내부 umask와 공개 root 거부를 검증했다. Ruff·변경 파일 타입 0 errors/0 warnings.
- 실제 CLI: `/var/tmp/sb-vector-recovery-hkcpa0ah/result.json`,
  `/var/tmp/sb-vector-recovery-native-final.log`.
  SQL 완료 직후 강제 종료 exit 17 → 이전 DB 바이트 및 검색 유지 → 재시도 exit 0, 4 vectors.
  기존 열린 reader 3행/새 reader 4행, `.sb` 링크 경로 exit 1/stdout 0/외부 파일 불변.
  reader 관측 한계의 경고 및 임시 DB 보존도 실제 출력으로 확인했다.
- 기존 hybrid CLI 필터·candidate·정정 전 vector 제외 5시나리오 통과:
  `/var/tmp/sb-hybrid-filter-xbupllrz/result.json`, `/var/tmp/sb-vector-recovery-hybrid-final.log`.
  검색 과정의 vector DB 바이트 불변. 봉인 hybrid/운영 활성화 증거가 아니다.

초기 native 인수는 내부 0775 권한 거부로 실패했고 이를 수정했다. 해당 코드의 전체 회귀는
SIGTERM/exit 143으로 중단했으며 통과 수치에 포함하지 않는다. 최종 전체는
**874 passed/2 skipped, 198.06초**, `/var/tmp/sb-vector-recovery-full-final.log`.
리포 기본 명령의 `--ignore=tests/test_embeddings.py`를 적용했고 해당 optional 모듈은 위 집중
검사에서 별도로 포함했다. 집중/전체의 중복 테스트 수를 합산하지 않는다.

## 다음 필수 개발과 보류

1. 봉인 vector의 실제 행/모델 identity·논리/물리 digest와 같은 generation pin을 연결한다.
2. MCP의 record 선택은 현재 lexical 단어 일치를 요구한다. 의미 후보의 record/citation 선택,
   필터·삭제·정정·복원까지 같은 결과 계약으로 검증해야 하며 설정만 켜는 변경은 보류한다.
3. 실제 한국어 질문·모델·대규모 인코딩 메모리/지연을 기준 lexical과 비교한다.
4. 관측 제한 환경의 잔여물은 삭제 완료로 보고하지 않는다. 기존 writer/reader 수명 증거를
   보강하는 별도 복구 설계가 필요하며 광범위 glob 삭제는 보류한다.
5. 자비스 C6~C8 세션 전달·compaction·삭제/범위, B4~B8 실제 클라이언트·운영 전환/DR 및
   기록/재정규화 지연의 기존 미완료 조건을 유지한다.

운영 서비스·실제 vault·DB migration·모델 다운로드·push는 수행하지 않았다.
