# Public portal validation — 2026-08-14

Deployment: `https://aethermoore.com/AetherDesk/`

The GitHub Pages deployment for AetherDesk commit `ee40960` completed successfully.
The deployed files were then fetched from the public AetherMoore domain rather than
inferred from the workflow result.

| Public resource | HTTP | Verified contract |
|---|---:|---|
| `/AetherDesk/` | 200 | portal document served |
| `/AetherDesk/rooms.json` | 200 | browser status `verified_preview`; expected packet ID; checkout `false` |
| `/AetherDesk/hallway.json` | 200 | fixed kernel status route and six-stage mutation contract |
| `/AetherDesk/llms.txt` | 200 | agent-visible kernel status route present |

Repository CI initially failed on an unrelated, pre-existing assertion that required
the generated Studio path to contain the Windows username `issda`. A clean-worktree
repair now tests the actual portable invariant (absolute path with basename `studio`)
and prevents ordinary `risk-tier` text from tripping a one-character secret regex.
AetherDesk commit `f86a20e` passed all 292 tests and the production build locally and
passed the Linux GitHub Actions run.

No checkout, entitlement mutation, remote browser write, or credential was exercised
by this public validation.

## Offer contract follow-up

AetherDesk commit `63e4d4e` added a public `offers.json` whose three offers are
tested for exact parity with the existing local revenue price book. The Pages deploy
and Linux CI both passed. A fresh public fetch returned HTTP 200 and SHA-256
`a23980b1b643d0a6c1460b1c622c7994aa22e496daafdf64c6d03e614a0cfd33`.

The Operator Pack is described as $99/month for 500 receipt-backed events with a
$30 API-cost reserve. `selling_enabled`, `checkout_connected`, and
`entitlement_connected` are all `false`. The catalog therefore supports discovery,
quoting, and routing without creating false sale or delivery state.

## Public doorway follow-up

The first portal contract exposed only the installed runtime route
`http://127.0.0.1:5717/api/aetherbrowser/kernel/status`. That is correct after a local
AetherDesk install, but it is not a public-web status page. Direct requests to both
plausible public `/api/.../status` URLs returned HTTP 404.

AetherDesk commit `3b8773b` added `/AetherDesk/kernel-status.json` as the durable public
doorway and kept the loopback API separately labeled as `local_launch`. The status file
states `live_public_runtime=false`; it reports the exact packet, test evidence, source,
local routes, write boundary, and disconnected sales boundary without pretending that
GitHub Pages is a live browser-control backend.

The primary-checkout pre-push gate passed 299/299 tests and the production build. The
Pages workflow completed successfully. A fresh public fetch returned HTTP 200, packet
ID `ea756662fa7f6c490b48f2d183e605a022a5609711e07ccddcd6f697282d531d`,
`remote_writes_default=denied`, `selling_enabled=false`, and SHA-256
`5c18cfc7e8abdcd93e9ee657aff3d42e91dc0acbb4eb278f751ac240d2f8d301`.

## Installed bridge follow-up

AetherDesk commit `96df8ea` turns the local doorway into an installed bridge rather
than a catalog-only promise. It allowlists the kernel routes, starts the backend from
the AetherBrowser repository rather than the SCBE repository, reports kernel health,
and proxies capabilities, observation, planning, approval, dispatch, verification,
receipts, and save slots.

An isolated end-to-end run started temporary AetherBrowser and AetherDesk processes on
non-default loopback ports. Through AetherDesk, a capture plan became `ready`, was
`dispatched`, and verified as `verified`; the receipt chain remained valid. A plan to
click “Delete account” returned `denied` with the kernel's remote-write boundary. Both
temporary processes were confirmed stopped afterward. The clean checkout passed
293/293 tests and the production build before push.

The first Linux CI run then failed only because its new test called POSIX
`path.basename()` on the deliberate Windows default `C:\\dev\\aetherbrowser`; Linux
correctly treated the backslashes as ordinary characters. Commit `5cba287` normalizes
both path separators in the assertion. Its focused 168-test run, full 293-test/build
gate, and fresh GitHub Actions run all passed. The bridge behavior itself was unchanged.

The pre-existing AetherDesk process on PID 7860 started before the bridge was written
and returns HTTP 404 for the new route. It was left untouched because it belongs to the
earlier credential-bearing sandbox session. The public status therefore correctly says
`live_public_runtime=false`, and local activation remains a deliberate clean restart.

## Other advertised doors

The two public download CTAs returned HTTP 200: AetherDesk Portable at 2,485,148 bytes
and Plugin+ at 4,012 bytes. The npm registry API and PyPI API both report
`scbe-aethermoore` version `4.3.1`; PyPI requires Python `>=3.11`, and npm exposes the
four advertised bins. The public AetherBrowser GitHub source route also returned HTTP
200. The npm website itself rejected an HTTP `HEAD` request with 403, so registry API
metadata—not that unsupported probe—is the availability evidence.

Both downloaded ZIPs also match the sizes and SHA-256 values published in the public
`release.json`: Portable
`2778f01ed4012e7717fcae8153c5778b3bca18ac559c25faf1aae7a21ac0b549`
and Plugin+
`8704758503fad9b9fce582ce93594aa080b75f24a17ae4802e0baf04fe07ccb7`.

Finally, AetherDesk commit `c37aa99` linked the public status record to the verified
control-plane bridge. Pages and Linux CI passed, and the fresh public record reports
bridge commit `5cba287`, bridge CI `passed`, the expected packet ID, and SHA-256
`411c41a0761f8768db2ce84797cc911473d19379fea4af3959e739dedb169334`.

## Portable-release boundary

The public AetherDesk Portable v0.1.0 ZIP was downloaded and inspected directly rather
than inferred from its CTA. It contains 212 files and includes `aetherdesk/server.js`,
but it does **not** contain the `/api/aetherbrowser/kernel/status` route or the browser-
kernel proxy added by the verified bridge commits. The downloadable ZIP therefore
predates today's bridge and is not yet the kernel's delivery vehicle.

AetherDesk commit `7cb90be` makes that boundary machine-readable. The public status now
sets `portable_release_contains_bridge=false`, `portable_update="pending"`, and tells
installed users to run source at or after bridge commit `5cba287`. The browser room's
delivery state is `source_ready_portable_update_pending`; `llms.txt` carries the same
warning for agents. GitHub Pages deployed the correction successfully and its Linux CI
run passed. A fresh public fetch returned HTTP 200, `live_public_runtime=false`, sales disabled, and SHA-256
`07a03c895c7fa044155fa7e5db92ce715c6ac1a185cb35e782e8994a3e5d93d9`.

This preserves the portal's useful role without making it a false storefront: it can
explain, quote, and route to verified source today, while checkout, entitlement, remote
writes, and the not-yet-rebuilt Portable delivery remain off.

A fresh cross-resource check also joined `offers.json`, `rooms.json`, and
`kernel-status.json`: the browser room's recommended `operator` offer exists; delivery
is pending in both room and status records; selling and checkout are false everywhere;
and the remote-write boundary is `denied` everywhere. All five consistency assertions
passed against the deployed files.
