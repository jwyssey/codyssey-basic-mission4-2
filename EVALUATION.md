# 미션 4-2 평가문항 답변

2026-09-18 WSL에서 측정한 결과를 바탕으로 평가 문항 20개와 보너스 문항에 답했다. 먼저 아래 결과를 보고, 각 문항에서 판단 근거를 확인하면 된다. 실험 방법과 전체 로그는 [README](README.md), [실행 기록](evidence/), [장애별 보고서](reports/)에 있다.

| 장애 | 변경한 설정 | 변경 전 | 변경 후 |
| --- | --- | --- | --- |
| 메모리 누적 | `MEMORY_LIMIT=64 → 128` | 8.418초 후 MemoryGuard 종료 | 17.536초 후 같은 이유로 종료 |
| CPU 부하 | `CPU_MAX_OCCUPY=100 → 40` | 27.302초 후 Watchdog 종료 | 90초 관찰 동안 작업 진행 |
| 교착상태 | `MULTI_THREAD_ENABLE=true → false` | 락 순환 대기, 로그 79.317초 정체 | 90초 관찰 동안 작업·로그 진행 |

이 수치는 **WSL에서 각 조건을 한 번씩 실행한 결과**다. Docker 재현 수치와 섞지 않았다. 앱 로그는 KST, 수집 CSV와 결과 파일은 UTC다. '생존 시간'은 실행을 시작한 때부터 종료를 관측할 때까지이며, 90초에 살아 있던 실행은 **90초 이상 생존**으로 표시했다.

앱이 출력한 Heap과 OS가 측정한 RSS는 범위가 다른 메모리 값이다. 앱의 `Current Load`도 OS가 계산한 프로세스 CPU 사용률과 다르다. 종료 주체는 종료 코드만으로 판단하지 않고 앱 로그, `result.json`의 종료 이유와 수집기의 신호 기록을 함께 확인했다.

## 1. 실측 결과와 보고서

### 1-1. OOM의 메모리 증가와 강제 종료가 기록되어 있는가?

**그렇다.** `MEMORY_LIMIT=64` 실행에서 앱 Heap은 약 3초마다 25MB씩 늘었고, 75MB가 되자 MemoryGuard가 종료를 알렸다. 아래는 실제 앱 로그의 연속된 구간이다.

```text
2026-09-18 18:06:16,803 [INFO] [MemoryWorker] Current Heap: 25MB
2026-09-18 18:06:19,834 [INFO] [MemoryWorker] Current Heap: 50MB
2026-09-18 18:06:22,866 [INFO] [MemoryWorker] Current Heap: 75MB
2026-09-18 18:06:22,867 [CRITICAL] [MemoryGuard] Memory limit exceeded (75MB >= 64MB) / (Recommend Over 256MB)
2026-09-18 18:06:22,868 [CRITICAL] [MemoryGuard] Self-terminating process 2440463 to prevent system instability.
```

같은 워커(PID 2440463)의 RSS도 **17.250 → 67.250MiB**로 증가했다. `result.json`에는 `reason=app_exited`, `launcher_returncode=-9`(SIGKILL), `runner_events=[]`가 남았다. 앱의 자체 종료 로그와 수집기의 신호 기록을 함께 보면 **앱 MemoryGuard의 보호 종료**로 판단할 수 있다. Linux 커널의 OOM Kill을 확인한 결과는 아니다. 마지막 RSS 샘플은 75MB 할당 직전에 찍혔으므로 종료 직전의 최대값은 아니다.

Heap은 앱이 보고한 할당량이고 RSS는 OS가 실제 메모리에 올라와 있다고 본 양이다. 따라서 두 수치가 정확히 같을 필요는 없다. 여기서는 **서로 다른 측정값이 같은 증가 방향을 보인다**는 점이 중요하다.

[원문 로그](evidence/runs/20260918T090614Z-oom-before-402105430/console.log) · [측정 CSV](evidence/runs/20260918T090614Z-oom-before-402105430/metrics.csv)

### 1-2. MEMORY_LIMIT 조정 뒤 생존 시간이 늘었는가?

**그렇다.** 메모리 설정만 64에서 128로 높이자 생존 시간이 **8.418초 → 17.536초**, 약 **2.08배**가 됐다. 두 실행 모두 `CPU_MAX_OCCUPY=100`, `MULTI_THREAD_ENABLE=false`, 최대 관찰 90초, 수집 간격 0.5초였다.

