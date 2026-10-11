"""Read-only post-restore integrity checks against immutable production relationships."""

from collections import defaultdict
from fractions import Fraction

from django.core.management.base import BaseCommand, CommandError

from aps.core import BusinessError, bom_lines, needed, require, stored_fraction, topo
from aps.models import ProductionDependency, ProductionOrder, SalesAllocation, SalesLine, SalesOrder


class Command(BaseCommand):
    help = (
        "Check production quantities, DAG, gating, exact progress, sales coverage, and batch links."
    )

    def handle(self, *args, **options):
        try:
            orders = {
                o.id: o
                for o in ProductionOrder.objects.exclude(status="REVOKED").select_related(
                    "bom", "item__unit"
                )
            }
            edges = list(
                ProductionDependency.objects.filter(
                    active=True, supplier_order_id__in=orders, consumer_order_id__in=orders
                )
            )
            outgoing, children = defaultdict(int), defaultdict(list)
            for edge in edges:
                outgoing[edge.supplier_order_id] += edge.qty_u
                children[edge.consumer_order_id].append(edge)
            line_coverage, sale_roots = defaultdict(int), defaultdict(set)
            for a in SalesAllocation.objects.filter(production_order_id__in=orders).select_related(
                "sales_line"
            ):
                outgoing[a.production_order_id] += a.qty_u
                line_coverage[a.sales_line_id] += a.qty_u
                sale_roots[a.sales_line.order_id].add(a.production_order_id)
            totals = {}
            for pk in topo(orders, [(e.supplier_order_id, e.consumer_order_id) for e in edges]):
                o = orders[pk]
                require(
                    o.planned_qty_u == outgoing[pk] + o.rounding_surplus_qty_u,
                    f"{o.batch_number} 数量不守恒",
                )
                component_quantities = defaultdict(int)
                for edge in children[pk]:
                    supplier = orders[edge.supplier_order_id]
                    component_quantities[(supplier.item_id, supplier.bom_id)] += edge.qty_u
                for line in bom_lines(o.bom):
                    if line.component_item.type == "SEMI":
                        require(
                            component_quantities[(line.component_item_id, line.child_bom_id)]
                            == needed(o.planned_qty_u, o.bom, line)[1],
                            f"{o.batch_number} 子单覆盖不完整",
                        )
                dependencies = [orders[e.supplier_order_id] for e in children[pk]]
                ready = all(d.status == "COMPLETED" for d in dependencies)
                if dependencies:
                    require(o.child_weight_bp is not None, f"{o.batch_number} 缺少子单贡献")
                    w = Fraction(o.child_weight_bp, 10000)
                    total = w * sum((totals[d.id] for d in dependencies), Fraction()) / len(
                        dependencies
                    ) + (1 - w) * Fraction(o.own_progress_bp, 10000)
                else:
                    require(o.child_weight_bp is None, f"{o.batch_number} 底层子单设置了子单贡献")
                    total = Fraction(o.own_progress_bp, 10000)
                from aps.progress import effective_progress

                total = effective_progress(o, total)
                require(
                    total == stored_fraction(o),
                    f"{o.batch_number} 进度缓存不一致",
                )
                require(not o.actual_started_at or ready, f"{o.batch_number} 依赖未完成却已经开工")
                require(
                    (o.status == "COMPLETED") == (total == 1 and ready),
                    f"{o.batch_number} 完成状态不一致",
                )
                totals[pk] = total
            for line in SalesLine.objects.all():
                require(line_coverage[line.id] <= line.qty_u, f"销售行 {line.id} 超额分配")
            for sale in SalesOrder.objects.filter(
                status__in=["CONFIRMED", "PRODUCTION_COMPLETED"]
            ).prefetch_related("lines"):
                roots = sale_roots[sale.id]
                value = (
                    sum((totals[i] for i in roots), Fraction()) / len(roots)
                    if roots
                    else Fraction()
                )
                require(
                    value == stored_fraction(sale),
                    f"销售单 {sale.number} 汇总进度不一致",
                )
                completed = (
                    bool(roots)
                    and all(orders[i].status == "COMPLETED" for i in roots)
                    and all(line_coverage[line.id] == line.qty_u for line in sale.lines.all())
                )
                require(
                    (sale.status == "PRODUCTION_COMPLETED") == completed,
                    f"销售单 {sale.number} 完成状态不一致",
                )
        except BusinessError as exc:
            raise CommandError(exc.message) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Integrity PASS: {len(orders)} active production nodes, {len(edges)} edges."
            )
        )
