"""Portable study commands; the actual app always runs as a non-root user."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import experiment
from monitor import positive
from runtime_context import runtime_context

DATA = Path("/data")
ARCHIVE = Path("/input/agent-app-leak.zip")
ARCHITECTURES = {"x86_64": ("agent-leak-app-x86", 62),
                 "aarch64": ("agent-leak-app-arm64", 183)}


def extract_app(archive, destination, machine=None):
    machine = machine or platform.machine()
    if machine not in ARCHITECTURES:
        raise ValueError(f"지원하지 않는 Linux 아키텍처: {machine}")
    if not archive.is_file():
        raise ValueError("제공 ZIP을 저장소의 vendor/agent-app-leak.zip으로 복사한 뒤 다시 실행하세요.")
    name, elf_machine = ARCHITECTURES[machine]
    with zipfile.ZipFile(archive) as source:
        try:
            entry = source.getinfo(name)
        except KeyError:
            raise ValueError(f"ZIP에 {name} 파일이 없습니다. 교육기관 원본 ZIP을 확인하세요.") from None
        if entry.file_size > 64 * 1024 * 1024:
            raise ValueError(f"예상보다 큰 실행 파일: {name}")
        # Extract this exact member only; do not unpack arbitrary archive paths.
        with source.open(entry) as incoming, destination.open("xb") as outgoing:
            shutil.copyfileobj(incoming, outgoing)
    with destination.open("rb") as stream:
        header = stream.read(20)
    if (len(header) != 20 or header[:6] != b"\x7fELF\x02\x01" or
            int.from_bytes(header[18:20], "little") != elf_machine):
        raise ValueError(f"{name}의 ELF 아키텍처가 {machine}과 맞지 않습니다.")
    destination.chmod(0o700)
    return name


def writable_data():
    if os.geteuid() == 0:
        raise ValueError("일반 사용자 UID 1000으로 실행하세요. root 실행은 지원하지 않습니다.")
    DATA.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryFile(dir=DATA):
            pass
    except OSError as error:
        raise ValueError("/data에 쓸 수 없습니다. compose.yaml의 named volume과 UID 1000을 확인하세요.") from error


def find_runs(selector="latest"):
    directories = sorted((DATA / "runs").glob("*"), reverse=True)
    if selector != "latest":
        directories = [p for p in directories if p.name == selector or f"-{selector}-" in p.name]
    return [p for p in directories if (p / "metadata.json").is_file()]


def show(selector):
    runs = find_runs(selector)
    if not runs:
        raise ValueError(f"실행 기록 없음: {selector}. 먼저 run 또는 suite를 실행하세요.")
    directory = runs[0]
    print(f"증거: {directory}")
    for name in ("metadata.json", "result.json", "summary.json"):
        path = directory / name
        print(f"\n--- {name} ---")
        print(path.read_text() if path.is_file() else "아직 생성되지 않음: 실행 중이거나 수집기가 중단됐을 수 있습니다.")
    snapshots = directory / "snapshots.txt"
    if snapshots.is_file():
        print("소켓 소유 PID:", sorted(set(re.findall(r'pid=(\d+),fd=', snapshots.read_text()))))
    log = directory / "console.log"
    if log.is_file():
        print("\n--- console.log 마지막 25줄 ---")
        print("\n".join(log.read_text(errors="replace").splitlines()[-25:]))


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="Docker에서 미션 4-2 실험·관찰·검증")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="UID, 바이너리 아키텍처, 포트, 볼륨, 자원 제한 점검")
    commands.add_parser("test", help="제공 앱 없이 도구 및 Docker 보조 코드 테스트")
    commands.add_parser("list", help="보존된 실행 목록")
    inspect = commands.add_parser("show", help="최근 실행의 설정·결과·로그 출력")
    inspect.add_argument("selector", nargs="?", default="latest", help="케이스 이름 또는 실행 폴더 이름")
    for command in ("run", "suite"):
        item = commands.add_parser(command, help="단일 실험" if command == "run" else "여섯 실험 순차 실행")
        if command == "run":
            item.add_argument("case", choices=experiment.PRESETS)
            item.add_argument("--memory-limit", type=experiment.ranged(50, 512))
            item.add_argument("--cpu-max-occupy", type=experiment.ranged(10, 100))
            item.add_argument("--multi-thread", type=experiment.boolean)
        item.add_argument("--duration", type=positive, default=90)
        item.add_argument("--interval", type=positive, help="기본: CPU 0.1초, OOM/Deadlock 0.5초")
        item.add_argument("--snapshot-interval", type=positive, default=5)
    args = parser.parse_args()
    writable_data()
    if args.command == "test":
        return subprocess.call([sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-p", "test_*.py", "-v"])
    if args.command == "list":
        for directory in find_runs():
            print(directory.name, "complete" if (directory / "result.json").is_file() else "incomplete")
        return 0
    if args.command == "show":
        show(args.selector)
        return 0
    with tempfile.TemporaryDirectory(prefix="mission4-app-") as scratch:
        app = Path(scratch) / "agent-leak-app"
        member = extract_app(ARCHIVE, app)
        experiment.preflight(app)
        print(f"UID={os.geteuid()} ARCH={platform.machine()} APP={member}", flush=True)
        print(f"SHA256={hashlib.sha256(app.read_bytes()).hexdigest()}", flush=True)
        if args.command == "doctor":
            print(json.dumps(runtime_context(), ensure_ascii=False, indent=2))
            print("환경 점검 통과. 앱 부팅·장애 검증은 run/suite로 실행하세요.")
            return 0
        cases = list(experiment.PRESETS) if args.command == "suite" else [args.case]
        session = {"started_at": experiment.utc_now(), "runs": {}}
        manifest = DATA / (time.strftime("suite-%Y%m%dT%H%M%SZ-") + str(time.time_ns()) + ".json")
        for case in cases:
            options = argparse.Namespace(
                app=app, output=DATA / "runs", duration=args.duration,
                interval=args.interval if args.interval is not None else (0.1 if case.startswith("cpu-") else 0.5),
                snapshot_interval=args.snapshot_interval, fixture=False,
                memory_limit=getattr(args, "memory_limit", None),
                cpu_max_occupy=getattr(args, "cpu_max_occupy", None),
                multi_thread=getattr(args, "multi_thread", None))
            directory = experiment.run_case(options, case)
            session["runs"][case] = str(directory.relative_to(DATA))
            if args.command == "suite":
                experiment.dump(manifest, session)
        if args.command == "suite":
            print(f"이번 비교 실행 목록: {manifest}")
        print("결과 확인: docker compose run --rm lab show <케이스 이름>")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        sys.exit(2)
