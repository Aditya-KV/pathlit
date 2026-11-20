"""`python -m pathlit` runs the friendly command line (see pathlit/cli.py)."""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
