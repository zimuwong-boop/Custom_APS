"""Consistent online backup; restore is explicit and requires the service stopped."""

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("source", type=Path)
parser.add_argument("destination", type=Path)
args = parser.parse_args()
if not args.source.is_file() or args.destination.exists():
    parser.error("Source must exist and destination must not already exist.")
args.destination.parent.mkdir(parents=True, exist_ok=True)
with closing(sqlite3.connect(f"file:{args.source.resolve()}?mode=ro", uri=True)) as source:
    if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        parser.error("Source database failed integrity_check.")
    with closing(sqlite3.connect(args.destination)) as destination:
        source.backup(destination)
print(f"Backup verified: {args.destination}")
