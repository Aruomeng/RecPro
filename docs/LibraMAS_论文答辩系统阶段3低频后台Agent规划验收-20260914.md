# LibraMAS 论文答辩系统阶段 3：低频后台 Agent 规划研究模式验收

## 1. 结论

阶段 3 状态为 `PASS`。

低频后台 Agent 规划已在显式研究运行时完成真实 DeepSeek 双身份验收：Guest Workspace 与正式读者身份 Workspace 各发起 1 次 `deepseek-v4-flash` 请求，均生成 1 条通过白名单校验的 Directive，并产生真实的 `AGENT_STARTED`、`AGENT_COMPLETED` 事件。两次运行均未触发规则回退。

默认 Compose 仍保持后台规划关闭；功能只有在显式研究配置、有效运行身份和预算共同满足时才启用。本阶段没有连接或写入 MySQL，没有修改 Neo4j 或 Chroma，也没有发起推荐、反馈、导航或画像写操作。

## 2. 实际功能产出

- 后台规划预算固定为：
  - 每个会话最多 3 次。
  - 同一会话两次规划至少间隔 10 分钟。
  - 同一设备每日最多 12 次。
- 真实模型只允许输出既有七类结构化 Directive；未知类型和非法载荷均被拒绝。
- 模型超时、非法 JSON 或非法 Directive 时，只进行确定性规则回退，不自动产生第二次模型请求。
- Workspace 公开状态和事件增加：
  - `attempted_provider`
  - `fallback_used`
  - `decision_id`
  - `context_version`
  - 证据引用
  - 请求次数、Directive 数量和执行耗时
  - 会话与设备预算、下一次允许时间
- 全局 Agent 工作栏显示真实规划来源、规则回退状态、预算和证据，不把历史回放或降级伪装为实时模型活动。
- 新增双身份受控执行器，严格绑定提交、ChangePlan、运行 ID、模型、请求次数、脱敏上下文和零写入边界。
- 修正研究 Compose 的运行身份配置键；默认配置继续保持 `background_planning=DISABLED`。

## 3. 真实 DeepSeek 验收

执行时间为 2026-09-14（Asia/Shanghai），绑定代码提交 `25dcdb67fead978170527bf477d8295cca9ca9bf`。

| 身份路径 | Workspace ID | 状态 | 模型请求 | Directive | 耗时 | 回退 |
|---|---|---|---:|---:|---:|---|
| Guest | `937bb79e-4cc7-5f63-9963-eecace00da9c` | `PLANNED` | 1 | 1 | 937 ms | 否 |
| 正式读者 Bearer Principal（user 10001） | `0541ba44-c53c-5be9-9156-e6d14b83d00c` | `PLANNED` | 1 | 1 | 784 ms | 否 |

两次运行共同满足：

- Provider 为 `deepseek`，模型为 `deepseek-v4-flash`。
- 原因码为 `BACKGROUND_PLAN_READY`。
- 每个 Workspace 的会话预算消耗为 1/3。
- 设备日预算累计为 2/12。
- 下一次允许规划时间严格晚于本次运行 10 分钟。
- 事件顺序包含真实 `AGENT_STARTED` 与 `AGENT_COMPLETED`。
- 没有业务 POST、数据库连接或持久化副作用。

## 4. 身份与隐私边界

- Guest 模型上下文不包含任何画像字段，`profile_present=false`。
- 正式读者路径经过 Bearer Principal 和个性化授权校验，只注入以下裁剪字段：
  - `confidence`
  - `grade`
  - `major`
  - `preferred_language`
  - `profile_version`
  - `research_direction`
- 两个模型上下文分别保存字符数和 SHA-256 摘要用于对账，不保存完整上下文。
- 回执不包含 API 密钥、登录标识、密码、原始画像、完整 Prompt、模型原文、SQL 或 Cypher。
- 本阶段正式读者验收聚焦服务端身份与授权边界；真实浏览器登录及端到端 SSE 展示归入阶段 4。

## 5. ChangePlan 与不可变回执

