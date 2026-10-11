from collections import defaultdict

from .core import qty, require
from .models import PlanRun, ProductionDependency, ProductionOrder, SalesAllocation
from .serializers import serialize


def graph(order_ids, direction="both", history=False):
    require(direction in ["up", "down", "both"], "图方向无效", status=400)
    orders = (
        ProductionOrder.objects.all()
        if history
        else ProductionOrder.objects.exclude(status="REVOKED")
    )
    ids = set(orders.values_list("id", flat=True))
    edges = list(
        ProductionDependency.objects.filter(supplier_order_id__in=ids, consumer_order_id__in=ids)
    )
    if not history:
        edges = [e for e in edges if e.active]
    suppliers, consumers = defaultdict(list), defaultdict(list)
    for edge in edges:
        suppliers[edge.consumer_order_id].append(edge.supplier_order_id)
        consumers[edge.supplier_order_id].append(edge.consumer_order_id)
    selected = set(order_ids) & ids
    # Start each direction at the requested roots; avoid including siblings via a zigzag.
    directions = (
        [suppliers, consumers]
        if direction == "both"
        else [suppliers if direction == "down" else consumers]
    )
    for adjacency in directions:
        seen, queue = set(order_ids) & ids, list(set(order_ids) & ids)
        while queue:
            key = queue.pop()
            for other in adjacency[key]:
                if other not in seen:
                    seen.add(other)
                    queue.append(other)
        selected.update(seen)
    chosen = list(orders.filter(id__in=selected).order_by("frozen_level", "id"))
    from .core import topo

    levels = {pk: {0} for pk in set(order_ids) & selected}
    selected_edges = [
        e for e in edges if e.supplier_order_id in selected and e.consumer_order_id in selected
    ]
    for consumer in topo(
        selected, [(e.consumer_order_id, e.supplier_order_id) for e in selected_edges]
    ):
        if consumer in levels:
            for supplier in suppliers[consumer]:
                if supplier in selected:
                    levels.setdefault(supplier, set()).update(
                        level + 1 for level in levels[consumer]
                    )
    nodes = []
    for order in chosen:
        data = serialize(order)
        data["relative_levels"] = sorted(levels.get(order.id, {order.frozen_level}))
        nodes.append(data)
    return {
        "nodes": nodes,
        "root_order_ids": sorted(set(order_ids) & selected),
        "plans": [
            serialize(plan, False)
            for plan in PlanRun.objects.filter(id__in={o.plan_id for o in chosen})
        ],
        "edges": [
            {
                "supplier_order_id": e.supplier_order_id,
                "consumer_order_id": e.consumer_order_id,
                "quantity": qty(e.qty_u),
                "active": e.active,
                "usage_confirmed_at": e.usage_confirmed_at.isoformat()
                if e.usage_confirmed_at
                else None,
            }
            for e in edges
            if e.supplier_order_id in selected and e.consumer_order_id in selected
        ],
        "sales_allocations": [
            {
                "production_order_id": a.production_order_id,
                "sales_line_id": a.sales_line_id,
                "sales_order_id": a.sales_line.order_id,
                "sales_order_number": a.sales_line.order.number,
                "quantity": qty(a.qty_u),
                "fulfilled": a.fulfillment_confirmed_at is not None,
            }
            for a in SalesAllocation.objects.filter(
                production_order_id__in=selected
            ).select_related("sales_line__order")
        ],
    }


def sale_plans(sale):
    ids = sale.lines.values_list("allocations__production_order__plan_id", flat=True)
    return list(PlanRun.objects.filter(pk__in=ids, status="CONFIRMED"))
