#!/usr/bin/env python3
r"""
Install / Uninstall the AetherBrowser Native Messaging Host
=============================================================

Registers the native messaging host manifest so Chrome can find it.

Windows:  Writes a registry key under HKCU\SOFTWARE\Google\Chrome\NativeMessagingHosts
macOS:    Writes manifest to ~/Library/Application Support/Google/Chrome/NativeMessagingHosts/
Linux:    Writes manifest to ~/.config/google-chrome/NativeMessagingHosts/

Usage:
    python install.py install           # register
    python install.py install --edge    # register for Edge instead of Chrome
    python install.py uninstall         # remove
    python install.py status            # check if registered
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path

HOST_NAME = "com.scbe.aetherbrowser"
HOST_DESCRIPTION = "AetherBrowser Native Messaging Host - starts/stops the backend server"

# The extension ID is determined after first load in Chrome.
# Use a wildcard during development, then lock to your published ID.
# To find your ID: chrome://extensions → load unpacked → copy the ID
ALLOWED_ORIGINS_CHROME = [
    "chrome-extension://EXTENSION_ID_HERE/",
]
ALLOWED_ORIGINS_EDGE = [
    "chrome-extension://EXTENSION_ID_HERE/",
]

SCRIPT_DIR = Path(__file__).resolve().parent
HOST_SCRIPT = SCRIPT_DIR / "host.py"
PYTHON = sys.executable


def _build_manifest(allowed_origins: list[str]) -> dict:
    """Build the native messaging host manifest JSON."""
    if platform.system() == "Windows":
        # Windows uses a .bat wrapper because Chrome expects an .exe or .bat
        host_path = str(SCRIPT_DIR / "host.bat")
    else:
        host_path = str(HOST_SCRIPT)

    return {
        "name": HOST_NAME,
        "description": HOST_DESCRIPTION,
        "path": host_path,
        "type": "stdio",
        "allowed_origins": allowed_origins,
    }


def _create_bat_wrapper() -> Path:
    """Create a .bat wrapper for Windows (Chrome can't run .py directly)."""
    bat_path = SCRIPT_DIR / "host.bat"
    # Use the same Python that's running this installer
    bat_content = f'@echo off\r\n"{PYTHON}" "{HOST_SCRIPT}" %*\r\n'
    bat_path.write_text(bat_content, encoding="utf-8")
    return bat_path


def _manifest_path(browser: str = "chrome") -> Path:
    """Return the OS-specific path for the manifest JSON file."""
    system = platform.system()

    if system == "Windows":
        # On Windows the manifest lives next to the host; registry points to it
        return SCRIPT_DIR / f"{HOST_NAME}.json"

    if system == "Darwin":
        if browser == "edge":
            base = Path.home() / "Library/Application Support/Microsoft Edge/NativeMessagingHosts"
        else:
            base = Path.home() / "Library/Application Support/Google/Chrome/NativeMessagingHosts"
    else:  # Linux
        if browser == "edge":
            base = Path.home() / ".config/microsoft-edge/NativeMessagingHosts"
        else:
            base = Path.home() / ".config/google-chrome/NativeMessagingHosts"

    base.mkdir(parents=True, exist_ok=True)
    return base / f"{HOST_NAME}.json"


def _registry_key(browser: str = "chrome") -> str:
    if browser == "edge":
        return rf"SOFTWARE\Microsoft\Edge\NativeMessagingHosts\{HOST_NAME}"
    return rf"SOFTWARE\Google\Chrome\NativeMessagingHosts\{HOST_NAME}"


def install(browser: str = "chrome", extension_id: str | None = None) -> None:
    """Register the native messaging host."""
    origins = ALLOWED_ORIGINS_EDGE if browser == "edge" else ALLOWED_ORIGINS_CHROME

    # Substitute extension ID if provided
    if extension_id:
        origins = [o.replace("EXTENSION_ID_HERE", extension_id) for o in origins]

    manifest = _build_manifest(origins)

    # Create .bat wrapper on Windows
    if platform.system() == "Windows":
        _create_bat_wrapper()

    # Make host.py executable on Unix
    if platform.system() != "Windows":
        HOST_SCRIPT.chmod(0o755)

    # Write manifest JSON
    manifest_file = _manifest_path(browser)
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Manifest written: {manifest_file}")

    # Windows: also set registry key pointing to manifest
    if platform.system() == "Windows":
        try:
            import winreg
            key_path = _registry_key(browser)
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest_file))
            print(f"Registry key set: HKCU\\{key_path}")
        except Exception as e:
            print(f"Warning: Could not set registry key: {e}")
            print(f"You may need to manually add HKCU\\{key_path}")
            print(f"  Default value = {manifest_file}")

    if "EXTENSION_ID_HERE" in json.dumps(origins):
        print()
        print("IMPORTANT: Update allowed_origins with your extension ID!")
        print("  1. Load the extension in Chrome: chrome://extensions -> Load unpacked")
        print("  2. Copy the extension ID from the card")
        print("  3. Re-run: python install.py install --id YOUR_EXTENSION_ID")
    else:
        print(f"Registered for extension: {extension_id}")

    print("Done.")


