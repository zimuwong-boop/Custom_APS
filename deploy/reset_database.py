"""Restore initial demo offline, retaining a timestamped safety backup and numbering."""

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

backup_dir = Path("/data/backups")
backup_dir.mkdir(exist_ok=True)
stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
safety = Path("/data/aps.sqlite3.before-restore")
if safety.exists():
    os.replace(safety, backup_dir / f"previous-before-restore-{stamp}.sqlite3")
subprocess.run(
    [
        sys.executable,
        "/app/scripts/restore_sqlite.py",
        "/opt/deploy/demo-initial.sqlite3",
        "/data/aps.sqlite3",
        "--service-stopped",
    ],
    check=True,
)
if safety.exists():
    os.replace(safety, backup_dir / f"before-reset-{stamp}.sqlite3")
subprocess.run(
    [
        sys.executable,
        "/app/manage.py",
        "shell",
        "-c",
        """from django.db import transaction
from aps.planning import recalculate
from aps.models import AuditEvent, SystemState
from aps.serializers import serialize
with transaction.atomic():
    plan = recalculate()
    AuditEvent.objects.create(
        event_type="DEMO_RECALCULATE", entity_type="plans",
        entity_id_text=str(plan.id), after_json=serialize(plan),
        dataset_epoch=SystemState.objects.get(pk=1).dataset_epoch,
    )
""",
    ],
    check=True,
)
subprocess.run([sys.executable, "/app/manage.py", "check_demo_integrity"], check=True)
print("Initial demo restored; previous data retained in /data/backups.")
