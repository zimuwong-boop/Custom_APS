# 调研与参考资料

核对日期：2026-10-10。以下只作为业务及技术依据；本项目按已确认需求自行实现，不声称照搬项目即可满足所有定制规则。

| 来源 | 参考内容 | 本项目取舍 |
|---|---|---|
| [ERPNext GitHub](https://github.com/frappe/erpnext) | 开源制造和销售模块 | 参考模型和流程，不引入完整ERP运行环境 |
| [ERPNext Production Plan](https://docs.frappe.io/erpnext/production-plan) | 多销售来源、生产项与共用半成品合并 | 增加同优先级规则，排除库存和采购执行 |
| [ERPNext Production Plan源码入口](https://github.com/frappe/erpnext/blob/develop/erpnext/manufacturing/doctype/production_plan/production_plan.py) | 计划服务与销售来源组织 | 只作为阅读入口，分支内容可能变化 |
| [Odoo GitHub](https://github.com/odoo/odoo) | 制造模块 | 参考拆合交互 |
| [Odoo生产单拆分与合并](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/manufacturing/workflows/split_merge.html) | 同产品和同BOM合并 | 加入优先级约束与本项目批次追溯 |
| [Odoo多层BOM](https://www.odoo.com/documentation/18.0/applications/inventory_and_mrp/manufacturing/advanced_configuration/sub_assemblies.html) | 子装配拥有独立BOM | 不引入补货和库存路由 |
| [frePPLe GitHub](https://github.com/frePPLe/frepple) | 开源供应链计划 | 参考需求关联，不采用完整优化引擎 |
| [frePPLe生产单模型](https://frepple.com/docs/current/model-reference/manufacturing-orders.html) | 建议/确认状态和需求数量关联 | 本项目人工确认后冻结图 |
| [frePPLe优先级](https://frepple.com/docs/current/examples/demand/demand-priorities.html) | 优先级排序 | 本期不预测产能约束完工时间 |
| [Django SQLite说明](https://docs.djangoproject.com/en/5.2/ref/databases/#sqlite-notes) | 写并发、事务模式、无select_for_update行锁 | 短事务、版本和幂等，不假设行锁有效 |
| [Django事务](https://docs.djangoproject.com/en/5.2/topics/db/transactions/) | atomic和提交行为 | 核心传播在事务内完成 |
| [Django版本信息](https://www.djangoproject.com/download/) | 支持版本信息 | M1实施时确认并锁定实际版本 |
| [Docker volumes](https://docs.docker.com/engine/storage/volumes/) | 容器外持久化 | SQLite数据置于/data卷 |
| [Mermaid ER语法](https://mermaid.js.org/syntax/entityRelationshipDiagram.html) | 文档ER图表达 | Markdown嵌入可维护图源 |

文档中的生产进度占比、销售等权平均、严格整单放行、独立批次层级规则来自用户讨论，不是上述系统原生能力的断言。
