"""Quantity-preserving scheduling on a supplier/consumer DAG."""

from collections import defaultdict

from .core import (
    BOMGraph,
    bom_lines,
    bom_snapshot,
    fields,
    needed,
    now,
    percent,
    qty,
    quantity,
    require,
    sequence,
    snapshot,
    state,
    topo,
    touch,
    validate_bom,
)
from .models import (
    BOM,
    Item,
    MaterialRequirement,
    PlanRun,
    ProductionDependency,
    ProductionOrder,
    SalesAllocation,
    SalesLine,
)


def pending_lines():
    from django.db.models import Q, Sum

    result = []
    lines = (
        SalesLine.objects.filter(order__status__in=["CONFIRMED", "PRODUCTION_COMPLETED"])
        .select_related("item__unit", "bom", "order")
        .annotate(
            assigned=Sum(
                "allocations__qty_u", filter=~Q(allocations__production_order__status="REVOKED")
            )
        )
    )
    for line in lines:
        allocated = line.assigned or 0
        if allocated < line.qty_u:
            result.append((line, line.qty_u - allocated))
    return result


def suggest():
    lines = pending_lines()
    repository = BOMGraph()
    groups, bom_map = {}, repository.boms
    for line, amount in lines:
        key = (line.item_id, line.bom_id, line.effective_priority)
        groups[key] = groups.get(key, 0) + amount

    # Discover the group graph first, then propagate aggregated parent requirements.
    queue = list(groups)
    adjacency = defaultdict(list)
    seen = set()
    while queue:
        key = queue.pop()
        if key in seen:
            continue
        seen.add(key)
        bom = bom_map.get(key[1]) or BOM.objects.get(pk=key[1])
        validate_bom(bom, repository=repository)
        for line in bom_lines(bom):
            if line.component_item.type == "SEMI":
                child = (line.component_item_id, line.child_bom_id, key[2])
                groups.setdefault(child, 0)

                adjacency[key].append((child, line))
                queue.append(child)
    ordered = topo(
        groups, [(parent, child) for parent, entries in adjacency.items() for child, _ in entries]
    )
    edges = []
    for key in ordered:
        for child, line in adjacency[key]:
            _, amount = needed(groups[key], bom_map[key[1]], line)
            groups[child] += amount
            edges.append((child, key, amount))
    names = {key: f"J{i + 1:04d}" for i, key in enumerate(ordered)}
    graph = {
        "schema_version": 1,
        "jobs": [
            {
                "key": names[key],
                "item_id": key[0],
                "bom_id": key[1],
                "priority": key[2],
                "quantity": qty(groups[key]),
                "rounding_surplus": "0",
                "child_weight": "60" if adjacency[key] else None,
            }
            for key in ordered
        ],
        "dependencies": [
            {"supplier_key": names[child], "consumer_key": names[parent], "quantity": qty(amount)}
            for child, parent, amount in edges
        ],
        "sales_allocations": [
            {
                "sales_line_id": line.id,
                "job_key": names[(line.item_id, line.bom_id, line.effective_priority)],
                "quantity": qty(amount),
            }
            for line, amount in lines
        ],
    }
    return graph


