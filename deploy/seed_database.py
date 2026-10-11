"""Only initialize a fresh deployment volume from the verified demo baseline."""

import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

source_path = Path("/opt/deploy/demo-initial.sqlite3")
destination = Path("/data/aps.sqlite3")
if destination.exists():
    print("Existing demo database preserved.")
else:
    with closing(sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)) as source:
        assert source.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        expected = {p.stem for p in Path("/app/aps/migrations").glob("[0-9]*.py")}
        actual = {
            r[0] for r in source.execute("SELECT name FROM django_migrations WHERE app='aps'")
        }
        assert expected == actual, "Demo database migration version does not match image."
        assert source.execute("SELECT COUNT(*) FROM aps_productionorder").fetchone()[0] == 0
        assert (
            source.execute(
                "SELECT COUNT(*) FROM aps_salesorder WHERE status='CONFIRMED'"
            ).fetchone()[0]
            == 20
        )
        fd, name = tempfile.mkstemp(prefix=".demo-seed-", dir=destination.parent)
        os.close(fd)
        staged = Path(name)
        try:
            with closing(sqlite3.connect(staged)) as target:
                source.backup(target)
            staged.chmod(0o600)
            os.replace(staged, destination)
        finally:
            staged.unlink(missing_ok=True)
    print("Initial demo loaded: 11 items, 5 BOMs, 20 confirmed sales; no production orders.")
