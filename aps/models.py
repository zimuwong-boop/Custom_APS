from django.db import models
from django.db.models import F, Q


class Versioned(models.Model):
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Unit(models.Model):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=50)
    decimal_places = models.PositiveSmallIntegerField(default=0)

    class Meta:
        pass
        constraints = [
            models.CheckConstraint(condition=Q(decimal_places__lte=6), name="unit_precision_range")
        ]


class Item(Versioned):
    code = models.CharField(max_length=60, unique=True)
    name = models.CharField(max_length=120)
    type = models.CharField(max_length=10)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT)
    active = models.BooleanField(default=True)

    class Meta:
        pass
        constraints = [
            models.CheckConstraint(
                condition=Q(type__in=["FINISHED", "SEMI", "RAW"]), name="item_type_valid"
            )
        ]
        indexes = [models.Index(fields=["type", "active"])]


class BOM(Versioned):
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    revision = models.CharField(max_length=40)
    base_qty_u = models.BigIntegerField()
    status = models.CharField(max_length=10, default="DRAFT")
    description = models.TextField(blank=True)
    activated_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["item", "revision"], name="unique_bom_revision"),
            models.UniqueConstraint(
                fields=["item"], condition=Q(status="ACTIVE"), name="one_active_bom"
            ),
            models.CheckConstraint(
                condition=Q(base_qty_u__gt=0, base_qty_u__lte=10**15), name="bom_base_positive"
            ),
        ]


class BOMLine(models.Model):
    bom = models.ForeignKey(BOM, on_delete=models.CASCADE, related_name="lines")
    position = models.PositiveIntegerField()
    component_item = models.ForeignKey(Item, on_delete=models.PROTECT)
    child_bom = models.ForeignKey(
        BOM, on_delete=models.PROTECT, null=True, related_name="parent_lines"
    )
    qty_u = models.BigIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["bom", "position"], name="unique_bom_position"),
            models.UniqueConstraint(fields=["bom", "component_item"], name="unique_bom_component"),
            models.CheckConstraint(
                condition=Q(qty_u__gt=0, qty_u__lte=10**15), name="bom_component_positive"
            ),
        ]


class SalesOrder(Versioned):
    number = models.CharField(max_length=60, unique=True)
    customer_name = models.CharField(max_length=120)
    default_priority = models.CharField(max_length=10, default="NORMAL")
    status = models.CharField(max_length=25, default="DRAFT")
    notes = models.TextField(blank=True)
    confirmed_at = models.DateTimeField(null=True)
    production_completed_at = models.DateTimeField(null=True)
    cancelled_at = models.DateTimeField(null=True)
    cancel_reason = models.TextField(blank=True)
    progress_num = models.TextField(default="0")
    progress_den = models.TextField(default="1")

    class Meta:
        pass
        indexes = [models.Index(fields=["status", "default_priority"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(default_priority__in=["HIGH", "NORMAL", "LOW"]),
                name="sale_priority_valid",
            )
        ]


class SalesLine(models.Model):
    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="lines")
    position = models.PositiveIntegerField()
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    qty_u = models.BigIntegerField()
    priority_override = models.CharField(max_length=10, null=True)
    effective_priority = models.CharField(max_length=10, null=True)
    bom = models.ForeignKey(BOM, on_delete=models.PROTECT, null=True)
    item_snapshot_json = models.JSONField(default=dict)
    bom_snapshot_json = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["order", "position"], name="unique_sales_position"),
            models.CheckConstraint(
                condition=Q(qty_u__gt=0, qty_u__lte=10**15), name="sales_quantity_positive"
            ),
        ]


class PlanRun(Versioned):
    number = models.CharField(max_length=60, unique=True)
    formal_sequence = models.PositiveIntegerField(null=True, unique=True)
    status = models.CharField(max_length=15, default="DRAFT")
    schema_version = models.PositiveIntegerField(default=1)
    source_data_revision = models.PositiveIntegerField()
    dataset_epoch = models.PositiveIntegerField()
    graph_json = models.JSONField(default=dict)
    validation_json = models.JSONField(default=dict)
    replaces_plan_ids_json = models.JSONField(default=list)
    confirmed_at = models.DateTimeField(null=True)
    revoked_at = models.DateTimeField(null=True)
    revoke_reason = models.TextField(blank=True)