| 비교 항목 | Before | After |
| --- | ---: | ---: |
| 앱 메모리 한도 | 64MB | 128MB |
| 종료 직전 앱 Heap 로그 | 75MB | 150MB |
| 관측한 생존 시간 | 8.418초 | 17.536초 |
| 종료 원인 | MemoryGuard | MemoryGuard |

After에서도 Heap이 150MB에 이르자 `150MB >= 128MB` 보호 로그를 남기고 종료했다. 따라서 한도 상향은 **종료를 늦춘 임시 조치**다.

설정 변경 후에도 약 3초마다 25MB씩 증가하는 모습은 그대로다.

```text
2026-09-18 18:06:45,379 [INFO] [MemoryWorker] Current Heap: 25MB
2026-09-18 18:06:48,408 [INFO] [MemoryWorker] Current Heap: 50MB
2026-09-18 18:06:51,441 [INFO] [MemoryWorker] Current Heap: 75MB
2026-09-18 18:06:54,475 [INFO] [MemoryWorker] Current Heap: 100MB
2026-09-18 18:06:57,505 [INFO] [MemoryWorker] Current Heap: 125MB
2026-09-18 18:07:00,533 [INFO] [MemoryWorker] Current Heap: 150MB
2026-09-18 18:07:00,534 [CRITICAL] [MemoryGuard] Memory limit exceeded (150MB >= 128MB) / (Recommend Over 256MB)
2026-09-18 18:07:00,535 [CRITICAL] [MemoryGuard] Self-terminating process 2440969 to prevent system instability.
```

[After 로그](evidence/runs/20260918T090643Z-oom-after-033262350/console.log) · [두 실행 결과](evidence/manifest.json)

### 1-3. CPU 임계 초과와 종료가 기록되어 있는가?

**그렇다.** 앱의 `Current Load`가 5.00%에서 52.69%로 계속 오른 직후 임계값 위반과 Watchdog의 SIGTERM이 기록됐다. 아래는 실제 앱 로그에서 `CpuWorker`의 연속된 구간이다.

```text
2026-09-18 18:11:24,056 [INFO] [CpuWorker] Current Load: 5.00%
2026-09-18 18:11:27,172 [INFO] [CpuWorker] Current Load: 13.56%
2026-09-18 18:11:30,289 [INFO] [CpuWorker] Current Load: 16.83%
2026-09-18 18:11:33,406 [INFO] [CpuWorker] Current Load: 21.75%
2026-09-18 18:11:36,522 [INFO] [CpuWorker] Current Load: 30.94%
2026-09-18 18:11:39,638 [INFO] [CpuWorker] Current Load: 32.60%
2026-09-18 18:11:42,755 [INFO] [CpuWorker] Current Load: 41.77%
2026-09-18 18:11:45,871 [INFO] [CpuWorker] Current Load: 44.69%
2026-09-18 18:11:48,987 [INFO] [CpuWorker] Current Load: 52.69%
2026-09-18 18:11:49,088 [CRITICAL] [CpuWorker] CPU Threshold Violated! (52.69%).
>>> [SYSTEM] WATCHDOG: INITIATING EMERGENCY ABORT (SIGTERM) <<<
```

워커 PID 2445628의 OS 측정 CPU는 종료 직전 약 0.1초 구간에서 **58.26%**였다. 두 수치는 계산 방식이 다르므로 같은 임계값으로 비교하지 않는다. `result.json`에는 `reason=app_exited`, `launcher_returncode=-15`, `runner_events=[]`가 남아 있어 수집기가 보낸 종료 신호는 없었다. 앱의 정확한 내부 임계값이나 계산식까지 확인한 것은 아니다.

`CPU_MAX_OCCUPY=100`이라는 설정만 보고 CPU가 정확히 100%일 때 종료한다고 해석할 수 없다. 실제로 확인한 것은 **앱이 52.69%에서 정책 위반을 선언하고 종료했다**는 사실이다.

`Current Load` 로그는 약 3초 간격이고, OS의 CPU 측정은 0.1초 간격이다. 위 로그는 앱 내부 부하의 상승을, [측정 CSV](evidence/runs/20260918T091121Z-cpu-before-748323350/metrics.csv)는 워커의 구간 CPU 사용률을 보여 준다. [원문 로그](evidence/runs/20260918T091121Z-cpu-before-748323350/console.log)

### 1-4. CPU_MAX_OCCUPY 조정 후 종료·생존이 달라졌는가?

