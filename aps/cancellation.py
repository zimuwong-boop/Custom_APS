"""Remove one sale's demand from existing batches without discarding shared progress."""

import json
from collections import defaultdict
from fractions import Fraction

from django.core.serializers.json import DjangoJSONEncoder
from django.forms.models import model_to_dict

from .core import (
    bom_lines,
    fraction_text,
    needed,
    now,
    qty,
    require,
    state,
    stored_fraction,
    topo,
    touch,
)
from .models import AuditEvent, ProductionDependency, ProductionOrder, SalesAllocation


def quantity_changes(sale, plans):
    orders = {
        o.id: o
        for o in ProductionOrder.objects.filter(plan__in=plans)
        .exclude(status="REVOKED")
        .select_related("item__unit", "bom")
    }
    edges = list(
        ProductionDependency.objects.filter(
            active=True, consumer_order_id__in=orders, supplier_order_id__in=orders
        )
    )
    allocations = list(
        SalesAllocation.objects.filter(production_order_id__in=orders).select_related(
            "sales_line__order"
        )
    )
    remaining = defaultdict(int)
    for a in allocations:
        if a.sales_line.order_id != sale.id and a.sales_line.order.status != "CANCELLED":
            remaining[a.production_order_id] += a.qty_u
    incoming = defaultdict(list)
    for e in edges:
        incoming[e.consumer_order_id].append(e)
    amounts, edge_amounts = {}, {}
    # Consumers first: re-explode their reduced actual quantities, including unit rounding.
    for pk in reversed(topo(orders, [(e.supplier_order_id, e.consumer_order_id) for e in edges])):
        o = orders[pk]
        amounts[pk] = remaining[pk]
        require(amounts[pk] <= o.planned_qty_u, "取消不得增加批次数量")
        by_component = defaultdict(list)
        for e in incoming[pk]:
            supplier = orders[e.supplier_order_id]
            by_component[(supplier.item_id, supplier.bom_id)].append(e)
        for line in bom_lines(o.bom):
            if line.component_item.type != "SEMI":
                continue
            suppliers = by_component[(line.component_item_id, line.child_bom_id)]
            target = needed(amounts[pk], o.bom, line)[1] if amounts[pk] else 0
            total = sum(e.qty_u for e in suppliers)
            require(total >= target and bool(suppliers), "原批次的子单分配不完整")
            step = 10 ** (6 - line.component_item.unit.decimal_places)
            parts = {e.id: (target * e.qty_u // (total * step)) * step for e in suppliers}
            extra = (target - sum(parts.values())) // step
            ranked = sorted(suppliers, key=lambda e: (-(target * e.qty_u % (total * step)), e.id))
            for e in ranked[:extra]:
                parts[e.id] += step
            for e in suppliers:
                require(parts[e.id] <= e.qty_u, "取消后的分配超过原数量")
                edge_amounts[e.id] = parts[e.id]
                remaining[e.supplier_order_id] += parts[e.id]
    return orders, edges, allocations, amounts, edge_amounts


def summary(sale, plans):
    orders, _, _, amounts, _ = quantity_changes(sale, plans)
    return [
        {
            "id": pk,
            "batch_number": o.batch_number,
            "old_quantity": qty(o.planned_qty_u),
            "new_quantity": qty(amounts[pk]),
            "cancelled": amounts[pk] == 0,
        }
        for pk, o in orders.items()
        if amounts[pk] != o.planned_qty_u
    ]


def cancel(sale, plans, reason, request_id):
    from . import progress
    from .serializers import serialize

    require(isinstance(reason, str) and reason.strip(), "请填写取消原因")
    orders, edges, allocations, amounts, edge_amounts = quantity_changes(sale, plans)
    changed = [pk for pk, o in orders.items() if amounts[pk] != o.planned_qty_u]
    before = {
        "orders": [serialize(orders[pk]) for pk in changed],
        "dependencies": [model_to_dict(e) for e in edges],
        "allocations": [model_to_dict(a) for a in allocations],
    }
    before = json.loads(json.dumps(before, cls=DjangoJSONEncoder))
    # Save active source removal as zero, preserving sale/batch identity for reverse trace.
    for a in allocations:
        if a.sales_line.order_id == sale.id:
            a.qty_u, a.fulfillment_confirmed_at = 0, None
            a.save()
    for e in edges:
        if edge_amounts[e.id] == 0:
            e.active = False
            e.save()
        elif edge_amounts[e.id] != e.qty_u:
            e.qty_u = edge_amounts[e.id]
            e.save()
    for pk in changed:
        o, amount = orders[pk], amounts[pk]
        if not amount:
            # Keep the last positive planned quantity as the cancelled batch's history.
            o.status = "REVOKED"
            o.completed_at, o.completion_mode = None, ""
        else:
            # Exact amount of already completed work, capped at remaining demand (no inventory).
            completed = min(stored_fraction(o) * o.planned_qty_u, Fraction(amount))
            o.retained_completed_qty_num = fraction_text(completed.numerator)
            o.retained_completed_qty_den = fraction_text(completed.denominator)
            o.own_progress_bp = min(10000, o.own_progress_bp * o.planned_qty_u // amount)
            o.planned_qty_u, o.rounding_surplus_qty_u = amount, 0
            for raw in o.raw_requirements.all():
                line = next(
                    line for line in bom_lines(o.bom) if line.position == raw.bom_line_position
                )
                exact, rounded = needed(amount, o.bom, line)
                raw.theoretical_qty_num, raw.theoretical_qty_den = (
                    fraction_text(exact.numerator),
                    fraction_text(exact.denominator),
                )
                raw.qty_u, raw.rounding_delta_u = (
                    rounded,
                    rounded - exact.numerator // exact.denominator,
                )
                raw.save()
        o.graph_revision += 1
        touch(o)
    for plan in plans:
        if not plan.orders.exclude(status="REVOKED").exists():
            plan.status, plan.revoked_at, plan.revoke_reason = "REVOKED", now(), reason
        touch(plan)
    sale.status, sale.cancelled_at, sale.cancel_reason = "CANCELLED", now(), reason
    touch(sale)
    system = state()
    system.data_revision += 1
    system.save()
    progress.recompute()
    AuditEvent.objects.create(
        event_type="CANCEL_DEMAND",
        entity_type="sales-orders",
        entity_id_text=str(sale.id),
        before_json=before,
        after_json={"orders": [serialize(ProductionOrder.objects.get(pk=pk)) for pk in changed]},
        affected_entities_json=changed,
        reason=reason,
        request_id=request_id,
        dataset_epoch=system.dataset_epoch,
    )
    return changed
