"""실제 /proc 관측, 신호 구분, 자식 정리 및 설정 경계를 검증한다."""
import argparse
from contextlib import redirect_stdout
import csv
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import experiment
import monitor


class ConfigurationTests(unittest.TestCase):
    def test_ranges_and_boolean(self):
        for low, high in ((50, 512), (10, 100)):
            parse = experiment.ranged(low, high)
            self.assertEqual(parse(str(low)), low)
            self.assertEqual(parse(str(high)), high)
            for bad in (str(low - 1), str(high + 1), "1.5", "abc"):
                with self.assertRaises((ValueError, argparse.ArgumentTypeError)):
                    parse(bad)
        self.assertEqual(experiment.boolean("yes"), "true")
        self.assertEqual(experiment.boolean("0"), "false")
        with self.assertRaises(argparse.ArgumentTypeError):
            experiment.boolean("maybe")

    def test_no_nonfinite_or_nonpositive_durations(self):
        for value in ("nan", "inf", "0", "-1"):
            with self.assertRaises(argparse.ArgumentTypeError):
                monitor.positive(value)

    def test_self_stat_matches_os(self):
        item = monitor.read_stat(os.getpid())
        self.assertEqual(item["ppid"], os.getppid())
        self.assertEqual(item["pgid"], os.getpgrp())
        self.assertGreater(item["rss_kib"], 0)
        self.assertGreater(item["start_ticks"], 0)

    def test_pid_reuse_starts_new_cpu_window(self):
        item = monitor.read_stat(os.getpid())
        previous = {}
        first = monitor.sample(item, previous, 1, 0, 1000000)
        self.assertEqual(first["cpu_percent"], "")
        next_item = {**item, "cpu_ticks": item["cpu_ticks"] + monitor.HZ}
        second = monitor.sample(next_item, previous, 3, 2, 1000000)
        self.assertEqual(float(second["cpu_percent"]), 50)
        replacement = {**next_item, "start_ticks": item["start_ticks"] + 1}
        self.assertEqual(monitor.sample(replacement, previous, 4, 3, 1000000)["cpu_percent"], "")

    def test_preflight_rejects_root_missing_app_and_busy_port(self):
        with patch("experiment.os.geteuid", return_value=0):
            with self.assertRaisesRegex(ValueError, "일반 사용자"):
                experiment.preflight(Path(sys.executable))
        with patch("experiment.os.geteuid", return_value=1000):
            with self.assertRaisesRegex(ValueError, "바이너리"):
                experiment.preflight(Path("/no/such/app"))
            with patch("experiment.socket.socket") as sock:
                sock.return_value.__enter__.return_value.bind.side_effect = OSError("address in use")
                with self.assertRaisesRegex(ValueError, "15034"):
                    experiment.preflight(Path(sys.executable))


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mission4-2-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        fixture = self.root / "fixture with spaces.py"
        fixture.write_bytes((ROOT / "tests/fixtures/workload.py").read_bytes())
        fixture.chmod(0o700)
        self.args = argparse.Namespace(app=fixture, output=self.root / "evidence", duration=1.5,
                                       interval=0.05, snapshot_interval=0.4, memory_limit=None,
                                       cpu_max_occupy=None, multi_thread=None, fixture=True)

    def run_fixture(self, mode):
        # 고정 포트의 기존 서비스를 건드리지 않고 프로세스 수집·정리만 통합 검증한다.
        # 소켓 preflight는 위의 별도 경계 테스트에서 검증한다.
        with patch("experiment.preflight"), patch.dict(os.environ, {"LAB_TEST_MODE": mode}), redirect_stdout(io.StringIO()):
            directory = experiment.run_case(self.args, "oom-before")
        result = json.loads((directory / "result.json").read_text())
        metadata = json.loads((directory / "metadata.json").read_text())
        self.assertEqual(metadata["evidence_source"], "test_fixture")
        self.assertEqual(result["monitor_returncode"], 0)
        self.assertFalse(experiment.group_alive(metadata["launcher_pid"]))
        with (directory / "metrics.csv").open() as file:
            rows = list(csv.DictReader(file))
        return directory, result, rows

    def test_resource_growth_cpu_and_timeout(self):
        directory, result, rows = self.run_fixture("resource")
        self.assertEqual(result["reason"], "observation_timeout")
        self.assertTrue(result["alive_before_cleanup"])
        self.assertEqual(result["runner_events"][0]["signal"], "SIGTERM")
        rss = [int(row["rss_kib"]) for row in rows]
        cpu = [float(row["cpu_percent"]) for row in rows if row["cpu_percent"]]
        self.assertGreater(max(rss) - min(rss), 4096)
        self.assertGreater(max(cpu), 20)
        self.assertIn("ps -L", (directory / "snapshots.txt").read_text())
        self.assertGreater(len((directory / "log-sizes.jsonl").read_text().splitlines()), 1)

    def test_self_signal_not_runner_timeout(self):
        directory, result, rows = self.run_fixture("exit")
        self.assertEqual(result["reason"], "app_exited")
        self.assertFalse(result["alive_before_cleanup"])
        self.assertEqual(result["launcher_returncode"], -signal.SIGTERM)
        self.assertEqual(result["runner_events"], [])
        self.assertIn("FIXTURE: sending SIGTERM to self", (directory / "console.log").read_text())
        self.assertTrue(rows)

    def test_child_monitored_and_cleaned_after_parent_exits(self):
        directory, result, rows = self.run_fixture("child")
        child_pid = int((directory / "console.log").read_text().split("FIXTURE_CHILD_PID=")[1].splitlines()[0])
        self.assertIn(str(child_pid), {row["pid"] for row in rows})
        self.assertEqual(result["reason"], "observation_timeout")
        self.assertEqual(result["launcher_returncode"], 0)
        item = monitor.read_stat(child_pid)
        self.assertTrue(item is None or item["state"] == "Z")

    def test_invalid_options_fail_without_launching(self):
        for options in (("--duration", "nan"), ("--memory-limit", "49"),
                        ("--cpu-max-occupy", "101"), ("--multi-thread", "maybe")):
            command = ["bash", str(ROOT / "scripts/run-case.sh"), "--app", str(self.args.app),
                       "--case", "oom-before", *options]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
        self.assertFalse(self.args.output.exists())

    def test_interruption_preserves_result_and_cleans_processes(self):
        self.args.duration = 30
        timer = threading.Timer(0.6, lambda: os.kill(os.getpid(), signal.SIGINT))
        with patch("experiment.preflight"), patch.dict(os.environ, {"LAB_TEST_MODE": "resource"}), redirect_stdout(io.StringIO()):
            timer.start()
            try:
                with self.assertRaises(KeyboardInterrupt):
                    experiment.run_case(self.args, "oom-before")
            finally:
                timer.cancel()
                timer.join()
        directory = next(self.args.output.iterdir())
        result = json.loads((directory / "result.json").read_text())
        metadata = json.loads((directory / "metadata.json").read_text())
        self.assertEqual(result["reason"], "interrupted")
        self.assertFalse(experiment.group_alive(metadata["launcher_pid"]))
        self.assertEqual(result["runner_events"][0]["received_signal"], signal.SIGINT)

    def test_monitor_does_not_overwrite_existing_evidence(self):
        output = self.root / "existing.csv"
        output.write_text("original evidence\n")
        result = subprocess.run(["bash", str(ROOT / "bin/monitor.sh"), "--pid", str(os.getpid()),
                                 "--duration", "0.1", "--output", str(output),
                                 "--log", str(self.root / "monitor.log")], capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(output.read_text(), "original evidence\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
