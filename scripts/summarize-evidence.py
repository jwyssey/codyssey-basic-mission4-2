#!/usr/bin/env python3
"""확정한 실험 목록에서 소켓 소유 워커의 통계·그래프를 다시 생성한다."""
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def load_run(relative):
    directory = ROOT / relative
    metadata = json.loads((directory / "metadata.json").read_text())
    result = json.loads((directory / "result.json").read_text())
    snapshots = (directory / "snapshots.txt").read_text()
    owners = set(re.findall(r'pid=(\d+),fd=', snapshots))
    if len(owners) != 1:
        raise ValueError(f"소켓 소유 워커를 하나로 특정할 수 없음: {relative}: {owners}")
    pid = owners.pop()
    cutoff = next((datetime.fromisoformat(e["timestamp"]) for e in result["runner_events"] if "signal" in e), None)
    with (directory / "metrics.csv").open() as file:
        rows = [r for r in csv.DictReader(file) if r["pid"] == pid and
                (cutoff is None or datetime.fromisoformat(r["timestamp"]) < cutoff)]
    rss = [int(r["rss_kib"]) / 1024 for r in rows]
    cpu = [float(r["cpu_percent"]) for r in rows if r["cpu_percent"]]
    tail = [r for r in rows if float(r["elapsed_s"]) >= 15]
    return {"directory": relative, "worker_pid": int(pid), "metadata": metadata, "result": result,
            "samples": len(rows), "first_rss_mib": rss[0], "max_rss_mib": max(rss),
            "last_rss_mib": rss[-1], "max_cpu_percent": max(cpu),
            "tail_cpu_max": max((float(r["cpu_percent"] or 0) for r in tail), default=None),
            "tail_rss_min_mib": min((int(r["rss_kib"]) / 1024 for r in tail), default=None),
            "tail_rss_max_mib": max((int(r["rss_kib"]) / 1024 for r in tail), default=None),
            "rows": rows}


def main():
    manifest = json.loads((ROOT / "evidence/manifest.json").read_text())
    runs = {case: load_run(path) for case, path in manifest["runs"].items()}
    result = {case: {key: value for key, value in run.items() if key != "rows"} for case, run in runs.items()}
    (ROOT / "evidence/comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    # 도표 생성에만 Matplotlib이 필요하다. 실험 수집기는 표준 라이브러리만 사용한다.
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "mission4-matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    charts = ROOT / "evidence/charts"
    charts.mkdir(exist_ok=True)
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    for kind in ("oom", "cpu", "deadlock"):
        fig, axes = plt.subplots(2, 1, figsize=(8, 5.4), sharex=True, constrained_layout=True)
        for suffix, color in (("before", "#c24139"), ("after", "#147d92")):
            run = runs[f"{kind}-{suffix}"]
            rows = run["rows"]
            x = [float(row["elapsed_s"]) for row in rows]
            rss = [int(row["rss_kib"]) / 1024 for row in rows]
            cpu = [float(row["cpu_percent"]) if row["cpu_percent"] else float("nan") for row in rows]
            env = run["metadata"]["environment"]
            variable = {"oom": "MEMORY_LIMIT", "cpu": "CPU_MAX_OCCUPY", "deadlock": "MULTI_THREAD_ENABLE"}[kind]
            label = f"{suffix.title()}: {variable}={env[variable]}"
            axes[0].plot(x, rss, color=color, label=label, linewidth=1.5)
            axes[1].plot(x, cpu, color=color, linewidth=1.3)
            if run["result"]["reason"] == "app_exited":
                for axis in axes:
                    axis.axvline(run["result"]["observed_s"], color=color, linestyle="--", alpha=0.6)
        axes[0].set_ylabel("Worker RSS (MiB)")
        axes[1].set_ylabel("Worker CPU (%)\n100% = one logical CPU")
        interval = runs[f"{kind}-before"]["metadata"]["interval_s"]
        axes[1].set_xlabel(f"Seconds since monitor start ({interval:g} s sample interval)")
        axes[0].legend(fontsize=8, loc="best")
        axes[0].set_title(f"{kind.upper()} | Measured before / after | 2026-09-18")
        for axis in axes:
            axis.grid(alpha=0.18)
            axis.set_ylim(bottom=0)
        fig.savefig(charts / f"{kind}.png", dpi=170)
        plt.close(fig)
    print("evidence/comparison.json 및 charts/{oom,cpu,deadlock}.png 생성 완료")


if __name__ == "__main__":
    main()
