#!/usr/bin/env python3
"""수집기 검증 전용. 교육기관 앱 대체물이나 과제 제출용 증거가 아니다."""
import os
import signal
import subprocess
import sys
import time

print("TEST FIXTURE ONLY; not agent-leak-app", flush=True)
mode = os.environ.get("LAB_TEST_MODE", "resource")
if mode == "exit":
    time.sleep(0.5)
    # flush를 명시하지 않아도 PTY의 줄 버퍼링으로 종료 직전 문구가 보존되어야 한다.
    print("FIXTURE: sending SIGTERM to self")
    os.kill(os.getpid(), signal.SIGTERM)
elif mode == "child":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    print(f"FIXTURE_CHILD_PID={child.pid}", flush=True)
    # 부모가 먼저 종료된 패키징 앱에서도 자식을 계속 관측·정리해야 한다.
    sys.exit(0)
else:
    blocks = []
    for _ in range(5):
        blocks.append(bytearray(2 * 1024 * 1024))
        time.sleep(0.08)
    end = time.monotonic() + 0.45
    while time.monotonic() < end:
        sum(i * i for i in range(1000))
time.sleep(120)
