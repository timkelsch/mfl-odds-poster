"""Make the lambda handler modules importable from the unit tests."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for sub in ("lambda/gather_odds", "lambda/post_odds"):
    path = str(ROOT / sub)
    if path not in sys.path:
        sys.path.insert(0, path)
