"""Read-only bridge to the vendored Bumao Core kernel.

The kernel is not a Python package, so it is loaded by inserting its directory
into ``sys.path``. This module resolves the vendored location and imports the
three modules a host needs: ``engine``, ``gate_registry`` and
``bumao_core_gates``.

The kernel tree is referenced read-only. Nothing in this project writes to it.
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KERNEL_DIR = os.path.join(PROJECT_ROOT, "kernel", "bumao_core")

SURFACE_NAMES = (
    "configure",
    "register",
    "set_expected",
    "verify_registration",
    "main",
    "cmd_check",
    "cmd_whoami",
)


def core_dir():
    """Return the absolute vendored kernel directory containing engine.py."""
    if not os.path.isdir(KERNEL_DIR):
        raise RuntimeError("Vendored kernel is missing: %s" % KERNEL_DIR)
    return os.path.abspath(KERNEL_DIR)


def load():
    """Import and return ``(engine, gate_registry, bumao_core_gates)``."""
    # Keep the vendored kernel tree untouched: no .pyc files are written.
    sys.dont_write_bytecode = True
    path = core_dir()
    if path not in sys.path:
        sys.path.insert(0, path)
    import engine
    import gate_registry
    import bumao_core_gates
    return engine, gate_registry, bumao_core_gates


def surface(core_module):
    """Report which real kernel entry points are present, without guessing."""
    return {name: hasattr(core_module, name) for name in SURFACE_NAMES}
