"""`python -P -m obelize.apidiff <root> <module>`: the child process that `surface.read` starts."""

import sys

from obelize.apidiff.worker import main
from obelize.native.limits import limit

limit()
raise SystemExit(main(sys.argv[1:]))
