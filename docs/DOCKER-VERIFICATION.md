# Docker 구성 검증 기록

2026-09-20 KST 검증. 앱 로그와 수집 시각은 컨테이너에서 UTC를 사용하므로 원문 파일에는 2026-09-19로 기록되어 있다. 기존 [WSL 제출 증거 검증](VERIFICATION.md)과 별도의 실행이다.

## 환경과 실제 적용 설정

| 항목 | 확인한 값 |
| --- | --- |
| 호스트 | Windows + Docker Desktop, WSL2 Linux 커널 6.6.87.2 |
| Docker Engine / Compose | 29.3.1 / v5.1.1 |
| 기본 이미지 | `python:3.12-slim-bookworm`, Debian glibc 2.36 |
| 기본 이미지 manifest digest | `sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e` |
| 실제 비교 실험 | 네이티브 Linux amd64, 논리 CPU 12개 |
| UID:GID | `1000:1000` |
| 네트워크 / root 파일시스템 | `none` / 읽기 전용 |
| 권한 | `cap_drop: ALL`, `no-new-privileges:true`, 추가 privileged 권한 없음 |
| 컨테이너 메모리 / 스왑 | 1,610,612,736 bytes / 0 bytes |
| CPU 쿼터 / PID 제한 | `cpu.max=max 100000` / 256 |
| 종료 처리 | Docker init 활성화, 유예 30초 |
| 데이터 | `/input` 읽기 전용 ZIP, `/data` named volume |

`docker inspect`로 실행 중인 컨테이너의 설정을 확인했다. `doctor`와 실행 metadata에서 cgroup v2 제한을 읽고, 앱의 실제 부팅·15034 포트 소유 PID를 별도로 확인했다. 이미지 빌드 문맥은 소스·도구·테스트만 허용하며 제공 ZIP, 바이너리, 증거, 키, Git 자료를 제외한다.

Dockerfile은 배포판·Python 계열을 고정하지만 태그와 apt 패키지는 이후 갱신될 수 있다. 위 digest는 이번 빌드의 식별 정보이며, 미래 빌드가 바이트 단위로 같다는 보장은 아니다.

## 실제 제공 앱: 6개 비교 실험

```text
docker compose build lab
docker compose run --rm lab doctor
docker compose run --rm lab suite
docker compose create lab
docker compose cp lab:/data/. ./docker-evidence
```

이번 비교 목록: `suite-20260919T160308Z-1789833788082871955.json`. 각 실행의 상한은 90초, CPU 샘플 간격은 0.1초, OOM·Deadlock은 0.5초, 스냅샷은 5초다.

| 케이스 | 관찰 시간 | 종료·진행 근거 |
| --- | --- | --- |
| oom-before | 8.202초 | RSS 17.50→최대 67.50MiB, MemoryGuard, 앱 SIGKILL |
| oom-after | 17.407초 | RSS 17.25→최대 142.25MiB, MemoryGuard, 앱 SIGKILL |
| cpu-before | 33.405초 | Watchdog의 emergency abort 로그, 앱 SIGTERM |
| cpu-after | 90.075초 | 관찰 상한까지 생존, 작업 완료·캐시 회수, 이후 수집기가 정리 |
| deadlock-before | 90.030초 | 두 락의 소유·대기 순환, 로그 79.635초 정체, PID 생존 |
| deadlock-after | 90.043초 | 관찰 상한까지 작업·로그 진행, 이후 수집기가 정리 |

여섯 실행 모두 UID 1000, 동일 x86 바이너리 SHA256, Boot Checks·READY, 워커 포트 소유 PID와 시계열을 확인했다. 수집기 오류와 시스템 도구 접근 오류가 없었다. 세 쌍 모두 관심 환경변수만 변경했고, 관찰 상한과 샘플 간격을 맞췄다.

**모든 실행에서 `cgroup_oom_kill_delta=0`이었다.** OOM 케이스의 `-9`는 MemoryGuard 로그와 수집기 정리 신호 부재를 함께 확인했다. 컨테이너 메모리 제한으로 발생한 커널 OOM 사례로 분류하지 않았다.

