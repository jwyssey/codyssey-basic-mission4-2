"""Linux /proc 기반 프로세스 관측. 표준 라이브러리만 사용한다."""
import argparse
import csv
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import signal
import sys
import time

COLUMNS = ["timestamp", "elapsed_s", "pid", "start_ticks", "ppid", "pgid",
           "state", "threads", "rss_kib", "vms_kib", "cpu_percent",
           "mem_percent", "cpu_ticks", "wchan"]
HZ = os.sysconf("SC_CLK_TCK")
PAGE_KIB = os.sysconf("SC_PAGE_SIZE") // 1024


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("유한한 양수를 입력하세요")
    return number


def process_id(value):
    number = int(value)
    if number <= 1:
        raise argparse.ArgumentTypeError("PID/PGID는 2 이상이어야 합니다")
    return number


def read_stat(pid):
    try:
        # comm에는 공백과 ')'가 들어갈 수 있으므로 마지막 ')' 뒤부터 읽는다.
        raw = Path(f"/proc/{pid}/stat").read_text()
        fields = raw[raw.rfind(")") + 2:].split()
        return {"pid": int(pid), "state": fields[0], "ppid": int(fields[1]),
                "pgid": int(fields[2]), "cpu_ticks": int(fields[11]) + int(fields[12]),
                "threads": int(fields[17]), "start_ticks": int(fields[19]),
                "vms_kib": int(fields[20]) // 1024,
                "rss_kib": int(fields[21]) * PAGE_KIB}
    except (OSError, ValueError, IndexError):
        return None  # 측정 중 종료된 프로세스도 정상적인 관측 결과다.


def processes(pid=None, pgid=None):
    entries = [str(pid)] if pid is not None else [p.name for p in Path("/proc").iterdir() if p.name.isdigit()]
    result = []
    for entry in entries:
        item = read_stat(entry)
        if item and (pgid is None or item["pgid"] == pgid):
            result.append(item)
    return sorted(result, key=lambda p: p["pid"])


def sample(item, previous, now, elapsed, mem_total):
    item = dict(item)
    identity = (item["pid"], item["start_ticks"])
    before = previous.get(identity)
    item["cpu_percent"] = ""
    if before and now > before[0]:
        # CPU 100% = 논리 CPU 1개. 최초 샘플은 구간이 없어 빈 칸.
        item["cpu_percent"] = f'{100 * (item["cpu_ticks"] - before[1]) / HZ / (now - before[0]):.2f}'
    previous[identity] = (now, item["cpu_ticks"])
    item["timestamp"] = utc_now()
    item["elapsed_s"] = f"{elapsed:.3f}"
    item["mem_percent"] = f'{100 * item["rss_kib"] / mem_total:.5f}'
    try:
        item["wchan"] = Path(f'/proc/{item["pid"]}/wchan').read_text().strip()
    except OSError:
        item["wchan"] = "unavailable"
    return item


def main():
    parser = argparse.ArgumentParser(description="PID별 RSS와 구간 CPU를 CSV 및 monitor.log로 기록")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--pid", type=process_id)
    target.add_argument("--pgid", type=process_id, help="패키징 앱의 부모·자식을 모두 기록")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--interval", type=positive, default=1.0)
    parser.add_argument("--duration", type=positive, default=900.0)
    args = parser.parse_args()
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    mem_total = next(int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()
                     if line.startswith("MemTotal:"))
    initial = read_stat(args.pid) if args.pid else None
    if args.pid and not initial:
        parser.error("대상 PID가 존재하지 않습니다")
    previous = {}
    start = time.monotonic()
    # 기존 증거 덮어쓰기를 방지한다.
    with args.output.open("x", buffering=1) as output, args.log.open("x", buffering=1) as log:
        writer = csv.DictWriter(output, fieldnames=COLUMNS)
        writer.writeheader()
        while not stopping:
            now = time.monotonic()
            rows = processes(args.pid, args.pgid)
            if args.pid:
                rows = [p for p in rows if p["start_ticks"] == initial["start_ticks"]]
            rows = [p for p in rows if p["state"] not in ("Z", "X")]
            if not rows:
                log.write(f"[{utc_now()}] EVENT:PROCESS_EXITED\n")
                break
            for row in rows:
                item = sample(row, previous, now, now - start, mem_total)
                writer.writerow(item)
                cpu = item["cpu_percent"] or "NA"
                log.write(f'[{item["timestamp"]}] PID:{item["pid"]} CPU:{cpu}% '
                          f'RSS_KIB:{item["rss_kib"]} MEM:{item["mem_percent"]}% '
                          f'STATE:{item["state"]} THREADS:{item["threads"]} WCHAN:{item["wchan"]}\n')
            if now - start >= args.duration:
                log.write(f"[{utc_now()}] EVENT:MONITOR_DURATION_REACHED\n")
                break
            time.sleep(min(args.interval, max(0, args.duration - (time.monotonic() - start))))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        sys.exit(2)
