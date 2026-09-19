# Linux 장애 분석: OOM · CPU 과점유 · Deadlock

AI/SW Basic · 미션 4 Linux와 OS · 과제 2

**2026-09-18 교육기관 제공 앱으로 장애 3종과 설정 변경 전후 총 6회 비교를 완료했다.** 이 README에 발생 현상, 실측 로그·그래프, 원인 분석, 조치 및 검증 결과를 모았다. 스케줄링 보너스 분석과 재현 방법도 아래에서 확인할 수 있다.

수집 도구 테스트 **11개**, 실측 증거 검사 **50개**가 통과했다. 개별 Issue로 옮겨 쓸 보고서는 [reports/](reports/), 원문 증거는 [evidence/](evidence/)에 있다.

바로가기: [결과 요약](#결과-요약) · [실행 환경](#실행-환경) · [OOM 분석](#oom-분석) · [CPU 분석](#cpu-분석) · [Deadlock 분석](#deadlock-분석) · [스케줄링 분석](#스케줄링-분석) · [재현 방법](#재현-방법) · [검증](#검증) · [공통 템플릿](#이슈-리포트-템플릿)

## 결과 요약

| 장애 | Before | After | 보고서 |
| --- | --- | --- | --- |
| OOM | MEMORY_LIMIT=64, 8.418초 후 MemoryGuard 종료 | 128로 상향, 17.536초 후 종료: 생존 약 2.08배 | [OOM](#oom-분석) |
| CPU | CPU_MAX_OCCUPY=100, 27.302초 후 Watchdog 종료 | 40으로 하향, 90초 이상 생존·냉각 확인 | [CPU](#cpu-분석) |
| Deadlock | MULTI_THREAD_ENABLE=true, 순환 락 대기·79.317초 로그 정체 | false, 90초 동안 작업·로그 진행 | [Deadlock](#deadlock-분석) |
| 보너스 | A→B→C 순환과 Preempted/Resumed 로그 | 앱 수준 Round-Robin으로 추론 | [스케줄링](#스케줄링-분석) |

생존 연장·회피는 관측 범위의 결과다. 커널 OOM, 영구적인 누수 해결, 장기간 무장애, 응답 지연 개선까지 주장하지 않는다. 앱의 `Current Load`와 OS가 측정한 CPU 사용률은 구분했다.

## 실행 환경

| 항목 | 실측 환경 |
| --- | --- |
| 실행 일자 | 2026-09-18 |
| 운영체제 | WSL2 Linux 6.6.87.2, x86_64 |
| 논리 CPU | 12개 |
| 실행 계정 | kjw, UID 1000 — 일반 사용자 |
| 제공 앱 | agent-app-leak.zip의 agent-leak-app-x86 |
| 네트워크 | 독립 사용자·네트워크 네임스페이스에서 0.0.0.0:15034 바인딩 |
| 관찰 상한 | 각 실행 90초 |
| 관제 간격 | OOM·Deadlock 0.5초, CPU 0.1초 |
| 시각 기준 | 앱 로그 KST(UTC+9), 관제 CSV·수집기 로그 UTC |

기존 서비스와 포트가 충돌하지 않도록 `unshare --user --map-current-user --net`으로 실행했다. 앱의 부팅 검사 6단계가 모두 통과했으며 CPU·메모리는 호스트 자원을 공유했다. 각 비교 쌍에서는 관심 환경변수 하나만 변경했다.

바이너리를 수정하거나 역공학하지 않았다. 원본 실행 파일의 SHA256은 다음과 같으며, [ZIP·바이너리 정보](evidence/artifact.json)와 각 실행의 metadata로 확인할 수 있다.

```text
7e0a19cfa80ece6b547a5008273661f0d4d71e526e96b51e0d0f341dd1bb3e40
```

## OOM 분석

**[Bug] OOM Crash - 메모리 누적 후 MemoryGuard가 SIGKILL로 종료**

실측 완료 · 2026-09-18 · 교육기관 제공 `agent-leak-app-x86`

### 1. Description (현상 설명)

WSL2 Linux x86_64에서 일반 계정 `kjw`(UID 1000)로 실행했다. 부팅 검사 6개와 `Agent READY`를 통과한 뒤 MemoryWorker의 메모리가 약 3초마다 25 MB씩 증가했다. `MEMORY_LIMIT=64`에서 실행 후 **8.418초**에 MemoryGuard가 강제 종료했다. 한도를 `128`로 높인 실행은 **17.536초**까지 생존했지만 같은 원인으로 종료했다.

두 실행에서 `CPU_MAX_OCCUPY=100`, `MULTI_THREAD_ENABLE=false`를 고정했다. 독립된 사용자·네트워크 네임스페이스에서 UID 1000으로 `0.0.0.0:15034`에 정상 바인딩했다. 바이너리는 수정하지 않았다. [실험 목록](evidence/manifest.json), [원본 SHA256](evidence/artifact.json).

### 2. Evidence & Logs (증거 자료)

#### 재현 명령

관찰 상한은 90초, 모니터 간격은 0.5초다. 저장소 루트에서 일반 사용자로 실행한다.

```bash
unshare --user --map-current-user --net bash scripts/run-case.sh \
  --app vendor/agent-leak-app-x86 --case oom-before \
  --duration 90 --interval 0.5 --snapshot-interval 5
unshare --user --map-current-user --net bash scripts/run-case.sh \
  --app vendor/agent-leak-app-x86 --case oom-after \
  --duration 90 --interval 0.5 --snapshot-interval 5
```

소켓 소유 워커는 Before **2440463**, After **2440969**였다. 약 2 MiB인 패키징 실행기 PID와 구분했다.

| 실행 | 워커 RSS 첫 샘플 → 마지막/최대 | 앱 로그 Heap 진행 | 결과 |
| --- | --- | --- | --- |
| Before | 17.250 → 67.250 MiB | 25 → 50 → 75 MB | 75 ≥ 64, 보호 종료 |
| After | 17.484 → 142.359 MiB | 25 → 50 → … → 150 MB | 150 ≥ 128, 보호 종료 |

![OOM 전후 RSS와 CPU 실측](evidence/charts/oom.png)

Before의 원문 발췌. 앱 시각은 KST(UTC+9)이며 관제 CSV와 수집기 시각은 UTC다.

```text
2026-09-18 18:06:16,803 [INFO] [MemoryWorker] Current Heap: 25MB
2026-09-18 18:06:19,834 [INFO] [MemoryWorker] Current Heap: 50MB
2026-09-18 18:06:22,866 [INFO] [MemoryWorker] Current Heap: 75MB
2026-09-18 18:06:22,867 [CRITICAL] [MemoryGuard] Memory limit exceeded (75MB >= 64MB) / (Recommend Over 256MB)
2026-09-18 18:06:22,868 [CRITICAL] [MemoryGuard] Self-terminating process 2440463 to prevent system instability.
```

After의 종료 직전 원문:

```text
2026-09-18 18:06:57,505 [INFO] [MemoryWorker] Current Heap: 125MB
2026-09-18 18:07:00,533 [INFO] [MemoryWorker] Current Heap: 150MB
2026-09-18 18:07:00,534 [CRITICAL] [MemoryGuard] Memory limit exceeded (150MB >= 128MB) / (Recommend Over 256MB)
2026-09-18 18:07:00,535 [CRITICAL] [MemoryGuard] Self-terminating process 2440969 to prevent system instability.
```

두 실행의 `result.json`은 `reason=app_exited`, `alive_before_cleanup=false`, `launcher_returncode=-9`, `runner_events=[]`다. 수집기가 종료 신호를 보내기 전에 앱 그룹이 종료됐고, 실행기는 SIGKILL 종료 상태를 반환했다. 종료 후 `monitor.log`에는 `EVENT:PROCESS_EXITED`가 기록됐다.

원문 자료:

- Before: [관제 로그](evidence/runs/20260918T090614Z-oom-before-402105430/monitor.log), [CSV](evidence/runs/20260918T090614Z-oom-before-402105430/metrics.csv), [실행 로그](evidence/runs/20260918T090614Z-oom-before-402105430/console.log), [ps·top·ss](evidence/runs/20260918T090614Z-oom-before-402105430/snapshots.txt), [종료 결과](evidence/runs/20260918T090614Z-oom-before-402105430/result.json)
- After: [관제 로그](evidence/runs/20260918T090643Z-oom-after-033262350/monitor.log), [CSV](evidence/runs/20260918T090643Z-oom-after-033262350/metrics.csv), [실행 로그](evidence/runs/20260918T090643Z-oom-after-033262350/console.log), [종료 결과](evidence/runs/20260918T090643Z-oom-after-033262350/result.json)

### 3. Root Cause Analysis (원인 분석)

관측된 직접 원인은 **메모리 누적과 앱의 MemoryGuard 임계치 초과**다. Heap 출력과 RSS가 함께 증가하고, Guard가 초과를 기록한 직후 종료됐다. 할당한 데이터를 종료 전까지 충분히 회수하지 않는 누수성 패턴과 일치한다. 다만 제공 바이너리를 분석하지 않았으므로 어떤 객체·참조가 원인인지, 의도된 실습용 누적과 실제 결함을 내부 구현 수준에서 구분할 수는 없다.

이 결과는 **커널 OOM killer의 시스템 메모리 고갈 판정이 아니다**. 앱이 자체 보호 종료를 명시했고 수집기 개입도 없었다. 커널 OOM 로그나 시스템 전체 메모리 고갈은 입증하지 않았다.

Guard의 Heap MB와 OS의 RSS MiB는 같은 지표가 아니다. RSS에는 런타임과 공유 라이브러리도 포함된다. 0.5초 샘플 사이에 마지막 할당과 종료가 연속해서 발생하므로 마지막 RSS 샘플은 종료 순간을 놓칠 수 있다. 따라서 로그의 75/150 MB와 RSS 최대 67.250/142.359 MiB를 같은 값으로 취급하지 않는다.

### 4. Workaround & Verification (조치 및 검증)

| 항목 | Before | After |
| --- | --- | --- |
| MEMORY_LIMIT | 64 MB | 128 MB |
| 고정 변수 | CPU=100%, 멀티스레드=false | 동일 |
| 관찰 상한 | 90초 | 90초 |
| 실제 생존 시간 | 8.418초 | 17.536초 |
| 종료 상태 | MemoryGuard / -9 | MemoryGuard / -9 |
| 최대 RSS | 67.250 MiB | 142.359 MiB |

한도 상향으로 생존 시간이 **9.118초 증가, 약 2.08배**가 됐다. 메모리 증가 자체는 계속됐으므로 임시 완화다. 이후 `MEMORY_LIMIT=512`, `CPU_MAX_OCCUPY=40`, `MULTI_THREAD_ENABLE=false`의 정상 관측에서는 앱의 캐시 정리와 계속되는 작업 로그를 확인했다. 이 추가 관측은 다른 변수도 바뀌었으므로 위 단일 변수 비교와 분리해 해석한다.

근본 개선 제안은 불필요한 참조 제거, 캐시·큐 크기 제한, 주기적인 회수, 장시간 부하 검증이다. 바이너리의 소스 수정은 수행하지 않았다.

## CPU 분석

**[Bug] CPU Latency - CPU 급상승과 Watchdog의 SIGTERM 보호 종료**

실측 완료 · 2026-09-18 · 교육기관 제공 `agent-leak-app-x86`

### 1. Description (현상 설명)

`MEMORY_LIMIT=512`, `MULTI_THREAD_ENABLE=false`를 고정하고 CPU 설정만 비교했다. `CPU_MAX_OCCUPY=100`에서 워커의 짧은 CPU 상승 구간을 관측했고, 앱 내부 부하 값이 52.69%가 되자 Watchdog가 종료했다. 실행부터 종료 관측까지 **27.302초**였다. `CPU_MAX_OCCUPY=40`으로 낮춘 실행은 **90초 이상 생존**하며 부하 증가·냉각과 작업 로그를 계속 남겼다.

공통 환경은 WSL2 Linux x86_64, 논리 CPU 12개, UID 1000이다. 독립 네트워크에서 앱이 `0.0.0.0:15034`에 정상 바인딩했다. 소켓 소유 워커 PID는 Before **2445628**, After **2447020**이다. HTTP 응답시간이나 실제 사용자 요청 지연은 측정하지 않았으므로 지연 감소를 실측 성과로 주장하지 않는다.

### 2. Evidence & Logs (증거 자료)

#### 재현 명령

짧은 CPU 상승을 포착하기 위해 양쪽 모두 **0.1초** 간격으로 관측했다.

```bash
unshare --user --map-current-user --net bash scripts/run-case.sh \
  --app vendor/agent-leak-app-x86 --case cpu-before \
  --duration 90 --interval 0.1 --snapshot-interval 5
unshare --user --map-current-user --net bash scripts/run-case.sh \
  --app vendor/agent-leak-app-x86 --case cpu-after \
  --duration 90 --interval 0.1 --snapshot-interval 5
```

#### CPU 상승과 종료 원문

Before의 `metrics.csv`에서 동일 워커의 CPU 구간 값이 다음과 같이 변했다. CPU 100%는 논리 CPU 한 개이며, 최초 샘플은 계산 구간이 없어 비워 둔다.

| UTC 시각 | 워커 PID | 구간 CPU | RSS KiB | 누적 CPU ticks |
| --- | --- | ---: | ---: | ---: |
| 09:11:48.850 | 2445628 | 0.00% | 17792 | 23 |
| 09:11:48.954 | 2445628 | 0.00% | 17792 | 23 |
| 09:11:49.057 | 2445628 | **58.26%** | 17792 | 29 |

![CPU 전후 RSS와 CPU 실측](evidence/charts/cpu.png)

앱 로그 원문은 KST(UTC+9)다. **앱의 Current Load는 OS 관제 CPU와 별도 지표**이며 동일 값으로 취급하지 않는다.

```text
2026-09-18 18:11:45,871 [INFO] [CpuWorker] Current Load: 44.69%
2026-09-18 18:11:48,987 [INFO] [CpuWorker] Current Load: 52.69%
2026-09-18 18:11:49,088 [CRITICAL] [CpuWorker] CPU Threshold Violated! (52.69%).

>>> [SYSTEM] WATCHDOG: INITIATING EMERGENCY ABORT (SIGTERM) <<<
```

Before 결과는 `app_exited`, `launcher_returncode=-15`, `runner_events=[]`다. 앱이 명시한 Watchdog 신호와 실제 SIGTERM 종료 상태가 일치하며, 수집기는 종료 신호를 보내지 않았다.

After에서는 다음과 같이 정상적인 냉각과 재증가가 이어졌다.

```text
2026-09-18 18:13:51,956 [INFO] [CpuWorker] Peak reached (40.00%). Starting cooldown...
2026-09-18 18:13:52,963 [INFO] [CpuWorker] Current Load: 40.00%
2026-09-18 18:14:07,533 [INFO] [CpuWorker] Cooldown complete (5.00%). Resuming load increase...
2026-09-18 18:14:08,539 [INFO] [CpuWorker] Current Load: 5.00%
2026-09-18 18:14:17,883 [INFO] [CpuWorker] Current Load: 19.12%
```

원문 자료:

- Before: [관제 로그](evidence/runs/20260918T091121Z-cpu-before-748323350/monitor.log), [CSV](evidence/runs/20260918T091121Z-cpu-before-748323350/metrics.csv), [실행 로그](evidence/runs/20260918T091121Z-cpu-before-748323350/console.log), [ps·top·ss](evidence/runs/20260918T091121Z-cpu-before-748323350/snapshots.txt), [종료 결과](evidence/runs/20260918T091121Z-cpu-before-748323350/result.json)
- After: [관제 로그](evidence/runs/20260918T091250Z-cpu-after-355471748/monitor.log), [CSV](evidence/runs/20260918T091250Z-cpu-after-355471748/metrics.csv), [실행 로그](evidence/runs/20260918T091250Z-cpu-after-355471748/console.log), [종료 결과](evidence/runs/20260918T091250Z-cpu-after-355471748/result.json)

### 3. Root Cause Analysis (원인 분석)

직접 원인은 **앱 내부 부하 증가와 Watchdog 정책 위반**이다. 본 바이너리는 CPU 설정 100%에서 부하를 높이다가 내부 값 52.69%에서 보호 종료했고, 40%에서는 고점 도달 후 냉각했다. 따라서 CPU_MAX_OCCUPY를 보호 임계값 그 자체로 해석해 높이는 조치는 이 앱에 맞지 않는다. 로그상 최대 부하 설정을 낮추는 방향으로 회피했다. 정확한 내부 측정·분기 코드는 분석하지 않았다.

관측한 OS CPU 급상승은 **0.1초 구간의 58.26%**다. 시스템 전체가 장시간 100% 과부하였다는 뜻은 아니다. 초기 0.5초 관측에서는 짧은 부하가 평균에 희석됐으므로 더 짧은 동일 간격의 최종 비교를 사용했다. `ps %CPU`는 수명 평균이라 해당 순간의 고점을 대신할 수 없다.

CPU 연산이 길어지면 실행 대기 중인 다른 작업의 응답이 늦어질 수 있다. 이 실험은 특정 프로세스의 상승과 앱 보호 정책의 종료를 입증하며, 외부 서비스 지연이나 커널 장애는 입증하지 않는다. After에서 정상 시나리오로 전환되어 메모리 워커도 함께 동작했으므로 CPU 지표 차이를 동일 연산량의 성능 개선율로 계산하지 않았다.

### 4. Workaround & Verification (조치 및 검증)

| 항목 | Before | After |
| --- | --- | --- |
| CPU_MAX_OCCUPY | 100% | 40% |
| 고정 변수 | MEMORY_LIMIT=512, 멀티스레드=false | 동일 |
| 관찰 상한 / 샘플 간격 | 90초 / 0.1초 | 동일 |
| OS 최대 구간 CPU | 58.26% | 39.02% |
| 앱 Current Load | 52.69%에서 정책 위반 | 40.00% 고점 후 냉각 |
| 생존 | 27.302초 후 Watchdog 종료 | 90초 이상 생존 |
| 최종 -15의 주체 | 앱 Watchdog | 관찰 종료 후 수집기 정리 |

After의 `result.json`은 `observation_timeout`, `alive_before_cleanup=true`, `observed_s=90.020`이고 수집기 SIGTERM 시각이 별도로 기록됐다. 따라서 After의 -15를 Watchdog 재발로 오인하지 않는다.

실습용 임시 설정은 CPU_MAX_OCCUPY=40이다. 근본 개선은 불필요한 반복 연산·busy wait 점검, 작업 분할, 워커 수·요청량 제어 및 실제 응답시간 검증이다. 이 관측만으로 장기간 무장애를 보장하지 않는다.

## Deadlock 분석

**[Bug] Deadlock - 두 워커의 순환 락 대기로 작업 진행 중단**

실측 완료 · 2026-09-18 · 교육기관 제공 `agent-leak-app-x86`

### 1. Description (현상 설명)

`MEMORY_LIMIT=512`, `CPU_MAX_OCCUPY=40`을 고정하고 멀티스레드 설정만 비교했다. `true`에서 실행 약 9초 뒤 두 워커가 서로의 자원을 기다리는 로그를 남겼다. 이후 PID는 계속 존재했지만 CPU·RSS와 로그 크기가 정체됐다. `false`로 변경한 실행은 동일한 90초 동안 작업·메모리 회수·CPU 냉각 로그가 계속 진행됐다.

일반 계정 UID 1000, WSL2 x86_64, 독립 네트워크의 고정 포트 15034에서 관측했다. 워커 PID는 Before **2448740**, After **2451259**다. 종료 여부뿐 아니라 작업의 진행 여부를 함께 확인했다.

### 2. Evidence & Logs (증거 자료)

#### 재현 명령

```bash
unshare --user --map-current-user --net bash scripts/run-case.sh \
  --app vendor/agent-leak-app-x86 --case deadlock-before \
  --duration 90 --interval 0.5 --snapshot-interval 5
unshare --user --map-current-user --net bash scripts/run-case.sh \
  --app vendor/agent-leak-app-x86 --case deadlock-after \
  --duration 90 --interval 0.5 --snapshot-interval 5
```

#### 마지막 진행 로그와 순환 대기

Before의 실제 로그 발췌. 시각은 KST다.

```text
2026-09-18 18:14:40,866 [INFO] [AgentWorker][Worker-Thread-1] LOCK ACQUIRED: [Shared_Memory_A]. (Holding...)
2026-09-18 18:14:40,866 [INFO] [AgentWorker][Worker-Thread-2] LOCK ACQUIRED: [Socket_Pool_B]. (Holding...)
2026-09-18 18:14:42,870 [INFO] [AgentWorker][Worker-Thread-1] Need resource [Socket_Pool_B] to finish job.
2026-09-18 18:14:42,871 [INFO] [AgentWorker][Worker-Thread-1] WAITING for [Socket_Pool_B]... (Status: BLOCKED)
2026-09-18 18:14:42,879 [INFO] [AgentWorker][Worker-Thread-2] Need resource [Shared_Memory_A] to write logs.
2026-09-18 18:14:42,880 [INFO] [AgentWorker][Worker-Thread-2] WAITING for [Shared_Memory_A]... (Status: BLOCKED)
```

#### PID·스레드·자원 정체

`09:16:03.609 UTC`의 `ps -L` 원문 발췌다. 동일 PID/TID들이 앞선 `09:14:44.299 UTC`에도 존재했다. 실행기 PID 2448732는 별도로 `do_wait` 상태였고, 실제 워커는 다음 세 스레드였다.

```text
    PID     TID STAT %CPU   RSS WCHAN                            COMMAND
2448740 2448740 SNl   0.0 17664 futex_wait_queue                 agent-leak-app-
2448740 2448841 SNl   0.0 17664 futex_wait_queue                 agent-leak-app-
2448740 2448842 SNl   0.0 17664 futex_wait_queue                 agent-leak-app-
```

전체 관제에서 워커 RSS는 **17664 KiB = 17.250 MiB**, 구간 CPU는 **0.00%**로 유지됐다. 프로세스는 `S` 상태였고 좀비 `Z`가 아니었다. 주 스레드의 워커 완료 대기와 두 워커의 락 대기를 로그·TID 상태가 함께 뒷받침한다. 로그 이름과 개별 TID의 일대일 매핑은 별도로 확인하지 않았다.

| UTC 관측 시각 | console.log | agent_app.log | PID 상태 |
| --- | ---: | ---: | --- |
| 09:14:44.539 | 2881 bytes | 1517 bytes | 생존 |
| 09:14:49.892 | 2881 bytes | 1517 bytes | 생존 |
| 09:15:59.424 | 2881 bytes | 1517 bytes | 생존 |
| 09:16:03.856 | 2881 bytes | 1517 bytes | 정리 직전 생존 |

로그 크기는 **79.317초** 동안 변하지 않았다. 마지막 앱 로그 시각 09:14:42.880부터 최종 기록까지는 약 80.976초다. `result.json`의 `alive_before_cleanup=true`와 종료 전 스냅샷이 지속 생존을 확인한다.

![Deadlock 전후 RSS와 CPU 실측](evidence/charts/deadlock.png)

원문 자료:

- Before: [관제 로그](evidence/runs/20260918T091433Z-deadlock-before-531338111/monitor.log), [CSV](evidence/runs/20260918T091433Z-deadlock-before-531338111/metrics.csv), [실행 로그](evidence/runs/20260918T091433Z-deadlock-before-531338111/console.log), [ps·ps -L·top -H](evidence/runs/20260918T091433Z-deadlock-before-531338111/snapshots.txt), [로그 크기](evidence/runs/20260918T091433Z-deadlock-before-531338111/log-sizes.jsonl), [종료 결과](evidence/runs/20260918T091433Z-deadlock-before-531338111/result.json)
- After: [관제 로그](evidence/runs/20260918T091713Z-deadlock-after-166295630/monitor.log), [CSV](evidence/runs/20260918T091713Z-deadlock-after-166295630/metrics.csv), [실행 로그](evidence/runs/20260918T091713Z-deadlock-after-166295630/console.log), [스레드 상태](evidence/runs/20260918T091713Z-deadlock-after-166295630/snapshots.txt), [로그 크기](evidence/runs/20260918T091713Z-deadlock-after-166295630/log-sizes.jsonl), [종료 결과](evidence/runs/20260918T091713Z-deadlock-after-166295630/result.json)

### 3. Root Cause Analysis (원인 분석)

서로 반대 순서로 자원을 보유·요청한 것이 로그에서 확인된다.

```text
Worker-Thread-1: Shared_Memory_A 보유 → Socket_Pool_B 대기
Worker-Thread-2: Socket_Pool_B 보유 → Shared_Memory_A 대기
순환: Thread-1 → Pool-B → Thread-2 → Memory-A → Thread-1
```

| 교착상태 조건 | 증거와 해석 |
| --- | --- |
| 상호 배제 | Strict resource locking 안내와 LOCK ACQUIRED / BLOCKED 로그 |
| 점유 대기 | 한 자원을 Holding한 채 다른 자원을 요청 |
| 비선점 | 관측 구간에 상대 락을 빼앗거나 강제로 회수한 기록 없이 대기 지속 |
| 순환 대기 | 1은 2의 Pool-B, 2는 1의 Memory-A를 기다림 |

락 대기는 CPU를 소비하지 않고 스레드를 잠들게 할 수 있다. 그래서 PID와 RSS가 유지돼도 작업은 진행되지 않는다. `futex_wait_queue` 또는 낮은 CPU 하나만으로는 교착상태를 단정할 수 없지만, 이번에는 양방향 보유·대기 로그와 장시간의 정체가 함께 있어 순환 대기라는 설명을 뒷받침한다. 비선점 정책의 내부 구현과 락 객체 주소는 역공학하지 않았다.

TCP LISTEN은 유지되어도 작업 완료를 보장하지 않는다. 실제 네트워크 요청의 타임아웃은 별도로 측정하지 않았으므로 증상은 확인된 작업·로그 진행 중단으로 한정한다.

### 4. Workaround & Verification (조치 및 검증)

| 항목 | Before | After |
| --- | --- | --- |
| MULTI_THREAD_ENABLE | true | false |
| 고정 변수 | MEMORY_LIMIT=512, CPU=40% | 동일 |
| 관찰 시간 | 90.021초 | 90.044초 |
| 워커 PID | 2448740 | 2451259 |
| 최대 구간 CPU | 0.00% | 11.87% |
| RSS 추세 | 17.250 MiB로 정체 | 최대 517.676 MiB, 캐시 회수 후 재증가 |
| 마지막 로그 | 양쪽 WAITING / BLOCKED | MemoryWorker·CpuWorker 계속 진행 |
| 최종 콘솔 크기 | 2881 bytes | 7747 bytes |
| 관찰 후 정리 | 수집기 SIGTERM | 수집기 SIGTERM |

After에서는 `All tasks completed`, 부하 냉각, `18:18:17.146 Memory Cache Flushed`, `18:18:43.359 Current Heap: 200MB`까지 진행했다. `WAITING`/`BLOCKED` 로그는 없었다. PID 존재만이 아니라 실제 로그 진행과 메모리 회수로 **관찰한 90초 동안 교착상태를 회피했음**을 확인했다.

멀티스레드를 끄는 것은 동시성 감소를 감수하는 임시 회피다. 근본 개선은 일관된 락 획득 순서, 임계 구역 축소, 타임아웃 시 보유 락 해제, 자원 의존 구조 개선이다. 바이너리 수정은 수행하지 않았다.

## 스케줄링 분석

**[Analysis] 작업 로그를 통한 Round-Robin 스케줄링 추론**

보너스 실측 분석 · 2026-09-18

### 1. 로그 관찰 개요

`MEMORY_LIMIT=512`, `CPU_MAX_OCCUPY=40`, `MULTI_THREAD_ENABLE=false`에서 앱이 `Healthy System Monitoring`을 선택했다. Task Scheduler가 A/B/C 작업을 등록하고 번갈아 실행하는 로그를 출력했다. [원문 실행 로그](evidence/runs/20260918T091250Z-cpu-after-355471748/console.log)를 분석했다.

### 2. 증거 자료

아래 시각은 KST다. 로그의 작업 이름·진행률·중단 문구를 기준으로 정리했다.

| 시각 | 작업 | 이벤트 / 진행률 |
| --- | --- | --- |
| 18:12:52.682 | A | Started / 20% |
| 18:12:52.733 | A | Calculating / 40% |
| 18:12:52.785 | A | Preempted / 40% 저장 |
| 18:12:52.837 | B | Started / 20% |
| 18:12:52.939 | B | Preempted / 40% 저장 |
| 18:12:52.990 | C | Started / 20% |
| 18:12:53.093 | C | Preempted / 40% 저장 |
| 18:12:53.144 | A | Resumed / 60% |
| 18:12:53.298 | B | Resumed / 60% |
| 18:12:53.451 | C | Resumed / 60% |
| 18:12:53.605 | A | Resumed / 100% |
| 18:12:53.656 | B | Resumed / 100% |
| 18:12:53.707 | C | Resumed / 100% |
| 18:12:53.758 | Scheduler | All tasks completed |

초기 작업 시작 간격 A→B는 **155 ms**, B→C는 **153 ms**, C→A 재개는 **154 ms**다. A의 첫 시작부터 중단 로그까지는 **103 ms**이며, 중단 로그부터 B 시작까지는 **52 ms**다. 전체 작업 로그 구간은 1.076초다. 이 시간은 로그 이벤트 간격이며 실제 커널 타임슬라이스 측정값은 아니다.

### 3. 패턴 분석 및 결론

하나의 작업이 완료되기 전에 다른 작업으로 넘어가고, A→B→C→A 순환과 저장된 진행률의 재개가 반복된다. 따라서 제시된 후보 중 **앱 수준 Round-Robin 방식과 가장 잘 일치**한다. 완료까지 한 작업만 수행하는 비선점 FCFS와는 맞지 않으며, 특정 작업이 우선권을 지속적으로 받는 패턴도 관측되지 않았다.

앱이 출력한 `Preempted` 문구만으로 **Linux 커널이 SCHED_RR 정책으로 이 프로세스를 실행했다**고 결론내리지는 않는다. sleep, 런타임, 앱 자체의 교육용 스케줄러가 동일 패턴을 만들 수 있다. 내부 소스나 커널 정책을 역공학하지 않았고, 이 결론의 범위는 앱 작업 로그다. 정책 구분은 [sched(7)](https://man7.org/linux/man-pages/man7/sched.7.html)을 참고한다.

### 4. 장단점 및 적용

| 관점 | 분석 |
| --- | --- |
| 장점 | 여러 작업에 반복적인 진행 기회를 제공해 긴 작업의 독점을 줄임 |
| 단점 | 작업 교체 비용이 발생하며 할당 시간이 짧으면 오버헤드, 길면 응답 지연 증가 |
| 적합한 성격 | 작업 간 공정성과 빠른 초기 응답이 중요한 대화형 처리·요청 큐 |
| 비교 대상 | 배치 작업은 완료 처리량·캐시 효율을 더 중시할 수 있고, 긴급 작업은 우선순위 정책이 필요할 수 있음 |

이 관측에서는 공정한 교대 진행을 확인했지만 요청 지연·처리량을 벤치마크한 것은 아니다. 실제 서비스에 적용할 때는 대기 시간과 교체 비용을 따로 측정해야 한다.

## 재현 방법

제공 ZIP의 `agent-leak-app-x86`을 `vendor/`에 추출했다. 원본은 수정하지 않았으며 [ZIP·바이너리 SHA256](evidence/artifact.json)을 보존했다. 다른 PC에서는 아키텍처에 맞는 교육기관 제공 파일을 준비한다.

```bash
# 저장소의 code 폴더에서 실행
chmod u+x vendor/agent-leak-app-x86

# 현재 PC처럼 기존 서비스가 15034를 쓰는 경우 독립 네트워크로 실행
unshare --user --map-current-user --net bash scripts/run-suite.sh \
  --app vendor/agent-leak-app-x86 --duration 90 --interval 0.1 \
  --snapshot-interval 5

# 한 건만 실행: 아래는 제출에 사용한 CPU Before와 같은 명령
unshare --user --map-current-user --net bash scripts/run-case.sh \
  --app vendor/agent-leak-app-x86 --case cpu-before \
  --duration 90 --interval 0.1 --snapshot-interval 5
```

실험에 사용한 명령 6개는 [manifest.json](evidence/manifest.json)에 있다. OOM·Deadlock 비교는 0.5초, CPU 비교는 0.1초 간격이었다. 위 suite 예시는 모든 케이스를 0.1초로 관측한다. 실행 시간과 부하 수치는 실행마다 달라질 수 있다.

Linux 일반 계정, Python 3.9 이상, Bash, `ps`, `top`, `ss`, `unshare`가 필요하다. 사용자 네임스페이스를 허용하지 않는 환경에서는 별도 Linux VM/컨테이너 안에서 `bash scripts/run-suite.sh ...`로 실행한다. 네트워크만 격리하며 CPU·메모리는 호스트와 공유한다. 기존 서비스·방화벽·cron을 변경하지 않았다.

### 비교 설정

| 실험 | MEMORY_LIMIT (MB) | CPU_MAX_OCCUPY (%) | MULTI_THREAD_ENABLE |
| --- | ---: | ---: | --- |
| oom-before | 64 | 100 | false |
| oom-after | 128 | 100 | false |
| cpu-before | 512 | 100 | false |
| cpu-after | 512 | 40 | false |
| deadlock-before | 512 | 40 | true |
| deadlock-after | 512 | 40 | false |

실제 앱 로그를 통해 위 조건을 확정했다. CPU_MAX_OCCUPY는 이 앱에서 최대 부하 설정으로 관측됐고 100→40으로 낮춰 보호 종료를 회피했다. 한 쌍 안에서는 해당 변수 하나만 바꿨다. 정상 관측 조합은 **512 / 40 / false**다.

## 코드와 증거

| 파일 | 역할 |
| --- | --- |
| [bin/monitor.sh](bin/monitor.sh) | PID 또는 그룹별 구간 CPU·RSS·스레드·상태 기록 |
| [scripts/run-case.sh](scripts/run-case.sh) | 환경 생성, 단일 실험, 로그·스냅샷 보존, 실험 프로세스 정리 |
| [scripts/run-suite.sh](scripts/run-suite.sh) | 6개 비교 케이스 순차 실행 |
| [scripts/summarize-evidence.py](scripts/summarize-evidence.py) | 확정 실행 목록의 워커 통계·그래프 재생성 |
| [scripts/verify-evidence.py](scripts/verify-evidence.py) | 실제 증거의 원본·설정·종료 원인·비교 검증 |
| [templates/issue-report.md](templates/issue-report.md) | 명세의 4개 섹션을 갖춘 공통 템플릿 |
| [evidence/manifest.json](evidence/manifest.json) | 제출에 사용하는 정확한 실행 목록·명령 |
| [evidence/comparison.json](evidence/comparison.json) | 원문 CSV에서 계산한 워커별 통계 |
| [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md) | 실행 방법·지표·종료 결과 해석 |
| [docs/VERIFICATION.md](docs/VERIFICATION.md) | 검증 범위와 한계 |

실험마다 `AGENT_HOME/upload_files`, `api_keys/secret.key`, 로그 폴더를 만들고 명세의 테스트 키 `agent_api_key_test`와 필수 환경변수를 구성한다. 환경변수는 해당 프로세스에만 적용된다.

각 `evidence/runs/<시각>-<실험>-<고유 번호>/`에는 `metadata.json`, `console.log`, `app-logs/`, `metrics.csv`, `monitor.log`, `snapshots.txt`, `log-sizes.jsonl`, `result.json`, `summary.json`을 보존한다. 소켓 소유 워커를 실행기와 구분하고, 여러 PID 또는 스레드의 RSS를 중복 합산하지 않는다.

수집기는 종료 직전 문구를 보존하도록 PTY로 앱을 실행한다. `observation_timeout`은 관찰 상한 이후 수집기가 종료한 것이며 앱 Watchdog 종료와 다르다. `result.json`에 정리 신호를 따로 기록한다. 초기 OOM 비교는 파이프 수집본으로도 MemoryGuard의 핵심 로그가 보존됐으며, 수집 방식의 차이는 manifest에 명시했다.

## 검증

| 구분 | 결과 | 원문 |
| --- | --- | --- |
| 수집 도구 테스트 | 11개 통과 | [tool-tests.txt](evidence/tool-tests.txt) |
| 실측 증거 검사 | 50개 통과, 실패 0개 | [verification.txt](evidence/verification.txt) |

테스트는 설정 범위, PID 추적, CPU·RSS 수집, 종료 원인 구분, 자식 프로세스 정리, 종료 직전 로그 보존을 확인했다. 실측 검사는 원본 SHA256, 일반 계정·부팅·포트, 비교 조건, 실제 장애 로그와 After의 작업 진행을 확인했다. 자세한 범위는 [검증 문서](docs/VERIFICATION.md)에 있다.

다음 명령으로 수집 도구와 기존 실측 증거를 검증할 수 있다.

```bash
bash tests/test_monitor.sh
python3 scripts/verify-evidence.py
```

그래프와 요약 통계를 다시 만들 때는 다음을 실행한다. 수집·검증은 Python 표준 라이브러리, 그래프 생성은 Matplotlib을 사용한다.

```bash
python3 scripts/summarize-evidence.py
```

## 이슈 리포트 템플릿

[공통 Markdown 템플릿](templates/issue-report.md)을 복사해 새 Issue를 작성할 수 있다. 위 장애 보고서 3건도 같은 네 항목으로 구성했다.

<details>
<summary>템플릿 원문 펼치기</summary>

````markdown
# [Bug] {장애 유형} - {한 줄 요약}

상태: **실측 전 초안 / 실측 완료 중 선택**

## 1. Description (현상 설명)

- 발생 일시·시간대:
- 실행 계정, OS, CPU 수, 앱 SHA256:
- 재현 조건: `MEMORY_LIMIT=...`, `CPU_MAX_OCCUPY=...`, `MULTI_THREAD_ENABLE=...`
- 어떤 현상이 어떤 순서로 관측되었는가:
- 서비스 영향: 실제 확인한 영향과 추정한 영향을 구분한다.

## 2. Evidence & Logs (증거 자료)

### 재현 명령

```bash
# 실제 실행한 명령을 기록한다.
```

### 관제 수치

| 관측 시각 | 워커 PID | CPU (%) | RSS (MiB) | 상태/스레드 수 |
| --- | --- | --- | --- | --- |
| 측정 대기 | | | | |

- `metrics.csv`, `monitor.log`, `metadata.json`, `result.json` 원문 링크:
- `console.log`와 앱 자체 로그 중 핵심 구간 발췌:
- `ps` / `top` / `ps -L` 출력과 관측 시각:
- 데드락인 경우 로그 마지막 수정 시각·크기와 관찰 지속 시간:

## 3. Root Cause Analysis (원인 분석)

- 관측된 사실:
- 증거에 근거한 추론:
- 관련 OS 동작 원리:
- 다른 가능한 원인과 배제 근거:
- 확인하지 못한 사항: 바이너리 내부 구현, 미측정 서비스 지연 등.

## 4. Workaround & Verification (조치 및 검증)

| 항목 | Before | After |
| --- | --- | --- |
| 실행 증거 경로 | | |
| 변경한 환경변수 | | |
| 고정한 나머지 환경변수 | | |
| 실제 관찰 시간 | | |
| 종료 여부와 앱 종료 로그 | | |
| RSS 처음 → 최대 | | |
| 최대 구간 CPU | | |
| PID 생존 / 로그 진행 / 스레드 상태 | | |

- 임시 조치와 그 효과:
- 관찰 시간 종료 시 생존한 경우 `N초 이상 생존`이라고 기록한다.
- 수집기 종료 신호와 앱 자체 종료를 구분한다.
- 근본 해결 제안과 추가 검증:
````

</details>
