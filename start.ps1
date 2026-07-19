#requires -Version 5.1
<#
  start.ps1 - single-spot launcher for the consolidated AetherBrowser.

  DEFAULT (matches the captured runtime trace):
    Launches the Electron desktop shell from this folder via `npm start`
    (-> `electron .`, main = desktop/electron/main.js). On app.whenReady(),
    main.js AUTO-SPAWNS the Python/FastAPI backend:
        python -m uvicorn src.aetherbrowser.serve:app --port 8002 --host 127.0.0.1
    with cwd = this folder (so the top-level package `src` resolves), then opens
    the browser pane + AI sidepanel. Do NOT also start uvicorn yourself or port
    8002 will be taken and the backend spawn will fail.

  -BackendOnly:
    Runs ONLY the FastAPI backend (no Electron) for API work / debugging:
        python -m uvicorn src.aetherbrowser.serve:app --host 127.0.0.1 --port 8002

  -Lan:
    With -BackendOnly, binds to 0.0.0.0 so an iPhone on the same LAN can reach
    the backend through this Windows machine's LAN IP.
#>
param(
  [switch]$BackendOnly,
  [switch]$Lan,
  [int]$Port = 8002
)

$ErrorActionPreference = 'Continue'
$Root = $PSScriptRoot
Set-Location $Root
Write-Host "AetherBrowser (consolidated)  @ $Root"

# --- Ensure Python backend deps (fastapi + uvicorn) ---
& python -c "import fastapi, uvicorn" *> $null
if ($LASTEXITCODE -ne 0) {
  Write-Host "[setup] Installing Python backend deps from requirements.txt ..."
  & python -m pip install -r (Join-Path $Root 'requirements.txt')
}

if ($BackendOnly) {
  $HostBind = if ($Lan) { '0.0.0.0' } else { '127.0.0.1' }
  Write-Host "[run] Backend only -> http://$HostBind`:$Port  (Ctrl+C to stop)"
  & python -m uvicorn src.aetherbrowser.serve:app --host $HostBind --port $Port
  return
}

# --- Ensure Electron is installed (node_modules excluded from the copy) ---
if (-not (Test-Path (Join-Path $Root 'node_modules\electron'))) {
  Write-Host "[setup] Installing Electron (npm install) ..."
  & npm install
}

# --- Launch the desktop app; Electron spawns the uvicorn backend itself ---
Write-Host "[run] Launching AetherBrowser. Electron will spawn uvicorn on 127.0.0.1:8002 (cwd=$Root)."
& npm start
