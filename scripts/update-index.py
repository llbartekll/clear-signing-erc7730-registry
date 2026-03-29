#!/usr/bin/env python3
"""Legacy wrapper for index generation.

The V3 split index is now owned exclusively by `generate-index-v2.py`.
This wrapper exists only to fail loudly for any old automation still calling it.
"""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "update-index.py is retired. Use scripts/generate-index-v2.py to regenerate "
        "index.json, index.calldata.json, and index.eip712.json.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
