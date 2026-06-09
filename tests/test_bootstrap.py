from __future__ import annotations

import sys

import src


def test_project_uses_supported_python_and_imports_package() -> None:
    assert sys.version_info >= (3, 11)
    assert src.__doc__ == "Personal Tracker Bot."
