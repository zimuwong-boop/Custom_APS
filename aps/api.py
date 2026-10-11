"""HTTP boundary: CSRF, epoch, idempotency and transactions cover every mutation."""

import hashlib
import json
import logging
import uuid

from django.conf import settings
from django.core import signing
from django.db import DatabaseError, IntegrityError, OperationalError, transaction
from django.db.models.deletion import ProtectedError
from django.http import FileResponse, HttpResponse, JsonResponse
from django.middleware.csrf import get_token

from . import cancellation, catalog, planning, progress, trace
from .core import (
    BusinessError,
    check_version,
    fields,
    now,
    qty,
    require,
    state,
    touch,
    validate_bom,
)
from .models import (
    BOM,
    AuditEvent,
    BOMLine,
    IdempotencyRequest,
    Item,
    MaterialRequirement,
    PlanRun,
    ProductionDependency,
    ProductionOrder,
    ProgressEvent,
    SalesAllocation,
    SalesLine,
    SalesOrder,
    SystemState,
    Unit,
)
from .serializers import serialize

logger = logging.getLogger(__name__)
READ_POST = {"revoke-preview", "cancel-preview", "reset-preview", "validate"}


def error(code, message, status, details=None, request_id=""):
    return JsonResponse(
        {
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "request_id": request_id,
            }
        },
        status=status,
    )


def csrf_failure(request, reason=""):
    return error(
        "CSRF_FAILED",
        "请求校验失败，请刷新页面",
        403,
        request_id=getattr(request, "request_id", ""),
    )


def page(request, queryset):
    try:
        p, size = int(request.GET.get("page", 1)), int(request.GET.get("page_size", 100))
    except ValueError:
        raise BusinessError("INVALID_PAGE", "分页参数无效", 400) from None
    require(p >= 1 and 1 <= size <= 500, "分页超出范围", status=400)
    search = request.GET.get("search", "").strip()
    if search:
        from django.db.models import Q

        columns = {f.name for f in queryset.model._meta.fields}
        names = [
            n
            for n in ["number", "code", "name", "customer_name", "batch_number", "event_type"]
            if n in columns
        ]
        condition = Q()
        for name in names:
            condition |= Q(**{f"{name}__icontains": search})
        queryset = queryset.filter(condition)
    for key in [
        "status",
        "type",
        "priority",
        "item_id",
        "plan_id",
        "event_type",
        "entity_type",
        "request_id",
        "entity_id_text",
    ]:
        if key in request.GET and key in {f.attname for f in queryset.model._meta.fields}:
            queryset = queryset.filter(**{key: request.GET[key]})
    return {
        "results": [
            serialize(o, False) for o in queryset.order_by("-id")[(p - 1) * size : p * size]
        ],
        "page": p,
        "page_size": size,
        "total": queryset.count(),
    }


def preview(kind, obj=None, plans=()):
    system = state()
    for plan in plans if kind != "cancel" else []:
        require(
            not plan.orders.filter(actual_started_at__isnull=False).exists()
            and not plan.orders.filter(progress_events__isnull=False).exists(),
            "关联排产已有生产操作，不能撤销",
            "PLAN_STARTED",
            409,
        )
    payload = {
        "kind": kind,
        "id": obj.id if obj else None,
        "version": obj.version if obj else None,
        "epoch": system.dataset_epoch,
        "revision": system.data_revision,
        "plans": [(p.id, p.version) for p in plans],
        "last_event_id": AuditEvent.objects.order_by("-id").values_list("id", flat=True).first()
        or 0,
    }
    return {
        "confirmation_token": signing.dumps(payload, salt="aps-preview"),
        "plan_ids": [p.id for p in plans],
        "production_order_ids": list(
            ProductionOrder.objects.filter(plan__in=plans).values_list("id", flat=True)
        ),
        "sales_order_ids": list(
            SalesOrder.objects.filter(lines__allocations__production_order__plan__in=plans)
            .values_list("id", flat=True)
            .distinct()
        ),
        "dataset_epoch": system.dataset_epoch,
        "data_revision": system.data_revision,
        "quantity_changes": cancellation.summary(obj, plans) if kind == "cancel" else [],
    }