**그렇다.** `CPU_MAX_OCCUPY=100`에서는 **27.302초 후 Watchdog 종료**, `40`에서는 **90초 이상 생존**하며 냉각과 작업 재개 로그가 이어졌다. 두 실행의 `MEMORY_LIMIT=512`, `MULTI_THREAD_ENABLE=false`, 관찰 상한 90초, 수집 간격 0.1초는 같았다.

| 비교 항목 | Before | After |
| --- | --- | --- |
| 변경한 설정 | `CPU_MAX_OCCUPY=100` | `CPU_MAX_OCCUPY=40` |
| 관찰 결과 | 27.302초 후 앱 종료 | 90초 관찰 때까지 생존 |
| 종료를 알리는 근거 | Watchdog 위반 로그 | 관찰 상한 후 수집기의 정리 신호 |

After의 앱 로그에서는 부하가 5.00%에서 40.00%까지 오른 뒤 냉각되고, 다시 증가한다. 아래는 `CpuWorker` 행만 시간순으로 뽑은 원문이다.

```text
2026-09-18 18:12:53,775 [INFO] [CpuWorker] Current Load: 5.00%
2026-09-18 18:12:56,891 [INFO] [CpuWorker] Current Load: 14.00%
2026-09-18 18:13:00,005 [INFO] [CpuWorker] Current Load: 18.17%
2026-09-18 18:13:03,121 [INFO] [CpuWorker] Current Load: 26.96%
2026-09-18 18:13:06,237 [INFO] [CpuWorker] Current Load: 33.44%
2026-09-18 18:13:08,348 [INFO] [CpuWorker] Peak reached (40.00%). Starting cooldown...
2026-09-18 18:13:09,355 [INFO] [CpuWorker] Current Load: 40.00%
2026-09-18 18:13:12,471 [INFO] [CpuWorker] Current Load: 38.77%
2026-09-18 18:13:15,587 [INFO] [CpuWorker] Current Load: 35.26%
2026-09-18 18:13:18,704 [INFO] [CpuWorker] Current Load: 33.39%
2026-09-18 18:13:21,813 [INFO] [CpuWorker] Current Load: 27.29%
2026-09-18 18:13:24,929 [INFO] [CpuWorker] Current Load: 18.17%
2026-09-18 18:13:28,042 [INFO] [CpuWorker] Current Load: 9.20%
2026-09-18 18:13:30,153 [INFO] [CpuWorker] Cooldown complete (5.00%). Resuming load increase...
2026-09-18 18:13:31,159 [INFO] [CpuWorker] Current Load: 5.00%
2026-09-18 18:13:34,273 [INFO] [CpuWorker] Current Load: 10.17%
2026-09-18 18:13:37,389 [INFO] [CpuWorker] Current Load: 12.11%
2026-09-18 18:13:40,506 [INFO] [CpuWorker] Current Load: 12.48%
2026-09-18 18:13:43,622 [INFO] [CpuWorker] Current Load: 22.00%
2026-09-18 18:13:46,733 [INFO] [CpuWorker] Current Load: 26.98%
2026-09-18 18:13:49,845 [INFO] [CpuWorker] Current Load: 34.93%
2026-09-18 18:13:51,956 [INFO] [CpuWorker] Peak reached (40.00%). Starting cooldown...
2026-09-18 18:13:52,963 [INFO] [CpuWorker] Current Load: 40.00%
```

After의 `result.json`에는 `reason=observation_timeout`, `alive_before_cleanup=true`, 수집기가 보낸 `SIGTERM`이 기록됐다. 따라서 After의 최종 종료 코드 `-15`는 장애 재발이 아니라 **90초 관찰을 마친 뒤 정리한 결과**다. [After 로그](evidence/runs/20260918T091250Z-cpu-after-355471748/console.log) · [종료 결과](evidence/runs/20260918T091250Z-cpu-after-355471748/result.json)

### 1-5. 살아 있지만 로그와 자원이 정체된 상태를 식별했는가?

**그렇다.** 워커 PID 2448740은 관찰 종료 직전까지 살아 있었지만, **79.317초** 동안 로그 크기가 그대로였고 CPU는 0%, RSS는 17.250MiB였다.

| 근거 | 관측값 |
| --- | --- |
| 로그 크기 | `console.log` 2881 bytes, 앱 로그 1517 bytes로 유지 |
| 관측 시각 | UTC 09:14:44.539 → 09:16:03.856 |
| 워커 상태 | 동일 PID·시작 틱 유지, `alive_before_cleanup=true` |
| 스레드 대기 | `ps -L`에서 워커 스레드들이 `futex_wait_queue` 대기 |

