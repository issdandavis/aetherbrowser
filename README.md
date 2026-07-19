# AetherBrowser (consolidated)

A single, self-contained copy of **AetherBrowser** — an AI-governed desktop
browser with a multi-agent sidepanel — assembled in one folder so it can be run
from here without the rest of the `instrument-wt` monorepo.

This folder is the dependency-closure of the running Electron app plus its
spawned Python/FastAPI backend. Files keep their original relative paths so the
absolute package imports (`from src.aetherbrowser.X import ...`) and the Electron
path math (`ROOT = resolve(__dirname, '..', '..')`) keep working unchanged.

## What it is

- **Electron desktop shell** (`desktop/`) — a Chromium window split into:
  - an address bar (top chrome),
  - a browser pane (loads real web pages, starts at google.com),
  - an AI **sidepanel** (reuses the extension UI in `src/extension/`).
- **Python backend** (`src/aetherbrowser/`) — a FastAPI app (`serve:app`) that
  the Electron main process spawns on `127.0.0.1:8002`. The sidepanel connects to
  it over `ws://127.0.0.1:8002/ws` and polls `http://127.0.0.1:8002/health`.
  It runs the agent squad / router / page-analysis / topology modules.

## Layout

```
aetherbrowser/
├─ package.json            # top-level: `npm start` -> `electron .` (main = desktop/electron/main.js)
├─ requirements.txt        # python backend deps (fastapi, uvicorn[standard])
├─ start.ps1               # one-command launcher (Windows PowerShell)
├─ README.md
├─ desktop/                # Electron shell
│  ├─ package.json         # original desktop package (main = electron/main.js)
│  ├─ electron/            # main.js + preload-{addressbar,browser,sidepanel}.js
│  └─ renderer/            # address-bar.html / address-bar.js
└─ src/
   ├─ aetherbrowser/       # FastAPI backend (serve.py + agents/router/planner/...)
   └─ extension/           # sidepanel UI (html/css/js + lib/ + components/) and
                           # chrome-extension artifacts (manifest/background/content/icons)
```

> Import note: the backend uses **absolute package imports** (`from
> src.aetherbrowser...`). It MUST be launched with the repo-root (this folder,
> which contains `src/`) as the working directory / on `sys.path` so the
> top-level package name `src` resolves. The Electron `main.js` already does this
> (`cwd = ROOT = this folder`). Do not flatten or rename to relative imports.

## Prerequisites

- **Windows** with Python 3.10+ (tested on 3.12) on `PATH` as `python`.
- **Node.js + npm** (Electron `^42` is installed locally via `npm install`).
- `node_modules/` is intentionally **not** included — install it once (below).

## Run it

From this folder:

```powershell
./start.ps1
```

`start.ps1` will:
1. install the Python deps (`fastapi`, `uvicorn[standard]`) if missing,
2. run `npm install` if Electron isn't present yet,
3. launch the desktop app with `npm start`.

Electron's `main.js` then **auto-spawns** the backend
(`python -m uvicorn src.aetherbrowser.serve:app --port 8002 --host 127.0.0.1`,
cwd = this folder) and tears it down on quit. You do not start uvicorn yourself.

### Equivalent manual launch

```powershell
npm install          # first time only (pulls Electron)
npm start            # == electron .  (spawns the uvicorn backend on :8002)
```

### Backend only (API / debugging, no desktop shell)

```powershell
./start.ps1 -BackendOnly
# or directly:
python -m uvicorn src.aetherbrowser.serve:app --host 127.0.0.1 --port 8002
```

### Headless agent use

Start the backend, then use the stable control-plane endpoints. External agents
and future communication-tool adapters should call these endpoints instead of
scraping the UI:

```text
GET  /headless/capabilities
POST /headless/command
POST /headless/page-context
POST /headless/browser-action
GET  /headless/browser-actions
GET  /headless/controller-state
POST /headless/controller-event
GET  /context
GET  /health
WS   /ws
```

Default policy: read-only planning and answering can run headless. Credential,
payment, publish, delete, submit, and unclear state-changing browser actions are
held for review unless the caller explicitly opts into that risk.

The controller layer treats a web page like a game state. Agents can observe the
current page, move through it with directional events, request browser controls,
and receive haptic feedback metadata. State-changing controller events such as
`primary`, `secondary`, and `type` are held unless the caller explicitly sets
`allow_state_change`.

### iOS mobile app

Open `ios/AetherBrowserMobile/AetherBrowserMobile.xcodeproj` in Xcode. The app
uses SwiftUI tabs on iPhone and a split workspace on iPad/regular-width layouts.
It embeds real web pages with `WKWebView`, provides browser controls, and talks
to the same `/ws`, `/health`, and `/headless/*` backend surfaces.

For Simulator, the backend URL can stay `http://127.0.0.1:8002`. For a physical
iPhone, start the backend with `./start.ps1 -BackendOnly -Lan` and set the app
backend URL to the Windows machine LAN IP.

## Verify

```powershell
npm run test:smoke
npm run test:headless
```

## Notes

- The browser pane navigates to **remote** URLs (e.g. google.com); no offline
  web content is bundled.
- `src/extension/` also contains the chrome-extension files (`manifest.json`,
  `background.js`, `content.js`, `icons/`) and two unused components
  (`SummaryCard.js`, `TopologyCanvas.js`). The Electron app does not load these
  at runtime — they're included for completeness/packaging.
- LLM-provider features in the backend may need additional provider API keys /
  packages; the minimal set to start the server is just `fastapi` + `uvicorn`.
