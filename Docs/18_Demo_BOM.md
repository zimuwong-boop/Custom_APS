# 演示数据BOM表

1.成品
a.A包装蒜蓉酱（12瓶蒜蓉酱和1个塑料包装组成）
b.B包装蒜蓉酱（24瓶蒜蓉酱和1个小纸箱组成）
c.C包装蒜蓉酱（36瓶蒜蓉酱和1一个大纸箱组成）
2.半成品
a.蒜蓉酱（一份蒜蓉半成品和一个玻璃瓶组成）
b.蒜蓉酱半成品（150克蒜蓉和50克油组成）
3.原料
a.塑料标准
b.小纸箱
c.大纸箱
d.玻璃瓶
e.蒜蓉
f.油

# 演示数据销售单

创建二十张销售单，要包含只有单一品类的销售单和混合品类的销售单，也要包含混合了成品和半成品的销售单

# 生产单

生产单目前不要建立，只根据销售单作出排产建议然后由演示者手工开始操作

# 备份

为此次演示数据创建备份，为以后不同地方演示可以快速恢复以本文档状态描述的初始状态

## 已创建的初始状态（2026-10-11）

- 初始演示基线包含：3 种成品、2 种半成品、6 种原料，5 个 DEMO-V1 生效 BOM。
- “塑料标准”统一命名为“塑料包装”；蒜蓉酱半成品以份计，每份包含 150 克蒜蓉和 50 克油；瓶装蒜蓉酱以瓶计，各成品以包装计。
- 销售单编号 DEMO-SO-001～020，覆盖单品、混合成品、瓶装半成品单品、成品与瓶装半成品混合，共41条明细；使用 HIGH / NORMAL / LOW 三种优先级，全部已确认。
- 初始基线有排产草稿建议，正式生产单、生产批次均为 0。请在排产页面调整并手工确认。
- 导入工具：[load_demo_bom.py](../aps/management/commands/load_demo_bom.py)。仅允许空业务库，整批失败回滚，不覆盖现有数据；基础单位可保留。
- 初始备份：[deploy/demo-initial.sqlite3](../deploy/demo-initial.sqlite3)（v3基线，随仓库和部署包分发）；已通过 SQLite integrity_check。备份包含销售确认、BOM、排产建议和审计。

### 在另一台机器恢复初始状态

先按 [部署说明](11_Deployment_Operations.md) 准备同版本镜像、`.env`，并启动一次服务建立数据卷。根目录Compose实例可使用仓库内初始库，然后执行：

```sh
docker compose cp deploy/demo-initial.sqlite3 aps:/data/demo-initial-20261011-v3.sqlite3
docker compose stop aps
docker run --rm -v custom_aps_data:/data --entrypoint python custom-aps:local \
  scripts/restore_sqlite.py /data/demo-initial-20261011-v3.sqlite3 /data/aps.sqlite3 --service-stopped
docker compose start aps
docker compose exec aps python manage.py check_demo_integrity
```

恢复会保留当前库的 `.before-restore` 安全副本；再次恢复前须归档该副本。恢复工具使旧页面失效，并将备份中的排产草稿标记为已替代。刷新页面后在排产端重新生成建议即可；销售单、物料和 BOM 恢复到初始数据，不自动建立生产单。

取消缩量功能新增数据库迁移后，提供了升级结构的 v2 初始备份；演示物料、20张销售单和无生产单状态不变。原始备份仍保留，当前代码的恢复工具应使用 v3 文件。

### 半成品销售资格修正

瓶装蒜蓉酱（DEMO-SAUCE）允许直接销售；蒜蓉酱中间料（DEMO-SAUCE-BULK）仅供生产，不允许直接销售。新初始数据仍包含20张确认销售单，销售明细改为41条，不含中间料直销。已部署实例保留历史销售和生产记录，升级不会自动取消历史订单或清空演示操作。v3初始备份包含销售资格字段和第5个迁移。

上述数字描述初始基线，实际实例经演示操作后可能已有生产单。快速部署包使用独立项目和数据卷，复演直接运行 [deploy说明](../deploy/README.md) 中的 reset-demo.sh；本节 custom_aps_data 命令仅适用于根目录Compose实例。v1/v2备份属于历史结构，不能直接用于当前严格恢复工具；须在副本迁移后再恢复。
