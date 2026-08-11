# LibraMAS / RecPro

LibraMAS 是一个面向智慧图书馆知识资源推荐的研究生论文原型，核心研究方向为多智能体协同、动态交互策略、可解释推荐与反馈学习。

## 当前状态

G0—G5 的核心代码切片、MySQL 隔离运行态和安全门禁已经建立；G6 已完成真实图书数据、可选检索能力和一次隔离目标只读融合验证。`Lib` 已完成 76 个 CSV 的只读规范化，并将版本化图 `lib-books-v1-20260810` 追加导入独立 Neo4j（15,538 条来源记录、63,388 个节点、191,865 条关系）；在用户明确授权后，同一书目已按 append-only ChangePlan 写入隔离 Compose MySQL（14,983 本书、8,516 个标签、70,750 条标签关系），并完成幂等复跑与只读计数核验。当前已基于同一 MySQL ChangePlan 离线构建 14,983 条确定性向量记录（`hash-char-ngram-v1`、384 维），两次独立构建哈希一致；用户授权后已在独立本地 Chroma 路径创建新 collection `library_resources__hash_char_ngram_v1`，追加 14,983 条向量，并完成全量回读、版本/元数据核验、召回冒烟和幂等复核（`chromadb==1.5.9`）。MySQL 的 `embedding_status=PENDING` 未修改。Neo4j/Chroma 只读召回端口已通过真实隔离运行态融合验证：固定三组版本，MySQL 计数和 Chroma 14,983 条向量前后不变，8 条候选同时带 MYSQL/GRAPH/VECTOR 通道且无 fallback；详细证据见 `artifacts/verification/g6/g6-retrieval-fusion-readonly-20260811-001/readonly.json`。G7 已有推荐工作台、契约化 RecommendationClient、澄清交互占位和明确标注的本地演示；默认页面会根据健康响应决定是否允许真实请求，默认 `can_recommend=false` 时仍只显示闸门提示，不会绕过健康闸门或自动写入数据库。新增的显式 Demo/Production HTTP 组合根只有在调用方提供服务、启用 API 与健康闸门后才会声明 `can_recommend=true`；默认 HTTP/API/Worker 仍保持关闭，`can_recommend` 不因容器启动而自动变为 `true`。

