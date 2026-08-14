#!/usr/bin/env python3
"""Unit checks for Kaggle packet discovery without a Kaggle runtime."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "deploy" / "kaggle" / "validate_kernel.py"
SPEC = importlib.util.spec_from_file_location("kaggle_kernel_validate", MODULE_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="aetherbrowser-kaggle-discovery-") as temp:
        root = Path(temp)
        expanded = root / "new-layout" / "dataset" / "packet"
        expanded.mkdir(parents=True)
        (expanded / "MANIFEST.json").write_text(
            json.dumps({"packet_id": VALIDATOR.EXPECTED_PACKET_ID}),
            encoding="utf-8",
        )
        VALIDATOR.INPUT_ROOT = root
        transport, path, inventory = VALIDATOR.discover_packet()
        check(transport == "kaggle_auto_extracted", "auto-extracted transport found")
        check(path == expanded, "nested mount directory is not assumed")
        check(bool(inventory), "bounded input inventory is recorded")

    with tempfile.TemporaryDirectory(prefix="aetherbrowser-kaggle-zip-") as temp:
        root = Path(temp)
        packet = root / "mount" / "aetherbrowser-kernel-test.zip"
        packet.parent.mkdir(parents=True)
        with zipfile.ZipFile(packet, "w") as archive:
            archive.writestr("placeholder.txt", "test")
        VALIDATOR.INPUT_ROOT = root
        transport, path, _ = VALIDATOR.discover_packet()
        check(transport == "zip", "intact ZIP transport found")
        check(path == packet, "nested ZIP path is returned")

    with tempfile.TemporaryDirectory(prefix="aetherbrowser-kaggle-ambiguous-") as temp:
        root = Path(temp)
        for index in range(2):
            directory = root / f"packet-{index}"
            directory.mkdir()
            (directory / "MANIFEST.json").write_text(
                json.dumps({"packet_id": VALIDATOR.EXPECTED_PACKET_ID}),
                encoding="utf-8",
            )
        VALIDATOR.INPUT_ROOT = root
        try:
            VALIDATOR.discover_packet()
        except SystemExit:
            print("[PASS] ambiguous packet mounts fail closed")
        else:
            raise AssertionError("ambiguous packet mounts must fail closed")

    with tempfile.TemporaryDirectory(prefix="aetherbrowser-kaggle-mixed-") as temp:
        root = Path(temp)
        expanded = root / "expanded"
        expanded.mkdir()
        (expanded / "MANIFEST.json").write_text(
            json.dumps({"packet_id": VALIDATOR.EXPECTED_PACKET_ID}),
            encoding="utf-8",
        )
        packet = root / "aetherbrowser-kernel-test.zip"
        with zipfile.ZipFile(packet, "w") as archive:
            archive.writestr("placeholder.txt", "test")
        VALIDATOR.INPUT_ROOT = root
        try:
            VALIDATOR.discover_packet()
        except SystemExit:
            print("[PASS] mixed ZIP and expanded mounts fail closed")
        else:
            raise AssertionError("mixed packet transports must fail closed")

    with tempfile.TemporaryDirectory(prefix="aetherbrowser-kaggle-zipslip-") as temp:
        root = Path(temp)
        packet = root / "packet.zip"
        with zipfile.ZipFile(packet, "w") as archive:
            archive.writestr("../escape.txt", "must not escape")
        destination = root / "destination"
        try:
            VALIDATOR.extract_packet(packet, destination)
        except SystemExit:
            print("[PASS] archive traversal fails closed")
        else:
            raise AssertionError("archive traversal must fail closed")
        check(not (root / "escape.txt").exists(), "archive traversal writes nothing")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
