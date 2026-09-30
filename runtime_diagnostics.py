from __future__ import annotations

import importlib.util
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any


def _playwright_node_path() -> Path | None:
    module = importlib.util.find_spec("playwright")
    if module is None or not module.submodule_search_locations:
        return None
    return Path(next(iter(module.submodule_search_locations))) / "driver" / "node"


def _file_description(path: Path | None) -> str:
    if path is None or not path.exists():
        return "ikke fundet"
    try:
        result = subprocess.run(
            ["/usr/bin/file", str(path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "kunne ikke aflæses"
    return result.stdout.strip() or "ukendt"


def collect_runtime_diagnostics() -> dict[str, Any]:
    node_path = _playwright_node_path()
    return {
        "python": sys.executable,
        "python_version": platform.python_version(),
        "machine": platform.machine(),
        "system": platform.system(),
        "playwright_node": str(node_path) if node_path else "ikke fundet",
        "playwright_node_architecture": _file_description(node_path),
    }
