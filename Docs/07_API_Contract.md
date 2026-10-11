# API 契约

版本：2.1 · 原始基线：2026-10-10 · 修订：2026-10-11 · 状态：当前需求与实现基线。

路径前缀 `/api/v1`（无结尾斜杠）；以 [api.py](../aps/api.py) 和 [serializers.py](../aps/serializers.py) 为当前接口依据。旧设计字段不作为并列契约。

## 通用协议

- JSON UTF-8；业务成功响应为 `data` 加 `meta.dataset_epoch/data_revision`；健康接口仅返回 `data.status`。创建201，其余成功200；DELETE草稿返回删除标识及记录。
- 错误返回 `error.code/message/details/request_id`；响应头包含 X-Request-ID。details 可为空，不保证返回路径、阻塞ID或最新版本；客户端重新GET相关实体刷新。
- 列表默认 page=1、page_size=100，最大500，返回 results/page/page_size/total。支持 search；按字段存在性过滤 status/type/priority/item_id/plan_id/event_type/entity_type/request_id/entity_id_text。
- 数量与百分比用十进制字符串，ID为整数，时间ISO 8601 UTC。优先级字符串HIGH/NORMAL/LOW。
- 所有非GET请求含 dataset_epoch；修改既有实体含 expected_version；业务写入请求头含 Idempotency-Key。服务端先验证epoch，再判定幂等重放；同键同请求返回原结果，同键不同请求409，失败不保存成功记录。
- GET /bootstrap 返回 CSRF token并设置cookie；后续非GET带 X-CSRFToken。无身份会话或Authorization头。
- 不允许客户端写status、progress、批次号、冻结层级等派生字段，未知字段（包括嵌套行）拒绝。
- 只读POST：cancel-preview、revoke-preview、reset-preview、validate，不写审计/版本，不要求幂等键；仍验证epoch、CSRF，实体动作仍要求版本。

## 路由清单

表中“通用”表示上述epoch、版本及业务写入幂等字段。

| 方法与路径 | 请求要点 | 作用 |
|---|---|---|
| GET /bootstrap | 无 | csrf_token、epoch、revision、物料/优先级枚举 |
| GET /units | 分页 | 只读单位及精度；无单位CRUD |
| GET /items | 列表参数 | 物料信息、单位ID、启用状态及有效 is_sellable |
| POST /items | code、name、type、unit_id、active?、is_sellable? | 创建物料 |
| GET /items/{id} | 无 | 当前物料 |
| PATCH /items/{id} | code/name/type/unit_id/active/is_sellable | 引用后code/type/unit不可修改 |
| DELETE /items/{id} | 通用 | 仅未引用物料 |
| GET /boms | item_id、status、分页 | BOM列表 |
| POST /boms | item_id、revision、base_quantity、lines、description? | 创建并验证草稿；子半成品须显式可用BOM |
| GET /boms/{id} | 无 | 当前版本与直接组成 |
| PATCH /boms/{id} | revision/base_quantity/description/完整lines | 仅草稿可修改；物料归属不变 |
| POST /boms/{id}/clone | new_revision | 复制为新草稿 |
| POST /boms/{id}/activate | 通用 | 校验完整图；旧默认版本转RETIRED |
| POST /boms/{id}/retire | reason | ACTIVE停止作为默认，显式历史引用仍可用 |
| DELETE /boms/{id} | 通用 | 仅无引用草稿 |
| GET /boms/{id}/graph | 无 | 完整去重BOM节点及制造边，非分页图 |
| GET /sales-orders | 列表参数 | 单头、行、覆盖数量、进度及根批次 |
| POST /sales-orders | number、customer_name、lines；default_priority/notes可选 | 草稿即强制已有启用制造项及完整可用BOM |
| GET /sales-orders/{id} | 无 | 销售详情 |
| PATCH /sales-orders/{id} | 草稿头字段/完整lines | 仅DRAFT；重新强制BOM校验 |
| DELETE /sales-orders/{id} | 通用 | 仅DRAFT |
| POST /sales-orders/{id}/confirm | 通用 | 重新校验、冻结BOM和行优先级，自动刷新建议 |
| POST /sales-orders/{id}/cancel-preview | 通用 | 签名confirmation_token、关联ID、逐批quantity_changes |
| POST /sales-orders/{id}/cancel | confirmation_token、reason、confirm=true | DRAFT/CONFIRMED/PRODUCTION_COMPLETED可取消；原地缩量、多级需求/进度重算，返回affected_order_ids |
| GET /planning/demands | 无 | 全部尚未安排的确认销售行，非分页列表 |
| GET /plans/current | 无 | 当前草稿；无建议为data=null |
| GET /plans/{id} | 无 | 指定计划详情，graph为原始/当前草稿快照 |
| POST /plans/recalculate | expected_data_revision | 刷新草稿，旧草稿SUPERSEDED |
| PUT /plans/{id}/graph | graph | 完整保存分配图并验证，只允许有效DRAFT |
| POST /plans/{id}/adjust | operation | split/merge/weight，自动BOM重展并返回validation.quantity_changes |
| POST /plans/{id}/validate | 通用 | 只读完整图校验 |
| POST /plans/{id}/confirm | 通用 | 原子正式落库，批次唯一，不重复确认 |
| POST /plans/{id}/revoke-preview | 通用 | 整计划影响；已有生产操作则409 |
| POST /plans/{id}/revoke | confirmation_token、reason、confirm=true | 未开工整计划撤销，关联销售恢复待排 |
| GET /production-orders | plan_id、priority、status、item_id、分页 | 当前数量、层级、状态、自身/总进度 |
| GET /production-orders/{id} | 无 | 快照、有效子单、销售分配、直接原料明细 |
| POST /production-orders/{id}/start | 通用 | 全部有效子单完成才允许开工 |
| POST /production-orders/{id}/progress | own_progress、reason? | 常规进度只能不下降，须已开工、子单完成且未完成 |
| POST /production-orders/{id}/correct-progress | own_progress、reason | 仅降低自身进度；检查下游并清除取消进度下限 |
| GET /production-orders/{id}/graph | direction=up/down/both，默认both | 依赖图；该接口包含历史边，active标识有效性 |
| GET /trace/sales-orders/{id} | include_history=true/false，默认false | 所有销售根的向下批次路径，含历史时保留无效边 |
| GET /trace/batches/{batch_number} | 无 | 批次双向历史图和销售去向 |
| GET /audit-events | entity_type/entity_id_text/request_id、分页 | 无操作人日志 |
| GET /audit-events/{id} | 无 | 单条前后审计 |
| GET /demo/scenarios | 无 | 当前空数组；18场景通过命令/备份加载，无菜单场景 |
| POST /demo/reset-preview | scenario_code可省略或null | 清空影响及confirmation_token |
| POST /demo/reset | scenario_code可省略或null、confirmation_token、confirm=true | 仅清空，递增epoch，保留序列/单位，旧请求失效 |
| GET /health/live | 无 | 进程存活，200 |
| GET /health/ready | 无 | 精确迁移清单、结构版本、SQLite完整性及写权限；异常503 |

