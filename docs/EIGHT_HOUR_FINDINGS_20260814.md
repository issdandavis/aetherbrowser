# Eight-hour browser-kernel findings — 2026-08-14

Session window: 07:02–15:02 UTC, followed by one post-window cleanup cycle. These
are elapsed-hour findings tied to executable evidence; they are not eight rapid runs
relabeled as hours.

## Hour 1 — 07:02–08:02 UTC: find the real seams

**Finding:** AetherDesk, AetherBrowser, SCBE, Clay, and the cloud services should not
be collapsed into one process. The stable join is a transaction contract: the website
discovers/routes, AetherDesk displays and approves, AetherBrowser executes, SCBE
governs, and external services keep source, evidence, or bounded compute.

**Boundary fixed before implementation:** remote writes and secret-bearing actions are
denied by default; a browser action requires an observation; raw page text and fill
values must not enter durable state.

## Hour 2 — 08:02–09:02 UTC: implement the transaction kernel

**Finding:** the usable kernel is the explicit cycle
`observe -> plan -> approve -> dispatch -> verify -> receipt`, not another free-form
browser wrapper. Plans bind to a hashed observation so a changed page becomes stale.
Navigation query/fragment values are represented by digests, fill values are ephemeral,
and unknown actions fail closed.

**Implementation:** `src/aetherbrowser/kernel.py` and the HTTP routes in
`src/aetherbrowser/serve.py`.

## Hour 3 — 09:02–10:02 UTC: saves and negative-path tests are load-bearing

**Finding:** the game-console save model transfers cleanly. Autosaves are a bounded
24-slot ring, checkpoints are an independent bounded 8-slot stack, and named/champion
saves plus rollback remain separate. A failed verification recommends rollback rather
than silently continuing.

**Evidence:** 14/14 kernel unit checks and 27/27 headless HTTP contract checks cover
unknown operations, private navigation, missing observations, stale plans, failed
verification, secret persistence, save bounds, approval holds, and receipt tampering.

## Hour 4 — 10:02–11:02 UTC: content address beats platform assumptions

**Finding:** a cloud run is evidence only when the exact packet comes back identifiable.
The release contains 21 manifest-named files, packet ID
`ea756662fa7f6c490b48f2d183e605a022a5609711e07ccddcd6f697282d531d`,
and transport SHA-256
`8088bc6f038a5a3f9e67416fe2aefae982ff951ee0d8938d615848913f52c598`.

**Evidence:** a disposable Lightning Sandbox on Python 3.13.1 reproduced 14/14 unit
and 27/27 HTTP checks, then was deleted with running count zero. GitHub holds source;
the public, secret-free Hugging Face dataset holds the packet, manifest, and sanitized
receipt; all were downloaded back and hash-matched. An unauthenticated audit later
confirmed public access, 0 secret-shaped files across the downloaded release, and the
same packet SHA-256.

## Hour 5 — 11:02–12:02 UTC: federation works when each service has one job

**Finding:** Kaggle auto-expands ZIP datasets and does not guarantee one historical
mount path. Version 3 discovered the packet by its inner ID, verified all 21 manifest
files, and passed unit, HTTP, smoke, and conveyor checks on private offline CPU. No
competition source, submission, GPU, TPU, or internet was used.

Clay's two candidate checkpoints were also compared on one cold, paired basis rather
than their incompatible native vocabularies: run4 beat run3 by `-0.25692` bits/character
(95% `[-0.27976,-0.23407]`) and `+0.00573` next-character accuracy
(95% `[+0.00329,+0.00817]`). This selects a character-form parent, not a general teacher.

The teaching-corpus gate then found 167 duplicate rows in a 240-row default corpus.
Audience-grounded, split-disjoint variants rebuilt it to 240/240 unique train prompts
and 48/48 unique holdout prompts, zero overlap, with all 288 tool receipts verified.

The public AetherMoore portal now exposes the verified browser route and a price-book-
matched offer catalog. It can quote and route the $99 Operator Pack, while sale,
checkout, and entitlement authority remain explicitly false. Pages and Linux CI pass.

## Hour 6 — 12:02–13:02 UTC

**Finding:** a pass is more useful when it survives time rather than being rerun in a
tight loop. The first hourly conveyor checkpoint finished at `12:15:43Z`: compile,
14/14 kernel, 27/27 HTTP, and 5/5 smoke checks all passed. Its 13-file source
fingerprint was
`7bb2b3d48a62b3400afe7882ce02beb4acca9f2908d2c9f304b509220fa0f174`,
identical to the initial `11:15:44Z` checkpoint.

