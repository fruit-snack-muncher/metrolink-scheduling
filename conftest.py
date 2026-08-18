"""
Makes the project root importable from inside tests/, so that test modules can
`import optimization_setup` without the package having to be installed.

pytest already prepends the directory holding the rootdir conftest.py to
sys.path, but doing it explicitly keeps the suite runnable no matter which
directory pytest is invoked from.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