정상적으로 다음 입력을 기다리는 앱도 CPU가 0%이고 로그가 멈출 수 있다. 그래서 **살아 있음과 작업 진행은 별도로 확인**했다. 포트가 열린 상태 역시 요청이 실제로 처리되고 있다는 증거는 아니다. 아래 3-4의 **서로 상대 락을 기다리는 로그**까지 합쳐 교착으로 판단했다. [관측 스냅샷](evidence/runs/20260918T091433Z-deadlock-before-531338111/snapshots.txt) · [로그 크기 기록](evidence/runs/20260918T091433Z-deadlock-before-531338111/log-sizes.jsonl)

### 1-6. MULTI_THREAD_ENABLE 조정 후 재현·회피를 비교했는가?

**그렇다.** `true`에서는 A와 B를 가진 두 스레드가 서로를 기다린 뒤 작업 로그가 멈췄다. `false`로 바꾼 새 실행에서는 `All tasks completed`, `Memory Cache Flushed`와 이후 Heap 로그가 이어졌다.

두 실행은 `MEMORY_LIMIT=512`, `CPU_MAX_OCCUPY=40`, 관찰 상한 90초, 수집 간격 0.5초를 같게 했다. 둘 다 관찰 종료 때 살아 있었지만, **락 대기 시점 이후의 작업 진행은 After에서만 확인**됐다. `false`는 문제의 동시 처리 경로를 피한 설정이며, 이미 걸린 락을 풀거나 락 설계를 고친 결과는 아니다.

After 로그에는 18:17:16의 `All tasks completed` 이후에도 메모리 회수와 새 Heap 기록이 이어진다. 이처럼 **완료 뒤에도 새 활동이 보인다는 점**이 단순한 PID 생존보다 강한 회피 근거다. `false`를 앱 전체가 단일 스레드로만 실행됐다는 뜻으로 해석하지 않는다.

After의 긴 로그에서 작업 완료와 메모리 회수 전후의 행을 발췌했다. 회수 뒤에도 Heap 로그가 다시 쌓여 작업이 이어졌음을 볼 수 있다.

```text
2026-09-18 18:17:16,593 [INFO] [Scheduler] All tasks completed.
2026-09-18 18:18:14,098 [INFO] [MemoryWorker] Current Heap: 500MB
2026-09-18 18:18:17,131 [INFO] [MemoryWorker] Current Heap: 525MB
2026-09-18 18:18:17,146 [INFO] [System] Memory Cache Flushed. Process Stabilized.
2026-09-18 18:18:22,173 [INFO] [MemoryWorker] Current Heap: 25MB
2026-09-18 18:18:25,204 [INFO] [MemoryWorker] Current Heap: 50MB
2026-09-18 18:18:28,228 [INFO] [MemoryWorker] Current Heap: 75MB
2026-09-18 18:18:31,259 [INFO] [MemoryWorker] Current Heap: 100MB
```

[Before 락 로그](evidence/runs/20260918T091433Z-deadlock-before-531338111/console.log) · [After 진행 로그](evidence/runs/20260918T091713Z-deadlock-after-166295630/console.log)

### 1-7. 세 보고서가 GitHub Issue 구조를 갖췄는가?

**그렇다.** [OOM](reports/01-oom.md), [CPU](reports/02-cpu.md), [Deadlock](reports/03-deadlock.md) 보고서 모두 **현상 → 증거 → 원인 → 조치 및 검증** 순서로 작성했다. GitHub Issue에 옮길 수 있는 형식이라는 뜻이며, 실제 Issue 등록 여부와는 별개다.

예를 들어 OOM 보고서는 **메모리 누적과 종료 → Heap·RSS·종료 로그 → 앱 한도 초과 판단 → 한도 변경 후 생존 시간 비교**로 이어진다. 나머지 두 보고서도 같은 순서로 증거와 판단을 연결했다.

### 1-8. PID·타임스탬프·핵심 로그가 증거로 첨부됐는가?

**그렇다.** 세 보고서에 원문 로그와 CSV 링크, 워커 PID, 시각과 핵심 문장을 넣었다.

| 장애 | 워커 PID | 핵심 시각(KST)과 메시지 |
| --- | ---: | --- |
| OOM | 2440463 | 18:06:22.868 자체 종료 |
| CPU | 2445628 | 18:11:49.088 임계값 위반 및 Watchdog |
| Deadlock | 2448740 | 18:14:42.871 / 42.880 서로 다른 락 대기 |

