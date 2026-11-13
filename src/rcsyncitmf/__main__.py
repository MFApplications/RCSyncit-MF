"""Entry point for `python -m rcsyncitmf` and the `rcsyncitmf` console script."""

from __future__ import annotations

import sys

from .application import RCSyncitMFApplication


def main() -> int:
    app = RCSyncitMFApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
