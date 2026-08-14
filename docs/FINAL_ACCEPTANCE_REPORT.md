# LibraMAS 核心功能最终验收报告

验收日期：2026-08-14

验收范围：本地研究原型的核心业务闭环，不包含公网生产部署与论文统计实验

安全结论：本次验收未删除文件，未删除或清理任何数据库数据；启动预检与最终对账均未产生数据库写入

## 1. 总体结论

LibraMAS 的核心原型已达到本地可正常使用状态。系统能够在隔离的 MySQL、项目专用 Neo4j 和本地 Chroma 数据之上，由 8 个职责独立的 Agent 完成意图理解、画像、语义分析、策略规划、多通道召回、排序、可解释生成和反馈学习；Intent 与 Explanation 默认研究运行配置均使用真实 DeepSeek `deepseek-v4-flash`，不是 Mock。

一条命令的研究工作台已通过实际启动验证：后端 readiness 与前端首页均返回 HTTP 200。启动器会先检查关键能力开关、真实模型配置、数据库端口、图数据库、向量数据和前端依赖，任何核心条件不满足都会拒绝启动。

核心研究原型完成度：**100%**。剩余事项属于生产化和论文实验层，不阻塞本地核心功能使用。

## 2. 已验收的 8 个 Agent

| Agent | 核心职责 | 自主决策/输出 |
| --- | --- | --- |
| IntentUnderstandingAgent | 理解自然语言目标与约束 | 识别意图、缺失槽位和置信度，必要时请求澄清 |
| UserProfileAgent | 汇总长期/短期偏好 | 生成可审计画像快照与负偏好约束 |
| ResourceSemanticAgent | 组织资源语义证据 | 形成主题、实体和证据范围 |
| RecommendationPolicyAgent | 选择协作路径 | `ASK_CLARIFICATION`、`PLAN_RECALL` 或安全降级 |
| CandidateRecallAgent | 执行多通道召回 | 融合 MySQL、Neo4j、Chroma 候选并保留来源 |
| RankingAgent | 排序与动态重规划 | 综合匹配、画像和负反馈，必要时 `REQUEST_REPLAN` |
| ExplanationAgent | 生成证据约束解释 | 使用真实 DeepSeek，引用只允许来自当前候选证据 |
| FeedbackLearningAgent | 处理反馈与行为 | 追加反馈、生成画像增量提案并通过 Outbox 投影 |

Agent 不是简单对话模型别名。每个 Agent 都有独立 Role、Goal、Observation、Tools、AllowedActions 和 AllowedTargets，决策经 Registry 校验后驱动 Orchestrator 状态转换；数据访问通过端口/适配器完成，Agent 之间不直接调用数据库。

## 3. 数据与基础设施

- MySQL：隔离实例保存书目目录、推荐任务、Agent 审计事实、反馈、行为、画像变更和 Outbox；业务事实采用追加式写入和幂等键。
- Neo4j：使用 RecPro 独立实例/数据卷及图版本 `lib-books-v1-20260810`，共有 63,388 个节点、191,865 条关系；未连接、修改或清理用户原有 Neo4j 大图。
- Chroma：collection `library_resources__hash_char_ngram_v1` 保存 14,983 条、384 维确定性向量，已完成全量回读与幂等核验。
- 书目目录：MySQL 中有 14,983 本导入图书、8,516 个标签和 70,750 条资源标签关系；原始 `Lib` 数据与历次导入证据均保留。
- DeepSeek：provider=`deepseek`，model=`deepseek-v4-flash`；密钥只存在 Git 忽略且权限受控的本机环境文件中，不进入仓库、报告或日志。

## 4. 核心功能验收结果

