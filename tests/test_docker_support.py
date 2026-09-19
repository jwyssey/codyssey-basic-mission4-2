"""Architecture selection, volume access, and cgroup OOM evidence boundaries."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from runtime_context import cgroup_snapshot, current_cgroup_root, oom_kill_delta

spec = importlib.util.spec_from_file_location("docker_entry", ROOT / "docker/entrypoint.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


def elf(machine):
    return b"\x7fELF\x02\x01" + bytes(12) + machine.to_bytes(2, "little") + bytes(44)


class DockerSupportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mission4-docker-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.archive = self.root / "app.zip"
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("agent-leak-app-x86", elf(62))
            archive.writestr("agent-leak-app-arm64", elf(183))
            archive.writestr("../unexpected", "must not extract")

    def test_extracts_only_matching_elf_for_each_architecture(self):
        for machine, code in (("x86_64", 62), ("aarch64", 183)):
            output = self.root / machine
            entry.extract_app(self.archive, output, machine)
            self.assertEqual(output.read_bytes(), elf(code))
            self.assertTrue(os.access(output, os.X_OK))
        self.assertFalse((self.root.parent / "unexpected").exists())

    def test_rejects_missing_zip_and_unsupported_architecture(self):
        with self.assertRaisesRegex(ValueError, "vendor/agent-app-leak.zip"):
            entry.extract_app(self.root / "missing.zip", self.root / "app", "x86_64")
        with self.assertRaisesRegex(ValueError, "아키텍처"):
            entry.extract_app(self.archive, self.root / "app", "riscv64")

    def test_rejects_wrong_architecture_inside_correct_filename(self):
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("agent-leak-app-x86", elf(183))
        with self.assertRaisesRegex(ValueError, "ELF 아키텍처"):
            entry.extract_app(self.archive, self.root / "wrong", "x86_64")

    def test_missing_member_and_existing_destination_are_not_overwritten(self):
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("another-file", elf(62))
        with self.assertRaisesRegex(ValueError, "파일이 없습니다"):
            entry.extract_app(self.archive, self.root / "app", "x86_64")
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("agent-leak-app-x86", elf(62))
        output = self.root / "existing"
        output.write_text("keep")
        with self.assertRaises(FileExistsError):
            entry.extract_app(self.archive, output, "x86_64")
        self.assertEqual(output.read_text(), "keep")

    def test_nonroot_writable_volume_and_root_rejection(self):
        with patch.object(entry, "DATA", self.root / "data"), patch.object(entry.os, "geteuid", return_value=1000):
            entry.writable_data()
        with patch.object(entry.os, "geteuid", return_value=0):
            with self.assertRaisesRegex(ValueError, "일반 사용자"):
                entry.writable_data()

    def test_cgroup_oom_counter_distinguishes_kernel_kill_from_app_signal(self):
        (self.root / "cgroup.controllers").write_text("cpu memory")
        (self.root / "memory.max").write_text("1610612736")
        events = self.root / "memory.events"
        events.write_text("oom 0\noom_kill 3\n")
        before = cgroup_snapshot(self.root)
        self.assertEqual(before["version"], 2)
        self.assertEqual(oom_kill_delta(before, cgroup_snapshot(self.root)), 0)
        events.write_text("oom 1\noom_kill 4\n")
        self.assertEqual(oom_kill_delta(before, cgroup_snapshot(self.root)), 1)
        self.assertIsNone(oom_kill_delta(before, {"files": {}}))

    def test_case_lookup_keeps_incomplete_runs_visible(self):
        runs = self.root / "runs"
        for name in ("20260920T000000Z-oom-before-1", "20260920T000100Z-cpu-after-2"):
            directory = runs / name
            directory.mkdir(parents=True)
            (directory / "metadata.json").write_text("{}")
        with patch.object(entry, "DATA", self.root):
            self.assertEqual(len(entry.find_runs()), 2)
            self.assertEqual(len(entry.find_runs("oom-before")), 1)
            self.assertEqual(entry.find_runs("no-such-case"), [])

    def test_cgroup_resolves_current_group_instead_of_host_root(self):
        for membership, expected in (("0::/\n", Path("/sys/fs/cgroup")),
                                     ("0::/user.slice/session.scope\n", Path("/sys/fs/cgroup/user.slice/session.scope")),
                                     ("0::/../outside\n", None),
                                     ("4:memory:/legacy\n", None)):
            with patch.object(Path, "read_text", return_value=membership):
                self.assertEqual(current_cgroup_root(), expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
