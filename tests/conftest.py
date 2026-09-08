from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = str(ROOT / "src")

# Developer shells may carry PYTHONPATH from another checkout; tests target this tree.
try:
    sys.path.remove(SRC)
except ValueError:
    pass
sys.path.insert(0, SRC)
