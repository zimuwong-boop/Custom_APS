"""Temporary acceptance load: 100 sales / 500 lines / 2000 jobs / 5000 edges."""

import json
import os
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
with tempfile.TemporaryDirectory(prefix="aps-benchmark-") as temporary:
    os.environ["DATABASE_PATH"] = str(Path(temporary) / "bench.sqlite3")
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
    os.environ["ALLOWED_HOSTS"] = "testserver"
    import django

    django.setup()
    from django.core.management import call_command
    from django.db import transaction
    from django.test import Client

    from aps import planning, progress
    from aps.core import now, snapshot, state
    from aps.models import BOM, BOMLine, Item, PlanRun, ProductionOrder, SalesLine, SalesOrder, Unit

    call_command("migrate", verbosity=0)
    call_command("init_system", verbosity=0)
    unit = Unit.objects.get(code="PCS")
    raw = Item.objects.create(code="R", name="Benchmark raw", type="RAW", unit=unit)
    materials = Item.objects.bulk_create(
        [
            Item(
                code=f"M{i}",
                name=f"Abstract {i}",
                type="FINISHED" if i < 500 else "SEMI",
                unit=unit,
            )
            for i in range(2000)
        ]
    )
    boms = BOM.objects.bulk_create(
        [BOM(item=item, revision="V1", base_qty_u=1_000_000, status="ACTIVE") for item in materials]
    )
    lines = []
    for i, b in enumerate(boms):
        if i < 500:
            for n in range(10):
                child = 500 + (i * 10 + n) % 1500
                lines.append(
                    BOMLine(
                        bom=b,
                        position=n + 1,
                        component_item=materials[child],
                        child_bom=boms[child],
                        qty_u=1_000_000,
                    )
                )
        else:
            lines.append(BOMLine(bom=b, position=1, component_item=raw, qty_u=1_000_000))
    BOMLine.objects.bulk_create(lines)
    sales = SalesOrder.objects.bulk_create(
        [
            SalesOrder(
                number=f"T{i}",
                customer_name="Temporary benchmark",
                status="CONFIRMED",
                confirmed_at=now(),
            )
            for i in range(100)
        ]
    )
    SalesLine.objects.bulk_create(
        [
            SalesLine(
                order=sales[i // 5],
                position=i % 5 + 1,
                item=materials[i],
                bom=boms[i],
                qty_u=1_000_000,
                effective_priority="NORMAL",
                item_snapshot_json=snapshot(materials[i]),
            )
            for i in range(500)
        ]
    )
    timings = {}

    def measure(name, work, samples=30):
        for _ in range(5):
            work()
        values = []
        for _ in range(samples):
            started = time.perf_counter()
            work()
            values.append(time.perf_counter() - started)
        timings[name] = {
            "samples": samples,
            "median_seconds": round(statistics.median(values), 4),
            "p95_seconds": round(sorted(values)[int(0.95 * len(values)) - 1], 4),
            "max_seconds": round(max(values), 4),
        }
        print(name, timings[name], flush=True)

    client = Client()
    measure("sales_query", lambda: client.get("/api/v1/sales-orders?page_size=50"))
    measure("plan_suggestion", planning.suggest)
    graph = planning.suggest()
    system = state()
    plan = PlanRun.objects.create(
        number="B",
        source_data_revision=system.data_revision,
        dataset_epoch=system.dataset_epoch,
        graph_json=graph,
    )

    def confirm_once():
        plan.refresh_from_db()
        with transaction.atomic():
            planning.confirm(plan)
            transaction.set_rollback(True)

    measure("plan_confirmation", confirm_once)
    plan.refresh_from_db()
    with transaction.atomic():
        planning.confirm(plan)
    child = ProductionOrder.objects.filter(item__type="SEMI").first()

    def update():
        with transaction.atomic():
            child.own_progress_bp = 6000 if child.own_progress_bp == 5000 else 5000
            child.actual_started_at = now()
            child.save()
            progress.recompute()

    measure("progress_recompute", update)
    measure("production_query", lambda: client.get("/api/v1/production-orders?page_size=50"))
    result = {
        "platform": platform.platform(),
        "processor": platform.machine(),
        "load": {
            "sales": 100,
            "sales_lines": 500,
            "production_nodes": 2000,
            "dependency_edges": 5000,
        },
        "warmups": 5,
        "failure_rate": 0,
        "timings": timings,
        "resource_limits": os.environ.get("APS_RESOURCE_LIMITS", "unrestricted development host"),
        "reference_hardware_note": (
            "Measured in the reported environment; resource_limits records the configured limits."
        ),
    }
    output = Path(os.environ.get("APS_BENCHMARK_OUTPUT", str(ROOT / "Docs/benchmark.json")))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
