"""Validate first, then atomically restore a stopped application's SQLite database."""

import argparse
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("backup", type=Path)
parser.add_argument("destination", type=Path)
parser.add_argument("--service-stopped", action="store_true", required=True)
args = parser.parse_args()
if not args.backup.is_file() or args.backup.resolve() == args.destination.resolve():
    parser.error("Backup must exist and differ from the destination.")
try:
    with closing(sqlite3.connect(f"file:{args.backup.resolve()}?mode=ro", uri=True)) as source:
        if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            parser.error("Backup failed integrity_check.")
        if source.execute("SELECT schema_version FROM aps_systemstate WHERE id=1").fetchone() != (
            1,
        ):
            parser.error("Incompatible APS schema version.")
        migrations = source.execute("SELECT name FROM django_migrations WHERE app='aps'").fetchall()
        expected_migrations = {
            path.stem
            for path in (Path(__file__).resolve().parent.parent / "aps/migrations").glob(
                "[0-9]*.py"
            )
        }
        if {name for (name,) in migrations} != expected_migrations:
            parser.error("Backup migration set does not match this application version.")
        backup_epoch, backup_revision = source.execute(
            "SELECT dataset_epoch, data_revision FROM aps_systemstate WHERE id=1"
        ).fetchone()
        backup_sequences = dict(source.execute("SELECT name, next_value FROM aps_numbersequence"))
except sqlite3.DatabaseError as error:
    parser.error(f"Invalid backup: {error}")
args.destination.parent.mkdir(parents=True, exist_ok=True)
preserved = None
old_epoch, old_revision, old_sequences = 0, 0, {}
if args.destination.exists():
    preserved = args.destination.with_name(args.destination.name + ".before-restore")
    if preserved.exists():
        parser.error("Prior restore safety backup exists; move it before restoring again.")
    # SQLite's backup API includes any outstanding WAL content in the safety copy.
    with closing(sqlite3.connect(f"file:{args.destination.resolve()}?mode=ro", uri=True)) as old:
        old_epoch, old_revision = old.execute(
            "SELECT dataset_epoch, data_revision FROM aps_systemstate WHERE id=1"
        ).fetchone()
        old_sequences = dict(old.execute("SELECT name, next_value FROM aps_numbersequence"))
        with closing(sqlite3.connect(preserved)) as safety:
            old.backup(safety)
with tempfile.NamedTemporaryFile(
    dir=args.destination.parent, prefix=".aps-restore-", delete=False
) as temporary:
    staging = Path(temporary.name)
try:
    shutil.copyfile(args.backup, staging)
    os.chmod(staging, 0o600)
    with closing(sqlite3.connect(staging)) as restored, restored:
        epoch, revision = max(old_epoch, backup_epoch) + 1, max(old_revision, backup_revision) + 1
        restored.execute(
            "UPDATE aps_systemstate SET dataset_epoch=?, "
            "data_revision=?, active_plan_id=NULL WHERE id=1",
            (epoch, revision),
        )
        restored.execute(
            "UPDATE aps_planrun SET status='SUPERSEDED', version=version+1 WHERE status='DRAFT'"
        )
        restored.execute("DELETE FROM aps_idempotencyrequest")
        for name in old_sequences.keys() | backup_sequences.keys():
            value = max(old_sequences.get(name, 1), backup_sequences.get(name, 1))
            restored.execute(
                "INSERT INTO aps_numbersequence(name,next_value) VALUES (?,?) "
                "ON CONFLICT(name) DO UPDATE SET next_value=excluded.next_value",
                (name, value),
            )
        restored.execute(
            "INSERT INTO aps_auditevent(event_type,entity_type,entity_id_text,before_json,"
            "after_json,affected_entities_json,reason,request_id,dataset_epoch,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "RESTORE",
                "system",
                "1",
                json.dumps({"backup_epoch": backup_epoch, "previous_epoch": old_epoch}),
                json.dumps({"dataset_epoch": epoch}),
                "[]",
                "Restore validated backup",
                str(uuid.uuid4()),
                epoch,
                datetime.now(UTC).isoformat(),
            ),
        )
    with staging.open("rb") as stream:
        os.fsync(stream.fileno())
    for suffix in ["-wal", "-shm", "-journal"]:
        args.destination.with_name(args.destination.name + suffix).unlink(missing_ok=True)
    os.replace(staging, args.destination)
finally:
    staging.unlink(missing_ok=True)
print(f"Restored {args.destination}; previous database retained at {preserved}.")
