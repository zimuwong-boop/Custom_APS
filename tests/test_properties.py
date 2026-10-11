"""Generated arithmetic properties use temporary records only."""

from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aps.core import now
from aps.models import BOM, Item, PlanRun, ProductionDependency, ProductionOrder, Unit
from aps.progress import recompute


@pytest.mark.django_db
@settings(max_examples=30, deadline=None)
@given(
    values=st.lists(st.integers(min_value=0, max_value=10000), min_size=1, max_size=6),
    weight=st.integers(min_value=0, max_value=10000),
)
def test_progress_equal_child_weights_exact_and_bounded(values, weight):
    # Hypothesis examples run in one pytest transaction; distinct fixture rows avoid collisions.
    number = ProductionOrder.objects.count()
    unit, _ = Unit.objects.get_or_create(
        code="PROP", defaults={"name": "Temporary", "decimal_places": 0}
    )
    item = Item.objects.create(code=f"PROP-{number}", name="Temporary", type="SEMI", unit=unit)
    bom = BOM.objects.create(item=item, revision="V1", base_qty_u=1_000_000, status="ACTIVE")
    plan = PlanRun.objects.create(
        number=f"PROP-{number}", source_data_revision=1, dataset_epoch=1, status="CONFIRMED"
    )

    def create(suffix, bp, w, level):
        return ProductionOrder.objects.create(
            number=f"{number}-{suffix}",
            batch_number=f"{number}-{suffix}",
            plan=plan,
            plan_node_key=str(suffix),
            item=item,
            bom=bom,
            priority="NORMAL",
            planned_qty_u=1_000_000,
            frozen_level=level,
            node_sequence=suffix,
            child_weight_bp=w,
            own_progress_bp=bp,
            actual_started_at=now() if w is None else None,
        )

    parent = create(0, 0, weight, 0)
    for index, value in enumerate(values, 1):
        child = create(index, value, None, 1)
        ProductionDependency.objects.create(
            supplier_order=child, consumer_order=parent, qty_u=1_000_000
        )
    recompute()
    parent.refresh_from_db()
    expected = (
        Fraction(weight, 10000)
        * sum((Fraction(v, 10000) for v in values), Fraction())
        / len(values)
    )
    actual = Fraction(int(parent.progress_num), int(parent.progress_den))
    assert actual == expected and 0 <= actual <= 1
    if any(v < 10000 for v in values):
        assert parent.status == "WAITING"
