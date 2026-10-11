"""Isolated abstract fixtures; these are not runtime demo datasets."""

import json
import uuid
from fractions import Fraction

import pytest
from django.test import Client

from aps import planning, progress
from aps.core import BusinessError, quantity, state, topo
from aps.models import (
    BOM,
    AuditEvent,
    Item,
    NumberSequence,
    PlanRun,
    ProductionDependency,
    ProductionOrder,
    SalesAllocation,
    SalesOrder,
    SystemState,
    Unit,
)

pytestmark = pytest.mark.django_db


class API:
    def __init__(self, csrf=False):
        self.client = Client(enforce_csrf_checks=csrf)
        self.token = self.client.get("/api/v1/bootstrap").json()["data"]["csrf_token"]

    def call(self, path, method="GET", body=None, status=200, key=None, epoch=None):
        data = {"dataset_epoch": state().dataset_epoch if epoch is None else epoch, **(body or {})}
        response = getattr(self.client, method.lower())(
            "/api/v1/" + path,
            data=json.dumps(data) if method != "GET" else None,
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self.token,
            HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()),
        )
        assert response.status_code == status, response.content
        return response.json().get("data", response.json())

    def post(self, path, body=None, **kwargs):
        return self.call(path, "POST", body, **kwargs)


@pytest.fixture
def api():
    Unit.objects.create(code="PCS", name="个", decimal_places=0)
    Unit.objects.create(code="KG", name="千克", decimal_places=3)
    return API()


def item(api, code, kind, unit="PCS"):
    return api.post(
        "items",
        {"code": code, "name": code, "type": kind, "unit_id": Unit.objects.get(code=unit).id},
        status=201,
    )


def bom(api, owner, components, base="1", revision="V1"):
    b = api.post(
        "boms",
        {
            "item_id": owner["id"],
            "revision": revision,
            "base_quantity": base,
            "lines": [
                {
                    "component_item_id": i["id"],
                    "child_bom_id": b["id"] if b else None,
                    "quantity": q,
                }
                for i, b, q in components
            ],
        },
        status=201,
    )
    return api.post(f"boms/{b['id']}/activate", {"expected_version": b["version"]})


def sale(api, name, lines, priority="NORMAL", confirm=True):
    s = api.post(
        "sales-orders",
        {
            "number": name,
            "customer_name": "Temporary test customer",
            "default_priority": priority,
            "lines": [{"item_id": i["id"], "quantity": q, **extra} for i, q, extra in lines],
        },
        status=201,
    )
    return (
        api.post(f"sales-orders/{s['id']}/confirm", {"expected_version": s["version"]})
        if confirm
        else s
    )


def formal(api):
    p = api.call("plans/current")
    assert p
    api.post(f"plans/{p['id']}/confirm", {"expected_version": p["version"]})
    return list(ProductionOrder.objects.filter(plan_id=p["id"]).order_by("frozen_level"))


def operate(api, order, action, **body):
    order.refresh_from_db()
    return api.post(
        f"production-orders/{order.id}/{action}", {"expected_version": order.version, **body}
    )


def finish(api, order):
    operate(api, order, "start")
    return operate(api, order, "progress", own_progress="100")


@pytest.fixture
def chain(api):
    raw = item(api, "R", "RAW")
    semi = item(api, "S", "SEMI")
    sb = bom(api, semi, [(raw, None, "2")])
    finished = item(api, "F", "FINISHED")
    fb = bom(api, finished, [(semi, sb, "2"), (raw, None, "1")])
    return raw, semi, sb, finished, fb


def test_empty_system_no_demo_data(api):
    assert api.call("items")["total"] == 0
    assert api.call("demo/scenarios") == []
    assert api.call("plans/current") is None
    assert api.call("health/ready") == {"status": "ok"}


def test_confirm_explode_quantity_and_dependency_gate(api, chain):
    raw, semi, sb, finished, _ = chain
    s = sale(api, "T1", [(finished, "3", {})])
    parent, child = formal(api)
    assert parent.planned_qty_u == 3_000_000 and child.planned_qty_u == 6_000_000
    assert child.raw_requirements.get().qty_u == 12_000_000
    assert parent.status == "WAITING" and child.status == "READY"
    api.post(
        f"production-orders/{parent.id}/start", {"expected_version": parent.version}, status=409
    )
    api.post(
        f"production-orders/{parent.id}/progress",
        {"expected_version": parent.version, "own_progress": "20"},
        status=409,
    )
    operate(api, child, "start")
    operate(api, child, "progress", own_progress="60")
    parent.refresh_from_db()
    assert Fraction(int(parent.progress_num), int(parent.progress_den)) == Fraction(36, 100)
    assert api.call(f"sales-orders/{s['id']}")["progress"] == "36.00"
    operate(api, child, "progress", own_progress="100")
    parent.refresh_from_db()
    assert parent.status == "READY" and parent.own_progress_bp == 0
    assert api.call(f"production-orders/{parent.id}")["progress"] == "60.00"
    assert parent.actual_started_at is None
    operate(api, parent, "start")
    operate(api, parent, "progress", own_progress="50")
    assert api.call(f"sales-orders/{s['id']}")["progress"] == "80.00"
    operate(api, parent, "progress", own_progress="100")
    assert api.call(f"sales-orders/{s['id']}")["status"] == "PRODUCTION_COMPLETED"
    assert ProductionDependency.objects.get().usage_confirmed_at
    assert SalesAllocation.objects.get().fulfillment_confirmed_at


