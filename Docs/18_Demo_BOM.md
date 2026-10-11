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

- 当前 Docker 演示库已导入：3 种成品、2 种半成品、6 种原料，5 个 DEMO-V1 生效 BOM。
- “塑料标准”统一命名为“塑料包装”；蒜蓉酱半成品以份计，每份包含 150 克蒜蓉和 50 克油；瓶装蒜蓉酱以瓶计，各成品以包装计。
- 销售单编号 DEMO-SO-001～020，覆盖单品、混合成品、混合半成品、成品与半成品混合；使用 HIGH / NORMAL / LOW 三种优先级，全部已确认。
- 当前有排产草稿建议，正式生产单、生产批次均为 0。请在排产页面调整并手工确认。
- 导入工具：[load_demo_bom.py](../aps/management/commands/load_demo_bom.py)。仅允许空业务库，整批失败回滚，不覆盖现有数据；基础单位可保留。
- 初始备份：[demo-initial-20261011-v2.sqlite3](../backups/demo-initial-20261011-v2.sqlite3)，容器数据卷内另存同名备份；已通过 SQLite integrity_check。备份包含销售确认、BOM、排产建议和审计。

### 在另一台机器恢复初始状态

先按 [部署说明](11_Deployment_Operations.md) 准备同版本镜像、`.env`，并启动一次服务建立数据卷。将备份复制到目标项目的 `backups` 目录，然后执行：

```sh
docker compose cp backups/demo-initial-20261011-v2.sqlite3 aps:/data/demo-initial-20261011-v2.sqlite3
docker compose stop aps
docker run --rm -v custom_aps_data:/data --entrypoint python custom-aps:local \
  scripts/restore_sqlite.py /data/demo-initial-20261011-v2.sqlite3 /data/aps.sqlite3 --service-stopped
docker compose start aps
docker compose exec aps python manage.py check_demo_integrity
```

恢复会保留当前库的 `.before-restore` 安全副本；再次恢复前须归档该副本。恢复工具使旧页面失效，并将备份中的排产草稿标记为已替代。刷新页面后在排产端重新生成建议即可；销售单、物料和 BOM 恢复到初始数据，不自动建立生产单。

取消缩量功能新增数据库迁移后，提供了升级结构的 v2 初始备份；演示物料、20张销售单和无生产单状态不变。原始备份仍保留，当前代码的恢复工具应使用 v2 文件。
