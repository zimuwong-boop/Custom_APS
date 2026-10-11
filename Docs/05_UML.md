# UML 与流程设计

版本：2.1 · 原始基线：2026-10-10 · 修订：2026-10-11 · 状态：当前需求与实现基线。

Markdown 内含 UML 类、状态和时序图；PlantUML 标准用例、活动、部署图源见 [图源目录](diagrams/README.md)。所有图描述2.1当前基线，销售取消为正式计划冻结的专门缩量动作；图源结构检查与实际渲染验证区分记录。

## 用例概览

```mermaid
flowchart LR
    User[演示操作者] --> Catalog[维护物料和多级 BOM]
    User --> Sale[启用且允许销售的已有BOM商品建立并确认销售单]
    User --> Cancel[取消销售并预览数量影响]
    Cancel --> Credit[逐批缩量与保留完成量重算]
    Credit --> Rollup
    Sale --> Suggest[自动展开并生成建议]
    User --> Adjust[拆合建议与设置子单占比]
    Adjust --> Confirm[确认生产计划和批次]
    User --> Start[手工开始生产]
    User --> Progress[手工调整自身进度]
    Progress --> Rollup[自动传播父单与销售进度]
    User --> Trace[双向批次追溯]
    User --> Reset[确认后重置演示]
```

此概览是流程视图；标准 UML 用例图源为 [01_use_cases.puml](diagrams/01_use_cases.puml)。

## 领域类图

```mermaid
classDiagram
    class Item {
        +code: string
        +type: ItemType
        +unitId: integer
        +isSellable: boolean
        +canSell(): boolean
    }
    class BOM {
        +revision: string
        +baseQty: Quantity
        +validateGraph()
    }
    class BOMLine {
        +quantity: Quantity
        +childBomId: integer
    }
    class SalesOrder {
        +number: string
        +status: SalesStatus
        +productionProgress()
        +cancelDemand()
    }
    class SalesLine {
        +quantity: Quantity
        +priority: string
    }
    class PlanRun {
        +version: integer
        +graphSnapshot: JSON
        +confirm()
    }
    class ProductionOrder {
        +batchNumber: string
        +plannedQty: Quantity
        +retainedCompletedQty: Rational
        +ownProgressBp: integer
        +childWeightBp: integer
        +status: ProductionStatus
        +start()
        +updateOwnProgress()
        +totalProgress()
    }
    class ProductionDependency {
        +active: boolean
        +allocatedQty: Quantity
        +usageConfirmedAt: datetime
    }
    class SalesAllocation {
        +allocatedQty: Quantity
    }
    Item "1" --> "0..*" BOM : manufactured by
    BOM "1" *-- "1..*" BOMLine
    BOMLine "0..*" --> "1" Item : component
    BOMLine "0..*" --> "0..1" BOM : selected child version
    SalesOrder "1" *-- "1..*" SalesLine
    SalesLine "0..*" --> "1" Item
    PlanRun "1" --> "0..*" ProductionOrder
    ProductionDependency "0..*" --> "1" ProductionOrder : supplier
    ProductionDependency "0..*" --> "1" ProductionOrder : consumer
    SalesAllocation "0..*" --> "1" SalesLine
    SalesAllocation "0..*" --> "1" ProductionOrder
```

## 生产状态图

```mermaid
stateDiagram-v2
    [*] --> READY: 确认叶节点
    [*] --> WAITING: 确认非叶节点
    WAITING --> READY: 所有直接子单完成且占比小于100%
    WAITING --> COMPLETED: 所有子单完成且占比等于100%
    READY --> IN_PROGRESS: 用户开始
    IN_PROGRESS --> IN_PROGRESS: 修改自身进度小于100%
    IN_PROGRESS --> COMPLETED: 自身进度100%
    COMPLETED --> IN_PROGRESS: 人工完成更正且无已手工开工下游
    COMPLETED --> WAITING: 自动完成节点的子单合法回退
    READY --> WAITING: 子单合法回退
    WAITING --> COMPLETED: 取消缩量记账达到100%且全部子单完成
    READY --> COMPLETED: 取消缩量记账达到100%
    IN_PROGRESS --> REVOKED: 销售取消且剩余需求为0
    COMPLETED --> REVOKED: 销售取消且剩余需求为0
    WAITING --> REVOKED: 整计划合法撤销或销售取消零需求
    READY --> REVOKED: 整计划合法撤销或销售取消零需求
    note right of WAITING
      总进度可以增长
      自身进度必须为0
    end note
```

AUTO或未手工开工的CANCEL完成不填写手工开工时间；IN_PROGRESS 不会因合法子单回退转 WAITING，因为已有手工开工的下游会阻止该回退。生产单撤销为历史终态；演示重置不属于业务状态迁移。