def validate_graph(graph):
    fields(
        graph,
        ["schema_version", "jobs", "dependencies", "sales_allocations"],
        ["schema_version", "jobs", "dependencies", "sales_allocations"],
        protocol=False,
    )
    require(graph["schema_version"] == 1, "排产图版本不支持")
    require(
        all(isinstance(graph[k], list) for k in ["jobs", "dependencies", "sales_allocations"]),
        "图字段必须是数组",
        status=400,
    )
    require(graph["jobs"], "没有待排产需求")
    jobs, incoming, outgoing, allocations = (
        {},
        defaultdict(list),
        defaultdict(int),
        defaultdict(int),
    )
    pending = {line.id: (line, amount) for line, amount in pending_lines()}
    repository = BOMGraph()
    for job in graph["jobs"]:
        fields(
            job,
            [
                "key",
                "item_id",
                "bom_id",
                "priority",
                "quantity",
                "rounding_surplus",
                "child_weight",
            ],
            [
                "key",
                "item_id",
                "bom_id",
                "priority",
                "quantity",
                "rounding_surplus",
                "child_weight",
            ],
            protocol=False,
        )
        require(
            isinstance(job["key"], str) and 0 < len(job["key"]) <= 80 and job["key"] not in jobs,
            "生产节点标识重复或无效",
        )
        bom = repository.boms.get(job["bom_id"])
        item = bom.item if bom and bom.item_id == job["item_id"] else None
        require(item and item.active and item.type != "RAW" and bom, "生产节点物料或 BOM 无效")
        validate_bom(bom, repository=repository)
        require(job["priority"] in ("HIGH", "NORMAL", "LOW"), "优先级无效")
        amount = quantity(job["quantity"], item.unit)
        surplus = quantity(job["rounding_surplus"], item.unit, True)
        jobs[job["key"]] = {
            "job": job,
            "item": item,
            "bom": bom,
            "amount": amount,
            "surplus": surplus,
        }
    pairs = set()
    parsed_edges = []
    for edge in graph["dependencies"]:
        fields(
            edge,
            ["supplier_key", "consumer_key", "quantity"],
            ["supplier_key", "consumer_key", "quantity"],
            protocol=False,
        )
        s, c = edge["supplier_key"], edge["consumer_key"]
        require(s in jobs and c in jobs and s != c and (s, c) not in pairs, "依赖边重复或无效")
        pairs.add((s, c))
        supplier, consumer = jobs[s], jobs[c]
        match = any(
            line.component_item_id == supplier["item"].id
            and line.child_bom_id == supplier["bom"].id
            for line in bom_lines(consumer["bom"])
        )
        require(
            match and supplier["job"]["priority"] == consumer["job"]["priority"],
            "子单物料、BOM 或优先级与父单不匹配",
        )
        amount = quantity(edge["quantity"], supplier["item"].unit)
        incoming[c].append((s, amount))
        outgoing[s] += amount
        parsed_edges.append((s, c, amount))
    ordered = topo(jobs, [(s, c) for s, c, _ in parsed_edges])
    for allocation in graph["sales_allocations"]:
        fields(
            allocation,
            ["sales_line_id", "job_key", "quantity"],
            ["sales_line_id", "job_key", "quantity"],
            protocol=False,
        )
        key, line_id = allocation["job_key"], allocation["sales_line_id"]
        require(key in jobs and line_id in pending, "销售分配引用无效或已经分配完毕")
        line = pending[line_id][0]
        job = jobs[key]
        require(
            (line.item_id, line.bom_id, line.effective_priority)
            == (job["item"].id, job["bom"].id, job["job"]["priority"]),
            "销售分配的物料、版本或优先级不匹配",
        )
        require((key, line_id) not in pairs, "销售分配重复")
        pairs.add((key, line_id))
        amount = quantity(allocation["quantity"], line.item.unit)
        allocations[line_id] += amount
        outgoing[key] += amount
    for line_id, amount in allocations.items():
        require(amount <= pending[line_id][1], "销售数量被重复或超额分配")
    # Allow partial scheduling; each consumer nevertheless requires full component coverage.
    raw = []
    for key, job in jobs.items():
        require(
            job["amount"] == outgoing[key] + job["surplus"],
            "生产数量不等于需求分配加声明余量",
            details={"job_key": key},
        )
        require(outgoing[key] > 0, "禁止没有业务去向的生产单")
        components = defaultdict(int)
        for supplier, amount in incoming[key]:
            components[(jobs[supplier]["item"].id, jobs[supplier]["bom"].id)] += amount
        has_child = False
        for line in bom_lines(job["bom"]):
            exact, amount = needed(job["amount"], job["bom"], line)
            if line.component_item.type == "SEMI":
                has_child = True
                require(
                    components[(line.component_item_id, line.child_bom_id)] == amount,
                    "子单分配没有完整覆盖父单 BOM 需求",
                    details={
                        "job_key": key,
                        "component_item_id": line.component_item_id,
                        "required_quantity": qty(amount),
                    },
                )
            else:
                raw.append((key, line, exact, amount))
        if has_child:
            require(job["job"]["child_weight"] is not None, "有子单的生产单必须设置子单贡献比例")
            job["weight"] = percent(job["job"]["child_weight"])
        else:
            require(job["job"]["child_weight"] is None, "最底层生产单不能设置子单贡献比例")
            job["weight"] = None
    roots = {a["job_key"] for a in graph["sales_allocations"]}
    levels = {key: (0 if key in roots else -1) for key in jobs}
    for consumer in reversed(ordered):
        require(levels[consumer] >= 0, "生产节点无法追溯到销售需求")
        for supplier, _ in incoming[consumer]:
            levels[supplier] = max(levels[supplier], levels[consumer] + 1)
    return jobs, parsed_edges, raw, levels


