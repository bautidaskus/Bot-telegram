from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

from tests.test_database import EXPECTED_TABLES


def test_alembic_upgrade_head_creates_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "migrated.db"
    env = os.environ | {"DB_PATH": str(db_path)}

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert set(inspect(create_engine(f"sqlite:///{db_path.as_posix()}")).get_table_names()) == (
        EXPECTED_TABLES | {"alembic_version"}
    )

    check_result = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )
    assert check_result.returncode == 0, check_result.stdout + check_result.stderr
