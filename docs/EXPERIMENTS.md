# 장애 재현과 증거 해석

이 문서는 Linux·WSL에서 직접 실행하는 방법과 기존 제출 실험을 설명한다. Windows·macOS를 포함한 Docker 실습은 [튜토리얼](../TUTORIAL.md)을 따른다. Docker 안에서는 아래의 `unshare` 접두사를 사용하지 않는다.

## 실행 환경과 포트

Linux 일반 계정, Python 3.9 이상, Bash, procps(`ps`, `top`), iproute2(`ss`)가 필요하다. 필수 범위는 `MEMORY_LIMIT=50..512`, `CPU_MAX_OCCUPY=10..100`, `MULTI_THREAD_ENABLE=true/false`다. `yes/no`, `1/0`도 정규화해서 전달한다. 포트는 명세대로 15034로 고정한다.

현재 PC에서는 `unshare --user --map-current-user --net`으로 독립된 사용자·네트워크 네임스페이스를 만들어 포트 충돌을 해결했다. 앱의 UID는 1000으로 유지되고 내부 `0.0.0.0:15034` 바인딩이 6회 모두 성공했다. 기존 과제 VM과 서비스를 종료하지 않았다. CPU·메모리는 호스트와 공유하므로 완전한 자원 격리와는 구분한다.

```bash
unshare --user --map-current-user --net bash scripts/run-case.sh \
  --app vendor/agent-leak-app-x86 --case cpu-before \
  --duration 90 --interval 0.1 --snapshot-interval 5
```

이 문서의 나머지 직접 실행 명령도 현재 PC에서는 같은 `unshare` 접두사를 붙인다. 별도 실습 VM에서 포트가 비어 있으면 접두사 없이 실행할 수 있다. 사용자 네임스페이스를 금지한 시스템에서는 VM/컨테이너를 사용한다. [2026-09-16 포트 확인 기록](../evidence/port-check.txt)은 초기 환경 조사 기록이며, 최종 실행의 실제 바인딩 증거는 각 `snapshots.txt`에 있다.

실행 바이너리는 해당 환경의 아키텍처와 호환되어야 한다. 과제 1의 정상 앱을 과제 2 앱으로 이름만 바꾸어 사용하면 안 된다. ZIP이 제공되면 `unzip -l 파일.zip`으로 목록을 보고 실행 파일만 일반적인 방법으로 추출한다. 패키징된 실행 파일 내부를 풀거나 디컴파일하지 않는다.

## 한 쌍씩 실행

실제 앱의 Boot Sequence와 각 장애를 검증했다. 재현 시에는 먼저 OOM Before를 실행해 Boot Sequence 완료를 확인한다.

```bash
bash scripts/run-case.sh --app "$PWD/vendor/agent-leak-app-x86" \
  --case oom-before --duration 180
```

출력된 폴더의 `console.log`와 `app-logs/`를 읽는다. 정상 준비 로그도 없이 곧바로 종료되면 장애 재현이 아니라 부팅 실패다. 이 경우 환경·실행 권한·키·포트 문제부터 해결한다.

제출 비교의 관찰 상한은 90초였으며 CPU는 0.1초, OOM·Deadlock은 0.5초 간격을 사용했다. 기본 suite 예시와 제출 실행의 구체적인 차이는 manifest의 명령을 기준으로 한다.

`--duration`은 수집기가 허용하는 관찰 시간이다. 종료 시 증거 스냅샷과 정리 시간이 추가될 수 있어 명령의 전체 실행 시간과 조금 다르다. 180초에서 장애가 나타나지 않으면 Before/After를 **같은 관찰 상한**으로 늘려 재실행한다.

```bash
bash scripts/run-case.sh --app "$PWD/vendor/agent-leak-app-x86" \
  --case oom-before --memory-limit 128 --duration 900
bash scripts/run-case.sh --app "$PWD/vendor/agent-leak-app-x86" \
  --case oom-after --memory-limit 256 --duration 900
```

실측에서 CPU_MAX_OCCUPY=100은 Watchdog 종료, 40은 냉각·생존으로 이어졌다. 따라서 확정한 CPU 비교 방향은 **100 → 40**이며 보호 임계값 자체를 높이는 실험으로 해석하지 않는다.

CPU는 `--cpu-max-occupy`, 멀티스레드는 `--multi-thread`로 조정한다. 단일 비교에서는 관심 변수 하나만 바꾸고, 다른 값과 앱 SHA256·관측 간격·관찰 상한을 맞춘다. 기본 suite 설정이 맞는 것을 확인한 뒤 `bash scripts/run-suite.sh --app ...`로 6건을 자동 수집할 수 있다. 실험은 고정 포트 충돌을 막기 위해 순차 실행한다.

실행 도중 Ctrl+C를 누르면 자신이 시작한 프로세스 그룹에만 SIGTERM을 보내고, 기다려도 남아 있으면 SIGKILL로 정리한다. 결과에는 `interrupted`와 수집기가 보낸 신호를 남긴다. 일반 관찰 시간 만료도 같은 정리 절차를 거치지만 `observation_timeout`으로 기록한다.