## 计划确认时序

```mermaid
sequenceDiagram
    actor U as 操作者
    participant V as Vue
    participant A as Django API
    participant P as PlanningService
    participant D as SQLite
    U->>V: 确认建议
    V->>A: plan_id、版本、epoch、幂等键
    A->>P: confirm_plan
    P->>D: 开始写事务并检查重试/版本
    alt 已成功处理同一请求
        D-->>P: 原始结果
    else 新请求
        P->>P: 校验BOM、数量、依赖、剩余需求
        P->>D: 生成单据、批次、关系、日志及幂等结果
    end
    P->>D: 提交（任一失败全部回滚）
    P-->>A: 正式计划与变更摘要
    A-->>V: 成功结果或明确冲突
    V-->>U: 展示生产单与批次
```

## 进度反馈时序

```mermaid
sequenceDiagram
    actor U as 操作者
    participant V as Vue
    participant A as ProgressService
    participant D as SQLite
    U->>V: 调整本级自身进度
    V->>A: 进度、版本、epoch、幂等键
    A->>D: 开始事务
    A->>A: 校验开工/依赖/回退约束
    A->>D: 保存自身进度事件
    loop 按供应到消费拓扑顺序
        A->>A: 重算受影响父单状态和总进度
        A->>D: 更新缓存及自动完成使用确认
    end
    A->>D: 更新相关销售进度、日志及版本
    A->>D: 提交
    A-->>V: 当前生产单、affected_order_ids、meta
    V-->>U: 刷新总进度、阻塞原因与销售结果
```

## 排产活动概览

```mermaid
flowchart TD
    S[建立或编辑销售草稿] --> V{已有启用商品及完整可用BOM?}
    V -->|否| R[拒绝保存并回滚]
    V -->|是| A[确认销售]
    A --> B{重新校验BOM与数量合法?}
    B -->|否| E[指出错误并拒绝确认]
    B -->|是| C[展开并汇总未安排需求]
    C --> D[生成可调整的建议图]
    D --> F[拆合、分配、设置占比]
    F --> G{数量守恒且版本有效?}
    G -->|否| F
    G -->|是| H[原子生成正式单据与批次]
    H --> I[逐层生产和进度传播]
    I --> J[销售生产完成及批次追溯]
```

## 部署视图

```mermaid
flowchart TB
    B[本机浏览器] -->|localhost:8000| P
    subgraph C[单个 Docker 容器]
        P[同步 Python 应用服务] --> A[Django API与领域服务]
        P --> S[Vue 构建静态文件]
        A --> Q[SQLite连接]
    end
    Q --> V[(持久化卷 /data)]
```

构建阶段 Node 与 Python 镜像层不等于两个运行容器；标准 UML 部署源见 [03_deployment.puml](diagrams/03_deployment.puml)。

## 销售状态图

```mermaid
stateDiagram-v2
    [*] --> DRAFT: 已有可用BOM商品
    DRAFT --> CONFIRMED: 确认并冻结版本及优先级
    CONFIRMED --> PRODUCTION_COMPLETED: 全覆盖且全部销售根完成
    PRODUCTION_COMPLETED --> CONFIRMED: 合法生产纠错
    DRAFT --> CANCELLED: 确认取消
    CONFIRMED --> CANCELLED: 确认取消及关联批次缩量
    PRODUCTION_COMPLETED --> CANCELLED: 确认取消并保留历史
    CANCELLED --> [*]
```

## 销售取消时序

```mermaid
sequenceDiagram
    actor U as 操作者
    participant V as Vue
    participant A as Django API
    participant C as CancellationService
    participant P as ProgressService
    participant D as SQLite
    U->>V: 取消销售
    V->>A: cancel-preview / 版本、epoch
    A->>C: 计算逐批旧数量与剩余数量
    A-->>V: 签名令牌、数量变化及影响范围
    U->>V: 填原因并确认
    V->>A: cancel / 令牌、版本、epoch、幂等键
    A->>D: 开始事务并验证版本、令牌、幂等
    A->>C: 逐销售分配扣量
    C->>C: 消费者优先重展BOM、单位取整及比例分配
    C->>D: 零需求撤销、无效边保留、共享单缩量及保留完成量
    C->>P: 子单优先重算总进度及完成门槛
    P->>D: 更新有效批次、使用确认、其他销售进度
    A->>D: 刷新待排建议、审计和幂等结果并提交
    A-->>V: 销售取消及affected_order_ids
    V-->>U: 刷新数量、状态、进度及历史追溯
```

详细数学口径见 [业务规则](03_Business_Rules.md)；标准取消活动图源见 [04_sales_cancellation.puml](diagrams/04_sales_cancellation.puml)。