def test_shared_semi_and_direct_sales_roots_and_trace(api, chain):
    raw, semi, sb, finished, _ = chain
    pack = item(api, "F2", "FINISHED")
    bom(api, pack, [(semi, sb, "3"), (raw, None, "1")])
    s1 = sale(api, "T1", [(finished, "1", {}), (semi, "1", {})])
    s2 = sale(api, "T2", [(pack, "2", {})])
    orders = formal(api)
    child = next(o for o in orders if o.item_id == semi["id"])
    assert child.planned_qty_u == 9_000_000
    assert child.consumers.count() == 2
    operate(api, child, "start")
    operate(api, child, "progress", own_progress="60")
    assert api.call(f"sales-orders/{s1['id']}")["progress"] == "48.00"
    assert api.call(f"sales-orders/{s2['id']}")["progress"] == "36.00"
    result = api.call(f"trace/batches/{child.batch_number}")
    assert len(result["nodes"]) == 3
    assert {a["sales_order_id"] for a in result["sales_allocations"]} == {s1["id"], s2["id"]}
    assert len(api.call(f"trace/sales-orders/{s2['id']}")["nodes"]) == 2
    assert len({o.batch_number for o in orders}) == 3
    assert "-L01-" in child.batch_number


def test_multiple_children_equal_weights(api):
    r = item(api, "R", "RAW")
    a = item(api, "A", "SEMI")
    ab = bom(api, a, [(r, None, "1")])
    b = item(api, "B", "SEMI")
    bb = bom(api, b, [(r, None, "1")])
    f = item(api, "F", "FINISHED")
    bom(api, f, [(a, ab, "100"), (b, bb, "1")])
    s = sale(api, "T", [(f, "1", {})])
    parent, *children = formal(api)
    for order, amount in zip(children, ["60", "20"], strict=True):
        operate(api, order, "start")
        operate(api, order, "progress", own_progress=amount)
    assert api.call(f"production-orders/{parent.id}")["progress"] == "24.00"
    assert api.call(f"sales-orders/{s['id']}")["progress"] == "24.00"


@pytest.mark.parametrize(
    "weight,expected_status,expected_progress",
    [("0", "READY", "0.00"), ("100", "COMPLETED", "100.00")],
)
def test_weight_extremes(api, chain, weight, expected_status, expected_progress):
    sale(api, "T", [(chain[3], "1", {})])
    p = api.call("plans/current")
    p["graph"]["jobs"][0]["child_weight"] = weight
    api.call(
        f"plans/{p['id']}/graph", "PUT", {"expected_version": p["version"], "graph": p["graph"]}
    )
    parent, child = formal(api)
    assert parent.status == "WAITING"
    finish(api, child)
    parent.refresh_from_db()
    assert parent.status == expected_status
    assert api.call(f"production-orders/{parent.id}")["progress"] == expected_progress
    assert parent.actual_started_at is None


def test_correction_auto_completion_regresses_and_downstream_started_block(api, chain):
    sale(api, "T", [(chain[3], "1", {})])
    p = api.call("plans/current")
    p["graph"]["jobs"][0]["child_weight"] = "100"
    api.call(
        f"plans/{p['id']}/graph", "PUT", {"expected_version": p["version"], "graph": p["graph"]}
    )
    parent, child = formal(api)
    finish(api, child)
    operate(api, child, "correct-progress", own_progress="60", reason="Test correction")
    parent.refresh_from_db()
    assert parent.status == "WAITING" and parent.completed_at is None
    assert ProductionDependency.objects.get().usage_confirmed_at is None
    assert SalesOrder.objects.get().status == "CONFIRMED"
    assert SalesAllocation.objects.get().fulfillment_confirmed_at is None


def test_correction_rejects_started_transitive_consumer(api, chain):
    sale(api, "T", [(chain[3], "1", {})])
    parent, child = formal(api)
    finish(api, child)
    operate(api, parent, "start")
    child.refresh_from_db()
    api.post(
        f"production-orders/{child.id}/correct-progress",
        {"expected_version": child.version, "own_progress": "50", "reason": "test"},
        status=409,
    )
    assert api.call(f"production-orders/{child.id}")["own_progress"] == "100.00"


def test_priority_partition_and_override(api, chain):
    sale(api, "T1", [(chain[3], "1", {})], "HIGH")
    sale(api, "T2", [(chain[3], "2", {"priority_override": "LOW"})], "HIGH")
    orders = formal(api)
    assert len(orders) == 4
    assert {o.priority for o in orders} == {"HIGH", "LOW"}


def test_bom_revision_frozen_and_new_default(api, chain):
    raw, semi, sb, finished, fb = chain
    s1 = sale(api, "T1", [(finished, "1", {})])
    fb2 = bom(api, finished, [(semi, sb, "3")], revision="V2")
    api.post("plans/recalculate", {"expected_data_revision": state().data_revision})
    sale(api, "T2", [(finished, "1", {})])
    orders = formal(api)
    roots = [o for o in orders if o.item_id == finished["id"]]
    assert {o.bom_id for o in roots} == {fb["id"], fb2["id"]}
    assert api.call(f"sales-orders/{s1['id']}")["lines"][0]["bom_id"] == fb["id"]
    api.call(
        f"boms/{fb['id']}",
        "PATCH",
        {"expected_version": BOM.objects.get(pk=fb["id"]).version, "base_quantity": "2"},
        status=409,
    )


def test_rounding_per_consumer_and_no_partial_release(api):
    r = item(api, "R", "RAW")
    a = item(api, "A", "SEMI")
    ab = bom(api, a, [(r, None, "1")])
    f1 = item(api, "F1", "FINISHED")
    bom(api, f1, [(a, ab, "1")], base="3")
    f2 = item(api, "F2", "FINISHED")
    bom(api, f2, [(a, ab, "1")], base="3")
    sale(api, "T1", [(f1, "1", {})])
    sale(api, "T2", [(f2, "1", {})])
    orders = formal(api)
    child = next(o for o in orders if o.item_id == a["id"])
    assert child.planned_qty_u == 2_000_000  # ceil(1/3) + ceil(1/3), not ceil(2/3)
    operate(api, child, "start")
    operate(api, child, "progress", own_progress="50")
    assert all(
        api.call(f"production-orders/{o.id}")["status"] == "WAITING" for o in orders if o != child
    )