앱 로그에 PID가 없는 줄은 같은 실행의 `ss`·`ps` 스냅샷과 CSV로 포트 소유 워커에 연결했다. 앱 로그(KST)와 수집 기록(UTC)은 9시간 차이를 맞춰 비교했다.

예를 들어 Deadlock 로그의 **18:14:42 KST**는 측정 파일의 **09:14:42 UTC**와 같은 때다. 시간대가 다르다는 점을 놓치면 서로 다른 실행의 로그처럼 보일 수 있다.

## 2. 수집 도구와 진단 과정

### 2-1. monitor.sh는 메모리 증가를 어떻게 추적했는가?

`bin/monitor.sh`는 [Python 수집기](lib/monitor.py)를 실행한다. 수집기는 대상 프로세스의 `/proc/PID/stat`에서 **24번째 필드인 RSS 페이지 수**를 읽고, 시스템 페이지 크기를 곱해 KiB로 바꾼다. 그 값을 시각·PID·시작 틱과 함께 `metrics.csv`에 기록한다. 예를 들어 `17664KiB ÷ 1024 = 17.250MiB`다.

`/proc/PID/stat`의 RSS는 바이트가 아닌 **페이지 수**다. 수집기는 프로세스 이름 뒤의 `)`를 먼저 찾은 다음 나머지 필드를 분리한다. 이름에 공백이 있어도 RSS 열을 잘못 읽지 않기 위해서다. 읽은 페이지 수에 `SC_PAGE_SIZE`를 곱해 바이트 단위로 바꾼 뒤 1024로 나눠 KiB로 저장한다.

실행기와 워커의 PID가 달라 `--pgid`로 프로세스 그룹을 추적하고, `ss`로 15034 포트 소유 워커를 골랐다. OOM 비교에서는 같은 워커의 RSS를 **0.5초 간격**으로 읽었다. 시작 틱은 PID 재사용으로 다른 프로세스의 측정값이 섞이는 일을 막는다.

### 2-2. CPU 사용률을 확인한 도구와 옵션은 무엇인가?

주요 시계열 값은 [수집기](lib/monitor.py)가 `/proc`의 사용자·시스템 CPU 누적 틱 차이를 실제 경과 시간으로 나눠 계산했다. **100%는 논리 CPU 하나를 계속 사용한 수준**이다. CPU 실험은 짧은 상승을 보기 위해 0.1초 간격으로 수집했다.

계산 순서는 **두 샘플 사이 CPU 틱 증가량 → CPU를 실제로 사용한 시간 → 그 구간의 경과 시간 대비 비율**이다. 예를 들어 0.1초 사이에 CPU를 0.06초 썼다면 구간 사용률은 약 60%다. 여러 CPU 코어를 동시에 쓰는 프로세스는 이 방식에서 100%를 넘을 수도 있다.

| 도구 | 주요 옵션과 용도 |
| --- | --- |
| 수집기 `--pgid ... --interval 0.1` | 프로세스 그룹을 0.1초마다 관찰 |
| `ps -p ... -o pid,ppid,pgid,stat,pcpu,rss` | PID 선택 및 프로세스 관계·상태·자원 열 표시 |
| `ps -L -p ... -o pid,tid,stat,wchan` | 스레드별 상태와 커널 대기 지점 확인 |
| `top -b -H -n 1 -p ...` | 한 번의 배치 스냅샷에서 스레드 확인 |
| `ss -ltnp 'sport = :15034'` | LISTEN TCP 포트의 소유 PID 확인 |

`ps %CPU`는 프로세스 수명 기준 평균이므로 수집기의 0.1초 구간 값과 바로 비교하지 않았다. 앱의 `Current Load`도 별도 지표다.

### 2-3. 살아 있지만 멈춘 프로세스를 어떤 순서로 진단했는가?

자동 수집된 자료를 다음 순서로 해석했다. 처음 네 단계는 같은 Before 실행, 마지막 단계는 설정을 바꾼 별도 After 실행이다.