The Kaggle notebook logic was also moved into tracked source at commit `c6a481b`.
Discovery accepts one intact ZIP or one matching auto-extracted packet, rejects mixed
or ambiguous mounts, and rejects archive traversal before extraction. This makes the
successful v3 validation repeatable instead of leaving it as a platform-side artifact.

## Hour 7 — 13:02–14:02 UTC

**Finding:** the website needs two different doors: a public evidence door and a local
execution door. Both plausible public `/api/.../status` paths returned 404 because
GitHub Pages is static. Commit `3b8773b` therefore published
`/AetherDesk/kernel-status.json` while keeping the loopback route labeled
`local_launch`. The public file returns HTTP 200 and explicitly says
`live_public_runtime=false`, remote writes denied, and selling disabled.

The second hourly conveyor checkpoint finished at `13:15:44Z` with the same four green
gates and the same source fingerprint. AetherDesk Linux CI and Pages deployment for the
public doorway both passed.

## Hour 8 — 14:02–15:02 UTC

**Finding:** the portal is only a bridge when an installed AetherDesk can traverse it.
Commit `96df8ea` added the allowlisted proxy and corrected backend startup to use the
AetherBrowser root. An isolated end-to-end run traversed AetherDesk into AetherBrowser:
`capture` moved `ready -> dispatched -> verified`, the receipt chain remained valid,
and “Delete account” was denied as a remote-write operation. Both temporary processes
were confirmed stopped.

The already-running local AetherDesk PID 7860 predates this bridge (started
`06:39:58Z`) and still returns HTTP 404 for the new route. It was intentionally not
restarted because that process was launched in the earlier credential-bearing sandbox
session. The committed/installable source is ready; activating it is a later clean
restart, not something to disguise as already live.

Linux then caught a test-only separator assumption: POSIX `path.basename()` does not
parse a Windows backslash path. Commit `5cba287` made the assertion separator-neutral;
the focused 168-test gate, full 293-test/build gate, and fresh GitHub CI all passed.

The third hourly soak checkpoint finished at `14:15:43Z`. Across all four checkpoints
(`11:15:44Z`, `12:15:43Z`, `13:15:44Z`, `14:15:43Z`), all four gates passed and the
source fingerprint stayed
`7bb2b3d48a62b3400afe7882ce02beb4acca9f2908d2c9f304b509220fa0f174`.

The final portal check caught a delivery-boundary error before it became a sales claim.
The current public Portable v0.1.0 contains 212 files and `aetherdesk/server.js`, but not
the new kernel status route or proxy. AetherDesk commit `7cb90be` now exposes
`portable_release_contains_bridge=false`, `portable_update=pending`, and
`source_ready_portable_update_pending` on the deployed website. Pages, Linux CI, and a
fresh public fetch all passed. The portal can explain, quote, and route to verified
source; it cannot yet sell, grant entitlement, or claim that the old ZIP delivers the
bridge.

## Post-window cleanup checkpoint

The scheduled fifth conveyor report finished at `15:15:44Z`. All 5/5 reports passed,
all 20/20 fixed gate executions returned zero, and all five reports carried the same
13-file source fingerprint:
`7bb2b3d48a62b3400afe7882ce02beb4acca9f2908d2c9f304b509220fa0f174`.
PID 31760 then exited on its own.

Final compute inventory found no process from the conveyor, Lightning Sandbox smoke,
or isolated bridge test. Ports 15718, 18002, and 5718 were closed. The only relevant
listener was the intentionally retained local AetherDesk PID 7860 on 5717; it is local,
not billable cloud compute, and belongs to the earlier session. AetherDesk's sanitized
controller reported `active_run=null` and exposed no key value. Kaggle's validator was
`COMPLETE`, its private dataset was `ready`, and both final AetherDesk GitHub workflows
were successful.

The Hugging Face visibility audit corrected an earlier label: its evidence dataset is
public, not private. An unauthenticated download succeeded; the packet ZIP hash matched;
and a downloaded-tree scan found zero secret-shaped files. A tracked dataset card now
states those boundaries. The 284,083-byte audit copy was content-sealed and moved to the
reversible staged-deletion lane. Its purge was not forced because the purge tool parsed
the UTC receipt as local time and deferred eligibility by seven hours; batch
`20260814T144944151Z-6ebd4bc1` records the exact recoverable state.

This is deliberately labeled post-window rather than counted as a ninth hourly finding.