def verify_preview(data, kind, obj=None, plans=()):
    require(data.get("confirm") is True, "需要明确确认影响范围", status=400)
    try:
        payload = signing.loads(data.get("confirmation_token", ""), salt="aps-preview", max_age=600)
    except signing.BadSignature:
        raise BusinessError("INVALID_CONFIRMATION", "确认令牌无效或过期", 409) from None
    expected = signing.loads(preview(kind, obj, plans)["confirmation_token"], salt="aps-preview")
    require(payload == expected, "影响范围已经改变，请重新预览", "STALE_PREVIEW", 409)


def route(request, parts, data):
    method = request.method
    resource = parts[0] if parts else ""
    pk = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    action = parts[2] if len(parts) > 2 else ""
    require(len(parts) <= 3, "接口不存在", "NOT_FOUND", 404)
    if resource == "bootstrap" and method == "GET":
        system = state()
        return (
            {
                "csrf_token": get_token(request),
                "dataset_epoch": system.dataset_epoch,
                "data_revision": system.data_revision,
                "enums": {
                    "item_types": ["FINISHED", "SEMI", "RAW"],
                    "priorities": ["HIGH", "NORMAL", "LOW"],
                },
            },
            200,
            None,
        )
    if resource == "units" and method == "GET":
        return page(request, Unit.objects.all()), 200, None
    if resource in ["items", "boms", "sales-orders"]:
        model, write = {
            "items": (Item, catalog.item_write),
            "boms": (BOM, catalog.bom_write),
            "sales-orders": (SalesOrder, catalog.sale_write),
        }[resource]
        obj = catalog.get(model, pk) if pk else None
        if method == "GET":
            require(
                not action or (action == "graph" and isinstance(obj, BOM)),
                "接口不存在",
                "NOT_FOUND",
                404,
            )
            if action == "graph" and isinstance(obj, BOM):
                nodes, edges, visited, queue = [], [], set(), [obj]
                while queue:
                    bom = queue.pop()
                    if bom.id in visited:
                        continue
                    visited.add(bom.id)
                    nodes.append(serialize(bom))
                    for line in bom.lines.all():
                        if line.child_bom_id:
                            edges.append(
                                {
                                    "consumer_bom_id": bom.id,
                                    "supplier_bom_id": line.child_bom_id,
                                    "quantity": qty(line.qty_u),
                                }
                            )
                            queue.append(line.child_bom)
                return {"nodes": nodes, "edges": edges}, 200, None
            return serialize(obj) if obj else page(request, model.objects.all()), 200, None
        if obj:
            check_version(obj, data)
        if method == "POST" and not obj or method == "PATCH" and obj and not action:
            obj = write(data, obj)
            state_changed()
            return serialize(obj), 201 if method == "POST" else 200, obj
        if method == "DELETE" and obj and not action:
            fields(data, [])
            if hasattr(obj, "status"):
                require(obj.status == "DRAFT", "只能删除草稿", "IMMUTABLE", 409)
            before = serialize(obj)
            obj.delete()
            state_changed()
            return {"deleted": True, "record": before}, 200, None
        if resource == "boms" and method == "POST":
            if action == "activate":
                fields(data, [])
                require(obj.status == "DRAFT", "仅草稿可生效", "IMMUTABLE", 409)
                validate_bom(obj, True)
                for previous in BOM.objects.filter(item=obj.item, status="ACTIVE"):
                    previous.status = "RETIRED"
                    touch(previous)
                obj.status, obj.activated_at = "ACTIVE", now()
                touch(obj)
            elif action == "retire":
                fields(data, ["reason"], ["reason"])
                require(
                    obj.status == "ACTIVE" and data["reason"].strip(),
                    "只有生效 BOM 可停用，且必须填写原因",
                )
                obj.status = "RETIRED"
                touch(obj)
            elif action == "clone":
                fields(data, ["new_revision"], ["new_revision"])
                source = serialize(obj)
                obj = catalog.bom_write(
                    {
                        "item_id": obj.item_id,
                        "revision": data["new_revision"],
                        "base_quantity": source["base_quantity"],
                        "description": obj.description,
                        "lines": [
                            {
                                "component_item_id": line["component_item_id"],
                                "child_bom_id": line["child_bom_id"],
                                "quantity": line["quantity"],
                            }
                            for line in source["lines"]
                        ],
                    }
                )
            else:
                raise BusinessError("NOT_FOUND", "操作不存在", 404)
            state_changed()
            return serialize(obj), 200, obj
        if resource == "sales-orders" and method == "POST":
            if action == "confirm":
                fields(data, [])
                catalog.confirm_sale(obj)
                state_changed()
                planning.recalculate()
            elif action == "cancel-preview":
                fields(data, [])
                return preview("cancel", obj, trace.sale_plans(obj)), 200, None
            elif action == "cancel":
                fields(
                    data,
                    ["reason", "confirm", "confirmation_token"],
                    ["reason", "confirm", "confirmation_token"],
                )
                require(
                    obj.status in ["DRAFT", "CONFIRMED", "PRODUCTION_COMPLETED"],
                    "销售单不可取消",
                    "IMMUTABLE",
                    409,
                )
                plans = trace.sale_plans(obj)
                verify_preview(data, "cancel", obj, plans)
                affected = cancellation.cancel(obj, plans, data["reason"], request.request_id)
                planning.recalculate()
                result = serialize(obj)
                result["affected_order_ids"] = affected
                return result, 200, obj
            else:
                raise BusinessError("NOT_FOUND", "操作不存在", 404)
            return serialize(obj), 200, obj
    if resource == "planning" and parts[1:] == ["demands"] and method == "GET":
        return (
            [
                {
                    "sales_line_id": line.id,
                    "sales_order_id": line.order_id,
                    "sales_order_number": line.order.number,
                    "item": line.item_snapshot_json,
                    "bom_id": line.bom_id,
                    "priority": line.effective_priority,
                    "pending_quantity": qty(amount),
                }
                for line, amount in planning.pending_lines()
            ],
            200,
            None,
        )
    if resource == "plans":
        if parts[1:] == ["current"] and method == "GET":
            current = state().active_plan
            return serialize(current) if current else None, 200, None
        if parts[1:] == ["recalculate"] and method == "POST":
            fields(data, ["expected_data_revision"], ["expected_data_revision"])
            require(
                data["expected_data_revision"] == state().data_revision,
                "排产需求已变化",
                "STALE_PLAN",
                409,
            )
            plan = planning.recalculate()
            return serialize(plan) if plan else None, 200, plan
        plan = catalog.get(PlanRun, pk)
        if method == "GET":
            require(not action, "接口不存在", "NOT_FOUND", 404)
            return serialize(plan), 200, None
        check_version(plan, data)
        if action == "graph" and method == "PUT":
            fields(data, ["graph"], ["graph"])
            require(
                plan.status == "DRAFT" and plan.source_data_revision == state().data_revision,
                "排产草稿已过期或冻结",
                "STALE_PLAN",
                409,
            )
            planning.validate_graph(data["graph"])
            plan.graph_json, plan.validation_json = data["graph"], {"valid": True}
            touch(plan)
        elif action == "adjust" and method == "POST":
            fields(data, ["operation"], ["operation"])
            require(
                plan.status == "DRAFT" and plan.source_data_revision == state().data_revision,
                "排产草稿已过期或冻结",
                "STALE_PLAN",
                409,
            )
            plan.graph_json, changes = planning.adjust_graph(plan.graph_json, data["operation"])
            plan.validation_json = {"valid": True, "quantity_changes": changes}
            touch(plan)
        elif action == "validate" and method == "POST":
            fields(data, [])
            planning.validate_graph(plan.graph_json)
            return {"valid": True}, 200, None
        elif action == "confirm" and method == "POST":
            fields(data, [])
            planning.confirm(plan)
            progress.recompute()
        elif action == "revoke-preview" and method == "POST":
            fields(data, [])
            return preview("revoke", plan, [plan]), 200, None
        elif action == "revoke" and method == "POST":
            fields(
                data,
                ["reason", "confirm", "confirmation_token"],
                ["reason", "confirm", "confirmation_token"],
            )
            verify_preview(data, "revoke", plan, [plan])
            planning.revoke_plans([plan], data["reason"])
            progress.recompute()
            planning.recalculate([plan.id])
        else:
            raise BusinessError("NOT_FOUND", "操作不存在", 404)
        return serialize(plan), 200, plan
    if resource == "production-orders":
        obj = catalog.get(ProductionOrder, pk) if pk else None
        if method == "GET":
            require(not action or (action == "graph" and obj), "接口不存在", "NOT_FOUND", 404)
            if action == "graph":
                return trace.graph([obj.id], request.GET.get("direction", "both"), True), 200, None
            return (
                serialize(obj) if obj else page(request, ProductionOrder.objects.all()),
                200,
                None,
            )
        check_version(obj, data)
        if action == "start" and method == "POST":
            fields(data, [])
            affected = progress.start(obj)
        elif action in ["progress", "correct-progress"] and method == "POST":
            fields(data, ["own_progress", "reason"], ["own_progress"])
            affected = progress.update(
                obj,
                data["own_progress"],
                request.request_id,
                action == "correct-progress",
                data.get("reason", ""),
            )
        else:
            raise BusinessError("NOT_FOUND", "操作不存在", 404)
        obj.refresh_from_db()
        result = serialize(obj)
        result["affected_order_ids"] = affected
        return result, 200, obj
    if resource == "trace" and method == "GET" and len(parts) == 3:
        if parts[1] == "sales-orders":
            sale = catalog.get(SalesOrder, int(parts[2]))
            ids = sale.lines.values_list("allocations__production_order_id", flat=True)
            return trace.graph(ids, "down", request.GET.get("include_history") == "true"), 200, None
        if parts[1] == "batches":
            order = ProductionOrder.objects.filter(batch_number=parts[2]).first()
            require(order is not None, "批次不存在", "NOT_FOUND", 404)
            return trace.graph([order.id], "both", True), 200, None
    if resource == "audit-events" and method == "GET":
        return (
            serialize(catalog.get(AuditEvent, pk))
            if pk
            else page(request, AuditEvent.objects.all()),
            200,
            None,
        )
    if resource == "demo":
        if parts[1:] == ["scenarios"] and method == "GET":
            return [], 200, None
        if parts[1:] == ["reset-preview"] and method == "POST":
            fields(data, ["scenario_code"])
            require(data.get("scenario_code") is None, "演示数据将在开发完成后规划")
            result = preview("reset")
            result["counts"] = {
                m.__name__: m.objects.count()
                for m in [Item, BOM, SalesOrder, PlanRun, ProductionOrder]
            }
            return result, 200, None
        if parts[1:] == ["reset"] and method == "POST":
            fields(
                data,
                ["scenario_code", "confirm", "confirmation_token"],
                ["confirm", "confirmation_token"],
            )
            require(data.get("scenario_code") is None, "当前仅支持重置为空数据")
            verify_preview(data, "reset")
            system = state()
            system.active_plan = None
            system.save()
            for model in [
                ProgressEvent,
                SalesAllocation,
                ProductionDependency,
                MaterialRequirement,
                ProductionOrder,
                PlanRun,
                SalesLine,
                SalesOrder,
                SystemState,
                BOMLine,
                BOM,
                Item,
                AuditEvent,
                IdempotencyRequest,
            ]:
                model.objects.all().delete()
            system.dataset_epoch += 1
            system.data_revision += 1
            system.save()
            return {"reset": True}, 200, None
    raise BusinessError("NOT_FOUND", "接口不存在或请求方法不支持", 404)


