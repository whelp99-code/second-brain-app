# 운영 전환 서비스 경계 — 2026-09-09

읽기 전용 systemctl 조회로 실제 구성을 조사했다. 중지·mask·재시작·설정 변경은 실행하지 않았다. 이 문서는 정본 `../Orca-JARVIS/docs/personal-os/release.md`의 전환 절차를 구체화하기 위한 준비 자료이며, 실행 승인이나 완성된 배포 절차가 아니다.

## 확인된 재기동 경로

- `jm-jarvis-dashboard.service`는 `Wants=jm-jarvis.service`, phone gateway는 `Requires=jm-jarvis-dashboard.service`다. authority만 중지한 상태를 전체 정지로 간주하면 안 된다.
- authority와 dashboard는 Restart=always, phone gateway와 SB web은 on-failure다. MainPID만 강제 종료하는 방법 대신 systemd 단위의 정지와 트리거 제어가 필요하다.
- backup·portfolio·refresh·maintenance timer와 요청 path가 활성 상태다. 대응 oneshot이 현재 inactive여도 이후 실행될 수 있다.
- `second-brain.timer`는 이번 관측에서 inactive지만 enabled다. 현재 상태만으로 이후 재활성화 가능성이 제거되지 않는다.

## 추가한 검사

`python deploy/check-transition-units.py`는 관련 서비스/timer/path 18개의 LoadState, ActiveState, SubState, MainPID, ControlPID, Job을 읽는다. loaded/inactive/dead가 아니거나 실행 PID·대기 job이 있으면 exit 1이다. 현재 운영에서는 실제 활성 단위 때문에 exit 1이며 정상적인 보류 결과다. 활성 timer, 시작 중 서비스, PID, control PID, job, 없는 단위와 정지 상태를 검증한 테스트 7개가 통과했다.

검사 범위는 명시된 단위뿐이다. 수동 실행 프로세스·원격 클라이언트·DB 열린 descriptor·다른 cgroup·향후 재기동을 검증하지 않으므로, 이 검사만 통과했다고 DB 전환을 허용하면 안 된다. side-notch와 mail relay 등 다른 제품 서비스는 임의 중지 대상으로 포함하지 않았다. 별도 DB 접근 여부를 조사해야 한다.

## 전환 절차에 반영할 순서

1. 실제 계정 입력과 신규 요청 유입을 정지시키는 경계를 준비하고, 불확실한 outbox·진행 중 작업·scheduler cursor를 기록한다. 요청의 결과가 불확실하면 재전송하지 않는다.
2. 관련 timer/path를 먼저 정지·재활성화 방지하고 gateway/dashboard, 수집·유지보수·요청·백업 실행과 authority/SB web을 정리한다. 변경 전 enabled/active 상태를 기록해 복구 시 임의로 disabled 단위를 켜지 않는다.
3. 위 읽기 전용 단위 검사와 별도의 전체 프로세스/DB 접근 검사를 수행한다. 중지 중에도 새 job이 생기면 전환을 보류한다.
4. 정지된 시점의 일관된 백업, 후보 봉인·계약·migration vector와 전체 release gate를 확인한 후에만 DB 전환을 검토한다. current 변경과 서비스 활성화는 명시적인 운영 전환 단계다.
5. 구버전은 새 DB를 거부하지 않는 것으로 재현됐다. 따라서 새 DB에 구버전을 연결하는 롤백을 허용하지 않는다. 이전 DB 복원도 전환 후 발생한 쓰기의 보존·대조 계획 없이는 수행하지 않는다.
6. 새 서비스의 doctor/status/dashboard/MCP, 실제 계정 쓰기·다른 세션 읽기와 철회, scheduler/uncertain outbox를 검증한 뒤 원래 의도한 트리거만 복구한다.

전체 프로세스 경계, 실제 계정 연결, 봉인된 배포본과 복구 실행 검증은 아직 미완료다. 운영 데이터와 서비스는 그대로 유지했다.
