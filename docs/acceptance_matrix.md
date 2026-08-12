# LibraMAS 自动化验收矩阵 v1

> 状态：G0 冻结验收语义，G1—G9 逐项实现
> 基线日期：2026-08-02
> 规范来源：LibraMAS 纯推荐模块实施文档第 24.2 节
> 安全优先级：SAFETY_POLICY.md 高于旧文档中的清理或重置表述

## 1. 使用规则

1. G0 只冻结编号、前置数据、可观察结果、目标 Gate 和证据类型，不把尚未实现的用例标记为通过。
2. 每个用例必须由自动化命令产生机器可读结果；人工截图只能作为补充证据。
3. 测试运行使用唯一 test_run_id、用户 ID 和版本化索引名；不得覆盖旧运行。
4. 失败运行保留原始事实并标记 FAILED 或 INVALIDATED，修复后创建新运行。
5. 某用例的目标 Gate 未通过时，依赖它的后续 Gate 不得标记为完成。
6. A01—A25 的最终全量回归属于 G8；冻结数据后的历史时点复算属于 G9。

## 2. Gate 映射

| 编号 | 冻结的可验证语义 | 首次实现 Gate | 最终复验 | 主要证据 |
|---|---|---:|---:|---|
| A01 | 同一批行为按不同到达顺序重放，最终画像内容哈希一致 | G5 | G8/G9 | 两个画像版本、事件清单、内容哈希 |
| A02 | 同一 request_id 重放返回同一任务，推荐记录数量不增加 | G3 | G8 | HTTP 回执、任务 ID、记录计数 |
| A03 | 同一 event_uuid 重放只对应一个行为事实 | G5 | G8 | 行为回执、唯一键审计查询 |
| A04 | 同一 feedback_uuid 重放只产生一次反馈影响 | G5 | G8 | 反馈回执、事实与 Outbox 计数 |
| A05 | 冷启动模糊请求进入 GUIDED，不因低证据直接降级 | G4 | G8 | PolicyResult、Agent Trace |
| A06 | 低画像但显式要求 Agentic RAG 论文时保留论文意图 | G3 | G8 | 意图结果、候选通道、资源类型断言 |
| A07 | ALREADY_READ 只抑制目标资源，不降低主题兴趣 | G5 | G8 | 前后画像差异、资源状态投影 |
| A08 | TOPIC_NOT_INTERESTED 增加目标负权重，反事实最终分严格下降 | G5 | G8/G9 | 配置固定的反事实评分明细 |
| A09 | 最大可视比例小于 0.5 时不计有效曝光 | G5 | G7/G8 | API 单测、浏览器可视性 E2E、曝光事实 |
| A10 | 可视时间小于 1000ms 时不计有效曝光 | G5 | G7/G8 | API 单测、浏览器时钟 E2E、曝光事实 |
| A11 | Chroma 超时时 semantic_score 为空且任务继续 | G6A | G8 | 故障注入 Trace、候选特征 |
| A12 | Neo4j 超时时 kg_score 为空且解释不含虚构路径 | G6B | G8 | 故障注入 Trace、证据引用 |
| A13 | Chroma 与 Neo4j 同时离线时，MySQL 候选充足仍返回结果 | G6 | G8 | 故障矩阵、完成状态、警告 |
| A14 | MySQL 离线时返回 HTTP 503，不从派生索引孤立服务 | G3 | G8 | 依赖故障响应、无完成记录证明 |
| A15 | 任一可选特征缺失时分数有限、合法且无除零 | G3 | G8 | 参数化领域测试、分数范围断言 |
| A16 | 固定快照、版本、种子和 evaluation_at 后结果顺序与分数一致 | G3 | G8/G9 | 两次结果哈希与环境清单 |
| A17 | 候选充分时满足作者/主题上限；不足时记录 diversity_relaxed | G3 | G8 | 排序单测、候选池和选择轨迹 |
| A18 | 阅读路径只有一个难度层时返回 DEGRADED，不伪造层级 | G4 | G8 | 组合结果、警告、证据集合 |
| A19 | LLM 引入不存在事实时证据校验失败并回退模板 | G6C | G8 | FaultInjecting Provider 记录、回退结果 |
| A20 | 每个最终推荐项至少追溯到一个召回通道 | G3 | G8 | recommendation item 与 candidate 关联审计 |
| A21 | 命中质量门槛后最多重规划一次 | G4 | G8 | replan_count 不大于 1、策略决策链 |
| A22 | 模糊任务在策略阶段早停，不运行完整召回与排序 | G4 | G8 | Agent Trace 中不存在后续完整调用 |
| A23 | 反馈提交成功后画像版本增长并产生 change log | G5 | G8 | 反馈事实、Outbox、画像版本与 change log |
| A24 | 自动推断接近阈值时两轮内保持输出类型，显式意图可覆盖 | G4 | G8 | 连续任务序列和策略原因码 |
| A25 | evaluation_at 之后的资源、行为、状态和热度不影响历史重放 | G9 | G9 | 冻结数据清单、历史/对照结果哈希 |

## 3. 实现位置约定

| 测试层 | 约定目录 | 责任边界 |
|---|---|---|
| 领域单元测试 | tests/unit/ | 纯函数、状态机、公式、缺失特征和边界值 |
| Agent 契约测试 | tests/contracts/ | 消息、结果、策略分支、错误与版本一致性 |
| MySQL 集成测试 | tests/integration/mysql/ | 事务、幂等、唯一约束、Outbox 和时点读取 |
| 可选适配器测试 | tests/integration/adapters/ | Chroma、Neo4j、LLM 的健康与故障语义 |
| HTTP 契约测试 | tests/api/ | OpenAPI、错误响应、鉴权、幂等头 |
| 浏览器端到端测试 | frontend/e2e/ | 六个演示场景和真实可视曝光 |
| 故障矩阵 | tests/resilience/ | 依赖超时、不可用、版本不匹配和恢复 |
| 历史复算与实验 | evaluation/tests/ | 时间隔离、数据泄漏、基线、消融和复算 |

目录可以在对应 Gate 创建，但测试编号不得改名或复用。测试名称使用 test_aNN_behavior，使 CI 报告可直接映射论文验收表。

## 4. 证据清单

每次验收在新的 artifacts/verification/{run_id}/ 目录写入以下追加型产物；目录存在时直接失败，不覆盖：

```text
manifest.json
environment.json
commands.jsonl
test-results.xml
contract-report.json
safety-report.json
data-snapshot-manifest.json
trace-index.json
summary.md
```

manifest.json 至少记录 Git commit、配置 Bundle、数据快照、索引版本、随机种子、evaluation_at、测试选择表达式和各文件 SHA-256。G0 只冻结该格式；实际证据写入器在 G1/G2 实现。

## 5. 当前状态

| 范围 | 状态 | 说明 |
|---|---|---|
| A01—A25 语义和 Gate 映射 | FROZEN_V1 | 本文件完成 |
| G0 契约与安全门禁 | COMPLETED | `make verify-g0`：125 tests，四类门禁 PASS |
| A01—A25 业务实现 | OFFLINE_AUDITED_WITH_BLOCKERS | 已完成逐项离线覆盖盘点；9 项有直接离线覆盖、14 项为相关覆盖、2 项缺少直接测试；最终 G8/G9 复验仍未运行 |

在业务代码、真实数据和依赖尚未出现前，不得把 FROZEN_V1 解释为验收用例已通过。