class ProductionOrder(Versioned):
    number = models.CharField(max_length=80, unique=True)
    batch_number = models.CharField(max_length=80, unique=True)
    plan = models.ForeignKey(PlanRun, on_delete=models.PROTECT, related_name="orders")
    plan_node_key = models.CharField(max_length=80)
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    bom = models.ForeignKey(BOM, on_delete=models.PROTECT)
    item_snapshot_json = models.JSONField(default=dict)
    bom_snapshot_json = models.JSONField(default=dict)
    priority = models.CharField(max_length=10)
    planned_qty_u = models.BigIntegerField()
    rounding_surplus_qty_u = models.BigIntegerField(default=0)
    frozen_level = models.PositiveIntegerField()
    node_sequence = models.PositiveIntegerField()
    child_weight_bp = models.PositiveIntegerField(null=True)
    own_progress_bp = models.PositiveIntegerField(default=0)
    progress_num = models.TextField(default="0")
    progress_den = models.TextField(default="1")
    retained_completed_qty_num = models.TextField(default="0")
    retained_completed_qty_den = models.TextField(default="1")
    status = models.CharField(max_length=15, default="READY")
    graph_revision = models.PositiveIntegerField(default=1)
    actual_started_at = models.DateTimeField(null=True)
    completed_at = models.DateTimeField(null=True)
    completion_mode = models.CharField(max_length=10, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["plan", "plan_node_key"], name="unique_plan_node"),
            models.CheckConstraint(
                condition=Q(planned_qty_u__gt=0, planned_qty_u__lte=10**15),
                name="production_quantity_positive",
            ),
            models.CheckConstraint(
                condition=Q(own_progress_bp__lte=10000), name="own_progress_range"
            ),
            models.CheckConstraint(
                condition=Q(child_weight_bp__isnull=True) | Q(child_weight_bp__lte=10000),
                name="child_weight_range",
            ),
            models.CheckConstraint(
                condition=Q(
                    rounding_surplus_qty_u__gte=0, rounding_surplus_qty_u__lte=F("planned_qty_u")
                ),
                name="production_surplus_range",
            ),
        ]
        indexes = [models.Index(fields=["status", "priority"], name="production_status_priority")]


class ProductionDependency(models.Model):
    active = models.BooleanField(default=True)
    supplier_order = models.ForeignKey(
        ProductionOrder, on_delete=models.PROTECT, related_name="consumers"
    )
    consumer_order = models.ForeignKey(
        ProductionOrder, on_delete=models.PROTECT, related_name="suppliers"
    )
    qty_u = models.BigIntegerField()
    usage_confirmed_at = models.DateTimeField(null=True)
    component_snapshot_json = models.JSONField(default=dict)
    source_detail_json = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["supplier_order", "consumer_order"], name="unique_dependency"
            ),
            models.CheckConstraint(
                condition=~Q(supplier_order=F("consumer_order")), name="no_self_dependency"
            ),
            models.CheckConstraint(condition=Q(qty_u__gt=0), name="dependency_quantity_positive"),
        ]


class SalesAllocation(models.Model):
    production_order = models.ForeignKey(
        ProductionOrder, on_delete=models.PROTECT, related_name="sales_allocations"
    )
    sales_line = models.ForeignKey(SalesLine, on_delete=models.PROTECT, related_name="allocations")
    qty_u = models.BigIntegerField()
    fulfillment_confirmed_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["production_order", "sales_line"], name="unique_sales_allocation"
            )
        ]


class MaterialRequirement(models.Model):
    production_order = models.ForeignKey(
        ProductionOrder, on_delete=models.PROTECT, related_name="raw_requirements"
    )
    raw_item = models.ForeignKey(Item, on_delete=models.PROTECT)
    bom_line_position = models.PositiveIntegerField()
    item_snapshot_json = models.JSONField(default=dict)
    theoretical_qty_num = models.TextField()
    theoretical_qty_den = models.TextField()
    qty_u = models.BigIntegerField()
    rounding_delta_u = models.BigIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["production_order", "bom_line_position"], name="unique_raw_bom_position"
            ),
            models.CheckConstraint(condition=Q(qty_u__gt=0), name="raw_quantity_positive"),
        ]


class ProgressEvent(models.Model):
    production_order = models.ForeignKey(
        ProductionOrder, on_delete=models.PROTECT, related_name="progress_events"
    )
    event_type = models.CharField(max_length=15)
    old_own_bp = models.PositiveIntegerField()
    new_own_bp = models.PositiveIntegerField()
    reason = models.TextField(blank=True)
    request_id = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)


class AuditEvent(models.Model):
    event_type = models.CharField(max_length=40)
    entity_type = models.CharField(max_length=40)
    entity_id_text = models.CharField(max_length=80)
    before_json = models.JSONField(default=dict)
    after_json = models.JSONField(default=dict)
    affected_entities_json = models.JSONField(default=list)
    reason = models.TextField(blank=True)
    request_id = models.CharField(max_length=80)
    dataset_epoch = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["entity_type", "entity_id_text"], name="audit_entity_lookup")
        ]


class IdempotencyRequest(models.Model):
    epoch = models.PositiveIntegerField()
    key = models.CharField(max_length=120)
    request_hash = models.CharField(max_length=64)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=200)
    status_code = models.PositiveIntegerField()
    response_json = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["epoch", "key"], name="unique_idempotency_key")
        ]


class NumberSequence(models.Model):
    name = models.CharField(max_length=40, unique=True)
    next_value = models.PositiveIntegerField(default=1)


class SystemState(models.Model):
    dataset_epoch = models.PositiveIntegerField(default=1)
    data_revision = models.PositiveIntegerField(default=1)
    active_plan = models.ForeignKey(PlanRun, on_delete=models.SET_NULL, null=True)
    demo_fixture_version = models.CharField(max_length=40, blank=True)
    schema_version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)
