from django.core.management.base import BaseCommand

from aps.models import SystemState, Unit


class Command(BaseCommand):
    help = "Initialize units and system state, without any business demonstration data."

    def handle(self, *args, **options):
        SystemState.objects.get_or_create(pk=1)
        for code, name, places in [("PCS", "个", 0), ("KG", "千克", 6), ("L", "升", 6)]:
            Unit.objects.get_or_create(code=code, defaults={"name": name, "decimal_places": places})
        self.stdout.write(self.style.SUCCESS("基础单位与系统状态已初始化；业务数据保持为空。"))
