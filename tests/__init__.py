"""Load the plugin under a test name so its relative imports resolve.

The plugin is a package at the repository root; Hermes loads it under a
synthetic name. Tests do the same thing, once, so ``from imprint_plugin import
arcs`` behaves exactly as it does at runtime.
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "imprint_plugin"

if PACKAGE not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        PACKAGE, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)
