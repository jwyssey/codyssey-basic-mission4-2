# 실측 증거 상태

2026-09-18 최종 수행 완료.

| 항목 | 상태 |
| --- | --- |
| 제공 `agent-app-leak.zip` | x86 파일 추출, 원본 SHA256 보존 |
| 필수 환경·일반 계정·15034 바인딩 | 독립 네트워크에서 6회 부팅 성공 |
| OOM Before/After | 64 → 128 MB, 8.418 → 17.536초 후 MemoryGuard 종료 |
| CPU Before/After | 100 → 40%, Watchdog 종료 → 90초 생존 |
| Deadlock Before/After | true → false, 순환 대기 → 작업 진행 |
| 보고서 | 실측 기반 3건 + 스케줄링 보너스 1건 |
| 공통 Issue 템플릿 | templates/issue-report.md |
| 수집기 테스트 | [11개 통과](tool-tests.txt) |
| 실측 증거 검사 | [50개 통과](verification.txt) |
| 결과 보고서 | [README의 장애 분석·그래프·전후 비교](../README.md) |

실험 목록·명령은 [manifest.json](manifest.json), 파생 통계는 [comparison.json](comparison.json), 원본 체크섬은 [artifact.json](artifact.json)에 있다. 초기 포트 조회 기록은 과거 환경 조사 자료이며, 최종 포트 바인딩은 각 실행의 snapshots.txt에서 확인한다. 수집기 테스트 결과와 제공 앱의 실측 증거는 분리했다.