1. **대상 식별:** `ss -ltnp 'sport = :15034'`로 포트 소유 워커 PID **2448740**을 찾고 `ps`의 부모·그룹 정보를 확인했다. 실행기 PID **2448732**과 구분했다.
2. **생존 확인:** `metrics.csv`의 첫·마지막 기록에서 PID와 `start_ticks=21797426`이 같고 상태가 `S`(대기)임을 확인했다. PID가 한 번 보였다는 사실만으로 생존을 판단하지 않았다.
3. **진행 확인:** 같은 워커의 CPU **0.00%**, RSS **17664KiB**가 유지되고 로그 크기도 **79.317초** 동안 변하지 않았다.
4. **대기 원인 확인:** `ps -L`의 `futex_wait_queue`는 동기화 대기를 보여 준다. 앱 로그의 A 소유·B 대기와 B 소유·A 대기를 결합해 순환 관계를 찾았다. `futex`만으로 어느 락을 기다리는지는 알 수 없다.
5. **조치 검증:** `MULTI_THREAD_ENABLE=false`로 새로 실행하자 90초 관찰 동안 작업 완료와 로그 갱신이 이어졌다. `result.json`의 `alive_before_cleanup=true`로 관찰 종료 시점의 생존도 확인했다.

핵심 판정은 **같은 PID의 생존 + 작업 정체 + 양방향 락 대기**다. [Before 스냅샷](evidence/runs/20260918T091433Z-deadlock-before-531338111/snapshots.txt) · [Before 측정 CSV](evidence/runs/20260918T091433Z-deadlock-before-531338111/metrics.csv) · [After 결과](evidence/runs/20260918T091713Z-deadlock-after-166295630/result.json)

`start_ticks`는 프로세스가 시작된 시점에 커널이 부여한 값이다. PID 번호만 같으면 종료 후 재사용된 다른 프로세스를 같은 워커로 착각할 수 있어 두 값을 함께 비교했다. `futex_wait_queue`는 동기화 대기 지점이지만 어떤 앱 락인지 알려 주지는 않으므로, 마지막 단계에서 앱의 락 로그가 필요했다.

## 3. 장애가 발생하고 보호하는 원리

### 3-1. 메모리 보호 정책은 왜 프로세스를 종료하는가?

**계속 늘어나는 메모리 소비를 멈추고 피해가 퍼질 가능성을 줄이기 위해서다.** 프로세스를 종료하면 그 프로세스가 쓰던 메모리를 OS가 회수할 수 있다. 이번에는 앱이 `75MB >= 64MB`를 감지해 스스로 종료했다. 이는 커널 OOM Kill의 증거가 아니다. 보호 종료는 증상을 멈추는 조치이며, 누적 원인은 별도로 고쳐야 한다.

앱의 `MEMORY_LIMIT`는 이 실습 앱이 해석하는 설정이다. OS가 그 값을 보고 메모리를 강제로 제한한 것은 아니다. 실제 운영에서도 한도를 올리기만 하면 누적 속도가 그대로인 경우 나중에 다시 같은 문제가 생긴다.

### 3-2. CPU 과점유 시 왜 단일 프로세스를 종료하는가?

**문제 프로세스의 CPU 소비를 멈춰 다른 작업이 실행할 시간을 확보하기 위해서다.** 이번 앱은 자체 Watchdog 정책 위반을 기록하고 해당 프로세스에 SIGTERM을 보냈다. CPU 사용률이 높다는 이유만으로 항상 종료할 필요는 없으므로, 운영에서는 지속 시간·작업 진행·응답 지연도 살피고 유입 제한이나 워커 수 조절을 검토한다. 다른 서비스의 지연 개선은 이번 실험에서 측정하지 않았다.

여기서 '단일 프로세스'는 **원인이 확인된 해당 프로세스를 골라 조치한다**는 의미다. 호스트 전체 CPU 사용률과 워커 한 개의 구간 사용률은 다른 값이므로, 어느 프로세스가 실제로 CPU를 쓰는지 PID 기준으로 먼저 확인해야 한다.

### 3-3. 상호 배제와 순환 대기로 교착상태를 설명할 수 있는가?

**각자 하나씩만 소유할 수 있는 락을 가진 채 상대의 락을 기다리면 둘 다 진행하지 못한다.** '상호 배제'는 A와 B를 각각 한 스레드만 가질 수 있다는 뜻이다. Thread-1은 A를 가진 채 B를, Thread-2는 B를 가진 채 A를 기다린다. 두 스레드가 다음 락을 얻어야 현재 락을 놓는다면 서로 상대가 먼저 놓기를 기다리는 **순환 대기**가 된다.

기다리는 동안 락을 강제로 빼앗거나 놓지 않는다면 대기는 계속된다. 이때 스레드가 잠들 수 있으므로 CPU가 낮아도 교착일 수 있다.

```text
Thread-1: A 보유 → B 대기 → Thread-2가 B 보유
Thread-2: B 보유 → A 대기 → Thread-1이 A 보유
```