- `plan_id`：`d8c6c0f4-a653-5868-82c4-1b9821f916fb`
- `plan_hash`：`2a9cee4543b9c3c520b6061cb98757853cb2d1b27f6ef277fd3bd9f8c912b3e5`
- 绑定提交：`25dcdb67fead978170527bf477d8295cca9ca9bf`
- 运行 ID：`stage3-background-dual-20260913-001`
- 外部模型请求上限：2；实际：2。
- 单次最大输出 Token：256。
- 自动重试：0。
- 数据库、Neo4j、Chroma 与业务写入上限：0；实际：0。
- 回执 SHA-256：`5209ee1e1f9d3b6a86ee8dcce6010e1e97a57ad93cf77144f3c94b6e06b693e5`。

关键证据：

- `artifacts/verification/background-planning/stage3-background-dual-20260913-001/change-plan.json`
- `artifacts/verification/background-planning/stage3-background-dual-20260913-001/fixture.json`
- `artifacts/verification/background-planning/stage3-background-dual-20260913-001/apply.json`

## 6. 测试与门禁

- 后端全量测试：797 项通过。
- G14 后台规划专项测试：37 项通过。
- 前端测试：21 个测试文件、88 项通过。
- TypeScript 检查：通过。
- 前端生产构建：通过。
- 安全扫描：637 个文件、0 违规。
- 架构守卫：187 个文件、0 违规。
- 契约与文档校验：通过。
- Compose 配置校验：通过。
- 真实回执 12 项关键断言全部通过：计划/提交绑定、双身份、请求预算、模型、状态、事件、画像隔离、零写入与零删除均成立。

已覆盖的故障行为包括：预算拒绝不调用模型、超时、非法 JSON、未知 Directive、Guest 画像隔离及正式读者裁剪画像。故障回退由 Fixture/Mock 验证，不额外消耗真实 DeepSeek 请求。

## 7. 数据、模型与删除计数

| 边界 | 新增 | 更新 | 删除 |
|---|---:|---:|---:|
| MySQL | 0 | 0 | 0 |
| Neo4j | 0 | 0 | 0 |
| Chroma | 0 | 0 | 0 |
| 业务事实 | 0 | 0 | 0 |

- DeepSeek 请求：2。
- 文件删除：0。
- 容器删除：0。
- 数据卷删除：0。
- 数据库物理删除：0。

## 8. Git 边界

- 阶段 3 功能实现：`25dcdb67fead978170527bf477d8295cca9ca9bf`。
- 该提交已推送至 `origin/codex/g1-runnable-skeleton`。
- 本文档作为独立阶段验收报告提交，不修改阶段 3 已批准执行器及功能代码。

## 9. 固定阶段汇报

```text
阶段：阶段 3：低频后台 Agent 规划研究模式
状态：PASS
完成内容：真实 DeepSeek 规划接线、双身份上下文隔离、三级预算、确定性降级、公开可追溯字段和 Agent 工作栏展示
实际产出：Guest 与正式读者 Workspace 各完成 1 次真实规划，各生成 1 条合法 Directive 和真实 Agent 开始/完成事件
测试与验收：后端 797 项、G14 37 项、前端 88 项、TypeScript、生产构建、安全、架构、契约和 Compose 门禁通过
MySQL新增/更新/删除：0 / 0 / 0
Neo4j新增/更新/删除：0 / 0 / 0
Chroma变化：0
DeepSeek请求：2
文件/容器/数据卷删除：0 / 0 / 0
Git提交与推送：25dcdb6 已推送；阶段报告提交随后记录
未完成内容：本阶段无剩余功能；真实浏览器登录与完整业务链路属于阶段 4
下一阶段：阶段 4：完整浏览器业务闭环
```

## 10. 下一阶段边界

阶段 4 将按九个冻结场景依次验证 Guest 只读探索、正式登录、推荐、澄清、v2 路径高亮、阅读路径、反馈学习、知识审核和隔离故障降级。推荐、登录、反馈与知识审核必须分别使用绑定最新提交的独立精确 ChangePlan；不得复用本阶段模型计划，也不得聚合写入预算。
