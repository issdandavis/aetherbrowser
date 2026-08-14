# Kaggle offline validation — 2026-08-14

Private kernel: `issacizrealdavis/aetherbrowser-kernel-validation`, version 3.
Private dataset: `issacizrealdavis/aetherbrowser-kernel-packet`.

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

The downloaded machine-readable receipt is mirrored privately with the release
evidence. Versions 1 and 2 are retained as audit history: version 1 assumed the
ZIP remained intact; version 2 still assumed one mount directory. Version 3
removed both platform-layout assumptions while retaining content verification.