## 지표를 읽는 방법

| 필드 | 의미 |
| --- | --- |
| `timestamp` | UTC ISO 8601 시각, 한국 시각은 UTC+9 |
| `elapsed_s` | 모니터 시작 후 단조 시계로 잰 경과초 |
| `pid` / `start_ticks` | PID와 커널 시작 틱. PID 재사용을 구분 |
| `ppid` / `pgid` | 부모 PID와 실험 프로세스 그룹 |
| `rss_kib` | `/proc/PID/stat`의 resident pages × 페이지 크기 / 1024 |
| `vms_kib` | 가상 주소 공간 크기. 실제 물리 메모리와 구분 |
| `mem_percent` | 대상 RSS / 호스트 MemTotal × 100 |
| `cpu_ticks` | 대상 프로세스의 user+system CPU 틱 누계 |
| `cpu_percent` | 두 샘플 사이 CPU 시간 / 실제 경과 시간 × 100 |
| `state`, `threads`, `wchan` | 프로세스 상태·스레드 수·커널 대기 지점 |

첫 샘플의 CPU는 빈 값이며 텍스트 로그에서는 `NA`다. CPU 100%는 논리 CPU 1개에 해당한다. 전체 CPU 수로 나누지 않는다. `%MEM`은 호스트 전체 메모리 대비 비율이므로 메모리가 큰 PC에서는 누수가 있어도 작은 수치로 보인다. OOM 분석의 주 지표는 **RSS 절대량과 시간 추세**다.

RSS는 커널의 근사 계측값이며 프로세스 전체의 물리 페이지 규모를 관찰하는 데 사용한다. RSS만으로 내부 객체의 누수 위치까지 알아낼 수 없다. 여러 스레드가 표시하는 RSS를 합산하거나 부모·자식의 공유 페이지를 중복 합산하지 않는다. 실제 소켓 소유 워커와 실행기를 `ss`·`ps`·앱 로그로 대조한다.

`ps %CPU`는 프로세스 전체 수명 동안의 평균이다. `top`의 첫 화면도 모니터의 구간 샘플과 같은 의미로 취급하지 않는다. 급격한 변화는 `metrics.csv`의 연속 샘플로 수치화하고 시스템 도구 출력을 보조 증거로 붙인다.

## 종료 결과 해석

| `result.json` 값 | 해석 |
| --- | --- |
| `reason=app_exited` | 관측 대상 그룹에 실행 중인 프로세스가 없어짐. 앱 로그로 원인 판정 |
| `reason=observation_timeout` | 관찰 상한에 도달. 앱이 아직 살아 있으면 수집기가 정리 |
| `reason=interrupted` | 사용자 또는 외부 신호로 수집 중단 |
| `reason=runner_error` | 수집기 오류. 결과를 성공적인 장애 재현으로 쓰지 않음 |
| `alive_before_cleanup=true` | 정리 신호 이전에 실행 중인 프로세스가 존재 |
| `launcher_returncode<0` | 직접 실행한 프로세스가 해당 번호의 신호로 종료 |
| `runner_events` | 수집기 신호와 외부 중단 수신 기록 |

실행기가 내부 워커의 신호를 숫자 종료 상태로 변환할 수 있다. 따라서 실행기 코드 137 같은 값 하나만으로 커널 OOM이나 특정 내부 신호를 확정하지 않는다. `monitor-stderr.log`, `snapshots.txt`의 명령 종료 코드와 오류 메시지도 확인한다. 접근 권한 때문에 도구 출력을 못 얻은 경우 미수집 사실을 보고서에 적고 해당 환경에서 다시 수집한다.

## 보고서 완성 순서

1. Before/After의 바이너리 SHA256과 고정 환경변수가 같은지 확인한다.
2. 실제로 정상 부팅한 워커 PID를 선택한다.
3. 각 실행의 원문 증거 파일을 보고서에 상대 링크로 연결한다.
4. 메모리 시작·최대, CPU 고점, 생존 시간, 종료 로그, 마지막 진행 로그를 기록한다.
5. 가설과 관측 사실을 구분해 원인 분석을 수정한다.
6. 이 저장소의 완료 보고서처럼 실제 결과를 채우고 원인 추론의 한계를 명시한다.

관찰 상한까지 살아 있는 실행의 수명은 `최소 N초`다. Before의 실제 종료 시간과 After의 관찰 상한을 동일한 종료 시간처럼 비교하지 않는다. 예를 들어 Before 45초에 보호 종료, After 180초 상한까지 생존이면 `45초 → 180초 이상 생존`이라고 기록한다. 이 숫자는 설명용 예시이며 이 저장소의 실측 결과가 아니다.

## 문서 근거

- [Linux 커널 /proc 문서](https://www.kernel.org/doc/html/latest/filesystems/proc.html): stat 필드·RSS·WCHAN 정의와 RSS 계측 정확도.
- [ps(1) 매뉴얼](https://man7.org/linux/man-pages/man1/ps.1.html): `%CPU`의 수명 평균 특성, 프로세스·스레드 출력.
