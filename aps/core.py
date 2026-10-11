"""Exact arithmetic, graph validation, and immutable business snapshots."""

import re
from collections import deque
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from fractions import Fraction

from django.conf import settings
from django.db.models import Prefetch
from django.utils import timezone

from .models import BOM, BOMLine, NumberSequence, SystemState

SCALE = 1_000_000
PRIORITIES = ("HIGH", "NORMAL", "LOW")


class BusinessError(Exception):
    def __init__(self, code, message, status=422, details=None):
        self.code, self.message, self.status, self.details = code, message, status, details or {}
        super().__init__(message)


def require(condition, message, code="VALIDATION_ERROR", status=422, details=None):
    if not condition:
        raise BusinessError(code, message, status, details)


def fields(data, allowed, required=(), protocol=True):
    require(isinstance(data, dict), "请求必须是对象", status=400)
    extras = (
        set(data) - set(allowed) - ({"dataset_epoch", "expected_version"} if protocol else set())
    )
    require(
        all(
            value is None or (type(value) is int and value > 0)
            for key, value in data.items()
            if key.endswith("_id")
        ),
        "引用 ID 必须是正整数",
        status=400,
    )
    require(not extras, "包含未知字段", status=400, details={"fields": sorted(extras)})
    require(
        all(k in data for k in required),
        "缺少必填字段",
        status=400,
        details={"required": list(required)},
    )


def quantity(value, unit, allow_zero=False):
    require(isinstance(value, str), "数量必须使用十进制字符串", status=400)
    require(
        len(value) <= 40 and re.fullmatch(r"[0-9]+(?:\.[0-9]{1,6})?", value),
        "数量格式或精度无效",
        "INVALID_QUANTITY",
    )
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise BusinessError("INVALID_QUANTITY", "数量格式无效", 400) from None
    require(
        number.is_finite()
        and (number >= 0 if allow_zero else number > 0)
        and number <= 1_000_000_000,
        "数量超出允许范围",
        "INVALID_QUANTITY",
    )
    scaled = number * SCALE
    require(
        scaled == scaled.to_integral_value()
        and int(scaled) % (10 ** (6 - unit.decimal_places)) == 0,
        "数量精度与单位不符",
        "INVALID_QUANTITY",
    )
    return int(scaled)


