from __future__ import annotations

from pathlib import Path


def ensure_private_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass


def protect_existing_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        path.chmod(0o600)
    except OSError:
        pass
