"""Focused checks for the data-only Aether Apps catalog."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.aetherbrowser.app_catalog import load_apps, render_app_home


class AppCatalogTests(unittest.TestCase):
    def test_required_products_and_route_boundaries(self):
        apps = load_apps(environ={})
        by_id = {app["id"]: app for app in apps}
        self.assertTrue({"clay-world", "parcel-study", "clay-code-builder"} <= set(by_id))
        self.assertTrue(by_id["clay-world"]["launchable"])
        self.assertFalse(by_id["aetherdesk"]["launchable"])
        self.assertFalse(by_id["claymail"]["launchable"])

    def test_environment_can_replace_a_reviewed_url(self):
        apps = load_apps(environ={"CLAY_WORLD_URL": "https://clay.test:9443/world"})
        clay = next(app for app in apps if app["id"] == "clay-world")
        self.assertEqual(clay["launch_url"], "https://clay.test:9443/world")

    def test_credentials_and_non_web_schemes_are_rejected(self):
        for value in ("file:///tmp/clay", "https://user:secret@example.test/"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                load_apps(environ={"CLAY_WORLD_URL": value})

    def test_duplicate_ids_are_rejected(self):
        payload = {
            "schema_version": "aether.apps.v1",
            "apps": [
                {"id": "same", "route": {"kind": "connected"}},
                {"id": "same", "route": {"kind": "connected"}},
            ],
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "apps.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_apps(catalog_path=path, environ={})

    def test_home_escapes_catalog_text_and_has_no_process_launcher(self):
        page = render_app_home(
            [
                {
                    "id": "test",
                    "name": "<Clay>",
                    "category": "test",
                    "description": "safe & local",
                    "status": "registered",
                    "launchable": False,
                    "launch_url": None,
                }
            ]
        )
        self.assertIn("&lt;Clay&gt;", page)
        self.assertNotIn("subprocess", page.lower())
        self.assertNotIn("powershell", page.lower())


if __name__ == "__main__":
    unittest.main()
