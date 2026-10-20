#!/usr/bin/env python3
"""Create an explicit fixed runtime without changing an installation or session."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from loop_work.runtime import main

if __name__ == '__main__':
    raise SystemExit(main())
