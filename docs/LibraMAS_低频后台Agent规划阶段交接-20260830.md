# LibraMAS 低频后台 Agent 规划阶段交接

```text
交接 ID：BACKGROUND-PLANNING-20260830-001
范围：阶段 5 的策略平面、预算和前端可观测契约
状态：CODE_COMPLETE / FIXTURE_VALIDATED / REAL_LLM_NOT_ENABLED
```

## 已完成

- 新增 `BackgroundPlanningPort`、`PlanningBudgetPort` 和 `PlanningContext`，把后台规划与 HTTP、数据库、模型客户端隔离。
- 新增 `BackgroundPlanningCoordinator`：只接受五类真实事件（会话启动、readiness 变化、外部情境更新、图谱节点选择、资源打开），按 `context_version` 和幂等键去重。
- 每个会话最多 3 次尝试；同一会话两次尝试至少间隔 10 分钟；同一设备按 UTC 日最多 12 次。预算按“尝试”预留，异常不退款，防止重试绕过上限。
- 规划调用不持有全局锁，慢调用不会阻塞其他 Workspace；单个 Workspace 仍由既有观察 Dispatcher 串行处理。
- 新增 `PlanningContextSanitizer`：仅允许路线、裁剪查询、主题、readiness、演示外部情境和在显式授权下的裁剪画像摘要进入模型适配器；不允许账号 ID、证号、密码、令牌、Prompt、SQL、Cypher 或模型原文。
- 新增 `DirectiveValidator`：只允许既有七类白名单 Directive、固定路由/输出类型/动作/说明密度和有限 payload；禁止 HTML、任意 DOM、自动业务写请求和未知字段。
- 新增 `FixtureBackgroundPlanner`，当前完全确定性、`model_requests=0`，用于本地运行与契约验证。
- Workspace 快照公开后台规划状态、决定 ID、上下文版本、来源、Directive 数、预算和真实事件类型；前端 Agent Rail 区分“低频后台规划”和普通 Agent 事件。
- readiness 新增 `background_planning` 组件。默认 `DISABLED`；只有显式组合时才可报告 Fixture `UP`。该状态不代表已启用 DeepSeek。

## 验证证据

- `tests/g14/test_background_planning.py`：预算、去重、敏感字段清理、Directive 白名单、Workspace 真实事件共 5 项通过。
- `tests/g14/test_background_readiness.py`：默认关闭与 Fixture readiness 共 2 项通过。
- 前端 `vue-tsc --noEmit` 通过。
- `git diff --check` 通过。

## 真实模型边界

当前没有创建 DeepSeek 客户端，也没有发起网络请求。接入真实 DeepSeek 前必须新增 successor ChangePlan，固定：每会话最多 3 次、10 分钟间隔、单设备日预算 12 次、最大输出 token、脱敏字段、成本上限、测试 Workspace/Session UUID 和回滚方式；未精确批准前只能继续使用 Fixture。

后台规划不会自动推荐、自动反馈、自动跳转、修改画像或写入 Neo4j/MySQL。Directive 只能成为建议或通知，所有业务动作仍需用户确认并沿用既有业务端口。

## 数据与安全副作用

- Guest 规划仅驻留内存，不入审计队列。
- 本阶段测试未连接 MySQL、Neo4j 或 Chroma，未产生业务 POST、数据库写入或 DeepSeek 请求。
- 文件删除、数据库记录删除、数据库删除、容器删除和数据卷删除均为 0。

## 后续衔接

1. 在阶段 4 successor 计划批准后完成六个浏览器真实业务场景；后台规划保持关闭或 Fixture 模式。
2. 在正式模型 successor 计划批准后，实现一个仅依赖 `BackgroundPlanningPort` 的 DeepSeek 适配器，并保留规则回退和请求计数。
3. 生产环境必须把后台规划视为独立 readiness 能力，预算、脱敏和 fail-closed 校验全部通过后才可启用。
