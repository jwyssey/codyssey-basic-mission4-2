"""Read resource limits without changing the host or requiring extra privileges."""
import os
from pathlib import Path
import platform


def current_cgroup_root():
    """Resolve our v2 group both in a private Docker namespace and on Linux."""
    try:
        for line in Path("/proc/self/cgroup").read_text().splitlines():
            if line.startswith("0::/"):
                relative = Path(line[4:])
                if ".." not in relative.parts and not relative.is_absolute():
                    return Path("/sys/fs/cgroup") / relative
    except OSError:
        pass
    return None


def cgroup_snapshot(root=None):
    """Read our own group's counters, never an unrelated host-wide OOM count."""
    root = root if root is not None else current_cgroup_root()
    if root is None:
        return {"version": None, "path": None, "files": {}}
    names = ("memory.max", "memory.current", "memory.peak", "memory.swap.max",
             "memory.events", "cpu.max", "cpu.stat", "cpuset.cpus.effective", "pids.max")
    values = {}
    for name in names:
        try:
            values[name] = (root / name).read_text().strip()
        except OSError:
            pass
    return {"version": 2 if (root / "cgroup.controllers").exists() else None,
            "path": str(root),
            "files": values}


def oom_kill_count(snapshot):
    for line in snapshot.get("files", {}).get("memory.events", "").splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0] == "oom_kill":
            try:
                return int(fields[1])
            except ValueError:
                return None
    return None


def oom_kill_delta(before, after):
    start, end = oom_kill_count(before), oom_kill_count(after)
    return None if start is None or end is None else end - start


def runtime_context():
    try:
        affinity = sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        affinity = None
    return {"machine": platform.machine(), "kernel": platform.release(),
            "docker": Path("/.dockerenv").exists(), "cpu_affinity": affinity,
            "timezone": os.environ.get("TZ", "system default"),
            "cgroup": cgroup_snapshot()}
