import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root

from . import agent  # noqa: E402,F401