def test_sales_root_equal_weights_not_quantity_weighted(api):
    r = item(api, "R", "RAW")
    a = item(api, "A", "SEMI")
    bom(api, a, [(r, None, "1")])
    b = item(api, "B", "SEMI")
    bom(api, b, [(r, None, "1")])
    s = sale(api, "T", [(a, "100", {}), (b, "1", {})])
    orders = formal(api)
    finish(api, orders[0])
    assert api.call(f"sales-orders/{s['id']}")["progress"] == "50.00"


def test_partial_assignment_never_completes_whole_sale(api):
    r = item(api, "R", "RAW")
    a = item(api, "A", "SEMI")
    bom(api, a, [(r, None, "1")])
    s = sale(api, "T", [(a, "2", {})])
    p = api.call("plans/current")
    p["graph"]["jobs"][0]["quantity"] = "1"
    p["graph"]["sales_allocations"][0]["quantity"] = "1"
    api.call(
        f"plans/{p['id']}/graph", "PUT", {"expected_version": p["version"], "graph": p["graph"]}
    )
    order = formal(api)[0]
    finish(api, order)
    result = api.call(f"sales-orders/{s['id']}")
    assert result["status"] == "CONFIRMED" and result["progress"] == "99.99"
    assert result["lines"][0]["pending_quantity"] == "1"


def test_idempotency_version_epoch_and_atomicity(api):
    payload = {"code": "R", "name": "R", "type": "RAW", "unit_id": Unit.objects.first().id}
    first = api.post("items", payload, status=201, key="same")
    assert api.post("items", payload, status=201, key="same") == first
    api.post("items", {**payload, "name": "Other"}, key="same", status=409)
    api.call(f"items/{first['id']}", "PATCH", {"expected_version": 0, "name": "Bad"}, status=409)
    assert Item.objects.get().name == "R"
    api.post("items", {**payload, "code": "R2", "surprise": True}, status=400)
    assert Item.objects.count() == 1
    old_epoch = state().dataset_epoch
    preview = api.post("demo/reset-preview", {"scenario_code": None})
    api.post("demo/reset", {"confirm": True, "confirmation_token": preview["confirmation_token"]})
    api.post("items", payload, key="same", epoch=old_epoch, status=409)
    assert Item.objects.count() == 0 and AuditEvent.objects.count() == 1


def test_csrf_required_even_without_accounts():
    client = Client(enforce_csrf_checks=True)
    response = client.post("/api/v1/items", data="{}", content_type="application/json")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_FAILED"


def test_revocation_whole_plan_history_and_sequence_not_reused(api, chain):
    s = sale(api, "T", [(chain[3], "1", {})])
    parent, child = formal(api)
    old_batch = parent.batch_number
    p = api.call(f"plans/{parent.plan_id}")
    preview = api.post(f"plans/{p['id']}/revoke-preview", {"expected_version": p["version"]})
    api.post(
        f"plans/{p['id']}/revoke",
        {
            "expected_version": p["version"],
            "confirm": True,
            "confirmation_token": preview["confirmation_token"],
            "reason": "test",
        },
    )
    assert ProductionOrder.objects.filter(status="REVOKED").count() == 2
    assert api.call(f"trace/sales-orders/{s['id']}")["nodes"] == []
    assert len(api.call(f"trace/sales-orders/{s['id']}?include_history=true")["nodes"]) == 2
    new = formal(api)
    assert new[0].batch_number != old_batch
    assert new[0].plan.replaces_plan_ids_json == [p["id"]]
    operate(api, new[-1], "start")
    p = api.call(f"plans/{new[0].plan_id}")
    api.post(f"plans/{p['id']}/revoke-preview", {"expected_version": p["version"]}, status=409)


def test_cancel_sale_replans_other_shared_sales(api, chain):
    s1 = sale(api, "T1", [(chain[3], "1", {})])
    s2 = sale(api, "T2", [(chain[3], "2", {})])
    formal(api)
    s1 = api.call(f"sales-orders/{s1['id']}")
    preview = api.post(
        f"sales-orders/{s1['id']}/cancel-preview", {"expected_version": s1["version"]}
    )
    api.post(
        f"sales-orders/{s1['id']}/cancel",
        {
            "expected_version": s1["version"],
            "confirm": True,
            "confirmation_token": preview["confirmation_token"],
            "reason": "test",
        },
    )
    assert SalesOrder.objects.get(pk=s1["id"]).status == "CANCELLED"
    assert api.call(f"sales-orders/{s2['id']}")["lines"][0]["pending_quantity"] == "0"
    assert api.call("plans/current") is None
    assert sorted(ProductionOrder.objects.values_list("planned_qty_u", flat=True)) == [
        2_000_000,
        4_000_000,
    ]


def test_stale_confirmation_preview(api, chain):
    sale(api, "T", [(chain[3], "1", {})])
    orders = formal(api)
    p = api.call(f"plans/{orders[0].plan_id}")
    preview = api.post(f"plans/{p['id']}/revoke-preview", {"expected_version": p["version"]})
    item(api, "NEW", "RAW")
    api.post(
        f"plans/{p['id']}/revoke",
        {
            "expected_version": p["version"],
            "confirm": True,
            "confirmation_token": preview["confirmation_token"],
            "reason": "test",
        },
        status=409,
    )


def test_invalid_material_and_quantity_rules(api, chain):
    unit = Unit.objects.get(code="PCS")
    for value in ["0", "-1", "0.5", "NaN", "1000000001"]:
        with pytest.raises(BusinessError):
            quantity(value, unit)
    raw = chain[0]
    api.post(
        "boms",
        {"item_id": raw["id"], "revision": "V1", "base_quantity": "1", "lines": []},
        status=422,
    )
    api.post(
        "sales-orders",
        {
            "number": "Bad",
            "customer_name": "Test",
            "lines": [{"item_id": raw["id"], "quantity": "1"}],
        },
        status=422,
    )
    assert SalesOrder.objects.count() == 0  # parent row and any lines rolled back
    api.call(
        f"items/{raw['id']}",
        "PATCH",
        {"expected_version": raw["version"], "type": "SEMI"},
        status=409,
    )


