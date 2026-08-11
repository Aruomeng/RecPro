# LibraMAS / RecPro

LibraMAS 是一个面向智慧图书馆知识资源推荐的研究生论文原型，核心研究方向为多智能体协同、动态交互策略、可解释推荐与反馈学习。

## 当前状态

G0—G5 的核心代码切片、MySQL 隔离运行态和安全门禁已经建立；G6 已完成真实图书数据、可选检索能力和一次隔离目标只读融合验证。`Lib` 已完成 76 个 CSV 的只读规范化，并将版本化图 `lib-books-v1-20260810` 追加导入独立 Neo4j（15,538 条来源记录、63,388 个节点、191,865 条关系）；在用户明确授权后，同一书目已按 append-only ChangePlan 写入隔离 Compose MySQL（14,983 本书、8,516 个标签、70,750 条标签关系），并完成幂等复跑与只读计数核验。当前已基于同一 MySQL ChangePlan 离线构建 14,983 条确定性向量记录（`hash-char-ngram-v1`、384 维），两次独立构建哈希一致；用户授权后已在独立本地 Chroma 路径创建新 collection `library_resources__hash_char_ngram_v1`，追加 14,983 条向量，并完成全量回读、版本/元数据核验、召回冒烟和幂等复核（`chromadb==1.5.9`）。MySQL 的 `embedding_status=PENDING` 未修改。Neo4j/Chroma 只读召回端口已通过真实隔离运行态融合验证：固定三组版本，MySQL 计数和 Chroma 14,983 条向量前后不变，8 条候选同时带 MYSQL/GRAPH/VECTOR 通道且无 fallback；详细证据见 `artifacts/verification/g6/g6-retrieval-fusion-readonly-20260811-001/readonly.json`。G7 已有推荐工作台、契约化 RecommendationClient、澄清交互占位和明确标注的本地演示；默认 `pipelineEnabled=false`，不会绕过健康闸门或自动写入数据库。默认 HTTP/API/Worker 仍保持关闭，`can_recommend` 不因容器启动而自动变为 `true`。

书目数据必须先经过 `contracts/data/intake/` 的规范化记录/Manifest 和图计划只读校验，再由 `scripts/import_book_graph.py` 以显式 `--apply` 追加到带 `graph_version` 的 Neo4j 影子图；实体/关系见 [图书图谱模型与导入契约](docs/book_graph_model.md)。仓库不保存外部大模型密钥，也不需要密钥运行 MockLLM/模板路径；DeepSeek 适配器已准备并保持默认关闭，当前本机的 opt-in 配置只能通过被 Git 忽略的环境文件注入，禁止提交到 Git。详见 [LLM 与 Prompt 配置基线](docs/LLM_PROMPT_CONFIGURATION.md)。

数据库管理员凭据只保存在本机 `.env.user-secrets`（权限 `0600`，已被 `.gitignore` 忽略），不进入应用日志或提交。MySQL 应用运行账号仍保持最小权限；`root` 仅作为后续受控管理/迁移凭据使用。Neo4j Community 只提供默认 `neo4j` 数据库，因此 RecPro 使用独立 Compose 实例和独立数据卷隔离于本机已有 Neo4j；不会连接本机 `7474/7687` 上的既有图。

当前 RecPro Neo4j 隔离实例为 `recpro-library-neo4j-20260810a`，使用独立数据卷和本地端口 `62475/62688`，图版本 `lib-books-v1-20260810` 当前为 63,388 节点、191,865 关系；原有 RecPro 验证实例和本机已有大图均保留，不迁移、不复用。

## 核心文档

