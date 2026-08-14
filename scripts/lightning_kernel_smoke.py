#!/usr/bin/env python3
"""Run the content-addressed browser-kernel packet in one disposable Sandbox."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path

from lightning_sdk.sandbox import Sandbox, SandboxConfig


ROOT = Path(__file__).resolve().parents[1]


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(sandbox, executable: str, argv: list[str], timeout: float) -> dict:
    command = sandbox.run_command(executable, argv)
    command.wait(timeout=timeout)
    stdout = command.stdout()
    stderr = command.stderr()
    return {
        "argv": [executable, *argv],
        "exit_code": command.exit_code,
        "stdout_tail": stdout[-8000:],
        "stderr_tail": stderr[-4000:],
        "stdout_sha256": sha256(stdout.encode("utf-8")),
        "stderr_sha256": sha256(stderr.encode("utf-8")),
    }


def latest_packet() -> tuple[Path, dict]:
    latest_path = ROOT / "dist" / "aetherbrowser-kernel-latest.json"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    packet = Path(latest["zip"]).resolve()
    if not packet.is_file():
        raise SystemExit(f"kernel packet does not exist: {packet}")
    actual = sha256(packet.read_bytes())
    if actual != latest["zip_sha256"]:
        raise SystemExit("local kernel packet hash differs from latest manifest")
    return packet, latest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, default=ROOT / "dist" / "lightning-kernel-smoke-receipt.json")
    parser.add_argument("--instance-type", default="cpu-1")
    parser.add_argument("--runtime", default="python313")
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    packet, latest = latest_packet()
    key = os.environ.get("LIGHTNING_SANDBOX_API_KEY", "").strip()
    if args.dry_run:
        print(
            json.dumps(
                {
                    "ok": bool(key),
                    "dry_run": True,
                    "key_configured": bool(key),
                    "key_exposed": False,
                    "packet_id": latest["packet_id"],
                    "zip_sha256": latest["zip_sha256"],
                    "zip_bytes": packet.stat().st_size,
                    "instance_type": args.instance_type,
                    "runtime": args.runtime,
                    "persistent": False,
                    "timeout_seconds": args.timeout_seconds,
                },
                sort_keys=True,
            )
        )
        return 0 if key else 2
    if not key:
        raise SystemExit("LIGHTNING_SANDBOX_API_KEY is not set")

    created = datetime.now(timezone.utc)
    name = "aetherbrowser-kernel-" + created.strftime("%Y%m%d-%H%M%S")
    sandbox = None
    receipt: dict = {
        "schema": "aetherbrowser.lightning-sandbox-smoke.v1",
        "created_at": now(),
        "name": name,
        "packet_id": latest["packet_id"],
        "zip_sha256": latest["zip_sha256"],
        "zip_bytes": packet.stat().st_size,
        "instance_type": args.instance_type,
        "runtime": args.runtime,
        "persistent": False,
        "timeout_seconds": args.timeout_seconds,
        "commands": [],
        "success": False,
        "deleted": False,
    }
    try:
        sandbox = Sandbox.create(
            config=SandboxConfig(api_key=key),
            name=name,
            instance_type=args.instance_type,
            runtime=args.runtime,
            persistent=False,
            timeout=int(args.timeout_seconds * 1000),
        )
        receipt["sandbox_id"] = sandbox.sandbox_id
        receipt["initial_status"] = str(sandbox.status)
        sandbox.create_directory("/workspace/kernel-smoke")
        sandbox.write_file(
            "/workspace/kernel-smoke/packet.zip.b64",
            base64.b64encode(packet.read_bytes()).decode("ascii"),
        )
        decode = (
            "import base64,hashlib,pathlib,zipfile; "
            "r=pathlib.Path('/workspace/kernel-smoke'); "
            "z=r/'packet.zip'; z.write_bytes(base64.b64decode((r/'packet.zip.b64').read_text())); "
            "print(hashlib.sha256(z.read_bytes()).hexdigest()); "
            "zipfile.ZipFile(z).extractall(r/'src')"
        )
        commands = [
            ("python", ["--version"]),
            ("python", ["-c", decode]),
            ("python", ["/workspace/kernel-smoke/src/tests/kernel_unit.py"]),
            (
                "python",
                [
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--quiet",
                    "-r",
                    "/workspace/kernel-smoke/src/requirements.txt",
                ],
            ),
            ("python", ["/workspace/kernel-smoke/src/tests/headless_contract.py"]),
        ]
        for executable, argv in commands:
            item = run(sandbox, executable, argv, args.timeout_seconds)
            receipt["commands"].append(item)
            if item["exit_code"] != 0:
                raise RuntimeError(f"remote command failed at index {len(receipt['commands']) - 1}")
        observed_hash = receipt["commands"][1]["stdout_tail"].strip().splitlines()[-1]
        if observed_hash != latest["zip_sha256"]:
            raise RuntimeError("remote packet hash differs from local manifest")
        receipt["success"] = True
    except Exception as exc:
        receipt["success"] = False
        receipt["error_type"] = type(exc).__name__
        receipt["stack"] = [
            {"file": frame.filename, "line": frame.lineno, "function": frame.name}
            for frame in traceback.extract_tb(exc.__traceback__)
        ]
    finally:
        if sandbox is not None:
            try:
                sandbox.delete()
                receipt["deleted"] = True
            except Exception as exc:
                receipt["delete_error_type"] = type(exc).__name__
                try:
                    sandbox.stop()
                    receipt["stopped_after_delete_failure"] = True
                except Exception as stop_exc:
                    receipt["stop_error_type"] = type(stop_exc).__name__
        receipt["finished_at"] = now()
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "success": receipt["success"],
                "deleted": receipt["deleted"],
                "commands": len(receipt["commands"]),
                "receipt": str(args.receipt),
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["success"] and receipt["deleted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