def recalculate(replaces=()):
    system = state()
    PlanRun.objects.filter(status="DRAFT").update(status="SUPERSEDED")
    graph = suggest()
    plan = None
    if graph["jobs"]:
        validate_graph(graph)
        plan = PlanRun.objects.create(
            number=f"D{sequence('draft'):06d}",
            source_data_revision=system.data_revision,
            dataset_epoch=system.dataset_epoch,
            graph_json=graph,
            replaces_plan_ids_json=list(replaces),
        )
    system.active_plan = plan
    system.save()
    return plan


def confirm(plan):
    system = state()
    require(plan.status == "DRAFT", "只有草稿可以确认", "IMMUTABLE", 409)
    require(
        plan.source_data_revision == system.data_revision
        and plan.dataset_epoch == system.dataset_epoch,
        "排产依据已变化，请重新计算",
        "STALE_PLAN",
        409,
    )
    jobs, edges, raw, levels = validate_graph(plan.graph_json)
    seq = sequence("formal_plan")
    date = now().astimezone().strftime("%Y%m%d")
    # timezone.localtime uses the configured Shanghai zone, independent of the host timezone.
    from django.utils.timezone import localtime

    date = localtime(now()).strftime("%Y%m%d")
    created = {}
    for i, (key, job) in enumerate(jobs.items(), 1):
        batch = f"P{date}-{seq:06d}-L{levels[key]:02d}-{i:04d}"
        created[key] = ProductionOrder(
            number=batch,
            batch_number=batch,
            plan=plan,
            plan_node_key=key,
            item=job["item"],
            bom=job["bom"],
            item_snapshot_json=snapshot(job["item"]),
            bom_snapshot_json=bom_snapshot(job["bom"]),
            priority=job["job"]["priority"],
            planned_qty_u=job["amount"],
            rounding_surplus_qty_u=job["surplus"],
            frozen_level=levels[key],
            node_sequence=i,
            child_weight_bp=job["weight"],
            status="WAITING" if job["weight"] is not None else "READY",
        )
    ProductionOrder.objects.bulk_create(list(created.values()))
    source_lines = defaultdict(set)
    for allocation in plan.graph_json["sales_allocations"]:
        source_lines[allocation["job_key"]].add(allocation["sales_line_id"])
    source_edges = defaultdict(list)
    for supplier, consumer, _ in edges:
        source_edges[consumer].append(supplier)
    for consumer in reversed(topo(jobs, [(s, c) for s, c, _ in edges])):
        for supplier in source_edges[consumer]:
            source_lines[supplier].update(source_lines[consumer])
    dependencies = []
    for supplier, consumer, amount in edges:
        dependencies.append(
            ProductionDependency(
                supplier_order=created[supplier],
                consumer_order=created[consumer],
                qty_u=amount,
                component_snapshot_json=snapshot(created[supplier].item),
                source_detail_json={
                    "sales_line_ids": sorted(source_lines[consumer]),
                    "consumer_node": consumer,
                },
            )
        )
    ProductionDependency.objects.bulk_create(dependencies)
    allocation_rows = []
    for a in plan.graph_json["sales_allocations"]:
        order = created[a["job_key"]]
        allocation_rows.append(
            SalesAllocation(
                production_order=order,
                sales_line_id=a["sales_line_id"],
                qty_u=quantity(a["quantity"], order.item.unit),
            )
        )
    SalesAllocation.objects.bulk_create(allocation_rows)
    raw_rows = []
    for key, line, exact, amount in raw:
        raw_rows.append(
            MaterialRequirement(
                production_order=created[key],
                raw_item=line.component_item,
                bom_line_position=line.position,
                item_snapshot_json=snapshot(line.component_item),
                theoretical_qty_num=str(exact.numerator),
                theoretical_qty_den=str(exact.denominator),
                qty_u=amount,
                rounding_delta_u=amount - exact.numerator // exact.denominator,
            )
        )
    MaterialRequirement.objects.bulk_create(raw_rows)
    plan.status, plan.formal_sequence, plan.confirmed_at = "CONFIRMED", seq, now()
    touch(plan)
    system.active_plan = None
    system.data_revision += 1
    system.save()
    return created


