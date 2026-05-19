"""Root pytest conftest.

Adds the project root to ``sys.path`` so that ``tests/test_module2_upi_lookup.py``
can ``import module2_upi_lookup`` regardless of which directory pytest or
``unittest`` is invoked from. Required because ``module2_upi_lookup.py`` lives
at the repository root rather than inside an installable package.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
