from decimal import Decimal
from fractions import Fraction

from .core import display_progress, qty, snapshot, stored_fraction
from .models import BOM, AuditEvent, Item, PlanRun, ProductionOrder, SalesOrder, Unit


def serialize(obj, detail=True):
    base = {"id": obj.id}
    for key in [
        "version",
        "number",
        "status",
        "created_at",
        "updated_at",
        "confirmed_at",
        "completed_at",
        "actual_started_at",
        "revoked_at",
    ]:
        if hasattr(obj, key):
            v = getattr(obj, key)
            base[key] = v.isoformat() if hasattr(v, "isoformat") else v
    if isinstance(obj, Unit):
        base.update(code=obj.code, name=obj.name, decimal_places=obj.decimal_places)
    elif isinstance(obj, Item):
        base.update(snapshot(obj), unit_id=obj.unit_id, active=obj.active, is_sellable=obj.can_sell)
    elif isinstance(obj, BOM):
        base.update(
            item_id=obj.item_id,
            item=snapshot(obj.item),
            revision=obj.revision,
            base_quantity=qty(obj.base_qty_u),
            description=obj.description,
        )
        if detail:
            base["lines"] = [
                {
                    "id": line.id,
                    "position": line.position,
                    "component_item_id": line.component_item_id,
                    "component": snapshot(line.component_item),
                    "child_bom_id": line.child_bom_id,
                    "quantity": qty(line.qty_u),
                }
                for line in obj.lines.select_related("component_item__unit")
            ]
    elif isinstance(obj, SalesOrder):
        base.update(
            customer_name=obj.customer_name,
            default_priority=obj.default_priority,
            notes=obj.notes,
            progress=display_progress(obj),
            cancel_reason=obj.cancel_reason,
        )
        lines = []
        roots, completed_roots = set(), set()
        for line in obj.lines.select_related("item__unit"):
            allocations = list(
                line.allocations.filter(qty_u__gt=0)
                .exclude(production_order__status="REVOKED")
                .select_related("production_order")
            )
            orders = {a.production_order.id: a.production_order for a in allocations}
            roots.update(orders)
            completed_roots.update(
                pk for pk, order in orders.items() if order.status == "COMPLETED"
            )
            progress = (
                sum(
                    (stored_fraction(o) for o in orders.values()),
                    Fraction(),
                )
                / len(orders)
                if orders
                else Fraction()
            )
            assigned = sum(a.qty_u for a in allocations)
            p = min(
                Decimal(progress.numerator) / Decimal(progress.denominator) * 100,
                Decimal("100")
                if assigned == line.qty_u and all(o.status == "COMPLETED" for o in orders.values())
                else Decimal("99.99"),
            )
            lines.append(
                {
                    "id": line.id,
                    "position": line.position,
                    "item_id": line.item_id,
                    "item": line.item_snapshot_json or snapshot(line.item),
                    "quantity": qty(line.qty_u),
                    "bom_id": line.bom_id,
                    "priority_override": line.priority_override,
                    "effective_priority": line.effective_priority,
                    "assigned_quantity": qty(assigned),
                    "pending_quantity": "0"
                    if obj.status == "CANCELLED"
                    else qty(line.qty_u - assigned),
                    "progress": format(p, ".2f"),
                    "assigned_progress": "100.00"
                    if orders and all(o.status == "COMPLETED" for o in orders.values())
                    else format(p, ".2f"),
                    "production_order_ids": sorted(orders),
                }
            )
        base["lines"] = lines
        base["production_order_ids"] = sorted(roots)
        base["has_pending_quantity"] = any(Decimal(line["pending_quantity"]) > 0 for line in lines)
        all_roots_completed = bool(roots) and completed_roots == roots
        base["assigned_progress"] = "100.00" if all_roots_completed else base["progress"]
    elif isinstance(obj, PlanRun):
        base.update(
            source_data_revision=obj.source_data_revision,
            dataset_epoch=obj.dataset_epoch,
            formal_sequence=obj.formal_sequence,
            replaces_plan_ids=obj.replaces_plan_ids_json,
        )
        if detail:
            base.update(graph=obj.graph_json, validation=obj.validation_json)
    elif isinstance(obj, ProductionOrder):
        base.update(
            batch_number=obj.batch_number,
            plan_id=obj.plan_id,
            item=obj.item_snapshot_json,
            item_id=obj.item_id,
            bom_id=obj.bom_id,
            priority=obj.priority,
            quantity=qty(obj.planned_qty_u),
            rounding_surplus=qty(obj.rounding_surplus_qty_u),
            level=obj.frozen_level,
            child_weight=None
            if obj.child_weight_bp is None
            else f"{obj.child_weight_bp / 100:.2f}",
            own_progress=f"{obj.own_progress_bp / 100:.2f}",
            progress=display_progress(obj),
            completion_mode=obj.completion_mode,
            has_cancellation_credit=obj.retained_completed_qty_num != "0",
            can_start=obj.status == "READY",
            can_update_progress=obj.status == "IN_PROGRESS",
        )
        if detail:
            base["dependencies"] = [
                {
                    "id": e.id,
                    "supplier_order_id": e.supplier_order_id,
                    "batch_number": e.supplier_order.batch_number,
                    "item": e.supplier_order.item_snapshot_json,
                    "quantity": qty(e.qty_u),
                    "status": e.supplier_order.status,
                    "progress": display_progress(e.supplier_order),
                    "usage_confirmed_at": e.usage_confirmed_at.isoformat()
                    if e.usage_confirmed_at
                    else None,
                }
                for e in obj.suppliers.filter(active=True).select_related("supplier_order")
            ]
            base["sales_allocations"] = [
                {
                    "sales_order_id": a.sales_line.order_id,
                    "sales_line_id": a.sales_line_id,
                    "quantity": qty(a.qty_u),
                    "fulfilled": a.fulfillment_confirmed_at is not None,
                }
                for a in obj.sales_allocations.select_related("sales_line")
            ]
            base["raw_requirements"] = [
                {
                    "item": r.item_snapshot_json,
                    "quantity": qty(r.qty_u),
                    "theoretical_qty": {
                        "numerator": r.theoretical_qty_num,
                        "denominator": r.theoretical_qty_den,
                    },
                }
                for r in obj.raw_requirements.all()
            ]
            base["bom_snapshot"] = obj.bom_snapshot_json
    elif isinstance(obj, AuditEvent):
        base.update(
            event_type=obj.event_type,
            entity_type=obj.entity_type,
            entity_id=obj.entity_id_text,
            before=obj.before_json,
            after=obj.after_json,
            affected_entities=obj.affected_entities_json,
            reason=obj.reason,
            request_id=obj.request_id,
            dataset_epoch=obj.dataset_epoch,
        )
    return base
