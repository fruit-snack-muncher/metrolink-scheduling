"""
Makes src/ importable, so that test modules can `import preformulation` without
the project having to be packaged and installed.

The primary mechanism is `pythonpath = src` in the project's pytest.ini; this
file repeats it as a fallback for invocations that never reach that config, and
so the directory carries its own sys.path setup alongside the modules it
applies to.
"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