G7 已在隔离 Compose MySQL（本地端口 `62306`）完成真实只读 HTTP 冒烟：live/ready 均通过，`can_recommend=true`，推荐管线版本为 `recommendation-g3-mysql-v1`；资源与推荐相关 13 张表的前后计数完全一致，业务 POST 与数据库写入均为 0。基线证据见 `artifacts/verification/g7/g7-mysql-http-readonly-20260811-005/readonly.json`（实际执行 30 条只读 SQL）；此前 `...-001` 至 `...-004` 证据均保留、未覆盖。此前一次旧计划执行在写入前因 15,000 资源上的重复全量排序被安全中止，计数经只读复核未变化；G3 已提交通道排名预计算修复（`4915351`），15,000 条离线基准约 0.14 秒。用户确认新 plan hash=`2b115b3790a6281f4725be7fe29a5448e674c92570cdaac766cc0f40eb961d53` 后，已按该 `S1_APPEND/DRY_RUN` ChangePlan 在同一隔离 MySQL 执行一次真实 POST：新增 task 1、transition 8、candidate 15、record 1、item 5、explanation 5、policy 1、trace 1，共 37 行；资源事实表计数不变，任务回读为 `COMPLETED`、record=`19`。只读回读证据见 `artifacts/verification/g7/g7-recommendation-post-reconcile-20260811-001/reconciliation.json`；回读本身数据库写入和业务 POST 均为 0，未进行重复提交。
前端现在有独立的显式 Demo HTTP 入口 `backend.app.demo_main:app`：必须同时设置 `RECPRO_APP_ENV=demo` 与 `RECPRO_DEMO_HTTP_ENABLED=true`，默认 `backend.app.main:app` 和 Compose 命令仍保持 health-only。Vite 代理浏览器冒烟已通过真实 health GET，工作台可识别 `can_recommend=true` 并安全展示本地演示；证据见 `artifacts/verification/g7/g7-frontend-api-browser-20260811-001/frontend.json`。浏览器尚未重复发送真实推荐 POST，避免复用已完成幂等键。
G4 已完成一次真实隔离只读多智能体融合：7 个 Agent 全部成功，8 条候选同时带 `MYSQL+GRAPH+VECTOR` 通道，固定 graph/embedding/index 版本，MySQL 资源与 Agent 事实表、Chroma collection 前后计数均不变；证据见 `artifacts/verification/g4/g4-readonly-fusion-20260811-001/readonly.json`。随后新增了无副作用的 G4→HTTP 投影契约和显式 MySQL writer：命令映射保留 scene 与冻结时间，候选通道可拆分为可持久化的独立值，写入前要求资源摘要、证据置信度、channel rank/score、解释证据和 item identity 完整；task/transition/candidate/record 写入均做 INSERT IGNORE 后身份回读。G4 RecommendationTaskService 及研究组合根已具备，但仍未替换 G3 HTTP 持久化服务；默认 HTTP/Worker 不会自动启用 G4。
随后按用户批准的 successor ChangePlan 完成了一次真实 G4 受控追加：精确请求返回 8 个候选，其中 `MYSQL=8`、`VECTOR=5`，拆分后追加 13 条候选行；连同 task、7 个 Agent 的 message/result、record、8 个 item、解释、policy、trace 等共 57 行。任务状态为 `COMPLETED`，8 个条目，Neo4j/Chroma/外部 LLM 均 0 写入或请求；详细执行与回读证据见 `artifacts/verification/g4/g4-projection-apply-20260811-002/g4-recommendation-projection-apply.json` 和 `artifacts/verification/g4/g4-readonly-fusion-20260811-008/readonly.json`。默认 HTTP/Worker 仍保持关闭。
G4 澄清续跑适配器随后已完成代码级实现：Orchestrator 可从 `WAITING_CLARIFICATION` 继续，G4 writer 对 context 2 及后续轮次只追加 transition、Agent facts、trace revision、policy、结果和回答上下文；服务在最新上下文校验、幂等重放、冲突、陈旧版本和并发唯一性失败时回滚，且不执行 `UPDATE/DELETE`。主题答案支持最多 500 字符的自定义组合文本，资源类型仍是封闭枚举。随后已对具体 task 完成一次获批真实续跑：`BOOK` + `多智能体+推荐系统+知识图谱` 进入 `COMPLETED/context_version=2`，record=`22`、5 个图书条目，精确追加 44 行；证据见 `artifacts/verification/g4/g4-clarification-continuation-apply-20260811-001/g4-clarification-continuation-apply.json`。默认 HTTP/Worker/外部 LLM 仍关闭。
等待态只读验证器和 19 行初始等待任务 DRY_RUN 构建器已加入仓库；它们会冻结 HOME 空请求、4 个 Agent、问题快照、完整表计数和幂等身份。当前 Docker CLI 符号链接指向不存在的 Docker Desktop 路径，尚未生成新的运行态基线或 ChangePlan artifact；恢复 Docker 后先运行只读验证，再生成计划，期间不执行任何业务写入。
隔离端口仍在运行，因此已绕过 Docker CLI 完成真实 MySQL 只读验证：HOME 空请求稳定进入 `WAITING_CLARIFICATION`，19 张相关表前后计数不变，证据见 `artifacts/verification/g4/g4-clarification-readonly-20260811-001/clarification-readonly.json`。初始 19 行等待任务计划已预演生成，但交接文档提交后会重新生成 hash；在最终 hash 获得用户批准前不会创建任务或提交答案。
等待任务专用执行器也已完成：它严格校验 plan/evidence/config/Git hash、权限、幂等身份和 19 张表的精确 delta；continuation 执行器进一步校验 44 行精确目标、最新上下文和 answer payload，显式 `--apply` 之外不会写库。此前失败尝试已按零增量隔离并修复；两次真实追加均完成独立只读回读，所有历史事实保留，不执行删除或覆盖。

最近配置修复已完成：`scripts/sync_host_env_from_compose.py` 将经过预检的隔离 Compose 参数安全同步到本机 `.env.host`，修复 host MySQL 端口与迁移凭据缺口，并保留 `0600` 备份；旧前端依赖目录只移动到 `/tmp` 备份后按 `package-lock.json` 恢复，40 个前端测试和生产构建通过。Makefile 现在能自动定位本机实际 Docker Desktop CLI；Compose 健康检查已改为对启动负载更稳健的超时与 Neo4j HTTP+Bolt 端口探测。当前 MySQL、backend、frontend 与本项目隔离 Neo4j 均已健康；独立图书 Neo4j 始终未停止或写入，也未删除任何卷或数据库数据。详细证据见 `docs/LibraMAS_实施状态与交接记录.md` 的 `CONFIG-FIX-20260811-001`。

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
