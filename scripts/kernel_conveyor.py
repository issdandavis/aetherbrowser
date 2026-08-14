#!/usr/bin/env python3
"""Run fixed AetherBrowser checks on an hourly, checkpointed conveyor."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "kernel-conveyor"
COMMANDS = [
    [sys.executable, "-m", "py_compile", "src/aetherbrowser/kernel.py", "src/aetherbrowser/serve.py"],
    [sys.executable, "tests/kernel_unit.py"],
    [sys.executable, "tests/headless_contract.py"],
    [sys.executable, "tests/smoke.py"],
]


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_command(argv: list[str]) -> dict[str, Any]:
    started = time.monotonic()
    completed = subprocess.run(
        argv,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    return {
        "argv": argv,
        "returncode": completed.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-2000:],
    }


def source_fingerprint() -> dict[str, Any]:
    paths = sorted((ROOT / "src" / "aetherbrowser").glob("*.py"))
    paths.extend([ROOT / "tests" / "kernel_unit.py", ROOT / "tests" / "headless_contract.py"])
    rows = [
        {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in paths
    ]
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {"sha256": digest, "files": rows}


def cycle(index: int, output: Path) -> dict[str, Any]:
    started_at = now()
    checks = []
    for argv in COMMANDS:
        try:
            checks.append(run_command(argv))
        except subprocess.TimeoutExpired as exc:
            checks.append(
                {
                    "argv": argv,
                    "returncode": 124,
                    "duration_seconds": 180,
                    "stdout_tail": str(exc.stdout or "")[-4000:],
                    "stderr_tail": "command timed out",
                }
            )
    passed = all(check["returncode"] == 0 for check in checks)
    report = {
        "schema": "aetherbrowser.kernel-conveyor.finding.v1",
        "cycle": index,
        "started_at": started_at,
        "finished_at": now(),
        "passed": passed,
        "host": platform.node(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "cpu_count": os.cpu_count(),
        "source": source_fingerprint(),
        "checks": checks,
    }
    output.mkdir(parents=True, exist_ok=True)
    path = output / f"hour-{index:03d}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    shutil.copyfile(path, output / "latest.json")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=float, default=8.0)
    parser.add_argument("--interval-seconds", type=float, default=3600.0)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    cycles = 1 if args.once else max(1, int(args.hours * 3600 // args.interval_seconds) + 1)
    began = time.monotonic()
    all_passed = True
    reports = []
    for index in range(cycles):
        report = cycle(index, args.output_dir)
        reports.append({"cycle": index, "passed": report["passed"], "finished_at": report["finished_at"]})
        all_passed = all_passed and report["passed"]
        summary = {
            "schema": "aetherbrowser.kernel-conveyor.summary.v1",
            "requested_hours": args.hours,
            "interval_seconds": args.interval_seconds,
            "cycles_completed": len(reports),
            "all_passed": all_passed,
            "reports": reports,
        }
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if index + 1 < cycles:
            target = began + (index + 1) * args.interval_seconds
            time.sleep(max(0.0, target - time.monotonic()))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
