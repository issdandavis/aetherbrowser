"""Validated product routes shown by AetherBrowser's local Apps surface.

The catalog is data, never a shell launcher. Web entries may navigate only to a
validated HTTP(S) URL. Connected entries are visible but deliberately have no
Open action until their product exposes a reviewed browser route.
"""

from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "config" / "aether_apps.json"
APP_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ROUTE_KINDS = {"web", "connected"}


def _safe_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("app route must be an absolute HTTP(S) URL")
    if parts.username or parts.password:
        raise ValueError("app route must not contain credentials")
    return value.strip()


def load_apps(
    *,
    catalog_path: Path = CATALOG_PATH,
    environ: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    environment = os.environ if environ is None else environ
    source = json.loads(catalog_path.read_text(encoding="utf-8"))
    if source.get("schema_version") != "aether.apps.v1":
        raise ValueError("unsupported app catalog schema")

    apps: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in source.get("apps", []):
        app_id = str(raw.get("id", ""))
        if not APP_ID.fullmatch(app_id) or app_id in seen:
            raise ValueError(f"invalid or duplicate app id: {app_id!r}")
        seen.add(app_id)

        route = raw.get("route") if isinstance(raw.get("route"), dict) else {}
        kind = str(route.get("kind", ""))
        if kind not in ROUTE_KINDS:
            raise ValueError(f"unsupported route kind for {app_id}: {kind!r}")

        launch_url = None
        if kind == "web":
            env_name = str(route.get("url_env", ""))
            configured = environment.get(env_name, "") if env_name else ""
            launch_url = _safe_url(configured or str(route.get("default_url", "")))

        apps.append(
            {
                "id": app_id,
                "name": str(raw.get("name", app_id)),
                "category": str(raw.get("category", "product")),
                "description": str(raw.get("description", "")),
                "status": str(raw.get("status", "registered")),
                "launchable": launch_url is not None,
                "launch_url": launch_url,
                "source_repository": raw.get("source_repository"),
            }
        )
    return apps


def render_app_home(apps: list[dict[str, Any]]) -> str:
    cards: list[str] = []
    for app in apps:
        name = html.escape(str(app["name"]))
        category = html.escape(str(app["category"]))
        description = html.escape(str(app["description"]))
        status = html.escape(str(app["status"]))
        if app["launchable"]:
            url = html.escape(str(app["launch_url"]), quote=True)
            action = f'<a class="open" href="{url}">Open</a>'
        else:
            action = '<span class="registered">Registered</span>'
        cards.append(
            f'<article class="card"><p class="category">{category}</p>'
            f"<h2>{name}</h2><p>{description}</p>"
            f'<div class="foot"><span>{status}</span>{action}</div></article>'
        )

    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; navigate-to http: https:">
<title>Aether Apps</title><style>
:root{color-scheme:dark;--bg:#090d14;--panel:#141b26;--line:#29374a;--text:#edf5ff;--muted:#9eb0c5;--accent:#65b8ff}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top,#142238,var(--bg) 48%);color:var(--text);font:16px/1.5 system-ui,sans-serif}
main{max-width:1100px;margin:auto;padding:56px 24px}h1{font-size:clamp(2.2rem,6vw,4.8rem);margin:0}.intro{color:var(--muted);max-width:720px;margin:10px 0 32px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:18px}.card{min-height:250px;padding:24px;border:1px solid var(--line);border-radius:18px;background:linear-gradient(145deg,rgba(24,34,49,.96),rgba(12,18,28,.96));display:flex;flex-direction:column}
.category{text-transform:uppercase;letter-spacing:.13em;color:var(--accent);font-size:.72rem;font-weight:750}.card h2{font-size:1.55rem;margin:.2rem 0}.card>p:not(.category){color:var(--muted)}.foot{margin-top:auto;display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:.78rem;color:var(--muted)}
.open,.registered{padding:8px 13px;border-radius:999px;font-weight:750}.open{background:var(--accent);color:#061321;text-decoration:none}.open:focus,.open:hover{outline:2px solid white;outline-offset:2px}.registered{border:1px solid var(--line)}
</style></head><body><main><p class="category">Local product shelf</p><h1>Aether Apps</h1>
<p class="intro">Reviewed routes into Clay and the tools around him. An Open button navigates to a service; it never starts a process or runs a command.</p>
<section class="grid">""" + "".join(cards) + """</section></main></body></html>"""
