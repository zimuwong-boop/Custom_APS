"""Load the explicitly requested Docs/18 demo through the normal API transaction boundary."""

import json
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.test import Client

from aps.models import BOM, Item, ProductionOrder, SalesOrder, SystemState, Unit


class Command(BaseCommand):
    help = "Create the Docs/18 garlic sauce baseline; refuses nonempty business databases."

    @transaction.atomic
    def handle(self, *args, **options):
        if (
            Item.objects.exists()
            or BOM.objects.exists()
            or SalesOrder.objects.exists()
            or ProductionOrder.objects.exists()
        ):
            raise CommandError("业务库非空，拒绝覆盖；请保留现有数据后再选择空库导入。")
        client = Client(HTTP_HOST="localhost")
        token = client.get("/api/v1/bootstrap").json()["data"]["csrf_token"]

        def post(path, body):
            response = client.post(
                "/api/v1/" + path,
                data=json.dumps(
                    {"dataset_epoch": SystemState.objects.get(pk=1).dataset_epoch, **body}
                ),
                content_type="application/json",
                HTTP_X_CSRFTOKEN=token,
                HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
            )
            if response.status_code not in (200, 201):
                raise CommandError(f"{path}: {response.content.decode()}")
            return response.json()["data"]

        for code, name in [("BOTTLE", "瓶"), ("PACK", "包装"), ("PORTION", "份"), ("G", "克")]:
            Unit.objects.get_or_create(code=code, defaults={"name": name, "decimal_places": 0})
        definitions = [
            ("DEMO-PLASTIC", "塑料包装", "RAW", "PCS"),
            ("DEMO-SMALL-BOX", "小纸箱", "RAW", "PCS"),
            ("DEMO-LARGE-BOX", "大纸箱", "RAW", "PCS"),
            ("DEMO-BOTTLE", "玻璃瓶", "RAW", "PCS"),
            ("DEMO-GARLIC", "蒜蓉", "RAW", "G"),
            ("DEMO-OIL", "油", "RAW", "G"),
            ("DEMO-SAUCE-BULK", "蒜蓉酱半成品", "SEMI", "PORTION"),
            ("DEMO-SAUCE", "蒜蓉酱", "SEMI", "BOTTLE"),
            ("DEMO-A", "A包装蒜蓉酱", "FINISHED", "PACK"),
            ("DEMO-B", "B包装蒜蓉酱", "FINISHED", "PACK"),
            ("DEMO-C", "C包装蒜蓉酱", "FINISHED", "PACK"),
        ]
        items = {}
        for code, name, kind, unit in definitions:
            items[code] = post(
                "items",
                {
                    "code": code,
                    "name": name,
                    "type": kind,
                    "is_sellable": kind == "FINISHED" or code == "DEMO-SAUCE",
                    "unit_id": Unit.objects.get(code=unit).id,
                },
            )
        recipes = [
            ("DEMO-SAUCE-BULK", [("DEMO-GARLIC", "150"), ("DEMO-OIL", "50")]),
            ("DEMO-SAUCE", [("DEMO-SAUCE-BULK", "1"), ("DEMO-BOTTLE", "1")]),
            ("DEMO-A", [("DEMO-SAUCE", "12"), ("DEMO-PLASTIC", "1")]),
            ("DEMO-B", [("DEMO-SAUCE", "24"), ("DEMO-SMALL-BOX", "1")]),
            ("DEMO-C", [("DEMO-SAUCE", "36"), ("DEMO-LARGE-BOX", "1")]),
        ]
        boms = {}
        for code, components in recipes:
            draft = post(
                "boms",
                {
                    "item_id": items[code]["id"],
                    "revision": "DEMO-V1",
                    "base_quantity": "1",
                    "lines": [
                        {
                            "component_item_id": items[component]["id"],
                            "child_bom_id": boms[component]["id"] if component in boms else None,
                            "quantity": quantity,
                        }
                        for component, quantity in components
                    ],
                },
            )
            boms[code] = post(
                f"boms/{draft['id']}/activate", {"expected_version": draft["version"]}
            )
        combinations = [
            ["DEMO-A"],
            ["DEMO-B"],
            ["DEMO-C"],
            ["DEMO-SAUCE"],
            ["DEMO-SAUCE-BULK"],
            ["DEMO-A", "DEMO-B"],
            ["DEMO-B", "DEMO-C"],
            ["DEMO-A", "DEMO-C"],
            ["DEMO-A", "DEMO-B", "DEMO-C"],
            ["DEMO-SAUCE", "DEMO-SAUCE-BULK"],
            ["DEMO-A", "DEMO-SAUCE"],
            ["DEMO-B", "DEMO-SAUCE"],
            ["DEMO-C", "DEMO-SAUCE"],
            ["DEMO-A", "DEMO-SAUCE-BULK"],
            ["DEMO-B", "DEMO-SAUCE-BULK"],
            ["DEMO-C", "DEMO-SAUCE-BULK"],
            ["DEMO-A", "DEMO-B", "DEMO-SAUCE"],
            ["DEMO-B", "DEMO-C", "DEMO-SAUCE-BULK"],
            ["DEMO-A", "DEMO-SAUCE", "DEMO-SAUCE-BULK"],
            ["DEMO-A", "DEMO-B", "DEMO-C", "DEMO-SAUCE", "DEMO-SAUCE-BULK"],
        ]
        for index, products in enumerate(combinations, 1):
            # Intermediate bulk sauce is a production component, never a sale item.
            if "DEMO-SAUCE-BULK" in products:
                products = [code for code in products if code != "DEMO-SAUCE-BULK"]
                replacement = next(
                    (
                        code
                        for code in ["DEMO-SAUCE", "DEMO-A", "DEMO-B", "DEMO-C"]
                        if code not in products
                    ),
                    None,
                )
                if replacement:
                    products.append(replacement)
            sale = post(
                "sales-orders",
                {
                    "number": f"DEMO-SO-{index:03d}",
                    "customer_name": f"演示客户{(index - 1) % 5 + 1:02d}",
                    "default_priority": ["HIGH", "NORMAL", "LOW"][(index - 1) % 3],
                    "notes": "Docs/18 演示初始状态；未建立正式生产单。",
                    "lines": [
                        {
                            "item_id": items[code]["id"],
                            "quantity": str(5 + index * 2 + position * 3),
                        }
                        for position, code in enumerate(products)
                    ],
                },
            )
            post(f"sales-orders/{sale['id']}/confirm", {"expected_version": sale["version"]})
        if ProductionOrder.objects.exists():
            raise CommandError("不应生成正式生产单。")
        self.stdout.write(
            self.style.SUCCESS(
                "11 种物料、5 个生效 BOM、20 张已确认销售单及排产建议已创建；生产单为 0。"
            )
        )