### 3-4. 로그에서 A→B, B→A 관계를 어떻게 찾았는가?

시간순으로 각 스레드의 `LOCK ACQUIRED`와 `WAITING` 대상을 연결했다. 아래는 시각과 핵심 메시지만 추린 로그다.

```text
18:14:40.866 Thread-1 LOCK ACQUIRED: Shared_Memory_A
18:14:40.866 Thread-2 LOCK ACQUIRED: Socket_Pool_B
18:14:42.871 Thread-1 WAITING for Socket_Pool_B
18:14:42.880 Thread-2 WAITING for Shared_Memory_A
```

로그의 `LOCK ACQUIRED`는 이미 쥔 자원, `WAITING`은 추가로 필요한 자원이다. Thread-1의 B는 Thread-2가, Thread-2의 A는 Thread-1이 쥐고 있다. 따라서 Thread-1은 **A→B**, Thread-2는 **B→A** 순서로 락이 필요하다. 이후 해제·완료 로그가 없고 OS 관측도 정체돼 순환 대기로 판단했다. 앱의 스레드 이름을 OS의 TID와 일대일로 연결한 것은 아니다. [락 로그 원문](evidence/runs/20260918T091433Z-deadlock-before-531338111/console.log)

## 4. 운영 환경에 적용하기

이 절은 실측 결과에서 출발한 **개선 제안**이다. 제공 바이너리의 내부 코드를 확인하거나 아래 변경을 구현한 것은 아니다.

### 4-1. 장애 전에 메모리 누수를 탐지하도록 monitor.sh를 어떻게 개선할 것인가?

**현재 RSS뿐 아니라 증가 속도와 메모리 회수 후의 기준선을 기록하겠다.** 정상 캐시도 잠시 증가할 수 있으므로, 회수 뒤 기준선이 계속 높아지는지 여러 구간에서 확인한 뒤 경보한다. 수집기의 PID·시작 틱에 추세를 연결하고, 컨테이너 한도와 사용량·마지막 작업 완료 시각도 함께 기록한다. 추세 계산은 `monitor.sh`가 호출하는 Python 수집기나 별도 분석기에 추가한다.

예를 들어 RSS가 올라가다가 `Memory Cache Flushed` 후 이전 수준으로 돌아오면 캐시 사용일 수 있다. 같은 부하를 반복해도 회수 후 최저값이 계속 높아진다면 누적을 의심할 근거가 강해진다. 경보에는 현재값뿐 아니라 최근 증가율과 해당 시각의 설정·로그를 함께 넣겠다.

한도까지 남은 시간을 추정할 때는 같은 범위의 지표만 사용한다. 예컨대 컨테이너 사용량 800MiB, 한도 1000MiB, 증가율 10MiB/s라면 약 20초다. 회수 없이 같은 속도로 증가한다는 가정이 필요하며, 프로세스 RSS와 앱 Heap 한도를 섞어 계산하면 안 된다.

### 4-2. 세 장애 중 무엇이 가장 치명적이며 어떻게 예방할 것인가?

**격리가 부족한 공유 서버라면 호스트 메모리 고갈이 가장 치명적이다.** 한 앱의 누적이 다른 서비스의 할당과 복구 도구 실행까지 방해할 수 있기 때문이다. 이는 **영향 범위**를 기준으로 한 운영 상황의 가정이다. 이번 실습에서 관측한 것은 앱 MemoryGuard의 자체 종료이며, 호스트 전체의 메모리 고갈은 확인하지 않았다.

예방하려면 불필요한 참조를 제거하고 캐시·큐의 크기와 보관 시간을 제한하며, 유입이 처리량을 넘으면 입력을 제어해야 한다. 같은 부하를 오래 주고 회수 뒤 기준선이 안정되는지 확인한다. 메모리 문제가 컨테이너 안에 격리돼 있고 교착이 모든 요청을 막는 서비스라면 교착상태가 더 시급할 수 있다.

### 4-3. OOM과 Deadlock이 동시에 발생하면 어떤 순서로 대응할 것인가?

1. 호스트·컨테이너의 남은 메모리와 서비스 영향을 확인하고, 같은 PID에서 두 증상이 나타났는지 살핀다.
2. 메모리 추세와 마지막 락 로그를 짧게 보존한다.
3. 메모리 고갈이 임박했다면 유입을 제한하고 문제 인스턴스를 정상 종료·교체한다. 교착으로 응답하지 않으면 정해진 유예 뒤 강제 종료한다.
4. 확보한 증거로 락 소유·대기를 분석하고, 큐 적체가 메모리 증가를 일으켰는지도 확인한다.
5. 재시작 여부만 보지 않고 작업 완료·메모리 추세·응답을 검증한다.