def qty(value):
    return (
        format(Decimal(value) / SCALE, "f").rstrip("0").rstrip(".")
        if value % SCALE
        else str(value // SCALE)
    )


def percent(value):
    require(isinstance(value, str), "百分比必须是字符串", status=400)
    require(
        len(value) <= 8 and re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", value),
        "百分比格式无效",
        "INVALID_PROGRESS",
    )
    try:
        n = Decimal(value)
    except InvalidOperation:
        raise BusinessError("INVALID_PROGRESS", "百分比无效", 400) from None
    require(
        n.is_finite() and 0 <= n <= 100 and n * 100 == (n * 100).to_integral_value(),
        "百分比范围为 0–100，最多两位小数",
    )
    return int(n * 100)


def stored_fraction(obj):
    # Decimal bridges arbitrarily long integer text without Python's decimal-int digit cap.
    return Fraction(int(Decimal(obj.progress_num)), int(Decimal(obj.progress_den)))


def fraction_text(value):
    return format(Decimal(value), "f")


def display_progress(obj):
    fraction = stored_fraction(obj)
    p = (Decimal(fraction.numerator) / Decimal(fraction.denominator) * 100).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if obj.status not in ("COMPLETED", "PRODUCTION_COMPLETED"):
        p = min(p, Decimal("99.99"))
    return format(p, ".2f")


def state():
    return SystemState.objects.get_or_create(pk=1)[0]


def sequence(name):
    row, _ = NumberSequence.objects.get_or_create(name=name)
    result = row.next_value
    row.next_value += 1
    row.save()
    return result


def snapshot(item):
    return {
        "id": item.id,
        "code": item.code,
        "name": item.name,
        "type": item.type,
        "unit": item.unit.code,
        "decimal_places": item.unit.decimal_places,
    }


def bom_snapshot(bom):
    return {
        "id": bom.id,
        "revision": bom.revision,
        "base_quantity": qty(bom.base_qty_u),
        "lines": [
            {
                "position": line.position,
                "item": snapshot(line.component_item),
                "quantity": qty(line.qty_u),
                "child_bom_id": line.child_bom_id,
            }
            for line in bom_lines(bom)
        ],
    }


def touch(obj):
    obj.version += 1
    obj.save()


def check_version(obj, data):
    require(
        type(data.get("expected_version")) is int and data["expected_version"] == obj.version,
        "数据已更新，请刷新后重试",
        "VERSION_CONFLICT",
        409,
        {"current_version": obj.version},
    )


def topo(keys, edges):
    keys = list(keys)
    require(
        len(keys) <= settings.GRAPH_NODE_BUDGET and len(edges) <= settings.GRAPH_EDGE_BUDGET,
        "图超出资源预算",
        "GRAPH_BUDGET_EXCEEDED",
    )
    children = {k: [] for k in keys}
    counts = dict.fromkeys(keys, 0)
    for supplier, consumer in edges:
        require(supplier in counts and consumer in counts, "依赖引用了不存在的生产节点")
        children[supplier].append(consumer)
        counts[consumer] += 1
    queue = deque(k for k in keys if counts[k] == 0)
    result = []
    while queue:
        node = queue.popleft()
        result.append(node)
        for consumer in children[node]:
            counts[consumer] -= 1
            if counts[consumer] == 0:
                queue.append(consumer)
    require(len(result) == len(keys), "检测到循环依赖", "CYCLE_DETECTED")
    return result


class BOMGraph:
    """One operation-local catalog snapshot; no stale process-global business cache."""

    def __init__(self):
        self.boms = {
            b.id: b
            for b in BOM.objects.select_related("item__unit").prefetch_related(
                Prefetch("lines", queryset=BOMLine.objects.select_related("component_item__unit"))
            )
        }
        self.validated = {}


def bom_lines(bom):
    if "lines" in getattr(bom, "_prefetched_objects_cache", {}):
        return list(bom.lines.all())
    return list(bom.lines.select_related("component_item__unit", "child_bom__item"))


def validate_bom(root, allow_root_draft=False, repository=None):
    """Iterative DFS; track material identity as well as BOM identity on each path."""
    done = repository.validated if repository else {}
    active_items, active_boms = set(), set()
    stack = [(root, False)]
    nodes = 0
    while stack:
        bom, exiting = stack.pop()
        if exiting:
            active_items.remove(bom.item_id)
            active_boms.remove(bom.id)
            descendants = set()
            for line in bom_lines(bom):
                descendants.add(line.component_item_id)
                if line.child_bom_id:
                    descendants.update(done[line.child_bom_id])
            require(bom.item_id not in descendants, "BOM 跨版本重复了祖先物料", "BOM_CYCLE")
            done[bom.id] = descendants
            continue
        require(
            bom.item_id not in active_items and bom.id not in active_boms,
            "BOM 存在直接或间接循环",
            "BOM_CYCLE",
        )
        if bom.id in done:
            require(not (done[bom.id] & active_items), "BOM 跨版本重复了祖先物料", "BOM_CYCLE")
            continue
        nodes += 1
        require(nodes <= settings.GRAPH_NODE_BUDGET, "BOM 超出资源预算", "GRAPH_BUDGET_EXCEEDED")
        require(
            bom.item.type in ("FINISHED", "SEMI") and bom.item.active,
            "只有启用的成品和半成品可设置 BOM",
        )
        require(
            bom.status in ("ACTIVE", "RETIRED") or (allow_root_draft and bom.id == root.id),
            "子 BOM 必须是已生效版本",
        )
        lines = bom_lines(bom)
        require(lines, "成品或半成品的 BOM 不可为空", "EMPTY_BOM")
        active_items.add(bom.item_id)
        active_boms.add(bom.id)
        stack.append((bom, True))
        for line in reversed(lines):
            require(
                line.component_item.active and line.component_item.type != "FINISHED",
                "BOM 组成只允许启用的半成品和原料",
            )
            if line.component_item.type == "RAW":
                require(line.child_bom_id is None, "原料不能继续拆分")
            else:
                require(
                    line.child_bom_id
                    and (
                        repository.boms[line.child_bom_id] if repository else line.child_bom
                    ).item_id
                    == line.component_item_id,
                    "半成品必须指定匹配的子 BOM",
                )
                stack.append(
                    ((repository.boms[line.child_bom_id] if repository else line.child_bom), False)
                )


def choose_bom(item, selected=None):
    bom = (
        BOM.objects.filter(pk=selected, item=item).first()
        if selected
        else BOM.objects.filter(item=item, status="ACTIVE").first()
    )
    require(bom is not None, f"{item.code} 没有可用 BOM", "BOM_REQUIRED")
    validate_bom(bom)
    return bom


def needed(parent_qty, bom, line):
    exact = Fraction(parent_qty * line.qty_u, bom.base_qty_u)
    step = 10 ** (6 - line.component_item.unit.decimal_places)
    rounded = (
        (exact.numerator + exact.denominator * step - 1) // (exact.denominator * step)
    ) * step
    require(rounded <= 10**15, "展开数量超出允许范围", "INVALID_QUANTITY")
    return exact, rounded


def now():
    return timezone.now()
