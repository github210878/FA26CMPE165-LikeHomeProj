"""
Ensures backend/ (which contains the app/ package) is on sys.path when
pytest is invoked with a working directory of tests/ itself — this happens
with some test runners (e.g. PyCharm's), which don't always honor the
`pythonpath` setting in pytest.ini the way plain `pytest` does.
"""

import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