def state_changed():
    system = state()
    system.data_revision += 1
    system.save()


def api(request, path=""):
    request.request_id = getattr(request, "request_id", str(uuid.uuid4()))
    parts = path.strip("/").split("/")
    if parts[0] == "health" and request.method == "GET":
        try:
            if parts[1:] == ["ready"]:
                from django.db import connection
                from django.db.models import F

                with transaction.atomic():
                    system = state()
                    from django.db.migrations.recorder import MigrationRecorder

                    expected = {
                        path.stem
                        for path in (settings.BASE_DIR / "aps/migrations").glob("[0-9]*.py")
                    }
                    applied = set(
                        MigrationRecorder.Migration.objects.filter(app="aps").values_list(
                            "name", flat=True
                        )
                    )
                    if applied != expected:
                        return error("NOT_READY", "数据库迁移版本不匹配", 503)
                    if system.schema_version != 1:
                        return error("NOT_READY", "数据库结构版本不匹配", 503)
                    SystemState.objects.filter(pk=1).update(schema_version=F("schema_version"))
                    with connection.cursor() as cursor:
                        if cursor.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                            return error("NOT_READY", "数据库完整性校验失败", 503)
            elif parts[1:] != ["live"]:
                return error("NOT_FOUND", "接口不存在", 404)
            return JsonResponse({"data": {"status": "ok"}})
        except DatabaseError:
            return error("NOT_READY", "数据库尚未就绪", 503)
    try:
        require(
            request.method in ["GET", "POST", "PATCH", "PUT", "DELETE"], "方法不支持", status=405
        )
        data = {}
        if request.method != "GET":
            require(request.content_type == "application/json", "请使用 JSON 请求", status=400)
            try:
                data = json.loads(request.body)
            except (ValueError, UnicodeDecodeError):
                raise BusinessError("INVALID_JSON", "JSON 格式错误", 400) from None
            require(isinstance(data, dict), "请求必须是对象", status=400)
        mutating = request.method != "GET" and parts[-1] not in READ_POST
        with transaction.atomic():
            system = state()
            if request.method != "GET":
                require(
                    type(data.get("dataset_epoch")) is int
                    and data["dataset_epoch"] == system.dataset_epoch,
                    "当前数据已经重置，请刷新页面",
                    "STALE_EPOCH",
                    409,
                )
            if mutating:
                key = request.headers.get("Idempotency-Key", "")
                require(0 < len(key) <= 120, "写入必须提供 Idempotency-Key", status=400)
                digest = hashlib.sha256(
                    (
                        request.method
                        + request.path
                        + json.dumps(data, sort_keys=True, ensure_ascii=False)
                    ).encode()
                ).hexdigest()
                old = IdempotencyRequest.objects.filter(epoch=system.dataset_epoch, key=key).first()
                if old:
                    require(
                        old.request_hash == digest,
                        "幂等键已用于其他请求",
                        "IDEMPOTENCY_CONFLICT",
                        409,
                    )
                    return JsonResponse(old.response_json, status=old.status_code)
            before = {}
            if mutating and len(parts) > 1 and parts[1].isdigit():
                models = {
                    "items": Item,
                    "boms": BOM,
                    "sales-orders": SalesOrder,
                    "plans": PlanRun,
                    "production-orders": ProductionOrder,
                }
                model = models.get(parts[0])
                if model:
                    before = serialize(catalog.get(model, int(parts[1])))
            result, status_code, obj = route(request, parts, data)
            system = state()
            payload = {
                "data": result,
                "meta": {
                    "dataset_epoch": system.dataset_epoch,
                    "data_revision": system.data_revision,
                },
            }
            if mutating:
                AuditEvent.objects.create(
                    event_type=f"{parts[0]}:{parts[-1] if len(parts) > 2 else request.method}",
                    entity_type=parts[0],
                    entity_id_text=str(obj.pk) if obj else "",
                    before_json=before,
                    after_json=result if isinstance(result, dict) else {"result": result},
                    affected_entities_json=result.get("affected_order_ids", [])
                    if isinstance(result, dict)
                    else [],
                    reason=data.get("reason", ""),
                    request_id=request.request_id,
                    dataset_epoch=system.dataset_epoch,
                )
                IdempotencyRequest.objects.create(
                    epoch=system.dataset_epoch,
                    key=key,
                    request_hash=digest,
                    method=request.method,
                    path=request.path,
                    status_code=status_code,
                    response_json=payload,
                )
            return JsonResponse(payload, status=status_code)
    except BusinessError as exc:
        return error(exc.code, exc.message, exc.status, exc.details, request.request_id)
    except ProtectedError:
        return error("IMMUTABLE", "记录已被引用，无法删除", 409, request_id=request.request_id)
    except IntegrityError:
        return error(
            "CONSTRAINT_CONFLICT",
            "编码、版本或分配重复，或引用无效",
            409,
            request_id=request.request_id,
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        logger.warning("Invalid API input %s", request.path, exc_info=True)
        return error(
            "INVALID_REQUEST", "请求字段类型或格式无效", 400, request_id=request.request_id
        )
    except OperationalError:
        return error(
            "DATABASE_BUSY", "数据库繁忙或未就绪，请稍后重试", 503, request_id=request.request_id
        )


def index(request):
    if request.path.startswith("/api/"):
        return error("NOT_FOUND", "接口不存在", 404)
    path = settings.BASE_DIR / "frontend/dist/index.html"
    if path.exists():
        return FileResponse(path.open("rb"), content_type="text/html")
    return HttpResponse("前端尚未构建，请运行 make frontend-check", status=503)