不存在GET /plans列表接口，已有正式计划ID从生产单plan_id及追溯plans获取。新增销售不得追加到已确认批次，形成新草稿；LOW仅用于分组，可先手工完成。

## 销售草稿示例

```json
{
  "dataset_epoch": 1,
  "number": "EXAMPLE-SO-001",
  "customer_name": "示例客户",
  "default_priority": "LOW",
  "lines": [{"item_id": 10, "quantity": "2", "bom_id": null, "priority_override": null}]
}
```

item_id必须已存在且启用，为FINISHED，或is_sellable=true的SEMI。未指定bom_id要求存在完整ACTIVE默认BOM；显式指定允许该物料ACTIVE/RETIRED完整版本。保存时验证但未指定默认版本的草稿不提前冻结，确认时解析并冻结；确认失败整单回滚。

## BOM 草稿示例

```json
{
  "dataset_epoch": 1,
  "item_id": 20,
  "revision": "V1",
  "base_quantity": "100",
  "lines": [
    {"component_item_id": 21, "child_bom_id": 7, "quantity": "20"},
    {"component_item_id": 30, "child_bom_id": null, "quantity": "100"}
  ]
}
```

半成品组件显式引用可用版本，原料child_bom_id必须为null。这里为接口结构示例，不保证这些ID存在，不作为可直接导入的演示数据。

## 建议图请求

PUT /plans/{id}/graph的完整请求如下；图内部只接受schema_version/jobs/dependencies/sales_allocations，epoch与版本在外层。

```json
{
  "dataset_epoch": 1,
  "expected_version": 3,
  "graph": {
    "schema_version": 1,
    "jobs": [
      {"key": "j-pack", "item_id": 10, "bom_id": 1, "priority": "LOW", "quantity": "2", "rounding_surplus": "0", "child_weight": "60"},
      {"key": "j-bottle", "item_id": 20, "bom_id": 2, "priority": "LOW", "quantity": "24", "rounding_surplus": "0", "child_weight": null}
    ],
    "dependencies": [{"supplier_key": "j-bottle", "consumer_key": "j-pack", "quantity": "24"}],
    "sales_allocations": [{"sales_line_id": 100, "job_key": "j-pack", "quantity": "2"}]
  }
}
```

