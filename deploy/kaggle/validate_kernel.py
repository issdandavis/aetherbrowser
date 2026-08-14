"""Offline Kaggle CPU validation for the content-addressed kernel packet."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile


EXPECTED_PACKET_ID = "ea756662fa7f6c490b48f2d183e605a022a5609711e07ccddcd6f697282d531d"
EXPECTED_ZIP_SHA256 = "8088bc6f038a5a3f9e67416fe2aefae982ff951ee0d8938d615848913f52c598"
INPUT_ROOT = Path("/kaggle/input")
WORK = Path("/kaggle/working/aetherbrowser-kernel")
RESULT = Path("/kaggle/working/kaggle-kernel-validation.json")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_check(label: str, command: list[str]) -> dict[str, object]:
    started = time.time()
    completed = subprocess.run(
        command,
        cwd=WORK,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    record = {
        "label": label,
        "command": command,
        "exit_code": completed.returncode,
        "duration_seconds": round(time.time() - started, 3),
        "stdout_tail": completed.stdout[-2000:],
        "stderr_tail": completed.stderr[-2000:],
    }
    print(f"[{label}] exit={completed.returncode}")
    print(record["stdout_tail"])
    if completed.stderr:
        print(record["stderr_tail"], file=sys.stderr)
    return record


def extract_packet(archive_path: Path, destination: Path) -> None:
    """Extract a pinned packet without permitting paths outside destination."""

    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if target != root and root not in target.parents:
                raise SystemExit(f"unsafe packet member: {member.filename}")
        archive.extractall(destination)


def discover_packet() -> tuple[str, Path, list[str]]:
    """Find the packet without trusting Kaggle's current mount-directory layout."""

    if not INPUT_ROOT.is_dir():
        raise SystemExit(f"Kaggle input root is absent: {INPUT_ROOT}")

    inventory = sorted(
        str(item.relative_to(INPUT_ROOT))
        for item in INPUT_ROOT.rglob("*")
        if len(item.relative_to(INPUT_ROOT).parts) <= 3
    )
    packet_zips = sorted(INPUT_ROOT.rglob("aetherbrowser-kernel-*.zip"))
    manifest_dirs: list[Path] = []
    for manifest_path in sorted(INPUT_ROOT.rglob("MANIFEST.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if manifest.get("packet_id") == EXPECTED_PACKET_ID:
            manifest_dirs.append(manifest_path.parent)

    if len(packet_zips) == 1 and not manifest_dirs:
        return "zip", packet_zips[0], inventory
    if len(manifest_dirs) == 1 and not packet_zips:
        return "kaggle_auto_extracted", manifest_dirs[0], inventory
    raise SystemExit(
        "expected exactly one content-addressed packet; "
        f"zips={len(packet_zips)} manifests={len(manifest_dirs)} "
        f"input_inventory={inventory[:80]}"
    )


def main() -> None:
    discovered_transport, packet_path, input_inventory = discover_packet()
    if discovered_transport == "zip":
        actual_zip_sha = sha256(packet_path)
        if actual_zip_sha != EXPECTED_ZIP_SHA256:
            raise SystemExit(f"packet hash mismatch: {actual_zip_sha}")
        WORK.mkdir(parents=True, exist_ok=True)
        extract_packet(packet_path, WORK)
        transport = "zip"
        zip_hash_verified = True
    else:
        # Kaggle expands uploaded ZIPs on some dataset paths. The transport hash is
        # then unavailable in the mount, but every inner manifest hash is checkable.
        shutil.copytree(packet_path, WORK, dirs_exist_ok=True)
        actual_zip_sha = EXPECTED_ZIP_SHA256
        transport = "kaggle_auto_extracted"
        zip_hash_verified = False

    manifest = json.loads((WORK / "MANIFEST.json").read_text(encoding="utf-8"))
    if manifest.get("packet_id") != EXPECTED_PACKET_ID:
        raise SystemExit(f"packet id mismatch: {manifest.get('packet_id')}")

    bad_files = []
    for entry in manifest["files"]:
        item = WORK / entry["path"]
        if not item.is_file() or sha256(item) != entry["sha256"]:
            bad_files.append(entry["path"])
    if bad_files:
        raise SystemExit(f"manifest verification failed: {bad_files}")

    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except Exception as exc:
        raise SystemExit(f"Kaggle image lacks declared runtime dependency: {exc}")

    checks = [
        run_check("kernel_unit", [sys.executable, "tests/kernel_unit.py"]),
        run_check("headless_contract", [sys.executable, "tests/headless_contract.py"]),
        run_check("smoke", [sys.executable, "tests/smoke.py"]),
        run_check(
            "conveyor_once",
            [
                sys.executable,
                "scripts/kernel_conveyor.py",
                "--once",
                "--output-dir",
                "/kaggle/working/conveyor",
            ],
        ),
    ]
    result = {
        "schema": "aetherbrowser.kaggle-validation.v1",
        "packet_id": EXPECTED_PACKET_ID,
        "zip_sha256": actual_zip_sha,
        "zip_sha256_verified_in_runtime": zip_hash_verified,
        "transport": transport,
        "input_inventory_sample": input_inventory[:80],
        "manifest_files": len(manifest["files"]),
        "python": sys.version,
        "cpu_count": os.cpu_count(),
        "internet_required": False,
        "competition_submission": False,
        "checks": checks,
        "all_passed": all(item["exit_code"] == 0 for item in checks),
    }
    RESULT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    if not result["all_passed"]:
        raise SystemExit("one or more checks failed")


if __name__ == "__main__":
    main()