CPU 워커의 구간 최대 사용률은 Before 59.69%, After 109.33%였다. 한 논리 CPU가 100%이며 멀티스레드 프로세스는 이를 넘을 수 있다. 이 결과는 **`CPU_MAX_OCCUPY=40`이 OS 사용률의 강제 상한이 아니라는 점**을 보여 준다. 최대값 감소를 조치 효과로 주장하지 않고, Watchdog 종료 회피·작업 진행·냉각 로그를 근거로 해석한다. CPU·시간의 절대값은 호스트 부하와 계측 시점에 따라 달라진다.

전체 원문은 로컬 `docker-evidence/runs/`와 Docker 볼륨 `codyssey-mission4-2_lab-evidence`에 보존했다. 새 실험 폴더는 Git에서 제외하며, 기존 `evidence/`의 WSL 실측을 덮어쓰지 않았다. 보고서를 재작성할 때는 위 suite 목록으로 이번 여섯 실행을 골라야 한다.

## 도구 테스트와 종료 처리

- 호스트 Python 테스트 **19개 통과**.
- 최종 Docker 이미지 내부 `docker compose run --rm lab test`: **19개 통과**.
- 기존 WSL 제출 증거 `python3 scripts/verify-evidence.py`: **50개 통과**.
- Docker 볼륨에 남은 결과를 새 컨테이너의 `show`에서 읽고, 생성만 한 서비스 컨테이너의 `/data`를 Windows 폴더로 복사하는 절차 확인.

추가한 테스트는 ZIP의 실제 아키텍처 선택·ELF 불일치·기존 파일 덮어쓰기 거부·누락 파일·root 실행 거부·볼륨 쓰기·미완료 실행 조회·cgroup OOM 카운터·현재 프로세스의 cgroup 경로를 다룬다. 기존 테스트는 프로세스 추적, CPU·RSS 수집, 정리·중단, 종료 원인 구분을 다룬다.

종료 검증 전용 컨테이너에 Docker stop으로 SIGTERM을 보냈다. 120초 상한 실행이 44.108초에 `interrupted`로 끝났고, 수집기가 받은 신호 15와 앱에 보낸 SIGTERM, 정상 종료한 monitor, cgroup OOM 증가량 0을 기록했다. `--rm`으로 해당 컨테이너가 제거된 뒤에도 볼륨의 `result.json`과 요약을 읽을 수 있었다.

중단 검증 실행은 `20260919T171743Z-deadlock-before-634904170`이며, 위 90초 비교 실험에 포함하지 않는다.

## ARM64 실행 호환성

동일 Dockerfile을 `linux/arm64`로 빌드해 별도 이미지에서 제공 ARM64 앱을 실행했다. **amd64 호스트의 Docker 에뮬레이션 검증이며 실제 Apple Silicon 장비 검증은 아니다.**

- `ARCH=aarch64`, `agent-leak-app-arm64` 자동 선택.
- SHA256: `2edd8eb1b6ae40ac611afe880b864f0399ff0977bfd72d9d0fd98aa41ca6d1ff`.
- UID 1000, 같은 네트워크·권한·메모리 제한으로 Boot Checks·READY·15034 포트 확인.
- OOM Before: 8.960초에 MemoryGuard 로그와 `-9` 종료, 수집기 신호 없음, `cgroup_oom_kill_delta=0`.
- 워커 PID 30의 RSS 시계열과 summary 생성, monitor 정상 종료.

ARM64 원문은 별도 볼륨 `codyssey-mission4-2_arm64-check`에 보존했다. ARM64에서 CPU·Deadlock 전체 비교나 성능 동등성을 검증한 것은 아니다. 실제 Apple Silicon에서는 기본 Compose로 네이티브 ARM64 이미지를 빌드하고 [튜토리얼](../TUTORIAL.md)에 따라 전후 비교를 수행한다.