def revoke_plans(plans, reason):
    require(reason.strip(), "请填写撤销原因")
    for plan in plans:
        require(plan.status == "CONFIRMED", "只能撤销正式排产", "IMMUTABLE", 409)
        require(
            not plan.orders.filter(actual_started_at__isnull=False).exists()
            and not plan.orders.filter(progress_events__isnull=False).exists(),
            "已有生产操作，不能撤销整批排产",
            "PLAN_STARTED",
            409,
        )
    for plan in plans:
        from django.db.models import F

        plan.orders.update(status="REVOKED", version=F("version") + 1)
        plan.status, plan.revoked_at, plan.revoke_reason = "REVOKED", now(), reason
        touch(plan)
    system = state()
    system.data_revision += 1
    system.save()


def adjust_graph(graph, operation):
    """Re-explode per consumer after a split/merge; never reuse pre-split rounding."""
    import copy

    graph = copy.deepcopy(graph)
    fields(operation, ["type", "job_key", "job_keys", "quantities", "child_weight"], ["type"])
    nodes = {j["key"]: j for j in graph["jobs"]}
    kind = operation["type"]
    if kind == "weight":
        target = nodes.get(operation.get("job_key"))
        require(target and target["child_weight"] is not None, "只能设置非底层节点的子单贡献")
        percent(operation.get("child_weight"))
        target["child_weight"] = operation["child_weight"]
        validate_graph(graph)
        return graph, []
    if kind == "split":
        target = nodes.get(operation.get("job_key"))
        require(target is not None, "拆分节点不存在")
        item = Item.objects.select_related("unit").get(pk=target["item_id"])
        values = operation.get("quantities")
        require(isinstance(values, list) and 2 <= len(values) <= 100, "拆分份数必须为 2–100")
        amounts = [quantity(q, item.unit) for q in values]
        require(
            sum(amounts) == quantity(target["quantity"], item.unit),
            "拆分数量总和必须等于原生产数量",
        )
        require(target["rounding_surplus"] == "0", "声明有余量的节点请先调整分配再拆分")
        target["quantity"] = values[0]
        for i, value in enumerate(values[1:], 1):
            key = f"{target['key']}-S{i}"
            while key in nodes:
                key += "x"
            require(len(key) <= 80, "拆分标识过长")
            nodes[key] = {**target, "key": key, "quantity": value}
    elif kind == "merge":
        keys = operation.get("job_keys")
        require(
            isinstance(keys, list)
            and len(set(keys)) == len(keys)
            and len(keys) >= 2
            and all(k in nodes for k in keys),
            "请选择至少两个不同节点",
        )
        chosen = [nodes[k] for k in keys]
        target = chosen[0]
        require(
            all(
                (j["item_id"], j["bom_id"], j["priority"])
                == (target["item_id"], target["bom_id"], target["priority"])
                for j in chosen
            ),
            "只能合并同物料、同版本、同优先级节点",
        )
        item = Item.objects.select_related("unit").get(pk=target["item_id"])
        target["quantity"] = qty(sum(quantity(j["quantity"], item.unit) for j in chosen))
        target["rounding_surplus"] = qty(
            sum(quantity(j["rounding_surplus"], item.unit, True) for j in chosen)
        )
        for key in keys[1:]:
            del nodes[key]
    else:
        require(False, "不支持的调整操作", status=400)
    old_nodes = {j["key"]: j for j in graph["jobs"]}

    def group_of(j):
        return j["item_id"], j["bom_id"], j["priority"]

    groups = defaultdict(list)
    for j in nodes.values():
        groups[group_of(j)].append(j)
    bom_map = {key: BOM.objects.get(pk=key[1]) for key in groups}
    items = {key: Item.objects.select_related("unit").get(pk=key[0]) for key in groups}
    group_edges, component_lines = [], {}
    for key, b in bom_map.items():
        component_lines[key] = list(b.lines.select_related("component_item__unit"))
        for line in component_lines[key]:
            if line.component_item.type == "SEMI":
                child = (line.component_item_id, line.child_bom_id, key[2])
                require(child in groups, "缺少制造层级")
                group_edges.append((key, child))
    group_sales = defaultdict(list)
    for allocation in graph["sales_allocations"]:
        old = old_nodes[allocation["job_key"]]
        group_sales[group_of(old)].append(
            (
                allocation["sales_line_id"],
                quantity(allocation["quantity"], items[group_of(old)].unit),
            )
        )
    # Collapse duplicate line destinations before reallocating after split/merge.
    demands = defaultdict(list)
    new_allocations, new_edges, changes = [], [], []
    for key in topo(groups, list(set(group_edges))):
        jobs, unit = groups[key], items[key].unit
        sales_totals = defaultdict(int)
        for line_id, amount in group_sales[key]:
            sales_totals[line_id] += amount
        required = sum(sales_totals.values()) + sum(amount for _, amount in demands[key])
        old_total = sum(quantity(j["quantity"], unit) for j in jobs)
        surplus = sum(quantity(j["rounding_surplus"], unit, True) for j in jobs)
        difference = required + surplus - old_total
        if difference:
            # Keep the number of split jobs; alter the final job to account for new rounding.
            last = jobs[-1]
            value = quantity(last["quantity"], unit) + difference
            require(
                value > quantity(last["rounding_surplus"], unit, True),
                "合并后用量减少，请先合并多余的下级拆分节点",
            )
            last["quantity"] = qty(value)
            changes.append(
                {
                    "item_id": key[0],
                    "old_quantity": qty(old_total),
                    "new_quantity": qty(required + surplus),
                    "difference": qty(difference),
                }
            )
        capacities = {
            j["key"]: quantity(j["quantity"], unit) - quantity(j["rounding_surplus"], unit, True)
            for j in jobs
        }
        for line_id, amount in sales_totals.items():
            remaining = amount
            for j in jobs:
                take = min(remaining, capacities[j["key"]])
                if take:
                    new_allocations.append(
                        {"sales_line_id": line_id, "job_key": j["key"], "quantity": qty(take)}
                    )
                    capacities[j["key"]] -= take
                    remaining -= take
            require(remaining == 0, "销售分配未守恒")
        edge_totals = defaultdict(int)
        for consumer, amount in demands[key]:
            remaining = amount
            for j in jobs:
                take = min(remaining, capacities[j["key"]])
                if take:
                    edge_totals[(j["key"], consumer)] += take
                    capacities[j["key"]] -= take
                    remaining -= take
            require(remaining == 0, "子单分配未守恒")
        new_edges.extend(
            {"supplier_key": s, "consumer_key": c, "quantity": qty(amount)}
            for (s, c), amount in edge_totals.items()
        )
        for j in jobs:
            amount = quantity(j["quantity"], unit)
            for line in component_lines[key]:
                if line.component_item.type == "SEMI":
                    _, child_amount = needed(amount, bom_map[key], line)
                    child = (line.component_item_id, line.child_bom_id, key[2])
                    demands[child].append((j["key"], child_amount))
    result = {
        "schema_version": 1,
        "jobs": list(nodes.values()),
        "dependencies": new_edges,
        "sales_allocations": new_allocations,
    }
    validate_graph(result)
    return result, changes
