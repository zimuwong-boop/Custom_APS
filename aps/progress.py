from collections import defaultdict
from decimal import Decimal
from fractions import Fraction

from .core import fraction_text, now, percent, require, stored_fraction, topo, touch
from .models import (
    ProductionDependency,
    ProductionOrder,
    ProgressEvent,
    SalesAllocation,
    SalesOrder,
)


def retained_progress(order):
    return (
        Fraction(
            int(Decimal(order.retained_completed_qty_num)),
            int(Decimal(order.retained_completed_qty_den)),
        )
        / order.planned_qty_u
    )


def effective_progress(order, base):
    return min(Fraction(1), max(base, retained_progress(order)))


def recompute():
    orders = {o.id: o for o in ProductionOrder.objects.exclude(status="REVOKED")}
    edges = list(
        ProductionDependency.objects.filter(
            active=True, supplier_order_id__in=orders, consumer_order_id__in=orders
        )
    )
    children = defaultdict(list)
    for edge in edges:
        children[edge.consumer_order_id].append(edge.supplier_order_id)
    affected = []
    for key in topo(orders, [(e.supplier_order_id, e.consumer_order_id) for e in edges]):
        order = orders[key]
        previous = (order.status, order.progress_num, order.progress_den)
        dependencies = [orders[i] for i in children[key]]
        if dependencies:
            average = sum(
                (stored_fraction(o) for o in dependencies),
                Fraction(),
            ) / len(dependencies)
            w = Fraction(order.child_weight_bp, 10000)
            total = w * average + (1 - w) * Fraction(order.own_progress_bp, 10000)
            ready = all(o.status == "COMPLETED" for o in dependencies)
        else:
            total, ready = Fraction(order.own_progress_bp, 10000), True
        total = effective_progress(order, total)
        if ready and total == 1:
            order.status = "COMPLETED"
            order.completed_at = order.completed_at or now()
            order.completion_mode = (
                "CANCEL"
                if retained_progress(order) >= 1
                else ("HUMAN" if order.actual_started_at else "AUTO")
            )
        else:
            order.status = (
                "IN_PROGRESS" if order.actual_started_at else ("READY" if ready else "WAITING")
            )
            order.completed_at, order.completion_mode = None, ""
        order.progress_num, order.progress_den = (
            fraction_text(total.numerator),
            fraction_text(total.denominator),
        )
        if previous != (order.status, order.progress_num, order.progress_den):
            touch(order)
            affected.append(order.id)
    for edge in edges:
        consumer = orders[edge.consumer_order_id]
        used = consumer.actual_started_at or (
            consumer.completed_at if consumer.completion_mode in ("AUTO", "CANCEL") else None
        )
        if edge.usage_confirmed_at != used:
            edge.usage_confirmed_at = used
            edge.save()
    all_allocations = list(
        SalesAllocation.objects.filter(production_order_id__in=orders).select_related("sales_line")
    )
    sales_roots, line_amounts = defaultdict(set), defaultdict(int)
    for allocation in all_allocations:
        if allocation.qty_u == 0:
            continue
        producer = orders[allocation.production_order_id]
        if allocation.fulfillment_confirmed_at != producer.completed_at:
            allocation.fulfillment_confirmed_at = producer.completed_at
            allocation.save()
        sales_roots[allocation.sales_line.order_id].add(producer.id)
        line_amounts[allocation.sales_line_id] += allocation.qty_u
    for sale in SalesOrder.objects.filter(
        status__in=["CONFIRMED", "PRODUCTION_COMPLETED"]
    ).prefetch_related("lines"):
        roots = [orders[i] for i in sales_roots[sale.id]]
        total = (
            sum((stored_fraction(o) for o in roots), Fraction()) / len(roots)
            if roots
            else Fraction()
        )
        full = all(line_amounts[line.id] == line.qty_u for line in sale.lines.all())
        completed = full and bool(roots) and all(o.status == "COMPLETED" for o in roots)
        new_status = "PRODUCTION_COMPLETED" if completed else "CONFIRMED"
        if (sale.progress_num, sale.progress_den, sale.status) != (
            fraction_text(total.numerator),
            fraction_text(total.denominator),
            new_status,
        ):
            sale.progress_num, sale.progress_den, sale.status = (
                fraction_text(total.numerator),
                fraction_text(total.denominator),
                new_status,
            )
            sale.production_completed_at = now() if completed else None
            touch(sale)
    return affected


def children_complete(order):
    return (
        not order.suppliers.filter(active=True).exclude(supplier_order__status="COMPLETED").exists()
    )


def start(order):
    require(
        order.status == "READY" and children_complete(order),
        "所有直接子单完成后才能开始生产",
        "DEPENDENCY_NOT_READY",
        409,
    )
    require(order.actual_started_at is None, "该生产单已经开始", "IMMUTABLE", 409)
    order.actual_started_at = now()
    order.status = "IN_PROGRESS"
    touch(order)
    return recompute()


def update(order, value, request_id, correction=False, reason=""):
    require(
        order.status != "REVOKED" and children_complete(order),
        "子单尚未全部完成，无法调整自身进度",
        "DEPENDENCY_NOT_READY",
        409,
    )
    require(order.actual_started_at is not None, "请先开始生产", "NOT_STARTED", 409)
    bp = percent(value)
    old = order.own_progress_bp
    if correction:
        require(reason.strip(), "纠错必须填写原因")
        require(bp < old, "纠错仅用于降低自身进度")
        edges = defaultdict(list)
        for s, c in (
            ProductionDependency.objects.filter(active=True)
            .exclude(consumer_order__status="REVOKED")
            .values_list("supplier_order_id", "consumer_order_id")
        ):
            edges[s].append(c)
        seen, queue = set(), list(edges[order.id])
        while queue:
            key = queue.pop()
            if key in seen:
                continue
            seen.add(key)
            queue.extend(edges[key])
        require(
            not ProductionOrder.objects.filter(
                id__in=seen, actual_started_at__isnull=False
            ).exists(),
            "下游已开始自身生产，不能回退上游进度",
            "DOWNSTREAM_STARTED",
            409,
        )
    else:
        require(
            order.status != "COMPLETED" and bp >= old,
            "进度不能回退，请使用纠错操作",
            "INVALID_PROGRESS",
            409,
        )
    if correction:
        order.retained_completed_qty_num, order.retained_completed_qty_den = "0", "1"
    order.own_progress_bp = bp
    touch(order)
    ProgressEvent.objects.create(
        production_order=order,
        event_type="CORRECTION" if correction else "UPDATE",
        old_own_bp=old,
        new_own_bp=bp,
        reason=reason,
        request_id=request_id,
    )
    return recompute()