| 功能 | 状态 | 验收结果 |
| --- | --- | --- |
| 自然语言推荐 | PASS | 真实 HTTP 请求可创建任务并返回图书推荐 |
| 多 Agent 编排 | PASS | 8 个角色具备独立决策边界，Orchestrator 可动态转移状态 |
| 三通道召回 | PASS | MySQL + Neo4j + Chroma 可在同一请求中融合，版本可追溯 |
| 真实 LLM Intent | PASS | DeepSeek `deepseek-v4-flash` 真实调用，无 Mock 替代 |
| 真实 LLM Explanation | PASS | 每项解释通过证据白名单校验，失败时有有界重试与显式降级 |
| 澄清与续跑 | PASS | 缺少条件时进入等待态，补充资源类型/主题后从新上下文继续 |
| 推荐持久化 | PASS | task、transition、Agent facts、record、item、policy、trace 追加写入 |
| HTTP 幂等 | PASS | 相同 request id 重放返回同一任务且数据库零增量 |
| 反馈与行为 | PASS | feedback/behavior 可入库，非法对象和越权输入 fail-closed |
| Outbox Worker | PASS | 显式开启时追加投影画像；默认关闭且无副作用 |
| 负反馈学习 | PASS | 被拒资源由原 rank 1 降权后在正分候选规则下退出推荐列表 |
| 前端工作台 | PASS | 推荐、澄清、反馈、行为、降级呈现和移动端布局已实现并测试 |
| 安全与可审计 | PASS | A01—A25 最终审计 25 PASS / 0 PENDING / 0 FAIL |

最近一次正分候选真实 LLM 验收任务为 `2698c23f-dc4a-5c9e-9db5-93e80964e681`：Intent 实际请求 2 次、4 项 Explanation 实际请求 6 次，均无模板回退；首次请求追加 44 行审计事实，相同请求重放零增量。结果只保留 4 个正分候选，被明确拒绝的资源不再用零分占位。

## 5. 本地启动方式

前提：项目隔离 MySQL 和 library Neo4j 已运行，`.env.host` 与 `.env.user-secrets` 已按本机配置且不提交 Git，前端依赖已安装。

先执行不写数据库的就绪检查：

```bash
make PYTHON=.venv-g1-final-py311/bin/python research-workbench-check
```

检查通过后启动完整研究工作台：

```bash
make PYTHON=.venv-g1-final-py311/bin/python research-workbench
```

- 前端：`http://127.0.0.1:5173`
- 后端 readiness：`http://127.0.0.1:8000/api/v1/health/ready`
- 使用 `Ctrl+C` 可安全停止本次前后端进程，不会停止或删除数据库容器、数据卷或数据。

研究工作台是显式 opt-in 入口；默认 Compose 后端和 Worker 继续 fail-closed，不会因容器启动自动开放业务写入或外部模型调用。

## 6. 尚未完成但不阻塞核心原型的工作

以下内容应作为论文实验或生产化后续工作，不计入本地核心功能缺口：

1. 论文正式实验：冻结测试用户/查询集，运行消融、基线对比、统计显著性和人工解释质量评价。
2. 生产身份体系：接入真实 OIDC/JWKS、角色权限与密钥托管，而不是本地研究身份。
3. 生产运维：TLS、域名、持续部署、集中日志、告警、备份恢复演练和容量压测。
4. 更大规模数据质量：ISBN 去重、实体消歧、主题词规范化和增量采集治理。

这些任务预计可拆为 3 个后续阶段：论文实验冻结与运行、生产安全加固、部署与运维验收。它们不会改变“当前本地核心业务闭环已真实可用”的结论。

## 7. 关键证据

- A01—A25 最终审计：`artifacts/verification/g8/g8-final-revalidation-audit-20260814-001/final-revalidation-audit.json`
- 正分候选真实 LLM 执行：`artifacts/verification/g4/g4-positive-only-real-llm-apply-20260814-001/g4-recommendation-projection-apply.json`
- 独立只读对账：`artifacts/verification/g4/g4-positive-only-real-llm-reconcile-20260814-001/reconciliation.json`
- Agent 自主性：`artifacts/verification/g4/g4-agent-autonomy-20260812-003/agent-autonomy-runtime.json`
- 三通道只读融合：`artifacts/verification/g6/g6-retrieval-fusion-readonly-20260811-001/readonly.json`
- 前端浏览器验收：`artifacts/verification/g8/` 下的 browser scenario artifacts
