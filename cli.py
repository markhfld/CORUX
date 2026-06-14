"""Convenience entrypoint:  python cli.py <input.json> [--literature]

Equivalent to `python -m corux ...`.
"""

import sys

from corux.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
