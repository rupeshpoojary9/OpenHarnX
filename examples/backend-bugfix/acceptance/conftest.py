"""Load the service under test from FIXTURE_SERVICE_DIR.

The acceptance tests are the protected oracle. They live outside the service
so an agent working in the service cannot change them.
"""

import os
import sys

_dir = os.environ.get("FIXTURE_SERVICE_DIR")
if not _dir:
    raise RuntimeError("set FIXTURE_SERVICE_DIR to the service directory under test")
sys.path.insert(0, _dir)