def test_graph_rejects_quantity_missing_child_and_duplicate_keys(api, chain):
    sale(api, "T", [(chain[3], "1", {})])
    p = api.call("plans/current")
    graph = p["graph"]
    graph["dependencies"][0]["quantity"] = "1"
    api.call(
        f"plans/{p['id']}/graph",
        "PUT",
        {"expected_version": p["version"], "graph": graph},
        status=422,
    )
    graph = api.call("plans/current")["graph"]
    graph["jobs"][1]["key"] = graph["jobs"][0]["key"]
    api.call(
        f"plans/{p['id']}/graph",
        "PUT",
        {"expected_version": p["version"], "graph": graph},
        status=422,
    )
    assert PlanRun.objects.get(pk=p["id"]).version == p["version"]


def test_graph_cycle_and_deep_iteration():
    assert len(topo(range(2000), [(i, i + 1) for i in range(1999)])) == 2000
    with pytest.raises(BusinessError):
        topo([1, 2], [(1, 2), (2, 1)])


def test_bom_cross_version_cycle(api):
    r = item(api, "R", "RAW")
    a = item(api, "A", "SEMI")
    ab = bom(api, a, [(r, None, "1")])
    b = item(api, "B", "SEMI")
    bb = bom(api, b, [(a, ab, "1")])
    api.post(
        "boms",
        {
            "item_id": a["id"],
            "revision": "V2",
            "base_quantity": "1",
            "lines": [{"component_item_id": b["id"], "child_bom_id": bb["id"], "quantity": "1"}],
        },
        status=422,
    )
    assert BOM.objects.filter(item_id=a["id"]).count() == 1


def test_reset_preserves_sequences_and_units(api, chain):
    sale(api, "T", [(chain[3], "1", {})])
    formal(api)
    seq = NumberSequence.objects.get(name="formal_plan").next_value
    p = api.post("demo/reset-preview", {})
    api.post("demo/reset", {"confirmation_token": p["confirmation_token"], "confirm": True})
    assert NumberSequence.objects.get(name="formal_plan").next_value == seq
    assert Unit.objects.count() == 2
    assert Item.objects.count() == ProductionOrder.objects.count() == PlanRun.objects.count() == 0
    assert SystemState.objects.get().dataset_epoch == 2


def test_fraction_unchanged_before_final_display(api, chain):
    sale(api, "T", [(chain[3], "1", {})])
    parent, child = formal(api)
    operate(api, child, "start")
    operate(api, child, "progress", own_progress="99.99")
    parent.refresh_from_db()
    assert Fraction(int(parent.progress_num), int(parent.progress_den)) == Fraction(29997, 50000)
    assert api.call(f"production-orders/{parent.id}")["progress"] == "59.99"


def test_split_parent_reexplodes_rounding_and_merge_reduces(api):
    r = item(api, "R", "RAW")
    a = item(api, "A", "SEMI")
    ab = bom(api, a, [(r, None, "1")])
    f = item(api, "F", "FINISHED")
    bom(api, f, [(a, ab, "1")], base="2")
    sale(api, "T", [(f, "2", {})])
    p = api.call("plans/current")
    root = p["graph"]["jobs"][0]
    p = api.post(
        f"plans/{p['id']}/adjust",
        {
            "expected_version": p["version"],
            "operation": {"type": "split", "job_key": root["key"], "quantities": ["1", "1"]},
        },
    )
    assert len(p["graph"]["jobs"]) == 3
    assert p["validation"]["quantity_changes"][0]["difference"] == "1"
    supplier = next(j for j in p["graph"]["jobs"] if j["item_id"] == a["id"])
    assert supplier["quantity"] == "2"
    roots = [j["key"] for j in p["graph"]["jobs"] if j["item_id"] == f["id"]]
    p = api.post(
        f"plans/{p['id']}/adjust",
        {"expected_version": p["version"], "operation": {"type": "merge", "job_keys": roots}},
    )
    assert len(p["graph"]["jobs"]) == 2
    assert next(j for j in p["graph"]["jobs"] if j["item_id"] == a["id"])["quantity"] == "1"
    assert p["validation"]["quantity_changes"][0]["difference"] == "-1"
    orders = formal(api)
    assert len(orders) == 2


def test_split_shared_supplier_across_multiple_consumers(api, chain):
    sale(api, "T1", [(chain[3], "2", {})])
    sale(api, "T2", [(chain[1], "1", {})])
    p = api.call("plans/current")
    supplier = next(j for j in p["graph"]["jobs"] if j["item_id"] == chain[1]["id"])
    p = api.post(
        f"plans/{p['id']}/adjust",
        {
            "expected_version": p["version"],
            "operation": {"type": "split", "job_key": supplier["key"], "quantities": ["2", "3"]},
        },
    )
    orders = formal(api)
    parent = next(o for o in orders if o.item_id == chain[3]["id"])
    assert parent.suppliers.count() == 2
    assert sum(parent.suppliers.values_list("qty_u", flat=True)) == 4_000_000
    assert (
        sum(
            SalesAllocation.objects.filter(sales_line__item_id=chain[1]["id"]).values_list(
                "qty_u", flat=True
            )
        )
        == 1_000_000
    )


def test_progress_transaction_failure_rolls_back_everything(api, chain, monkeypatch):
    sale(api, "T", [(chain[3], "1", {})])
    parent, child = formal(api)
    operate(api, child, "start")
    old_count = AuditEvent.objects.count()
    original = progress.recompute

    def broken():
        original()
        raise RuntimeError("Injected transaction failure")

    monkeypatch.setattr(progress, "recompute", broken)
    with pytest.raises(RuntimeError):
        operate(api, child, "progress", own_progress="60")
    child.refresh_from_db()
    parent.refresh_from_db()
    assert child.own_progress_bp == 0 and parent.progress_num == "0"
    assert child.progress_events.count() == 0 and AuditEvent.objects.count() == old_count


