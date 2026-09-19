#!/usr/bin/env bash
# 과제 2: 대상 PID 또는 프로세스 그룹의 구간 CPU와 RSS를 수집한다.
set -Eeuo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 "$script_dir/../lib/monitor.py" "$@"
