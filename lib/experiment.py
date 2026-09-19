"""원본 앱을 실행하고 전후 비교용 증거를 보존한다. 바이너리 분석은 하지 않는다."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import pty
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import tty

from monitor import positive, processes, utc_now

ROOT = Path(__file__).resolve().parents[1]
PRESETS = {
    "oom-before": (64, 100, "false"),
    "oom-after": (128, 100, "false"),
    "cpu-before": (512, 100, "false"),
    "cpu-after": (512, 40, "false"),
    "deadlock-before": (512, 40, "true"),
    "deadlock-after": (512, 40, "false"),
}


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def ranged(low, high):
    def parse(value):
        number = int(value)
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f"{low}~{high} 범위의 정수여야 합니다")
        return number
    return parse


def boolean(value):
    table = {"true": "true", "false": "false", "1": "true", "0": "false", "yes": "true", "no": "false"}
    if value.lower() not in table:
        raise argparse.ArgumentTypeError("true/false, 1/0, yes/no 중 하나를 입력하세요")
    return table[value.lower()]


def preflight(app):
    if os.geteuid() == 0:
        raise ValueError("제공 앱은 일반 사용자로 실행해야 합니다. sudo를 사용하지 마세요.")
    if not app.is_file() or not os.access(app, os.X_OK):
        raise ValueError(f"실행 가능한 제공 바이너리가 필요합니다: {app}")
    for command in ("bash", "ps", "top", "ss"):
        if not shutil.which(command):
            raise ValueError(f"필수 명령어 없음: {command}")
    # 점유 중인 앱을 종료하지 않고 실패시킨다. 최종 bind는 실제 앱이 검증한다.
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", 15034))
        except OSError as error:
            raise ValueError(f"0.0.0.0:15034 바인딩 불가: {error}") from error


def capture(file, command):
    file.write(f"\n[{utc_now()}] $ {shlex.join(command)}\n")
    file.flush()
    try:
        result = subprocess.run(command, stdout=file, stderr=subprocess.STDOUT, timeout=5,
                                env={**os.environ, "LC_ALL": "C"})
        file.write(f"[command_exit={result.returncode}]\n")
    except (OSError, subprocess.TimeoutExpired) as error:
        file.write(f"[capture_error={error}]\n")


def snapshot(directory, pgid, phase):
    members = processes(pgid=pgid)
    pids = ",".join(str(p["pid"]) for p in members)
    with (directory / "snapshots.txt").open("a", buffering=1) as output:
        output.write(f"\n=== {utc_now()} phase={phase} PGID={pgid} PIDS={pids or 'none'} ===\n")
        if pids:
            capture(output, ["ps", "-p", pids, "-o", "user,pid,ppid,pgid,etime,stat,pcpu,pmem,rss,vsz,args"])
            capture(output, ["ps", "-L", "-p", pids, "-o", "pid,tid,stat,pcpu,rss,wchan:32,comm"])
            capture(output, ["top", "-b", "-H", "-n", "1", "-p", pids])
        capture(output, ["ss", "-ltnp", "sport = :15034"])
        for item in members:
            pid = item["pid"]
            for name in ("status", "wchan"):
                try:
                    output.write(f"\n/proc/{pid}/{name}\n" + Path(f"/proc/{pid}/{name}").read_text() + "\n")
                except OSError as error:
                    output.write(f"[proc_read_error={error}]\n")
    files = [directory / "console.log", *(directory / "app-logs").rglob("*")]
    sizes = {}
    for file in files:
        if file.is_file():
            try:
                sizes[str(file.relative_to(directory))] = file.stat().st_size
            except OSError:
                pass
    with (directory / "log-sizes.jsonl").open("a") as output:
        output.write(json.dumps({"timestamp": utc_now(), "phase": phase, "bytes": sizes}) + "\n")


def group_alive(pgid):
    return any(p["state"] not in ("Z", "X") for p in processes(pgid=pgid))


def cleanup(app, events):
    # start_new_session으로 만든 이 실험의 그룹만 종료한다. pkill 이름 검색은 사용하지 않는다.
    # 부모는 아직 wait하지 않았으므로 PGID가 다른 실행에 재사용되지 않는다.
    for sig, grace in ((signal.SIGTERM, 2), (signal.SIGKILL, 2)):
        if not group_alive(app.pid):
            break
        events.append({"timestamp": utc_now(), "actor": "runner", "signal": sig.name})
        try:
            os.killpg(app.pid, sig)
        except ProcessLookupError:
            break
        deadline = time.monotonic() + grace
        while group_alive(app.pid) and time.monotonic() < deadline:
            time.sleep(0.05)
    return app.wait(timeout=5)


def summarize(directory):
    data = {}
    with (directory / "metrics.csv").open() as file:
        for row in csv.DictReader(file):
            identity = f'{row["pid"]}:{row["start_ticks"]}'
            data.setdefault(identity, []).append(row)
    summary = {}
    for identity, rows in data.items():
        rss = [int(row["rss_kib"]) / 1024 for row in rows]
        cpu = [float(row["cpu_percent"]) for row in rows if row["cpu_percent"]]
        summary[identity] = {"pid": int(rows[0]["pid"]), "samples": len(rows),
                             "first_rss_mib": round(rss[0], 3), "last_rss_mib": round(rss[-1], 3),
                             "max_rss_mib": round(max(rss), 3),
                             "max_cpu_percent": max(cpu) if cpu else None,
                             "last_cpu_percent": cpu[-1] if cpu else None}
    dump(directory / "summary.json", summary)


def run_case(args, case):
    preflight(args.app)
    memory, cpu, multi = PRESETS[case]
    memory = args.memory_limit if args.memory_limit is not None else memory
    cpu = args.cpu_max_occupy if args.cpu_max_occupy is not None else cpu
    multi = args.multi_thread if args.multi_thread is not None else multi
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    directory = args.output.resolve() / f"{stamp}-{case}-{time.time_ns() % 1000000000:09d}"
    directory.mkdir(parents=True)
    home = directory / "agent-home"
    for path in (home / "upload_files", home / "api_keys", directory / "app-logs"):
        path.mkdir(parents=True)
    key = home / "api_keys" / "secret.key"
    key.write_text("agent_api_key_test\n")
    key.chmod(0o600)
    env = {"AGENT_HOME": str(home), "AGENT_PORT": "15034",
           "AGENT_UPLOAD_DIR": str(home / "upload_files"), "AGENT_KEY_PATH": str(home / "api_keys"),
           "AGENT_LOG_DIR": str(directory / "app-logs"), "MEMORY_LIMIT": str(memory),
           "CPU_MAX_OCCUPY": str(cpu), "MULTI_THREAD_ENABLE": multi}
    metadata = {"case": case, "started_at": utc_now(), "uid": os.getuid(),
                "platform": platform.platform(), "logical_cpus": os.cpu_count(),
                "app_path": str(args.app), "app_sha256": hashlib.sha256(args.app.read_bytes()).hexdigest(),
                "environment": env, "duration_limit_s": args.duration,
                "interval_s": args.interval, "snapshot_interval_s": args.snapshot_interval,
                "namespaces": {name: os.readlink(f"/proc/self/ns/{name}") for name in ("user", "net")},
                "stdout_mode": "pty_line_buffered",
                "evidence_source": "test_fixture" if args.fixture else "provided_app"}
    dump(directory / "metadata.json", metadata)
    print(f"[RUN] {case}: {directory}", flush=True)
    started = time.monotonic()
    app = None
    monitor = None
    reader = None
    master_fd = None
    events = []
    reason = "runner_error"
    error = None
    interrupted = False

    def stop(signum, _frame):
        nonlocal interrupted
        interrupted = True
        events.append({"timestamp": utc_now(), "actor": "runner", "received_signal": signum})

    old_handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    with (directory / "console.log").open("wb") as console, (directory / "monitor-stderr.log").open("wb") as monitor_errors:
        try:
            # PyInstaller 앱은 PYTHONUNBUFFERED를 무시할 수 있다. TTY로 실행해야
            # SIGKILL/SIGTERM 직전 print한 보호 정책 문구가 파이프 버퍼에 남지 않는다.
            master_fd, slave_fd = pty.openpty()
            tty.setraw(slave_fd)  # 원문 개행 보존: 터미널의 LF→CRLF 변환을 끈다.
            try:
                app = subprocess.Popen([str(args.app)], cwd=home,
                                       env={**os.environ, **env, "PYTHONUNBUFFERED": "1"},
                                       stdin=subprocess.DEVNULL, stdout=slave_fd, stderr=slave_fd,
                                       start_new_session=True)
            finally:
                os.close(slave_fd)

            def copy_console():
                while True:
                    try:
                        chunk = os.read(master_fd, 65536)
                    except OSError:
                        break  # Linux PTY는 slave 종료 후 EIO를 반환한다.
                    if not chunk:
                        break
                    console.write(chunk)
                    console.flush()

            reader = threading.Thread(target=copy_console, daemon=True)
            reader.start()
            metadata["launcher_pid"] = app.pid
            dump(directory / "metadata.json", metadata)
            monitor = subprocess.Popen(["bash", str(ROOT / "bin/monitor.sh"), "--pgid", str(app.pid),
                                        "--output", str(directory / "metrics.csv"),
                                        "--log", str(directory / "monitor.log"),
                                        "--interval", str(args.interval), "--duration", str(args.duration + 10)],
                                       stdout=monitor_errors, stderr=subprocess.STDOUT)
            next_snapshot = 0.0
            while group_alive(app.pid):
                elapsed = time.monotonic() - started
                if interrupted:
                    reason = "interrupted"
                    break
                if elapsed >= args.duration:
                    reason = "observation_timeout"
                    break
                if monitor.poll() is not None:
                    if not group_alive(app.pid):
                        reason = "app_exited"
                        break
                    raise RuntimeError("대상 앱이 실행 중인데 monitor가 종료되었습니다. monitor-stderr.log 확인")
                if elapsed >= next_snapshot:
                    snapshot(directory, app.pid, "observing")
                    next_snapshot = time.monotonic() - started + args.snapshot_interval
                time.sleep(min(0.1, args.interval))
            else:
                reason = "app_exited"
            # 관찰 종료 시각은 runner의 정리 신호 이전에 기록한다.
            observed = time.monotonic() - started
            alive = group_alive(app.pid)
            snapshot(directory, app.pid, "before_cleanup")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            observed = time.monotonic() - started
            alive = group_alive(app.pid) if app else False
        finally:
            exit_code = cleanup(app, events) if app else None
            if reader:
                reader.join(timeout=3)
            if master_fd is not None:
                os.close(master_fd)
            if monitor:
                try:
                    monitor.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    monitor.terminate()
                    try:
                        monitor.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        monitor.kill()
                        monitor.wait()
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)
    result = {"ended_at": utc_now(), "reason": reason, "observed_s": round(observed, 3),
              "alive_before_cleanup": alive, "launcher_returncode": exit_code,
              "monitor_returncode": monitor.returncode if monitor else None,
              "runner_events": events, "error": error}
    dump(directory / "result.json", result)
    if (directory / "metrics.csv").is_file():
        summarize(directory)
    print(f"[END] {case}: {reason}, {observed:.2f}s, launcher_returncode={exit_code}", flush=True)
    if error:
        raise RuntimeError(error)
    if interrupted:
        raise KeyboardInterrupt
    return directory


def main():
    parser = argparse.ArgumentParser(description="agent-leak-app 장애 실험과 증거 수집")
    parser.add_argument("--app", type=Path, required=True, help="교육기관 제공 실행 파일")
    parser.add_argument("--case", choices=PRESETS)
    parser.add_argument("--suite", action="store_true", help="6개 기본 비교 실험을 순차 실행")
    parser.add_argument("--output", type=Path, default=ROOT / "evidence" / "runs")
    parser.add_argument("--duration", type=positive, default=180)
    parser.add_argument("--interval", type=positive, default=1)
    parser.add_argument("--snapshot-interval", type=positive, default=10)
    parser.add_argument("--memory-limit", type=ranged(50, 512))
    parser.add_argument("--cpu-max-occupy", type=ranged(10, 100))
    parser.add_argument("--multi-thread", type=boolean)
    parser.add_argument("--fixture", action="store_true", help="수집기 테스트 전용: 증거를 test_fixture로 표시")
    args = parser.parse_args()
    if bool(args.case) == args.suite:
        parser.error("--case 또는 --suite 중 하나만 지정하세요")
    if args.suite and any(v is not None for v in (args.memory_limit, args.cpu_max_occupy, args.multi_thread)):
        parser.error("suite 설정 변경은 비교를 훼손합니다. 개별 --case에서 값을 조정하세요")
    args.app = args.app.expanduser().resolve()
    os.umask(0o077)
    paths = [run_case(args, case) for case in (PRESETS if args.suite else [args.case])]
    print("\n수집 완료. 장애 판정은 console.log와 app-logs, metrics.csv를 함께 검토하세요.")
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        sys.exit(2)