def test_stale_plan_confirm_atomic(api, chain):
    sale(api, "T", [(chain[3], "1", {})])
    p = api.call("plans/current")
    item(api, "NEW", "RAW")
    api.post(f"plans/{p['id']}/confirm", {"expected_version": p["version"]}, status=409)
    assert ProductionOrder.objects.count() == 0
    assert NumberSequence.objects.filter(name="formal_plan").count() == 0


def test_shanghai_batch_date(api, chain, monkeypatch):
    import datetime

    monkeypatch.setattr(
        planning, "now", lambda: datetime.datetime(2026, 1, 1, 18, tzinfo=datetime.UTC)
    )
    sale(api, "T", [(chain[3], "1", {})])
    orders = formal(api)
    assert all(o.batch_number.startswith("P20260102-") for o in orders)


def test_graph_resource_budget_atomic(api, chain, settings):
    sale(api, "T", [(chain[3], "1", {})])
    p = api.call("plans/current")
    settings.GRAPH_NODE_BUDGET = 1
    api.post(f"plans/{p['id']}/confirm", {"expected_version": p["version"]}, status=422)
    assert ProductionOrder.objects.count() == 0


def test_backup_restore_and_corrupt_backup_preserves_destination(tmp_path):
    import os
    import sqlite3
    import subprocess
    import sys
    from contextlib import closing
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    source = tmp_path / "source.sqlite3"
    env = {**os.environ, "DATABASE_PATH": str(source), "DJANGO_SETTINGS_MODULE": "config.settings"}
    for command in [("migrate", "--noinput"), ("init_system",)]:
        subprocess.run(
            [sys.executable, str(root / "manage.py"), *command],
            env=env,
            check=True,
            capture_output=True,
        )
    backup = tmp_path / "backup.sqlite3"
    subprocess.run(
        [sys.executable, str(root / "scripts/backup_sqlite.py"), str(source), str(backup)],
        check=True,
        capture_output=True,
    )
    with closing(sqlite3.connect(source)) as connection, connection:
        connection.execute("UPDATE aps_systemstate SET dataset_epoch=9")
        connection.execute(
            "INSERT INTO aps_numbersequence(name,next_value) VALUES ('formal_plan',9)"
        )
    subprocess.run(
        [
            sys.executable,
            str(root / "scripts/restore_sqlite.py"),
            str(backup),
            str(source),
            "--service-stopped",
        ],
        check=True,
        capture_output=True,
    )
    with closing(sqlite3.connect(source)) as connection, connection:
        assert connection.execute("SELECT dataset_epoch FROM aps_systemstate").fetchone() == (10,)
        assert connection.execute(
            "SELECT next_value FROM aps_numbersequence WHERE name='formal_plan'"
        ).fetchone() == (9,)
    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"corrupt")
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/restore_sqlite.py"),
            str(corrupt),
            str(source),
            "--service-stopped",
        ],
        capture_output=True,
    )
    assert result.returncode != 0
    with closing(sqlite3.connect(source)) as connection, connection:
        assert connection.execute("SELECT dataset_epoch FROM aps_systemstate").fetchone() == (10,)
        assert connection.execute(
            "SELECT next_value FROM aps_numbersequence WHERE name='formal_plan'"
        ).fetchone() == (9,)


def test_one_hundred_bom_levels_exact_iterative_propagation(api):
    from aps.models import BOMLine

    unit = Unit.objects.get(code="PCS")
    raw = Item.objects.create(code="DEEP-R", name="Temporary raw", type="RAW", unit=unit)
    nodes = Item.objects.bulk_create(
        [
            Item(
                code=f"DEEP-{i}",
                name=f"Temporary {i}",
                type="FINISHED" if i == 0 else "SEMI",
                unit=unit,
            )
            for i in range(100)
        ]
    )
    versions = BOM.objects.bulk_create(
        [BOM(item=n, revision="V1", base_qty_u=1_000_000, status="ACTIVE") for n in nodes]
    )
    BOMLine.objects.bulk_create(
        [
            BOMLine(
                bom=b,
                position=1,
                component_item=nodes[i + 1] if i < 99 else raw,
                child_bom=versions[i + 1] if i < 99 else None,
                qty_u=1_000_000,
            )
            for i, b in enumerate(versions)
        ]
    )
    s = sale(api, "DEEP", [(dict(id=nodes[0].id), "1", {})])
    orders = formal(api)
    assert len(orders) == 100 and max(o.frozen_level for o in orders) == 99
    finish(api, orders[-1])
    root = ProductionOrder.objects.get(pk=orders[0].id)
    assert Fraction(int(root.progress_num), int(root.progress_den)) == Fraction(3, 5) ** 99
    assert root.status == "WAITING"
    assert len(api.call(f"trace/sales-orders/{s['id']}")["nodes"]) == 100


def test_continuous_unit_ceiling_and_input_exactness(api):
    precise = Unit.objects.create(code="KG6", name="Temporary six-decimal unit", decimal_places=6)
    raw = item(api, "R", "RAW", "KG6")
    f = item(api, "F", "FINISHED")
    bom(api, f, [(raw, None, "1")], base="3")
    sale(api, "T", [(f, "1", {})])
    order = formal(api)[0]
    raw_requirement = order.raw_requirements.get()
    assert raw_requirement.qty_u == 333334
    assert Fraction(
        int(raw_requirement.theoretical_qty_num), int(raw_requirement.theoretical_qty_den)
    ) == Fraction(1_000_000, 3)
    assert quantity("0.333334", precise) == 333334
    assert (
        api.call(f"production-orders/{order.id}")["raw_requirements"][0]["quantity"] == "0.333334"
    )


