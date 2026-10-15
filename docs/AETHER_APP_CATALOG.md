# Aether Apps catalog

`config/aether_apps.json` is the reviewed boundary between AetherBrowser and the
products around it. It records product identity, purpose, and an optional web
route. It does not contain startup commands, credentials, runtime data, or model
payloads.

Current browser routes:

| Product | Default route | Override |
|---|---|---|
| Clay World | `http://127.0.0.1:8792/` | `CLAY_WORLD_URL` |
| Parcel Study | `http://127.0.0.1:8765/` | `PARCEL_STUDY_URL` |
| Clay Code Builder | `http://127.0.0.1:5173/` | `CLAY_CODE_BUILDER_URL` |

AetherDesk and ClayMail remain visible as connected products, but have no Open
button until they expose a reviewed HTTP(S) route. Environment overrides reject
non-web schemes and URLs containing credentials.

The API and page are available at `GET /apps` and `GET /apps/home`. The Electron
address bar's **Apps** button navigates to the latter on the configured backend
port.