- [可运行版实施文档](docs/LibraMAS_纯推荐模块实施文档_可运行版.md)
- [安全低耦合实施计划](docs/LibraMAS_系统实施计划_安全低耦合版.md)
- [实施状态与交接记录](docs/LibraMAS_实施状态与交接记录.md)
- [G1 可启动工程骨架本地验收清单](docs/G1_RUNNABLE_SKELETON_MANIFEST.md)
- [安全与零删除政策](docs/SAFETY_POLICY.md)
- [模块化单体 ADR](docs/adr/0001-modular-monolith.md)
- [核心数据字典](docs/data_dictionary.md)
- [HTTP API 契约](docs/api.md)
- [论文实验协议](docs/experiment_protocol.md)
- [A01—A25 验收矩阵](docs/acceptance_matrix.md)
- [图书数据接入契约](contracts/data/intake/book-intake-manifest.schema.json)
- [书目图谱模型与导入契约](docs/book_graph_model.md)
- [LLM 与 Prompt 配置基线](docs/LLM_PROMPT_CONFIGURATION.md)
- [书目图计划 Schema](contracts/data/intake/book-graph-plan.schema.json)
- [MySQL 书目计划 Schema](contracts/data/intake/mysql-book-plan.schema.json)
- [向量索引计划 Schema](contracts/data/intake/vector-index-plan.schema.json)
- [Chroma Collection 计划 Schema](contracts/data/intake/chroma-collection-plan.schema.json)

## 最高优先级安全约束

未经用户查看详细影响报告并明确批准：

- 不得删除任何文件；
- 不得物理删除任何数据库数据或对象；
- 不得清理持久卷、测试运行、实验结果或旧索引；
- 纠错、撤回、停用和恢复必须使用版本、补偿事件或前向修复。

详细规则已经固化在 `docs/SAFETY_POLICY.md`，并由自动化安全扫描强制执行。

## 架构方向

采用模块化单体与端口适配器：Catalog、Profile、Recommendation、Feedback 等业务域保持高内聚；Agent通过结构化消息和Orchestrator协作，不直接访问数据库或互相调用。

## 本地验证

需要 Python 3.11。Python 依赖拆分为 G0 门禁、G1 运行时和 G1 测试三个哈希锁；应在全新的虚拟环境中安装：

```bash
python3.11 -m venv .venv-g1-release-001
.venv-g1-release-001/bin/python -m pip install --require-hashes \
  -r backend/requirements-g0.lock \
  -r backend/requirements-g1.lock \
  -r backend/requirements-g1-test.lock
make verify-g0 PYTHON=.venv-g1-release-001/bin/python
make test-g1-python PYTHON=.venv-g1-release-001/bin/python
```

前端依赖必须在全新克隆或新的隔离目录中执行 `npm ci --ignore-scripts`。测试和构建命令为：

```bash
npm --prefix frontend run test
BUILD_RUN_ID=g1-local-20260802-001 make frontend-build
```

构建只写入新的 `frontend/dist/<run-id>`；若目标已存在则失败，不覆盖旧产物。以上本地门禁不连接数据库，也不修改业务数据。

## 隔离运行时

复制环境模板只能通过 create-only bootstrap 完成；已有目标不会被覆盖：

```bash
make bootstrap
# 编辑被 Git 忽略的 .env.compose，使用新的项目名和三个互不相同的本地密码
RUN_ID=g1-20260802-001 make verify-g1-runtime
# 首次验收通过并保留停止后的容器与卷后，日常使用：
make start
make status
make stop
```

首次运行时验收必须先于该项目名的任何手工 `make start`，因为它只允许此前不存在的 Compose 项目、网络和三个命名卷。它检查五个服务、前后端健康接口、最小权限持久化标记以及两次安全停止/启动的一致性，并把证据追加到新的 `artifacts/verification/g1/<run-id>`。停止只使用 `docker compose stop`；不得执行删容器、删卷或数据库清理命令。

## 当前目录

```text
backend/app/                          领域契约、健康应用切片及基础设施适配器
contracts/                            Agent、配置、安全和 OpenAPI Schema
frontend/                             G1 状态页、G7 推荐工作台及追加式构建脚本
infra/                                新卷专用的最小权限初始化入口
scripts/                              安全、架构、环境与验收门禁
tests/                                G0/G1 自动化测试
contracts/data/intake/                 规范化书目与接入 Manifest Schema
```

## 版本管理

每个Gate使用独立分支和详细提交说明。提交正文至少记录：

1. 变更目的与范围；
2. 关键设计决策；
3. 验证命令和结果；
4. 文件与数据库安全影响；
5. 后续工作或已知限制。

远程仓库固定为 `https://github.com/Aruomeng/RecPro.git`。发布前必须先通过本地门禁；推送和 Pull Request 只在认证工具可用后执行。
