"""Alternativă la `python -m server`: `python server/run.py [comandă]`."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