def uninstall(browser: str = "chrome") -> None:
    """Remove the native messaging host registration."""
    manifest_file = _manifest_path(browser)
    if manifest_file.exists():
        manifest_file.unlink()
        print(f"Manifest removed: {manifest_file}")

    bat_file = SCRIPT_DIR / "host.bat"
    if bat_file.exists():
        bat_file.unlink()
        print(f"Bat wrapper removed: {bat_file}")

    if platform.system() == "Windows":
        try:
            import winreg
            key_path = _registry_key(browser)
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
            print(f"Registry key removed: HKCU\\{key_path}")
        except FileNotFoundError:
            print("Registry key not found (already clean)")
        except Exception as e:
            print(f"Warning: Could not remove registry key: {e}")

    print("Done.")


def status(browser: str = "chrome") -> None:
    """Check registration status."""
    manifest_file = _manifest_path(browser)
    print(f"Host name: {HOST_NAME}")
    print(f"Manifest path: {manifest_file}")
    print(f"Manifest exists: {manifest_file.exists()}")

    if manifest_file.exists():
        data = json.loads(manifest_file.read_text())
        print(f"Host path: {data.get('path')}")
        host_exists = Path(data.get("path", "")).exists()
        print(f"Host script exists: {host_exists}")
        print(f"Allowed origins: {data.get('allowed_origins')}")

    if platform.system() == "Windows":
        try:
            import winreg
            key_path = _registry_key(browser)
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                val, _ = winreg.QueryValueEx(key, "")
                print(f"Registry key: HKCU\\{key_path} = {val}")
        except FileNotFoundError:
            print("Registry key: NOT SET")
        except Exception as e:
            print(f"Registry key error: {e}")

    bat_file = SCRIPT_DIR / "host.bat"
    if platform.system() == "Windows":
        print(f"Bat wrapper: {bat_file} (exists: {bat_file.exists()})")


def main():
    parser = argparse.ArgumentParser(
        description="Install/uninstall AetherBrowser Native Messaging Host"
    )
    parser.add_argument(
        "action",
        choices=["install", "uninstall", "status"],
        help="Action to perform",
    )
    parser.add_argument(
        "--edge",
        action="store_true",
        help="Register for Microsoft Edge instead of Chrome",
    )
    parser.add_argument(
        "--id",
        type=str,
        default=None,
        help="Chrome extension ID (from chrome://extensions)",
    )
    args = parser.parse_args()

    browser = "edge" if args.edge else "chrome"

    if args.action == "install":
        install(browser, args.id)
    elif args.action == "uninstall":
        uninstall(browser)
    elif args.action == "status":
        status(browser)


if __name__ == "__main__":
    main()