示例假设j-bottle仅原料BOM；实际BOM还有制造组件时须包含所有下级，不能复制示例绕过校验。key在图内唯一；原料需求及层级由后端计算。

POST adjust的operation分别为：split含type/job_key/quantities；merge含type/job_keys；weight含type/job_key/child_weight。只允许同物料、版本、优先级合并。拆合后重展每个消费者用量，告知取整引起的变化。正式确认后的原始graph快照不改，销售取消后的当前数据以production-orders及trace为准。

## 生产与进度响应

下例为GET生产详情的精简响应，不声明未实现的formula/changed_sales_orders等字段。

```json
{
  "data": {
    "id": 8,
    "version": 4,
    "status": "WAITING",
    "own_progress": "0.00",
    "child_weight": "60.00",
    "progress": "36.00",
    "can_start": false,
    "can_update_progress": false,
    "has_cancellation_credit": false
  },
  "meta": {"dataset_epoch": 1, "data_revision": 25}
}
```

详情包含dependencies、sales_allocations、raw_requirements、bom_snapshot；列表不含这些大字段。进度及开工动作返回当前生产单并附affected_order_ids。前端据此刷新销售等相关视图，公式用返回的w、M及子单值说明，但不做权威校验。

has_cancellation_credit说明存在取消保留完成量，总progress可能高于常规公式。完成方式HUMAN/AUTO/CANCEL；未完成方式为空字符串。精确保留量在数据库记录，不接受客户端编辑。

## 取消及追溯

预览绑定epoch、revision、目标实体版本、计划版本、最新审计事件ID，有效10分钟。quantity_changes逐行含id/batch_number/old_quantity/new_quantity/cancelled；new_quantity=0的批次取消，正数批次保留。confirm提交时重新校验令牌，过期不扣量。重放幂等请求不重复取消。

追溯返回nodes/edges/sales_allocations/root_order_ids/plans。节点level为冻结最大深度（根L00），relative_levels为查询根的路径层级。边含supplier_order_id/consumer_order_id/quantity/usage_confirmed_at/active；历史active=false边仅供解释，不参与开工。取消销售的分配qty=0保留身份，原数量见CANCEL_DEMAND审计；原确认计划快照也保留。

## 错误码

| HTTP | code | 含义 |
|---|---|---|
| 400 | INVALID_JSON / INVALID_REQUEST / INVALID_PAGE / VALIDATION_ERROR | 请求体、字段、分页、引用ID或通用协议无效 |
| 403 | CSRF_FAILED | 非登录同源校验失败 |
| 404 | NOT_FOUND | 实体或接口不存在 |
| 409 | VERSION_CONFLICT / STALE_PLAN / STALE_EPOCH / STALE_PREVIEW | 实体、草稿、数据世代、影响预览冲突 |
| 409 | IDEMPOTENCY_CONFLICT / INVALID_CONFIRMATION | 幂等内容不同或签名无效 |
| 409 | DEPENDENCY_NOT_READY / NOT_STARTED / DOWNSTREAM_STARTED / INVALID_PROGRESS | 当前状态不允许生产操作或回退 |
| 409 | IMMUTABLE / PLAN_STARTED / CONSTRAINT_CONFLICT | 冻结记录、整计划已开工、数据库唯一/约束冲突 |
| 422 | BOM_REQUIRED / BOM_CYCLE / EMPTY_BOM / CYCLE_DETECTED | 缺少可用BOM、空BOM或图存在环 |
| 422 | INVALID_QUANTITY / INVALID_PROGRESS / VALIDATION_ERROR | 数量精度、比例、组件或跨表业务校验失败 |
| 422 | GRAPH_BUDGET_EXCEEDED | 超出资源预算，整次拒绝 |
| 503 | DATABASE_BUSY / NOT_READY | SQLite忙或就绪检查失败 |

详细算法见 [业务规则](03_Business_Rules.md)，当前取消验证见 [20](20_Sales_Cancellation.md)。客户端以HTTP和code共同判断，不能依赖旧设计错误码的别名。

物料接口的 is_sellable 为布尔值；SEMI 可设定，省略时新建默认 false；FINISHED 固定 true、RAW 固定 false。GET /items 返回实际销售资格。销售资格关闭后，已有草稿保存或确认返回业务校验失败，历史已确认单据不追溯撤销。

半成品销售资格字段只接受布尔值；成品固定 true、原料固定 false。销售草稿创建、编辑及确认均验证启用状态、销售资格和完整可用BOM，失败返回422 VALIDATION_ERROR。停用半成品销售资格不撤销已确认订单；冻结物料快照不随当前资格改变。
