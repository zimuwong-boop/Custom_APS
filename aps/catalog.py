from .core import (
    PRIORITIES,
    bom_snapshot,
    choose_bom,
    fields,
    now,
    quantity,
    require,
    snapshot,
    touch,
    validate_bom,
)
from .models import BOM, BOMLine, Item, SalesLine, SalesOrder, Unit


def get(model, pk):
    require(type(pk) is int and pk > 0, "记录 ID 无效", "NOT_FOUND", 404)
    obj = model.objects.filter(pk=pk).first()
    require(obj is not None, "记录不存在", "NOT_FOUND", 404)
    return obj


def item_write(data, obj=None):
    fields(
        data,
        ["code", "name", "type", "unit_id", "active"],
        ["code", "name", "type", "unit_id"] if obj is None else [],
    )
    if obj is None:
        obj = Item()
    elif any(k in data and data[k] != getattr(obj, k) for k in ["code", "type", "unit_id"]):
        require(
            not (obj.bom_set.exists() or obj.bomline_set.exists() or obj.salesline_set.exists()),
            "已被引用的物料不能改变编码、类型或单位",
            "IMMUTABLE",
            409,
        )
    for key in ["code", "name", "type", "unit_id", "active"]:
        if key in data:
            setattr(obj, key, data[key])
    require(obj.type in ("FINISHED", "SEMI", "RAW"), "物料类型无效")
    require(
        type(obj.active) is bool
        and isinstance(obj.code, str)
        and 0 < len(obj.code.strip()) <= 60
        and isinstance(obj.name, str)
        and 0 < len(obj.name.strip()) <= 120,
        "物料编码、名称或启用状态无效",
    )
    get(Unit, obj.unit_id)
    if obj.pk:
        touch(obj)
    else:
        obj.save()
    return obj


def bom_write(data, obj=None):
    fields(
        data,
        ["item_id", "revision", "base_quantity", "description", "lines"],
        ["item_id", "revision", "base_quantity", "lines"] if obj is None else [],
    )
    if obj is None:
        item = get(Item, data["item_id"])
        require(item.active and item.type != "RAW", "原料不能建立 BOM")
        obj = BOM(item=item)
    else:
        require(obj.status == "DRAFT", "生效或停用的 BOM 不可修改", "IMMUTABLE", 409)
        require("item_id" not in data or data["item_id"] == obj.item_id, "BOM 所属物料不可修改")
    if "revision" in data:
        require(
            isinstance(data["revision"], str) and 0 < len(data["revision"]) <= 40, "BOM 版本无效"
        )
        obj.revision = data["revision"]
    if "base_quantity" in data:
        obj.base_qty_u = quantity(data["base_quantity"], obj.item.unit)
    obj.description = data.get("description", obj.description)
    if obj.pk:
        touch(obj)
    else:
        obj.save()
    if "lines" in data:
        require(isinstance(data["lines"], list) and data["lines"], "BOM 至少需要一条组成")
        obj.lines.all().delete()
        for i, row in enumerate(data["lines"], 1):
            fields(
                row,
                ["component_item_id", "child_bom_id", "quantity", "position"],
                ["component_item_id", "quantity"],
                protocol=False,
            )
            item = get(Item, row["component_item_id"])
            require(item.type != "FINISHED" and item.active, "BOM 组成只允许启用的半成品和原料")
            child = get(BOM, row["child_bom_id"]) if row.get("child_bom_id") else None
            require(
                (item.type == "RAW" and child is None)
                or (
                    item.type == "SEMI"
                    and child
                    and child.item_id == item.id
                    and child.status in ["ACTIVE", "RETIRED"]
                ),
                "半成品需要指定有效的 BOM 版本；原料不能指定 BOM",
            )
            BOMLine.objects.create(
                bom=obj,
                position=row.get("position", i),
                component_item=item,
                child_bom=child,
                qty_u=quantity(row["quantity"], item.unit),
            )
    validate_bom(obj, True)
    return obj


def sale_write(data, obj=None):
    fields(
        data,
        ["number", "customer_name", "default_priority", "notes", "lines"],
        ["number", "customer_name", "lines"] if obj is None else [],
    )
    if obj is None:
        obj = SalesOrder()
    else:
        require(obj.status == "DRAFT", "只有草稿销售单可修改", "IMMUTABLE", 409)
    for key in ["number", "customer_name", "default_priority", "notes"]:
        if key in data:
            setattr(obj, key, data[key])
    require(
        obj.number.strip()
        and len(obj.number) <= 60
        and obj.customer_name.strip()
        and len(obj.customer_name) <= 120
        and obj.default_priority in PRIORITIES,
        "销售单信息或优先级无效",
    )
    if obj.pk:
        touch(obj)
    else:
        obj.save()
    if "lines" in data:
        require(isinstance(data["lines"], list) and data["lines"], "销售单必须包含商品")
        obj.lines.all().delete()
        for i, row in enumerate(data["lines"], 1):
            fields(
                row,
                ["item_id", "quantity", "priority_override", "bom_id", "position"],
                ["item_id", "quantity"],
                protocol=False,
            )
            item = get(Item, row["item_id"])
            require(item.active and item.type != "RAW", "只能销售启用的成品或半成品")
            priority = row.get("priority_override")
            require(priority is None or priority in PRIORITIES, "行优先级无效")
            validated_bom = choose_bom(item, row.get("bom_id"))
            bom = validated_bom if row.get("bom_id") else None
            SalesLine.objects.create(
                order=obj,
                position=row.get("position", i),
                item=item,
                bom=bom,
                qty_u=quantity(row["quantity"], item.unit),
                priority_override=priority,
            )
    require(obj.lines.exists(), "销售单必须包含商品")
    for line in obj.lines.select_related("item__unit"):
        require(line.item.active and line.item.type != "RAW", "只能销售启用的成品或半成品")
        choose_bom(line.item, line.bom_id)
    return obj


def confirm_sale(obj):
    require(obj.status == "DRAFT", "销售单不可重复确认", "IMMUTABLE", 409)
    for line in obj.lines.select_related("item__unit"):
        require(line.item.active, "销售物料已停用")
        line.bom = choose_bom(line.item, line.bom_id)
        line.effective_priority = line.priority_override or obj.default_priority
        line.item_snapshot_json = snapshot(line.item)
        line.bom_snapshot_json = bom_snapshot(line.bom)
        line.save()
    obj.status, obj.confirmed_at = "CONFIRMED", now()
    touch(obj)