def test_distinct_root_union_not_average_of_sales_lines(api):
    raw = item(api, "R", "RAW")
    a = item(api, "A", "SEMI")
    bom(api, a, [(raw, None, "1")])
    b = item(api, "B", "SEMI")
    bom(api, b, [(raw, None, "1")])
    c = item(api, "C", "SEMI")
    bom(api, c, [(raw, None, "1")])
    s = sale(api, "T", [(a, "1", {}), (a, "9", {}), (b, "1", {}), (c, "1", {})])
    orders = formal(api)
    by_item = {o.item_id: o for o in orders}
    for i, value in [(a["id"], "36"), (b["id"], "60"), (c["id"], "90")]:
        operate(api, by_item[i], "start")
        operate(api, by_item[i], "progress", own_progress=value)
    result = api.call(f"sales-orders/{s['id']}")
    assert result["progress"] == "62.00" and len(result["production_order_ids"]) == 3


def test_historical_names_and_usage_survive_master_rename(api, chain):
    s = sale(api, "T", [(chain[3], "1", {})])
    parent, child = formal(api)
    finish(api, child)
    finish(api, parent)
    i = api.call(f"items/{chain[3]['id']}")
    api.call(
        f"items/{i['id']}", "PATCH", {"expected_version": i["version"], "name": "New catalog name"}
    )
    result = api.call(f"trace/sales-orders/{s['id']}")
    assert next(n for n in result["nodes"] if n["id"] == parent.id)["item"]["name"] == "F"
    assert api.call(f"sales-orders/{s['id']}")["lines"][0]["item"]["name"] == "F"
    assert result["edges"][0]["usage_confirmed_at"] is not None


def test_immutability_and_progress_bounds(api, chain):
    sale(api, "T", [(chain[3], "1", {})])
    parent, child = formal(api)
    api.call(
        f"production-orders/{child.id}",
        "PATCH",
        {"expected_version": child.version, "quantity": "2"},
        status=404,
    )
    operate(api, child, "start")
    child.refresh_from_db()
    for value in ["100.01", "-1", "NaN", "1e999999", "0.001"]:
        api.post(
            f"production-orders/{child.id}/progress",
            {"expected_version": child.version, "own_progress": value},
            status=422,
        )
    assert api.call(f"production-orders/{child.id}")["progress"] == "0.00"


def test_unknown_nested_fields_and_fake_identifiers(api, chain):
    api.post(
        "sales-orders",
        {
            "number": "BAD",
            "customer_name": "Test",
            "lines": [{"item_id": chain[3]["id"], "quantity": "1", "expected_version": 1}],
        },
        status=400,
    )
    api.post("items", {"code": "BAD", "name": "BAD", "type": "RAW", "unit_id": True}, status=400)
    assert SalesOrder.objects.count() == 0


def test_live_independent_of_corrupted_or_unwritable_database(api, monkeypatch):
    from django.db import OperationalError

    import aps.api as http_api

    def unavailable():
        raise OperationalError("database read-only or corrupt")

    monkeypatch.setattr(http_api, "state", unavailable)
    assert api.client.get("/api/v1/health/live").status_code == 200
    assert api.client.get("/api/v1/health/ready").status_code == 503


def test_f03_exact_324_split_matrix_and_reverse_genealogy(api):
    raw = item(api, "F03-R", "RAW")
    semi = item(api, "F03-B", "SEMI")
    sb = bom(api, semi, [(raw, None, "1")])
    a1 = item(api, "F03-A1", "FINISHED")
    bom(api, a1, [(semi, sb, "120")])
    a2 = item(api, "F03-A2", "FINISHED")
    bom(api, a2, [(semi, sb, "180")])
    s1 = sale(api, "F03-T1", [(a1, "1", {})])
    s2 = sale(api, "F03-T2", [(a2, "1", {}), (semi, "24", {})])
    p = api.call("plans/current")
    graph = p["graph"]
    by_item = {j["item_id"]: j for j in graph["jobs"]}
    b1 = by_item[semi["id"]]
    assert b1["quantity"] == "324"
    b1["quantity"] = "200"
    b2 = {**b1, "key": "B2", "quantity": "124"}
    graph["jobs"].append(b2)
    graph["dependencies"] = [
        {"supplier_key": b1["key"], "consumer_key": by_item[a1["id"]]["key"], "quantity": "120"},
        {"supplier_key": b1["key"], "consumer_key": by_item[a2["id"]]["key"], "quantity": "80"},
        {"supplier_key": "B2", "consumer_key": by_item[a2["id"]]["key"], "quantity": "100"},
    ]
    for allocation in graph["sales_allocations"]:
        if allocation["job_key"] == b1["key"]:
            allocation["job_key"] = "B2"
    api.call(f"plans/{p['id']}/graph", "PUT", {"expected_version": p["version"], "graph": graph})
    orders = formal(api)
    producer = next(o for o in orders if o.plan_node_key == "B2")
    consumer = next(o for o in orders if o.item_id == a2["id"])
    assert sorted(consumer.suppliers.values_list("qty_u", flat=True)) == [80_000_000, 100_000_000]
    result = api.call(f"trace/batches/{producer.batch_number}")
    assert {n["item_id"] for n in result["nodes"]} == {semi["id"], a2["id"]}
    assert {a["sales_order_id"] for a in result["sales_allocations"]} == {s2["id"]}
    assert {n["item_id"] for n in api.call(f"trace/sales-orders/{s1['id']}")["nodes"]} == {
        a1["id"],
        semi["id"],
    }


def test_auto_chain_regression_and_transitive_manual_block(api):
    raw = item(api, "AUTO-R", "RAW")
    c = item(api, "AUTO-C", "SEMI")
    cb = bom(api, c, [(raw, None, "1")])
    b = item(api, "AUTO-B", "SEMI")
    bb = bom(api, b, [(c, cb, "1")])
    a = item(api, "AUTO-A", "FINISHED")
    bom(api, a, [(b, bb, "1")])
    sale(api, "AUTO", [(a, "1", {})])
    p = api.call("plans/current")
    for job in p["graph"]["jobs"]:
        if job["child_weight"] is not None:
            job["child_weight"] = "100"
    api.call(
        f"plans/{p['id']}/graph", "PUT", {"expected_version": p["version"], "graph": p["graph"]}
    )
    orders = formal(api)
    finish(api, orders[-1])
    assert ProductionOrder.objects.filter(status="COMPLETED").count() == 3
    operate(api, orders[-1], "correct-progress", own_progress="60", reason="Temporary correction")
    assert ProductionOrder.objects.filter(status="WAITING").count() == 2
    assert not ProductionDependency.objects.filter(usage_confirmed_at__isnull=False).exists()