메모리가 충분히 격리되고 교착이 전체 요청을 막는다면 서비스 복구를 먼저 진행한다.

우선순위를 정하는 기준은 장애 이름보다 **남은 메모리 여유와 실제 요청 영향**이다. 메모리 여유가 거의 없다면 무거운 덤프 수집으로 복구를 늦추기보다 짧은 로그와 지표를 먼저 남긴다. 그 뒤 교착을 재현해 락 순서를 고치는 쪽으로 원인을 좁힌다.

### 4-4. 소스를 수정할 수 있다면 각 장애를 어떻게 개선할 것인가?

| 장애 | 소스 수정 후보 | 확인할 결과 |
| --- | --- | --- |
| 메모리 | 불필요한 참조 정리, 캐시·큐 상한과 만료 | 장시간 같은 부하에서 회수 후 기준선 안정 |
| CPU | 프로파일링 후 반복 연산·busy wait·무제한 재시도 수정 | 같은 요청량에서 CPU·처리량·지연 비교 |
| Deadlock | 모든 경로에서 락 획득 순서를 A→B로 통일하고 실패 시 보유 락 해제 | 동시 요청·예외 상황에서도 제한 시간 안에 완료 |

실제 원인은 바이너리 내부 소스를 확인한 뒤 좁혀야 한다. 환경변수 변경이나 한도 상향만으로 코드 원인을 고쳤다고 보지 않는다.

특히 Deadlock은 두 경로가 모두 **A를 먼저 획득하고 B를 나중에 획득**하도록 맞추면 이번 A↔B 순환을 끊을 수 있다. 단, 두 번째 락을 얻지 못했을 때 첫 락을 확실히 해제해야 한다. 메모리와 CPU 수정도 사용량만 낮추는 데 그치지 않고 처리량·오류·작업 완료 여부를 함께 비교해야 한다.

### 4-5. 다시 수행한다면 무엇을 다르게 할 것인가?

**실험 전에 대상 PID, 수집 간격, 종료 판정 기준을 정하고 조건별로 여러 번 실행하겠다.** 이번 기록에서 실행기와 워커 PID가 달랐고, CPU After도 종료 코드는 `-15`였지만 수집기의 정리 신호로 끝났다. 다음에는 포트 소유 워커를 처음부터 지정하고 앱 종료와 관찰 종료를 구분하겠다.

비교 쌍의 수집 간격을 같게 하고, KST·UTC를 함께 기록하며, Before/After 실행 순서를 바꿔 반복한다. 90초에 살아 있는 경우에는 정확한 수명 대신 **90초 이상 생존**으로 적는다. 실제 응답 지연의 개선을 주장하려면 별도로 요청 지연을 측정한다.

반복 실행으로 생존 시간의 범위를 보면 한 번의 우연한 호스트 부하에 휘둘리지 않을 수 있다. 장애별로 OOM은 증가와 보호 종료, CPU는 Watchdog 로그와 작업 진행, Deadlock은 생존·정체·순환 대기를 미리 판정 기준으로 적어 두겠다.

## 5. 보너스: 스케줄링 분석

**앱 로그의 A→B→C 순환과 `Preempted`·`Resumed`를 근거로 앱 수준의 Round-Robin 패턴을 추론했다.** CPU After 로그에서 A·B·C는 차례로 40%까지 진행한 뒤 상태를 저장했고, 다음 순회에서는 60~80%, 마지막 순회에서는 100%까지 이어서 실행됐다. 18:12:53.758에 `All tasks completed`가 기록됐다.

예를 들어 A가 `Preempted. Progress saved at (40%)`를 남긴 뒤 B와 C가 실행되고, 다음 차례의 A는 `Resumed`로 저장한 진행률에서 이어간다. 한 작업을 끝까지 실행하는 방식과 달리 **각 작업에 차례를 돌린다**는 점이 판단 근거다.

한 작업이 끝날 때까지 기다리지 않고 실행 기회를 번갈아 주는 방식은 다른 작업의 긴 대기를 줄일 수 있지만 전환 비용이 든다. 이 기록은 **앱이 출력한 작업 순서**를 보여 주며 Linux 커널의 실제 `SCHED_RR` 정책을 입증하지는 않는다. [CPU After 로그](evidence/runs/20260918T091250Z-cpu-after-355471748/console.log)
