# P17 — 통화·녹음 로컬 CPU 전사

명세 등록 / 구현·시험 NOT_RUN. Refs #3, #36. 선행 P03 #22, P10 #29. R2 (제안) / Capture·Core·QA / 4~6인일 추정(확정 일정 아님). 사건 계약은 P01 #20, 영속 접수·삭제 계보는 P02 #21을 따른다. 기준: 09-23 계획 작업 21·22, 대조 문서 3절.

## 목표
사용자가 명시적으로 공유한 통화 녹음과 음성 파일을 로컬에 원본 그대로 보존하고, 무료 CPU 로컬 모델로 전사본을 만든다. 전사본은 원본 audio에 묶인 별도 revision이며 사실 확정이 아니다. P03은 전사 상태를 별도로 둔다고만 했고 전사 worker는 범위 밖이었다. 지금은 통화 녹음 첨부 수집(`life_documents`, Phone History)만 있고 전사 worker는 없다.

## 구현 체크리스트
계획 21. 원본과 전사 입력 연결
- [ ] A-dot 표시는 사용자 선언과 실제 audio 검증이 모두 있을 때만 인정한다. 하나만 있으면 일반 첨부로 둔다.
- [ ] audio hash, 보관 locator, capture method, 발생 시각, 길이, 형식을 기록한다. 접수 시각과 발생 시각은 분리한다.
- [ ] 원본은 Phone History 로컬 저장소에 암호화 보존하고 export 문서에는 원문 연결정보만 넣는다. raw audio 외부 전송은 0이다.
- [ ] `attachment_retention_days=None` 기본값과 기존 원본 `expires_at` 해제를 인수한다. 설정과 migration 코드는 있으나 인수 근거는 없다.
- [ ] maintenance는 원본을 지우지 않는다. blob 삭제는 명시적 delete receipt 뒤에만 한다.
- [ ] audio identity 하나에 transcript revision 여러 개를 허용하고 pending/transcribed/partial/unavailable/failed를 구분한다. 미전사 음성은 기억 완료가 아니다.

계획 22. 로컬 전사 worker
- [ ] Phone History 선택 extra에 `faster-whisper==1.2.1`을 넣고 기본 설치에서는 뺀다. 전사는 별도 worker entry로 한 번씩 실행한다.
- [ ] multilingual small, CPU int8, 2 threads, worker 1개, `local_files_only`를 고정한다. 준비 manifest에 model revision·hash·license를 봉인하고 불일치면 실행하지 않는다.
- [ ] segment/word time span, 언어, 무음, 낮은 신뢰도, 불확실한 화자 구분을 그대로 남긴다. 단어나 문장을 사실로 승격하지 않는다.
- [ ] 같은 input hash와 model revision이면 재시작 후 결과를 재사용한다.
- [ ] model이 없으면 unavailable로 끝낸다. cloud fallback은 없고 worker network egress는 0이다.
- [ ] 전사 결과는 P01 계약 검증과 P02 영속 접수를 거치며 Vault 게시는 `sb.vault`만 한다.

## 코드·API
재사용(기존):
- `sb/connectors/life_documents.py`: 음성은 cursor에 `untranscribed`로만 남는다.
- `sb/life_phone.py`, `sb/life_attachments.py`, `sb/life_exports.py`, `sb/life_contracts.py`: `call_recording_imported`의 audio 필수 검사, audio MIME 검증, `audio_saved`·`audio_transcript` 사건 타입.
- `sb/life_config.py`(flag·source 정책), `sb/life_model_policy.py`(P10 local-only 판정).
- `sb/parsers/docling_worker.py`, `sb/parsers/docling_adapter.py`: 별도 프로세스 worker 선례.
- `phone-history/contracts/phone-event-v1.schema.json`, `phone-history/ios/Core/PhoneEvent.swift`, `phone-history/server/phone_history/`의 `models.py`, `crypto.py`, `service.py`, `repository.py`, `config.py`, `sink.py`, 그리고 `phone-history/pyproject.toml`.

신규 후보:
- `phone-history/server/phone_history/transcription.py`: worker entry와 manifest 검증 (신규 후보).
- `sb/life_config.py`의 flag 값 `local_transcription` (신규 후보).
- `phone-history/tests/test_transcription.py`, `tests/test_life_transcription.py` (신규 후보).
- `phone-history/contracts/fixtures/` 아래 한국어 라이선스 음성 fixture (신규 후보).

worker는 상주 daemon이 아니다. 기존 CLI나 타이머가 한 번 부르고 끝난다. 모델 파일은 운영자가 미리 준비한다.

## 인수시험
AC-01: 같은 audio 10회 재전송에 audio identity 1개, 같은 model revision의 transcript revision 1개. AC-03: 지연 공유 녹음의 발생·접수 시각 분리. AC-10: worker 실패·timeout은 partial/failed로 표시하고 전사를 지어내지 않음. AC-12: flag OFF, model 없음(unavailable), worker 장애를 서로 다르게 표시. AC-15: 원문 audio·전사본의 외부 모델 입력과 egress 0. AC-16: worker kill 뒤 원본·receipt 보존. AC-18: 삭제 후 복원·재접속에서 원본과 전사본 재활성화 차단. AC-21: rollback 뒤 원본·전사 revision·삭제 의도 보존. AC-23: audio 위장, 손상, 길이·크기 초과 차단. AC-24: 기존 회귀 통과.

작업 고유: `A 21 happy`(share/import event→audio identity→pending transcription), `A 21 failure`(위장·손상·중복·초과에서 분류된 오류와 원본 보존), `A 22 happy`(한국어 fixture 실제 전사, 화자 불확실성 포함, audio span 재생 연결), `A 22 failure`(무음·손상·model mismatch·worker kill에서 지어낸 확정자료 0, 원본 삭제 0). 시계 400일 전진 후 maintenance 원본 삭제 0도 본다. 증거는 `$E/T21/`, `$E/T22/`.

## 적용·중단·완료
`local_transcription` flag는 기본 OFF이고 전사 extra도 기본 설치에 없다. 선택한 출처 하나에서 시작한다.

제외: 전역 통화 녹음, iPhone 사설 DB 접근, cloud 전사와 fallback, 전사 단어의 사실 확정, 새 상주 queue·event bus, 원천 DB 쓰기. 원천 DB는 소유자 것이며 읽기만 한다. 인증 정보는 명세에 적지 않는다.

rollback은 flag OFF로 새 전사만 멈춘다. 원본 audio, receipt, 기존 transcript revision, 삭제 의도는 그대로 두고 pending은 pending으로 남긴다. egress 감지, manifest hash 불일치, 원본 손실이 나오면 즉시 OFF로 되돌린다.

완료 증거: requested/run/pass/fail/skip/not-run, 코드·model revision, 봉인 manifest, fixture license, egress 측정 로그, 테스트 로그. 증거 없이 #36을 닫지 않는다. 현 diff는 이 문서 1개이며 구현·시험 모두 NOT_RUN.