def test_integrity_command_read_only_and_detects_bad_cache(api, chain):
    import io

    from django.core.management import CommandError, call_command

    sale(api, "T", [(chain[3], "1", {})])
    parent, child = formal(api)
    output = io.StringIO()
    call_command("check_demo_integrity", stdout=output)
    assert "PASS" in output.getvalue()
    ProductionOrder.objects.filter(pk=parent.id).update(progress_num="1", progress_den="2")
    with pytest.raises(CommandError):
        call_command("check_demo_integrity", stdout=io.StringIO())


def test_reset_preview_invalidated_by_progress_event(api, chain):
    sale(api, "T", [(chain[3], "1", {})])
    parent, child = formal(api)
    operate(api, child, "start")
    preview = api.post("demo/reset-preview", {})
    operate(api, child, "progress", own_progress="20")
    api.post(
        "demo/reset",
        {"confirmation_token": preview["confirmation_token"], "confirm": True},
        status=409,
    )
    assert ProductionOrder.objects.count() == 2


def test_deep_fraction_storage_has_no_decimal_digit_depth_limit():
    from types import SimpleNamespace

    from aps.core import display_progress, fraction_text, stored_fraction

    value = Fraction(3, 5) ** 8000
    obj = SimpleNamespace(
        progress_num=fraction_text(value.numerator),
        progress_den=fraction_text(value.denominator),
        status="WAITING",
    )
    assert stored_fraction(obj) == value
    assert display_progress(obj) == "0.00"


@pytest.mark.parametrize("kind", ["FINISHED", "SEMI"])
def test_sales_draft_requires_existing_usable_bom(api, kind):
    product = item(api, "NO-BOM", kind)
    body = {
        "number": "NO-BOM-SALE",
        "customer_name": "Temporary test customer",
        "lines": [{"item_id": product["id"], "quantity": "1"}],
    }
    error = api.post("sales-orders", body, status=422)
    assert error["error"]["code"] == "BOM_REQUIRED"
    assert not SalesOrder.objects.exists()
    raw = item(api, "RAW", "RAW")
    draft = api.post(
        "boms",
        {
            "item_id": product["id"],
            "revision": "V1",
            "base_quantity": "1",
            "lines": [{"component_item_id": raw["id"], "quantity": "1"}],
        },
        status=201,
    )
    api.post("sales-orders", body, status=422)
    api.post(f"boms/{draft['id']}/activate", {"expected_version": draft["version"]})
    created = api.post("sales-orders", body, status=201)
    assert created["status"] == "DRAFT"
    missing = item(api, "OTHER-NO-BOM", kind)
    api.call(
        f"sales-orders/{created['id']}",
        "PATCH",
        {
            "expected_version": created["version"],
            "lines": [{"item_id": missing["id"], "quantity": "1"}],
        },
        status=422,
    )
    saved = api.call(f"sales-orders/{created['id']}")
    assert saved["lines"][0]["item"]["id"] == product["id"]
    assert saved["version"] == created["version"]


def cancel_sale(api, sale_id):
    current = api.call(f"sales-orders/{sale_id}")
    preview = api.post(
        f"sales-orders/{sale_id}/cancel-preview", {"expected_version": current["version"]}
    )
    return api.post(
        f"sales-orders/{sale_id}/cancel",
        {
            "expected_version": current["version"],
            "confirm": True,
            "confirmation_token": preview["confirmation_token"],
            "reason": "取消数量重算验证",
        },
    )


@pytest.mark.parametrize(
    "initial_progress, expected", [("60", "100.00"), ("80", "100.00"), ("30", "50.00")]
)
def test_cancel_shared_leaf_preserves_completed_quantity(api, initial_progress, expected):
    from django.core.management import call_command

    raw = item(api, "R", "RAW")
    semi = item(api, "S", "SEMI")
    bom(api, semi, [(raw, None, "2")])
    cancelled = sale(api, "CANCEL", [(semi, "40", {})])
    remaining = sale(api, "KEEP", [(semi, "60", {})])
    order = formal(api)[0]
    batch = order.batch_number
    operate(api, order, "start")
    operate(api, order, "progress", own_progress=initial_progress)
    result = cancel_sale(api, cancelled["id"])
    order.refresh_from_db()
    assert result["status"] == "CANCELLED"
    assert not result["has_pending_quantity"]
    assert order.planned_qty_u == 60_000_000 and order.batch_number == batch
    assert api.call(f"production-orders/{order.id}")["progress"] == expected
    assert api.call(f"sales-orders/{remaining['id']}")["progress"] == expected
    assert order.raw_requirements.get().qty_u == 120_000_000
    call_command("check_demo_integrity")


def test_cancel_multilevel_credit_can_complete_without_parent_start(api, chain):
    from django.core.management import call_command

    cancelled = sale(api, "CANCEL", [(chain[3], "40", {})])
    remaining = sale(api, "KEEP", [(chain[3], "60", {})])
    parent, child = formal(api)
    finish(api, child)
    assert api.call(f"production-orders/{parent.id}")["progress"] == "60.00"
    cancel_sale(api, cancelled["id"])
    parent.refresh_from_db()
    child.refresh_from_db()
    assert parent.status == child.status == "COMPLETED"
    assert parent.actual_started_at is None
    assert parent.planned_qty_u == 60_000_000 and child.planned_qty_u == 120_000_000
    assert api.call(f"sales-orders/{remaining['id']}")["status"] == "PRODUCTION_COMPLETED"
    call_command("check_demo_integrity")


