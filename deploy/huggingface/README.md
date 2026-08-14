---
pretty_name: AetherBrowser Kernel Evidence Packet
tags:
  - browser-agents
  - reproducibility
  - verification
  - governance
---

# AetherBrowser kernel evidence packet

This public dataset is a content-addressed, secret-free evidence mirror for the
AetherBrowser transaction kernel. It is not a training dataset, hosted inference
service, credential store, or competition submission.

The kernel constrains browser work to:

`observe -> plan -> approve -> dispatch -> verify -> receipt`

Raw page text, fill values, and credentials are excluded from durable state. Unknown
operations and remote-write flows fail closed. The save model keeps a 24-slot autosave
ring, an independent 8-slot checkpoint stack, named saves, and separate champion and
rollback states.

## Content identity

- Packet ID: `ea756662fa7f6c490b48f2d183e605a022a5609711e07ccddcd6f697282d531d`
- ZIP SHA-256: `8088bc6f038a5a3f9e67416fe2aefae982ff951ee0d8938d615848913f52c598`
- Manifest-named files: 21
- Source: <https://github.com/issdandavis/aetherbrowser>
- Public portal: <https://aethermoore.com/AetherDesk/>

## Verification

- Local: 14/14 kernel, 27/27 HTTP contract, 5/5 smoke
- Lightning Python 3.13 clean room: passed, disposable Sandbox deleted
- Kaggle private offline CPU validator: passed and terminated
- Public-mirror audit: unauthenticated download succeeded; zero secret-shaped files;
  downloaded ZIP hash matched the value above

The AetherDesk source bridge is verified, but public Portable v0.1.0 predates it. The
portal therefore reports `source_ready_portable_update_pending`; checkout, entitlement,
public live runtime, and remote writes remain disabled.

No license is asserted by this evidence card. Consult the source repository before
redistribution or reuse.
