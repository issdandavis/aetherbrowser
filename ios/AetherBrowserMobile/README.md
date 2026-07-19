# AetherBrowser Mobile

Native iOS shell for the existing AetherBrowser backend.

This is not an Electron port. Electron is desktop-only, so the mobile shape is:

- SwiftUI app shell with tab navigation.
- `WKWebView` browser tab for real pages.
- Native agent console that talks to the existing FastAPI/WebSocket backend.
- Health and settings screens for local backend diagnostics.

## Backend

From `C:\dev\aetherbrowser`:

```powershell
python -m uvicorn src.aetherbrowser.serve:app --host 0.0.0.0 --port 8002
```

For Simulator, keep the default backend URL:

```text
http://127.0.0.1:8002
```

For a physical iPhone, set the backend URL in Settings to the Windows machine IP on the same network:

```text
http://<windows-lan-ip>:8002
```

## Xcode

Open:

```text
ios/AetherBrowserMobile/AetherBrowserMobile.xcodeproj
```

Target: iOS 17.0+

The project uses only SwiftUI, WebKit, Foundation, and the built-in URLSession WebSocket client.

## Controller Model

The app consumes the same controller protocol as desktop and headless agents:

- `move_up`, `move_down`, `move_left`, `move_right` scroll the current page.
- `back`, `forward`, and `reload` use browser controls.
- `observe` sends the current page context to the backend.
- `primary`, `type`, and other state-changing events are expected to be gated by the backend.
- Haptic metadata on controller events maps to native iOS selection, impact, warning, success, or error feedback.
