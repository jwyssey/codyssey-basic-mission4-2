#!/usr/bin/env python3
"""제출할 6회 실측 증거의 원본·설정·종료 원인·비교 조건을 검증한다."""
import hashlib
import json
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from experiment import PRESETS


def main():
    manifest = json.loads((ROOT / "evidence/manifest.json").read_text())
    stats = json.loads((ROOT / "evidence/comparison.json").read_text())
    artifact = json.loads((ROOT / "evidence/artifact.json").read_text())
    errors = []
    count = 0

    def check(condition, label):
        nonlocal count
        count += 1
        print(f"[{'PASS' if condition else 'FAIL'}] {label}")
        if not condition:
            errors.append(label)

    check(hashlib.sha256((ROOT / "vendor/agent-leak-app-x86").read_bytes()).hexdigest() == artifact["binary_sha256"], "원본 바이너리 SHA256 일치")
    logs = {}
    sizes = {}
    for case, relative in manifest["runs"].items():
        directory = ROOT / relative
        meta, result = stats[case]["metadata"], stats[case]["result"]
        logs[case] = (directory / "console.log").read_text()
        sizes[case] = [json.loads(line) for line in (directory / "log-sizes.jsonl").read_text().splitlines()]
        snapshots = (directory / "snapshots.txt").read_text()
        check(meta["uid"] != 0 and meta["evidence_source"] == "provided_app" and meta["app_sha256"] == artifact["binary_sha256"], f"{case}: 일반 계정·제공 원본")
        actual = tuple(meta["environment"][key] for key in ("MEMORY_LIMIT", "CPU_MAX_OCCUPY", "MULTI_THREAD_ENABLE"))
        check(actual == tuple(map(str, PRESETS[case])), f"{case}: 확정 비교 설정")
        check(logs[case].count("[OK]") >= 6 and "Agent READY" in logs[case], f"{case}: 부팅 완료")
        check(result["error"] is None and result["monitor_returncode"] == 0 and (directory / "monitor-stderr.log").stat().st_size == 0, f"{case}: 관제 오류 없음")
        check(stats[case]["samples"] >= 10 and f'pid={stats[case]["worker_pid"]},' in snapshots and "ps -L" in snapshots, f"{case}: 워커 PID·시계열·스레드 증거")
        check(not any(token in snapshots for token in ("[capture_error=", "Operation not permitted", "Permission denied")), f"{case}: 시스템 도구 접근 성공")
    for kind in ("oom", "cpu", "deadlock"):
        a, b = stats[kind + "-before"]["metadata"], stats[kind + "-after"]["metadata"]
        variable = {"oom": "MEMORY_LIMIT", "cpu": "CPU_MAX_OCCUPY", "deadlock": "MULTI_THREAD_ENABLE"}[kind]
        envkeys = {"MEMORY_LIMIT", "CPU_MAX_OCCUPY", "MULTI_THREAD_ENABLE"}
        changes = [k for k in envkeys if a["environment"][k] != b["environment"][k]]
        check(changes == [variable] and a["duration_limit_s"] == b["duration_limit_s"] and a["interval_s"] == b["interval_s"], f"{kind}: 단일 변수·동일 관찰 설정")
    for case in ("oom-before", "oom-after"):
        s = stats[case]
        check("Memory limit exceeded" in logs[case] and "Self-terminating" in logs[case] and s["result"]["launcher_returncode"] == -9 and not s["result"]["runner_events"] and s["max_rss_mib"] > s["first_rss_mib"] + 20, f"{case}: RSS 증가와 앱 MemoryGuard 종료")
    check(stats["oom-after"]["result"]["observed_s"] > stats["oom-before"]["result"]["observed_s"], "OOM 한도 상향 후 생존 연장")
    check("WATCHDOG: INITIATING EMERGENCY ABORT (SIGTERM)" in logs["cpu-before"] and stats["cpu-before"]["result"]["launcher_returncode"] == -15 and not stats["cpu-before"]["result"]["runner_events"] and stats["cpu-before"]["max_cpu_percent"] > 20, "CPU 상승과 앱 Watchdog 종료")
    before = stats["deadlock-before"]
    stable = sizes["deadlock-before"][2:]
    stable_seconds = (datetime.fromisoformat(stable[-1]["timestamp"]) - datetime.fromisoformat(stable[0]["timestamp"])).total_seconds()
    check("WAITING for [Socket_Pool_B]" in logs["deadlock-before"] and "WAITING for [Shared_Memory_A]" in logs["deadlock-before"] and "LOCK ACQUIRED: [Shared_Memory_A]" in logs["deadlock-before"] and "LOCK ACQUIRED: [Socket_Pool_B]" in logs["deadlock-before"], "Deadlock 양방향 락 보유·대기 로그")
    check(stable_seconds >= 60 and all(item["bytes"] == stable[0]["bytes"] for item in stable) and before["tail_cpu_max"] == 0 and before["tail_rss_min_mib"] == before["tail_rss_max_mib"] and before["result"]["alive_before_cleanup"], f"Deadlock PID 생존·자원 및 로그 정체 {stable_seconds:.3f}초")
    for case in ("cpu-after", "deadlock-after"):
        result = stats[case]["result"]
        check(result["reason"] == "observation_timeout" and result["alive_before_cleanup"] and result["observed_s"] >= 90 and result["runner_events"][0]["signal"] == "SIGTERM", f"{case}: 90초 생존 뒤 수집기가 정리")
        check("All tasks completed" in logs[case] and "MEMORY RECOVERED" in logs[case] and "WAITING for" not in logs[case] and "WATCHDOG:" not in logs[case] and sizes[case][-1]["bytes"]["console.log"] > sizes[case][2]["bytes"]["console.log"], f"{case}: 실제 작업·로그 진행, 캐시 회수")
    print(f"Checks: {count}, Failed checks: {len(errors)}")
    return bool(errors)


if __name__ == "__main__":
    sys.exit(main())
