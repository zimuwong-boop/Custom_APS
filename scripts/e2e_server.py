"""Run browser integration tests against a disposable database, never the local business DB."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory(prefix="aps-e2e-") as directory:
    env = {
        **os.environ,
        "DATABASE_PATH": str(Path(directory) / "test.sqlite3"),
        "DEBUG": "1",
        "CSRF_TRUSTED_ORIGINS": "http://127.0.0.1:15173",
    }
    for command in [("migrate", "--noinput"), ("init_system",)]:
        subprocess.run(
            [sys.executable, str(ROOT / "manage.py"), *command], cwd=ROOT, env=env, check=True
        )
    subprocess.run(
        [sys.executable, str(ROOT / "manage.py"), "runserver", "127.0.0.1:18081", "--noreload"],
        cwd=ROOT,
        env=env,
        check=True,
    )