def test_cancel_exclusive_started_batches_preserves_history(api, chain):
    from django.core.management import call_command

    cancelled = sale(api, "CANCEL", [(chain[3], "10", {})])
    parent, child = formal(api)
    operate(api, child, "start")
    operate(api, child, "progress", own_progress="20")
    cancel_sale(api, cancelled["id"])
    assert all(o.status == "REVOKED" for o in ProductionOrder.objects.all())
    assert ProductionDependency.objects.filter(active=False).count() == 1
    graph = api.call(f"trace/sales-orders/{cancelled['id']}?include_history=true")
    assert len(graph["nodes"]) == 2 and len(graph["edges"]) == 1
    assert AuditEvent.objects.filter(event_type="CANCEL_DEMAND").exists()
    call_command("check_demo_integrity")


def test_cancel_split_allocation_and_shared_supplier_rounding(api, chain):
    from django.core.management import call_command

    cancelled = sale(api, "CANCEL", [(chain[3], "40", {})])
    remaining = sale(api, "KEEP", [(chain[3], "60", {})])
    plan = api.call("plans/current")
    root = next(j for j in plan["graph"]["jobs"] if j["item_id"] == chain[3]["id"])
    plan = api.post(
        f"plans/{plan['id']}/adjust",
        {
            "expected_version": plan["version"],
            "operation": {"type": "split", "job_key": root["key"], "quantities": ["30", "70"]},
        },
    )
    orders = formal(api)
    leaf = next(o for o in orders if o.item_id == chain[1]["id"])
    operate(api, leaf, "start")
    operate(api, leaf, "progress", own_progress="30")
    cancel_sale(api, cancelled["id"])
    assert (
        sum(
            ProductionOrder.objects.filter(item_id=chain[3]["id"])
            .exclude(status="REVOKED")
            .values_list("planned_qty_u", flat=True)
        )
        == 60_000_000
    )
    leaf.refresh_from_db()
    assert leaf.planned_qty_u == 120_000_000
    assert api.call(f"production-orders/{leaf.id}")["progress"] == "50.00"
    assert api.call(f"sales-orders/{remaining['id']}")["lines"][0]["pending_quantity"] == "0"
    call_command("check_demo_integrity")


def test_repeated_cancellation_keeps_exact_completed_amount(api):
    from django.core.management import call_command

    from aps.core import stored_fraction

    raw = item(api, "R", "RAW")
    semi = item(api, "S", "SEMI")
    bom(api, semi, [(raw, None, "1")])
    first = sale(api, "FIRST", [(semi, "40", {})])
    second = sale(api, "SECOND", [(semi, "20", {})])
    keep = sale(api, "KEEP", [(semi, "40", {})])
    order = formal(api)[0]
    operate(api, order, "start")
    operate(api, order, "progress", own_progress="32")
    cancel_sale(api, first["id"])
    order.refresh_from_db()
    assert stored_fraction(order) == Fraction(32, 60)
    cancel_sale(api, second["id"])
    order.refresh_from_db()
    assert order.planned_qty_u == 40_000_000
    assert stored_fraction(order) == Fraction(4, 5)
    assert api.call(f"sales-orders/{keep['id']}")["progress"] == "80.00"
    call_command("check_demo_integrity")


def test_cancel_preview_stale_after_production_update(api, chain):
    cancelled = sale(api, "CANCEL", [(chain[3], "40", {})])
    sale(api, "KEEP", [(chain[3], "60", {})])
    parent, child = formal(api)
    cancelled = api.call(f"sales-orders/{cancelled['id']}")
    preview = api.post(
        f"sales-orders/{cancelled['id']}/cancel-preview", {"expected_version": cancelled["version"]}
    )
    operate(api, child, "start")
    result = api.post(
        f"sales-orders/{cancelled['id']}/cancel",
        {
            "expected_version": cancelled["version"],
            "confirmation_token": preview["confirmation_token"],
            "confirm": True,
            "reason": "test",
        },
        status=409,
    )
    assert result["error"]["code"] == "STALE_PREVIEW"
    parent.refresh_from_db()
    assert parent.planned_qty_u == 100_000_000


def test_cancel_already_completed_shared_sale(api, chain):
    cancelled = sale(api, "CANCEL", [(chain[3], "40", {})])
    remaining = sale(api, "KEEP", [(chain[3], "60", {})])
    parent, child = formal(api)
    finish(api, child)
    finish(api, parent)
    cancel_sale(api, cancelled["id"])
    parent.refresh_from_db()
    assert parent.status == "COMPLETED" and parent.planned_qty_u == 60_000_000
    assert api.call(f"sales-orders/{remaining['id']}")["progress"] == "100.00"


def test_cancel_quantity_changes_roll_back_on_failure(api, chain, monkeypatch):
    cancelled = sale(api, "CANCEL", [(chain[3], "40", {})])
    sale(api, "KEEP", [(chain[3], "60", {})])
    parent, child = formal(api)
    cancelled = api.call(f"sales-orders/{cancelled['id']}")
    preview = api.post(
        f"sales-orders/{cancelled['id']}/cancel-preview", {"expected_version": cancelled["version"]}
    )
    count = AuditEvent.objects.count()

    def fail():
        raise BusinessError("INJECTED", "测试事务回滚", 422)

    monkeypatch.setattr(progress, "recompute", fail)
    api.post(
        f"sales-orders/{cancelled['id']}/cancel",
        {
            "expected_version": cancelled["version"],
            "confirmation_token": preview["confirmation_token"],
            "confirm": True,
            "reason": "test",
        },
        status=422,
    )
    parent.refresh_from_db()
    assert parent.planned_qty_u == 100_000_000
    assert SalesOrder.objects.get(pk=cancelled["id"]).status == "CONFIRMED"
    assert AuditEvent.objects.count() == count
    assert parent.sales_allocations.get(sales_line__order_id=cancelled["id"]).qty_u == 40_000_000
