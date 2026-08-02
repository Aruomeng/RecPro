# LibraMAS / RecPro

LibraMAS 是一个面向智慧图书馆知识资源推荐的研究生论文原型，核心研究方向为多智能体协同、动态交互策略、可解释推荐与反馈学习。

## 当前状态

`G0：安全与规格基线` 已在本地通过统一验收。当前仓库已经具备零删除门禁、模块依赖门禁、无框架运行时契约、JSON Schema、OpenAPI 草案、实验协议和自动化测试；`G1：可启动工程骨架` 尚未开始。

G0 冻结的是工程边界，不代表推荐服务已经可启动。首个真实推荐闭环按计划在 G3 形成。

## 核心文档

- [可运行版实施文档](docs/LibraMAS_纯推荐模块实施文档_可运行版.md)
- [安全低耦合实施计划](docs/LibraMAS_系统实施计划_安全低耦合版.md)
- [实施状态与交接记录](docs/LibraMAS_实施状态与交接记录.md)
- [安全与零删除政策](docs/SAFETY_POLICY.md)
- [模块化单体 ADR](docs/adr/0001-modular-monolith.md)
- [核心数据字典](docs/data_dictionary.md)
- [HTTP API 契约](docs/api.md)
- [论文实验协议](docs/experiment_protocol.md)
- [A01—A25 验收矩阵](docs/acceptance_matrix.md)

## 最高优先级安全约束

未经用户查看详细影响报告并明确批准：

- 不得删除任何文件；
- 不得物理删除任何数据库数据或对象；
- 不得清理持久卷、测试运行、实验结果或旧索引；
- 纠错、撤回、停用和恢复必须使用版本、补偿事件或前向修复。

详细规则已经固化在 `docs/SAFETY_POLICY.md`，并由自动化安全扫描强制执行。

## 架构方向

采用模块化单体与端口适配器：Catalog、Profile、Recommendation、Feedback 等业务域保持高内聚；Agent通过结构化消息和Orchestrator协作，不直接访问数据库或互相调用。

## G0 验证

需要 Python 3.11，以及 `backend/pyproject.toml` 中的 `g0` 可选依赖。执行：

```bash
python3 -m pip install --require-hashes -r backend/requirements-g0.lock
make verify-g0
```

该命令依次验证文件/数据零删除规则、模块依赖方向、Markdown 结构化示例、本地链接、Schema/OpenAPI/枚举一致性和 G0 单元测试。命令不连接数据库，也不修改业务数据。

## G0 目录

```text
backend/app/shared_kernel/contracts/  无框架 Python 契约
contracts/                            Agent、配置、安全和 OpenAPI Schema
docs/                                 架构、数据、API、实验与安全规范
scripts/                              安全、架构、文档和契约门禁
tests/                                G0 自动化测试
```

## 版本管理

每个Gate使用独立分支和详细提交说明。提交正文至少记录：

1. 变更目的与范围；
2. 关键设计决策；
3. 验证命令和结果；
4. 文件与数据库安全影响；
5. 后续工作或已知限制。

远程仓库固定为 `https://github.com/Aruomeng/RecPro.git`。发布前必须先通过本地门禁；推送和 Pull Request 只在认证工具可用后执行。
