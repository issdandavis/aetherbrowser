"""Root conftest — ensure the project root is on sys.path so that
``from src.aetherbrowser…`` and ``from src.extension…`` imports resolve
without requiring ``pip install -e .``."""

import pathlib
import sys

_PROJECT_ROOT = str(pathlib.Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
