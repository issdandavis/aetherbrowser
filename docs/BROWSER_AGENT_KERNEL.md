# AetherBrowser transaction kernel

The kernel is the narrow execution seam shared by AetherBrowser, AetherDesk,
Clay, SCBE governance, and bounded cloud runners.

```text
website / operator / Clay
          |
          v
 AetherDesk fixed routes
          |
          v
 observe -> plan -> approve -> dispatch -> verify -> receipt
          |
          v
 AetherBrowser page driver
```

It is not a generic shell and page text is never treated as a command.  The
caller publishes a page observation, proposes one fixed operation, and returns
a post-action observation.  The kernel hashes observations, holds state changes
for approval, rejects stale plans, verifies visible outcomes, and appends each
transition to a SHA-256 receipt chain.

## Fixed operations

- Read-only: `capture`, `read_page`, `highlight`, `scroll`, `done`, `refuse`
- Held for approval: `navigate`, `click`, `fill`
- Denied by default: arbitrary JavaScript, shell commands, credential entry,
  payment, publish, submit, deploy, transfer, and delete flows

Entered text is kept only in process memory.  Persistent state records its
length and SHA-256 digest, so a process restart expires a pending fill instead
of replaying it.

## Save model

- 24 rotating autosaves for observations
- 8 rotating verified-action checkpoints
- named saves for deliberate handoff points
- `champion` and `rollback` namespaces for operator-selected states

These save kernel metadata, not an assertion that an external website can be
rolled back.  A failed action recommends rollback to the last known kernel
state while the page itself must be inspected and repaired explicitly.

## Service roles

- AetherDesk: local control plane and fixed proxy routes
- AetherBrowser: browser body and transaction kernel
- Clay: reasoning/teaching policy; proposes actions but does not bypass gates
- SCBE: governance and verification research; optional evidence, not a magical
  override of deterministic checks
- Lightning Free Studio: sustained CPU tests and common-basis evaluation
- Lightning Sandbox: short clean-room portability test only
- GitHub: source, CI, and immutable commit identity
- Hugging Face: model and packet mirror
- Kaggle: isolated notebook validation; never a competition submission here
- Website: customer portal, entitlement/tool routing, and verified evidence

No service is used merely because it is available.  Each lane has one job and
all lanes consume the same content-addressed packet.

## Local verification

```powershell
python tests\kernel_unit.py
python tests\headless_contract.py
python tests\smoke.py
python scripts\kernel_conveyor.py --once
python scripts\build_kernel_packet.py
python scripts\lightning_kernel_smoke.py --dry-run
```

The conveyor writes one JSON finding per interval and never modifies source.
The packet builder writes a deterministic zip plus an external manifest under
`dist/`; those artifacts are ignored by git and are what remote lanes verify.
