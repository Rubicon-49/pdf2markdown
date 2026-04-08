"""
utils.py — Shared utility helpers for pdf2markdown.
"""

from pathlib import Path


def find_project_root(anchor: Path = Path(__file__)) -> Path:
    """Walk up the directory tree to find the project root.

    The root is identified as the first directory that contains a
    ``pyproject.toml`` file.

    Args:
        anchor: Starting path for the upward search. Defaults to the location
            of this file so callers can use it without arguments.

    Returns:
        Absolute path to the project root directory.

    Raises:
        FileNotFoundError: If no ``pyproject.toml`` is found before reaching
            the filesystem root.
    """
    for directory in [anchor, *anchor.parents]:
        if (directory / "pyproject.toml").exists():
            return directory
    raise FileNotFoundError(
        f"Could not locate pyproject.toml starting from {anchor}"
    )
