# AetherBrowser — Privacy Policy

_Last updated: 2026-07-03_

AetherBrowser is a browser extension that puts a multi-agent AI sidebar next to the pages you browse. It is designed to keep your data on your own machine.

## What it accesses
- **The current tab** (title, URL, and page text) — only when you explicitly ask (e.g. "This Page", "Research").
- **Your open tab list** — only when you request an action that needs it.
- **A screenshot of the visible tab** — only when you trigger a capture.
- **Local settings** — stored on your device via the browser's `storage` API.

## Where your data goes
All of the above is sent **only to a backend running on your own computer** at `http://127.0.0.1:8002`. The extension does **not** send your browsing data to AetherMoore, the developer, or any third-party server. There is no analytics, no advertising, no tracking, and no sale of data.

## AI providers
The local backend may forward a request to an AI provider **you configure** (for example a local model via Ollama, or a cloud provider using your own API key). When it does, that provider's privacy policy applies to that specific request. With no provider configured, the local/deterministic path is used.

## Governance
State-changing browser actions — using credentials, making payments, publishing, deleting, or submitting — are **held for your review** and are never performed automatically.

## Permissions, briefly
- `activeTab` / `tabs`: read the page and tabs you explicitly act on.
- `sidePanel`: show the assistant as a side panel.
- `storage`: save your local settings.
- host access to `127.0.0.1` / `localhost`: connect to your own local backend. No remote hosts are contacted by the extension.

## Contact
Questions: **aethermoregames@pm.me**
