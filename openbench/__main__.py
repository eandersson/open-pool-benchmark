"""Enable `python -m openbench`."""

import sys

from openbench import cli

if __name__ == "__main__":
    sys.exit(cli.main())
