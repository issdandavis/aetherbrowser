# Kaggle offline validation — 2026-08-14

Private kernel: `issacizrealdavis/aetherbrowser-kernel-validation`, version 3.
Private dataset: `issacizrealdavis/aetherbrowser-kernel-packet`.

At final inventory, the authenticated dataset status was `ready` and its unauthenticated
API view returned HTTP 403, independently confirming that the Kaggle packet remains
private. The Hugging Face evidence mirror is public and secret-free; the two services
therefore have deliberately different visibility.

The run used Kaggle CPU only, with internet, GPU, TPU, competition sources, and
competition submission all disabled. Kaggle auto-expanded the uploaded ZIP, so
the validator located the packet by the expected `packet_id` rather than trusting
a mount-directory name. It then verified every file named by the inner manifest.

| Check | Result |
|---|---:|
| Packet ID | `ea756662fa7f6c490b48f2d183e605a022a5609711e07ccddcd6f697282d531d` |
| Manifest files | 21 / 21 hash-valid |
| Kernel unit suite | pass |
| Headless HTTP contract | pass |
| Smoke suite | pass |
| Conveyor cycle | pass |
| Overall | **PASS** |

The downloaded machine-readable receipt is mirrored with the public, secret-free
release evidence on Hugging Face. Versions 1 and 2 are retained as audit history: version 1 assumed the
ZIP remained intact; version 2 still assumed one mount directory. Version 3
removed both platform-layout assumptions while retaining content verification.

The successful v3 logic is also tracked at AetherBrowser commit `c6a481b` in
`deploy/kaggle/validate_kernel.py` with its private kernel metadata. Local discovery
tests cover a nested auto-extracted packet, a nested intact ZIP, ambiguous duplicate
manifests, mixed transports, and archive traversal; the last three fail closed.
