#!/usr/bin/env python3
"""Build a deterministic, content-addressed AetherBrowser kernel packet."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"

EXACT_FILES = {
    "README.md",
    "requirements.txt",
    "package.json",
    "docs/BROWSER_AGENT_KERNEL.md",
    "scripts/build_kernel_packet.py",
    "scripts/kernel_conveyor.py",
    "scripts/lightning_kernel_smoke.py",
    "tests/headless_contract.py",
    "tests/kernel_unit.py",
    "tests/smoke.py",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_files() -> list[Path]:
    paths = [ROOT / relative for relative in EXACT_FILES]
    paths.extend(sorted((ROOT / "src" / "aetherbrowser").glob("*.py")))
    missing = [str(path.relative_to(ROOT)) for path in paths if not path.is_file()]
    if missing:
        raise SystemExit(f"missing packet source files: {', '.join(missing)}")
    return sorted(set(paths), key=lambda path: path.relative_to(ROOT).as_posix())


def build() -> dict:
    rows = []
    payloads: dict[str, bytes] = {}
    for path in source_files():
        relative = path.relative_to(ROOT).as_posix()
        data = path.read_bytes()
        payloads[relative] = data
        rows.append({"path": relative, "bytes": len(data), "sha256": sha256_bytes(data)})

    packet_id = sha256_bytes(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    manifest = {
        "schema": "aetherbrowser.kernel-packet.v1",
        "packet_id": packet_id,
        "files": rows,
        "verification": [
            "python tests/kernel_unit.py",
            "python tests/headless_contract.py",
            "python tests/smoke.py",
            "python scripts/kernel_conveyor.py --once",
        ],
    }
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n"

    DIST.mkdir(parents=True, exist_ok=True)
    zip_path = DIST / f"aetherbrowser-kernel-{packet_id[:16]}.zip"
    manifest_path = DIST / f"aetherbrowser-kernel-{packet_id[:16]}.manifest.json"
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, data in sorted(payloads.items()):
            info = ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
        info = ZipInfo("MANIFEST.json", date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        archive.writestr(info, manifest_bytes)
    manifest_path.write_bytes(manifest_bytes)
    result = {
        **manifest,
        "zip": str(zip_path),
        "zip_bytes": zip_path.stat().st_size,
        "zip_sha256": sha256_bytes(zip_path.read_bytes()),
        "manifest": str(manifest_path),
    }
    (DIST / "aetherbrowser-kernel-latest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, sort_keys=True))
