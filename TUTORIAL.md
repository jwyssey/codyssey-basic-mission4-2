# 미션 4-2 따라 하기: Docker로 장애를 만들고 증거로 설명하기

목표는 OOM·CPU 과점유·Deadlock을 직접 관찰하고, 설정 하나를 바꾼 뒤 무엇이 달라졌는지 설명하는 것이다. **처음에는 OOM 한 쌍만 실행하고 로그를 읽는다.** 그다음 CPU, Deadlock 순서로 진행한다.

Windows PowerShell, macOS 터미널, Linux에서 아래 `docker compose` 명령을 그대로 사용할 수 있다. 호스트에 Python이나 Linux 관측 도구를 따로 설치할 필요는 없다. 처음 이미지 빌드에는 인터넷이 필요하고, 실험 컨테이너는 외부 네트워크 없이 실행된다.

기존 [README의 보고서](README.md#결과-요약)는 2026-09-18 WSL 실측이다. 내 컴퓨터에서 실행한 값은 별도의 Docker 볼륨에 쌓인다. 기존 수치를 내 실험 결과로 옮기지 않는다.

## 1. 공부 순서

『혼자 공부하는 컴퓨터 구조+운영체제』의 운영체제 부분을 실험과 연결한다. 강의 번호는 [한빛미디어 공식 강의 목록](https://www.youtube.com/playlist?list=PLVsNizTWUw7FCS83JhC1vflK8OcLRG0Hl) 기준이다.

| 순서 | 책 | 유튜브 강의 | 실습에서 확인할 것 |
| --- | --- | --- | --- |
| 1 | 9장 운영체제 시작하기, 10장 프로세스와 스레드 | 23~25강, 26~30강 | PID, 실행 중인 프로세스, 워커와 스레드 |
| 2 | 14장 가상 메모리 | 37~40강 | RSS·가상 메모리의 차이, OOM 실험 |
| 3 | 11장 CPU 스케줄링 | 31~32강 | CPU 사용률, 작업 진행, Watchdog |
| 4 | 12장 프로세스 동기화, 13장 교착 상태 | 33~36강 | 락 소유·대기 관계와 순환 대기 |

이전의 책 읽기 순서인 `9~10장 → 11장 → 12~13장 → 14장`으로 먼저 읽어도 된다. 이 튜토리얼은 실행 결과를 빨리 관찰할 수 있는 OOM부터 실습하므로 14장을 먼저 연결했다.

한 실험마다 **예측 → 실행 → 증거 확인 → 설명**을 반복한다. 명령어만 끝내기보다 각 절의 질문에 자기 말로 답해 본다.

## 2. Docker가 준비해 주는 환경

```text
내 컴퓨터
  vendor/agent-app-leak.zip ── 읽기 전용 연결 ──┐
                                               ▼
  Docker의 Linux 컨테이너
    /input : 제공 ZIP
    /tmp   : CPU 종류에 맞는 실행 파일을 임시 추출
    UID 1000으로 앱 + 관측 도구 실행
    /data  : 로그·CSV·설정·결과 기록
       │
       ▼
  Docker 볼륨 lab-evidence ── docker compose cp ── 내 폴더 docker-evidence/
```

- macOS·Windows에서는 Docker Desktop의 Linux 환경을 이용한다. 별도로 VMware를 설치할 필요는 없다.
- Intel/AMD 컴퓨터는 ZIP의 `agent-leak-app-x86`, Apple Silicon 등 ARM64 환경은 `agent-leak-app-arm64`를 선택한다. macOS용 실행 파일로 바꾸는 방식이 아니다.
- `USER 1000:1000`으로 root 실행을 피한다. 이 설정 자체가 Docker 사용자 네임스페이스를 활성화한다는 뜻은 아니다.
- `network_mode: none`으로 네트워크를 격리한다. 앱은 컨테이너 내부에서 15034 포트를 사용한다. 호스트로 포트를 공개하지 않는다.
- 메모리는 컨테이너 전체에 1.5GiB, 스왑은 0으로 제한한다. 앱의 `MEMORY_LIMIT`와 별개다. CPU 쿼터는 별도로 걸지 않는다.
- 원본 ZIP은 저장소의 `vendor/agent-app-leak.zip`에 포함한다. Docker는 이 ZIP을 실행 시 읽기 전용으로 연결한다. ZIP과 실행 파일은 이미지에 포함하지 않으며, 추출한 실행 파일은 Git에서 제외한다.

Docker 안에서 기존 `unshare --user --map-current-user --net` 명령을 다시 실행할 필요는 없다. 필요한 격리는 Compose가 구성한다.

## 3. 처음 한 번 준비하기

### 3-1. Docker 확인

Windows·macOS는 Docker Desktop을 설치하고 실행한다. Windows에서는 **Linux containers**를 사용한다. WSL 터미널에서 실행하려면 해당 배포판에 대한 Docker Desktop의 WSL Integration도 켠다. Linux에서는 Docker Engine과 Compose 플러그인을 사용할 수 있다.

```text
docker version
docker compose version
```

`docker version`에 Client와 Server가 모두 나와야 한다. Docker Desktop의 Linux 환경에는 여유 메모리를 준다. 이 실습에서는 4GiB 이상을 시작점으로 권장한다. 컨테이너의 1.5GiB 외에 Docker 자체와 다른 컨테이너도 메모리를 사용한다.

### 3-2. 저장소와 ZIP 준비

새 컴퓨터에서는 다음과 같이 받는다.

```text
git clone https://github.com/jwyssey/codyssey-basic-mission4-2.git
cd codyssey-basic-mission4-2
```

이미 저장소가 있다면 `Dockerfile`과 `compose.yaml`이 있는 디렉터리로 이동하고 `git pull`로 최신 파일을 받는다. 현재 과제 작업 폴더에서는 `code/`가 그 위치다.

교육기관 제공 원본 ZIP이 `vendor/agent-app-leak.zip`에 포함되어 있으므로 별도 다운로드나 복사 없이 다음 단계로 진행한다. Docker가 실행 파일을 자동 추출한다. 이름이 비슷한 과제 1 앱으로 대체하지 않는다.

```text
codyssey-basic-mission4-2/
  compose.yaml
  Dockerfile
  vendor/
    README.md
    agent-app-leak.zip
```

### 3-3. 이미지 만들기와 점검

```text
docker compose config --quiet
docker compose build lab
docker compose run --rm lab doctor
docker compose run --rm lab test
```

`doctor`에서는 `UID=1000`, `ARCH=x86_64` 또는 `ARCH=aarch64`, 선택한 파일명과 SHA256을 확인한다. cgroup v2 환경에서는 다음 제한도 보인다.

| 항목 | 기본값 | 의미 |
| --- | --- | --- |
| `memory.max` | `1610612736` | 컨테이너 메모리 1.5GiB |
| `memory.swap.max` | `0` | 컨테이너 스왑 사용 안 함 |
| `cpu.max` | `max 100000` | 별도 CPU 시간 쿼터 없음 |
| `pids.max` | `256` | 컨테이너 프로세스·스레드 수 제한 |

`doctor`는 환경·ZIP·ELF 형식·쓰기 권한·포트를 점검한다. 앱의 부팅 성공까지 확인하려면 다음 OOM 실험을 실행한다. `test`는 작은 임시 프로세스로 수집 도구를 검사하며 제공 앱의 장애 재현을 대신하지 않는다.

## 4. 실행 명령과 결과 파일 먼저 이해하기

```text
docker compose run --rm lab run oom-before --duration 90
```

왼쪽 `run --rm lab`은 일회성 컨테이너를 만들고 끝나면 지운다. 오른쪽 `run oom-before`는 그 안의 실험 도구에 케이스를 지정한다. **컨테이너를 지워도 `/data`의 기록은 Docker 볼륨에 남는다.** `--duration 90`은 최대 관찰 시간이며, 앱이 먼저 종료되면 실험도 먼저 끝난다.

```text
docker compose run --rm lab list
docker compose run --rm lab show oom-before
```

`show oom-before`는 해당 케이스의 가장 최근 실행을 표시한다. 인자 없이 `show`를 실행하면 전체에서 가장 최근 실행을 표시한다. `list`에서 복사한 실행 폴더 이름을 넘기면 특정 기록을 볼 수 있다. `incomplete`는 `result.json`이 아직 없다는 뜻이므로 실행 중인지 비정상 중단됐는지 확인한다.

한 실행은 다음 구조로 저장된다.

```text
/data/runs/실행시각-케이스-고유번호/
  metadata.json       실행 설정, 앱 SHA256, 아키텍처, cgroup 제한
  console.log         부팅·장애·작업 진행 로그
  metrics.csv         PID별 CPU·RSS 등 시계열
  snapshots.txt       ps, ps -L, top -H, ss, /proc 관측
  log-sizes.jsonl      시점별 로그 크기: 진행·정체 확인
  result.json         관찰 종료 이유, 정리 신호, cgroup OOM 증가량
  summary.json        PID별 관측치 요약
  monitor.log         수집 도구 로그
  monitor-stderr.log  수집 도구 오류 출력
  app-logs/           앱이 별도로 쓴 로그
  agent-home/         실습용 디렉터리와 공개 테스트 키
```

읽는 순서는 `metadata.json → console.log → metrics.csv·snapshots.txt → result.json`이다. `show`는 요약과 마지막 로그 25줄을 보여 준다. 전체 파일은 9절의 내보내기로 읽는다.

### 종료 코드만 보고 판정하지 않기

| 결과 | 해석 |
| --- | --- |
| `reason=app_exited` | 관찰 중 앱 프로세스 그룹이 종료됨. 이유는 로그로 확인 |
| `reason=observation_timeout` | 정한 시간까지 관찰한 뒤 수집기가 정리 |
| `reason=interrupted` | 중단 요청을 받아 수집기가 정리 |
| `alive_before_cleanup=true` | 정리 신호를 보내기 직전까지 프로세스가 살아 있었음 |
| `runner_events` | 수집기가 받은 중단 요청이나 앱에 보낸 정리 신호 |
| `launcher_returncode=-9/-15` | 각각 SIGKILL/SIGTERM 종료. 신호를 누가 보냈는지는 별도 확인 |
| `cgroup_oom_kill_delta=0` | 관측한 cgroup에서 실험 전후 커널 OOM kill 증가 없음 |
| `cgroup_oom_kill_delta>0` | 해당 cgroup에서 커널 OOM kill 발생. 어떤 프로세스인지 추가 확인 |
| `cgroup_oom_kill_delta=null` | 카운터를 읽지 못함. OOM이 없었다고 단정할 수 없음 |

`-9`만으로 커널 OOM이라고 할 수 없다. 앱의 MemoryGuard가 보낸 SIGKILL일 수 있다. `-15`도 앱 Watchdog인지 수집기 정리인지 로그·`runner_events`를 함께 본다. CLI가 정상 종료됐다는 것은 증거 수집 완료라는 뜻이며, 앱이 정상 동작했다는 뜻은 아니다.

### PID와 사용률 읽기

패키징된 앱은 실행 런처와 실제 워커 PID가 다를 수 있다. `snapshots.txt`의 `ss` 출력에서 15034 포트를 소유한 PID를 확인하고 그 PID의 CSV를 읽는다. 서로 다른 실행의 PID 번호는 달라도 된다.

`cpu_percent`는 논리 CPU 한 개가 100%인 구간 사용률이다. `ps %CPU`는 프로세스 수명 동안의 평균이므로 같은 숫자가 아닐 수 있다. 앱이 출력하는 `Current Load`도 OS 관측치와 구분한다. RSS는 실제 상주 메모리, VMS는 가상 주소 공간이다. 수집기의 메모리 비율은 `/proc/meminfo`를 기준으로 하므로 Docker의 1.5GiB 한도 대비 비율로 읽지 않는다.

## 5. 첫 실험: 메모리가 늘다가 종료되는 이유

**가설:** 앱의 메모리가 누적된다면 `MEMORY_LIMIT`를 올려도 종료 시점만 늦어질 수 있다.

| 설정 | Before | After |
| --- | --- | --- |
| `MEMORY_LIMIT` | 64 | 128 |
| `CPU_MAX_OCCUPY` | 100 | 100 |
| `MULTI_THREAD_ENABLE` | false | false |

4절에서 Before를 실행했다면 같은 기록을 사용해도 된다.

```text
docker compose run --rm lab run oom-before
docker compose run --rm lab show oom-before
docker compose run --rm lab run oom-after
docker compose run --rm lab show oom-after
```

1. 두 로그에서 Boot Sequence 통과와 `Agent READY`를 확인한다. READY 이전 종료는 먼저 환경 문제를 조사한다.
2. 실제 워커의 RSS가 시간에 따라 증가하는지 확인한다.
3. 마지막 부분의 `MemoryGuard`와 제한 초과 메시지를 읽는다.
4. `result.json`에서 `app_exited`, `-9`, 수집기 정리 신호 유무, cgroup OOM 증가량을 확인한다.
5. After에서도 같은 패턴으로 종료됐는지 비교한다.

기존 WSL 실측은 64에서 8.418초, 128에서 17.536초였다. 내 Docker 실행의 정확한 시간은 다를 수 있다. 앱 메모리 누적과 보호 정책 종료를 입증했다면 결론은 **한도 상향은 생존 시간을 늘리는 임시 조치이며 누적 원인의 제거는 아니다**가 된다.

스스로 답하기:

- RSS와 VMS 중 실제 물리 메모리 사용을 비교할 때 어떤 값이 더 직접적인가?
- MemoryGuard 로그와 `-9`가 있어도 왜 커널 OOM이라고 바로 쓰면 안 되는가?
- 메모리 한도를 두 배로 올렸을 때 생존 시간이 정확히 두 배가 아닐 수 있는 이유는 무엇인가?

## 6. 두 번째 실험: CPU 설정과 Watchdog

**가설:** 이 앱에서 CPU 설정을 낮추면 과부하 동작이 줄고 냉각 구간이 나타나 Watchdog 종료를 피할 수 있다.

| 설정 | Before | After |
| --- | --- | --- |
| `MEMORY_LIMIT` | 512 | 512 |
| `CPU_MAX_OCCUPY` | 100 | 40 |
| `MULTI_THREAD_ENABLE` | false | false |

```text
docker compose run --rm lab run cpu-before
docker compose run --rm lab show cpu-before
docker compose run --rm lab run cpu-after
docker compose run --rm lab show cpu-after
```

기본 관찰 상한은 양쪽 모두 90초, CPU 샘플 간격은 0.1초다.

1. Before에서 CPU 관련 경고와 `Watchdog` 종료 로그를 찾는다.
2. 워커의 `metrics.csv`에서 구간 CPU 사용률 변화를 본다. 로그의 `Current Load`를 CSV 수치로 대체하지 않는다.
3. After에서 냉각·작업 진행 로그가 계속되는지 확인한다.
4. After의 `observation_timeout`, `alive_before_cleanup=true`, 수집기 SIGTERM을 확인한다. 종료 코드가 `-15`여도 관찰 완료 뒤 수집기가 끝낸 것일 수 있다.

`CPU_MAX_OCCUPY=40`이 OS 측정값을 항상 40% 이하로 제한한다는 보장은 없다. 앱의 동작을 조절하는 설정이다. Docker CPU 쿼터도 함께 바꾸면 원인 변수가 두 개가 되므로 기본 비교에서는 그대로 둔다.

스스로 답하기:

- 전체 CPU가 12개일 때 워커의 60%와 컴퓨터 전체 사용률 60%는 같은 뜻인가?
- Before와 After 모두 `-15`로 끝났다면 어떤 증거로 원인을 구분할 것인가?
- CPU 부하가 줄었다는 증거만으로 HTTP 응답 지연이 개선됐다고 쓸 수 있는가?

## 7. 세 번째 실험: 살아 있지만 진행하지 않는 Deadlock

**가설:** 두 스레드가 서로 상대의 자원을 기다리면 PID는 살아 있어도 작업은 진행하지 못한다.

| 설정 | Before | After |
| --- | --- | --- |
| `MEMORY_LIMIT` | 512 | 512 |
| `CPU_MAX_OCCUPY` | 40 | 40 |
| `MULTI_THREAD_ENABLE` | true | false |

```text
docker compose run --rm lab run deadlock-before
docker compose run --rm lab show deadlock-before
docker compose run --rm lab run deadlock-after
docker compose run --rm lab show deadlock-after
```

양쪽 모두 90초 관찰한다. Before가 조용해져도 곧바로 Ctrl+C를 누르지 않는다. 로그의 자원 소유·대기를 읽고, 그 이후 로그가 얼마나 오랫동안 갱신되지 않는지 확인한다.

관계가 다음과 같다면 순환 대기가 성립한다. 실제 보고서에는 자기 로그에 나온 자원명을 사용한다.

```text
Thread-1: Memory-A 소유 → Pool-B 획득 대기
Thread-2: Pool-B 소유   → Memory-A 획득 대기

Thread-1 → Pool-B → Thread-2 → Memory-A → Thread-1
스레드→자원은 요청, 자원→스레드는 소유 관계
```

| 교착 상태 조건 | 로그에서 찾을 것 |
| --- | --- |
| 상호 배제 | 자원을 한 스레드가 점유 |
| 점유와 대기 | 자원을 가진 상태에서 다른 자원 요청 |
| 비선점 | 로그상 보유 자원을 강제로 회수하는 동작 없이 대기 |
| 순환 대기 | 두 스레드의 소유·요청 관계가 원을 형성 |

Before에서 PID 생존, 작업 완료 로그 정체, 낮은 CPU와 일정한 RSS를 함께 확인한다. **낮은 CPU 하나만으로 Deadlock이라고 판정하지 않는다.** 정상적인 대기도 CPU를 거의 쓰지 않는다. `ps -L`, `top -H`로 스레드를 볼 수 있지만 Docker 권한·커널에 따라 `wchan`이 `0` 또는 제한된 정보로 보일 수 있다. 이 값을 얻기 위해 컨테이너 권한을 높일 필요는 없다.

After에서는 작업 완료·캐시 회수·로그 갱신이 이어지는지 본다. `MULTI_THREAD_ENABLE=false`여도 OS 스레드가 여러 개일 수 있다. 설정이 문제를 일으키는 동시 트랜잭션 경로를 피한 것이지, 앱 전체가 단일 스레드가 됐다는 뜻은 아니다.

스스로 답하기:

- 프로세스가 살아 있다는 사실과 서비스가 일을 한다는 사실은 왜 다른가?
- 네 가지 조건 중 어떤 조건을 깨면 이 순환을 없앨 수 있는가?
- 동시 기능을 끄는 임시 조치와 락 획득 순서를 통일하는 근본 조치는 어떤 차이가 있는가?

## 8. 한 번에 여섯 실험 실행하기

개별 실험의 의미를 이해한 다음 전체 비교를 수집한다.

```text
docker compose run --rm lab suite
docker compose run --rm lab list
```

OOM Before/After, CPU Before/After, Deadlock Before/After를 순차 실행한다. 기본 관찰 상한은 각각 90초다. CPU 샘플 간격은 0.1초, 나머지는 0.5초, 스냅샷 간격은 5초다. 앱이 먼저 종료되지 않는다면 관찰만 최대 9분이고 정리 시간이 추가된다.

`/data/suite-실행시각-고유번호.json`은 **이번 실행의 비교 대상 폴더**를 기록한다. 중단되면 완료한 케이스만 들어 있을 수 있으므로 여섯 키가 있는지 확인한다. 케이스별 `show`는 가장 최근 기록이므로 여러 번 실험했다면 이 목록으로 비교 쌍을 고른다.

관찰 시간을 늘리려면 쌍의 양쪽을 같은 값으로 다시 실행한다.

```text
docker compose run --rm lab suite --duration 120
```

다른 한도를 탐색하는 실험도 가능하다.

```text
docker compose run --rm lab run oom-after --memory-limit 256 --duration 120
```

이것은 기본 After와 설정이 다른 탐색 실행이다. 90초 실험과 섞어 단일 변수 비교라고 쓰지 않는다. 실행 중 다른 CPU 부하 실험을 병렬로 돌리지 않는다.

## 9. 내 컴퓨터로 결과 가져오기

실험이 끝난 뒤 저장소 루트에서 실행한다.

```text
docker compose create lab
docker compose cp lab:/data/. ./docker-evidence
```

첫 명령은 복사용 컨테이너를 준비한다. 앱을 실행하지 않는다. 두 번째 명령은 볼륨의 내용을 현재 폴더의 `docker-evidence/`로 복사한다. 호스트의 편집기나 스프레드시트로 로그·JSON·CSV를 열 수 있다. 다시 복사하면 동일 경로의 파일은 갱신된다.

`docker-evidence/`는 Git에서 제외한다. 제출할 실행 폴더만 따로 골라 증거로 첨부하고, 보고서에는 해당 폴더와 파일명을 적는다. `agent-home/`에는 실습용 키가 있으므로 제출 증거에서 제외한다.

일반적인 `docker compose down`은 named volume을 남긴다. **`docker compose down -v`나 볼륨 삭제는 실험 기록도 지운다.** 필요한 데이터는 먼저 내보낸다. 저장소 디렉터리를 복사하는 것만으로 Docker 볼륨이 다른 PC에 옮겨지지는 않는다.

## 10. 내 증거로 보고서 작성하기

[공통 템플릿](templates/issue-report.md)을 복사하고 장애마다 다음 순서로 쓴다.

1. **현상:** 어디서, 어떤 설정으로, 언제부터 무엇이 일어나지 않았는가?
2. **증거:** 앱 로그, 실제 워커 PID, CPU·RSS 시계열, 종료 이유를 연결한다.
3. **원인:** 증거로 설명할 수 있는 범위를 적고 가설과 확인된 사실을 구분한다.
4. **조치·검증:** 바꾼 설정 하나와 전후 결과, 남은 문제를 적는다.

비교 전에 아래 표부터 채운다.

| 기록 | Before | After |
| --- | --- | --- |
| 실행 폴더·앱 SHA256 | 직접 기록 | 직접 기록 |
| 아키텍처·Docker 자원 제한 | 직접 기록 | 동일 조건 확인 |
| 관심 환경변수 | 직접 기록 | 바꾼 값 |
| 나머지 변수·관찰 상한·샘플 간격 | 직접 기록 | 동일 조건 확인 |
| 실제 워커 PID·CPU·RSS | 직접 기록 | 직접 기록 |
| 종료·정체 근거와 cgroup OOM 증가량 | 직접 기록 | 직접 기록 |

OOM 한도 상향, CPU 설정 조정, 문제 동시 경로 비활성화는 관찰 결과에 따라 임시 완화나 회피로 설명한다. 앱 내부를 수정한 것이 아니므로 메모리 누수나 락 설계 자체를 고쳤다고 쓰지 않는다. 90초 생존은 90초 동안의 결과다.

보너스 스케줄링 분석은 CPU After의 전체 로그에서 A→B→C 실행과 `Preempted`/`Resumed`를 찾아 앱 수준 Round-Robin으로 추론한다. 이 로그만으로 Linux 커널 스케줄링 정책이 `SCHED_RR`이라고 결론 내리지 않는다.

## 11. 막힐 때 확인하기

| 증상 | 확인·조치 |
| --- | --- |
| Docker Server에 연결하지 못함 | Docker Desktop 실행, Linux containers 선택, WSL Integration 확인 |
| ZIP이 없다고 나옴 | `git pull`로 최신 저장소를 받고 `vendor/agent-app-leak.zip` 위치와 파일명 확인 |
| ELF 또는 아키텍처 오류 | 과제 2 원본 ZIP의 x86·arm64 파일 확인. `platform: linux/amd64`를 임의로 강제하지 않기 |
| `/data` 권한 오류 | Compose의 named volume 및 UID 1000 유지. 임의의 호스트 폴더로 `/data`를 교체했는지 확인 |
| READY 이전 즉시 종료 | 마지막 로그에서 부팅 실패·라이브러리·키·경로 문제 확인 |
| 이전 보고서와 CPU 수치·시간이 다름 | CPU 종류, Docker VM 자원, 다른 작업 부하, 샘플 간격 확인 |
| `wchan`이 0임 | 권한·커널에 따른 관측 제한. 로그의 소유·대기와 진행 여부를 함께 확인 |
| After도 `-15`로 끝남 | `reason`, `alive_before_cleanup`, `runner_events`를 먼저 확인 |
| `result.json`이 없음 | 실행 중인지 확인. Docker 강제 종료·컨테이너 OOM 등으로 수집기가 함께 죽었을 수 있음 |

`cgroup_oom_kill_delta`가 양수라면 컨테이너 메모리 제한이 실험에 개입한 것이다. Docker 환경의 여유 메모리를 확인하고 필요하다면 `mem_limit`와 `memswap_limit`를 같은 더 큰 값으로 조정해 스왑 없이 재실험한다. 이때 Before/After 양쪽을 같은 새 제한으로 다시 실행하고 변경을 기록한다.

컨테이너 자체가 비정상 종료되어 정보를 남기고 싶다면 `--rm` 없이 별도 이름으로 실행한다.

```text
docker compose run --name mission4-2-diagnose lab run oom-before
docker inspect mission4-2-diagnose --format '{{json .State}}'
```

이름이 이미 존재한다면 다른 이름을 사용한다. `OOMKilled`는 컨테이너 상태 판단의 보조 자료다. 자식 프로세스만 OOM으로 종료되었는지는 `memory.events`와 앱 로그도 확인한다.

Ctrl+C를 누르면 수집기는 종료 요청을 받아 앱을 정리하고 결과를 저장한다. Docker Desktop 강제 종료나 PC 전원 종료는 이 절차를 보장하지 않는다.

## 12. 재현 범위와 다음 학습

Docker는 같은 도구·설정·실행 절차를 제공한다. 컴퓨터의 CPU 성능과 Docker Linux 커널까지 같게 만들지는 않는다. Apple Silicon에서는 ARM64를 기본으로 사용하며, x86 에뮬레이션의 CPU 수치를 네이티브 x86 결과와 직접 비교하지 않는다. 관찰값의 절대 일치보다 원인과 변화의 재현 여부를 확인한다.

컨테이너의 1.5GiB 한도에는 앱 외에 수집기와 임시 파일 등도 포함된다. 앱의 `MEMORY_LIMIT=512`와 컨테이너 한도를 같은 값으로 설정하면 커널 OOM이 먼저 개입할 수 있다. 기본값을 유지한 뒤 실제 cgroup 기록으로 확인한다.

기존 [직접 Linux 실행 안내](docs/EXPERIMENTS.md)는 `unshare`와 OS 도구를 별도로 익힐 때 사용한다. `scripts/verify-evidence.py`, `scripts/summarize-evidence.py`는 기존 `evidence/manifest.json`의 WSL 제출 증거를 대상으로 한다. 새 Docker 볼륨을 자동 판정하거나 그래프로 바꾸는 명령은 아니다. 기존 `submission/`의 PDF·ZIP도 당시 제출본이며 Docker 재실행 때 자동 갱신되지 않는다.

현재 Docker 구성의 실제 검증 범위는 [Docker 검증 기록](docs/DOCKER-VERIFICATION.md)에 적었다.

마지막으로 다음 설명을 스스로 할 수 있으면 이 실습의 핵심을 익힌 것이다.

- 실제 워커 PID를 찾아 CPU·RSS를 읽을 수 있다.
- 앱 보호 종료, 커널 OOM, 수집기 정리를 구분할 수 있다.
- 살아 있는 프로세스의 Deadlock을 소유·대기 관계로 설명할 수 있다.
- 조건 하나만 바꿔 전후 비교하고, 임시 조치의 한계를 적을 수 있다.
- Docker 볼륨에서 필요한 증거를 내보내고 보고서와 연결할 수 있다.

## 참고 문서

- [Docker Desktop의 WSL 사용](https://docs.docker.com/desktop/features/wsl/)
- [Docker Compose 서비스 설정](https://docs.docker.com/reference/compose-file/services/)
- [Docker 컨테이너 자원 제한](https://docs.docker.com/engine/containers/resource_constraints/)
- [Docker 볼륨의 수명과 동작](https://docs.docker.com/engine/storage/volumes/)
- [docker compose cp](https://docs.docker.com/reference/cli/docker/compose/cp/)
- [Linux cgroup v2의 memory.events](https://docs.kernel.org/admin-guide/cgroup-v2.html)
