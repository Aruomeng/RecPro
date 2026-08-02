# LibraMAS 安全与零删除政策

| 属性 | 值 |
|---|---|
| 文档状态 | 生效（G0 基线） |
| 版本 | 1.0.0 |
| 生效日期 | 2026-08-02 |
| 适用仓库 | `Aruomeng/RecPro` |
| 适用环境 | 本地开发、测试、演示、实验、CI 和未来部署环境 |
| 最高优先级规则 | 未经用户看到详细报告并对精确申请作出明确批准，不得删除任何文件或任何数据库数据 |

本文是 LibraMAS 开发、测试、演示和实验的强制安全基线。实施文档、脚本、框架默认行为、第三方工具惯例、Agent 决策和临时口头说明均不得降低本文约束。若其他文档与本文冲突，以约束更严格者为准。

---

## 1. 不可破坏原则

1. 不删除既有文件，包括 Git 已跟踪文件、未跟踪文件、生成物、日志、实验结果、数据集、备份和持久化目录。
2. 不物理删除数据库中的任何数据或对象，包括行、节点、关系、属性历史、向量记录、集合、表、列、索引、Schema、数据库和持久卷。
3. 不覆盖同名文件、备份、实验运行、索引版本或数据集；输出必须使用新版本、新代次或新 `run_id`。
4. 纠错、撤销、隐藏和停用通过追加版本、状态事件、补偿事件或查询过滤完成，原始事实保留。
5. 任何无法证明 `expected_delete_count == 0` 的变更都必须拒绝执行。
6. 任何出现删除意图、危险命令或不确定影响的任务必须立即停止；先按 [删除申请模板](./DELETE_REQUEST_TEMPLATE.md) 向用户汇报，未获得对精确申请的一次性明确批准前不得继续。
7. Agent、LLM、前端和普通应用账号不得获得文件删除、数据库管理、自由 SQL/Cypher 或容器卷管理能力。
8. 故障发生后保留现场和证据，通过新的提交、新迁移、新版本或补偿事件前向修复，不通过清理、回滚已提交事实或重置环境恢复。

### 1.1 保护对象

保护范围至少包括：

- 源码、配置、密钥模板、迁移、测试、文档和 Git 元数据；
- MySQL 中的全部业务事实、审计事实、表结构和数据库对象；
- Chroma 的集合、记录、元数据、活动版本记录和持久化目录；
- Neo4j 的节点、关系、属性、约束、索引、图版本和数据库；
- Docker 容器的命名卷、绑定挂载目录、镜像构建证据和运行清单；
- Fixture、评测输入、实验输出、日志、Trace、备份、Manifest 和论文图表。

临时、测试、失败、过期、未跟踪或可再生成，不构成删除理由。

---

## 2. 操作分级与授权

| 级别 | 定义与示例 | 默认授权 | 强制控制 |
|---|---|---|---|
| S0 只读 | 查看文件、Git 状态、哈希、健康检查、只读查询 | 当前任务范围内允许 | 不产生持久化写入；记录关键证据 |
| S1 追加 | 新建文件、提交新版本、插入新事实、建立新版本索引 | 用户已启动对应实施阶段时允许 | ChangePlan、dry-run、幂等键、影响上限、执行回执 |
| S2 受控更新 | 修改既有源码；更新运行状态白名单列；切换活动版本指针 | 仅限任务明确范围 | ChangePlan、原版本可追溯、字段白名单、乐观锁、审计事件 |
| S3 破坏性 | 删除、清空、覆盖、降级、重置、移除持久卷或无法证明零删除的操作 | 禁止 | 立即停止并提交删除申请；只有精确、一次性批准才可重新评估 |

授权不得从一个环境、目标、命令或时间窗口推断到另一个。用户批准开发某功能不等于批准数据迁移，更不等于批准删除。

### 2.1 默认拒绝的行为类别

- 文件或目录删除、强制清理工作区、覆盖无可验证副本的既有文件；
- 数据行物理删除、表/列/Schema/数据库移除、清空、级联删除或破坏性迁移降级；
- Chroma 记录/集合移除、重置或复用名称覆盖旧版本；
- Neo4j 节点/关系/数据库移除，或为了消环修改持久化事实；
- Docker 持久卷移除、卷清理、带卷销毁环境；
- 自动清理旧测试、旧索引、失败构建、日志、备份、缓存或实验 run；
- 任何未解析变量、宽泛路径、通配符或未限定查询范围的持久化写操作。

安全扫描在可执行源码、迁移、Shell、Makefile、Compose 和 CI 配置中检查上述行为；政策与测试夹具中的文字样例必须明确标记为文档或拒绝用例。

---

## 3. ChangePlan 与 dry-run 协议

导入、迁移、回填、画像重算、索引构建、Fixture 准备、批量状态变更和活动版本切换必须先生成不可变 ChangePlan。默认模式始终为 dry-run；apply 不能由 dry-run 自动触发。

### 3.1 最小 ChangePlan 契约

```json
{
  "schema_version": "1.0.0",
  "plan_id": "bb4cae47-8bd8-4a33-9b18-0d269c90bff1",
  "created_at": "2026-08-02T00:00:00Z",
  "git_commit": "0123456789abcdef0123456789abcdef01234567",
  "classification": "S1_APPEND",
  "mode": "DRY_RUN",
  "intent": "Append a new, uniquely named fixture generation without changing existing facts.",
  "environment": {
    "environment_id": "recpro_dev_unique",
    "workspace": "/workspace/RecPro",
    "host_fingerprint": "sha256:9e5ed3a061ba0d5b74ea500c884a54c4f89cf94c6405318d2e5da47c404e70f1",
    "database_identity": "mysql://recpro_dev_unique",
    "index_namespace": null
  },
  "targets": [
    {
      "kind": "MYSQL",
      "identifier": "recpro_dev_unique.resource_catalog:fixture_generation=fixture-20260802-g0",
      "operation": "APPEND",
      "expected_before_count": 0,
      "expected_after_min_count": 120
    }
  ],
  "input_hashes": {
    "resources.jsonl": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
  },
  "idempotency_key": "fixture-20260802-g0",
  "max_changes": 120,
  "preconditions": [
    "environment identity matches the reviewed dry-run target",
    "runtime role has no delete privilege",
    "fixture generation does not already exist"
  ],
  "safety_assertions": {
    "file_deletions": 0,
    "database_physical_deletions": 0,
    "overwrite_existing": false,
    "destructive_capabilities_required": false,
    "counts_must_not_decrease": true
  },
  "plan_hash": "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
}
```

`safety_assertions.file_deletions` 与 `safety_assertions.database_physical_deletions` 必须为零，`safety_assertions.overwrite_existing` 与 `safety_assertions.destructive_capabilities_required` 必须为 `false`。未知值不等于零；无法计算时计划无效。`plan_hash` 由规范化后的计划内容计算，不能只覆盖部分字段。

跨字段门禁同样必须通过：`S0_READ_ONLY` 只允许 `READ` 且 `max_changes=0`；`S1_APPEND` 不允许受控更新操作；每个目标的 `expected_after_min_count` 不得小于 `expected_before_count`，全部目标的最小预期增量之和不得超过 `max_changes`。

### 3.2 dry-run 必须产出的证据

1. Git 提交、环境 ID、主机指纹、数据库/集合/图版本和目标命名空间。
2. 精确目标、主键或版本范围、选择器及其哈希。
3. 输入文件清单、字节数、SHA-256、配置版本和随机种子。
4. 变更前对象数量、预估变更数量、`expected_after_min_count` 以及 `max_changes` 影响上限。
5. 将执行的 SQL、Cypher、API 调用或文件写入计划；敏感值必须脱敏。
6. 权限自检、环境隔离检查、幂等检查、同名输出检查和零删除断言。
7. 失败注入或补偿路径，以及用于证明旧版本仍可用的检查。

dry-run 只能进行 S0 操作，不得通过“先写后回滚”模拟。离线迁移使用 SQL 渲染和静态扫描；数据任务使用只读计数、选择器和哈希计算。

### 3.3 apply 门禁

apply 必须同时满足：

- 明确携带 `--apply --plan-id <plan_id>`，且默认命令不包含 `--apply`；
- 重新计算的 `plan_hash`、输入哈希、环境身份和 Git 提交与 dry-run 一致；
- `safety_assertions.file_deletions == 0`、`safety_assertions.database_physical_deletions == 0` 且 `safety_assertions.overwrite_existing == false`；
- 实际账号权限不超过本政策矩阵；
- 目标 `run_id`、Fixture 代次、备份名或索引版本从未存在；
- 预计影响不超过 `max_changes` 和其他限制；
- ChangePlan 已得到当前阶段所需的执行授权。

任何一项不满足都必须 fail closed，不得询问脚本是否“继续执行”。执行结束生成不可变回执，至少含实际影响数、前后计数、版本指针、错误、耗时和证据哈希。实际影响超过计划时立即停止后续批次并标记 `QUARANTINED`。

---

## 4. 最小权限矩阵

| 身份 | 允许 | 明确禁止 | 启动门禁 |
|---|---|---|---|
| `recpro_readonly` | MySQL 只读查询；只读查看索引状态 | 所有写入、DDL 和管理操作 | 用于诊断和 dry-run；不得借用其他账号 |
| `recpro_runtime` | MySQL `SELECT`、`INSERT`；指定运行状态表的白名单 `UPDATE` | 删除、清空、DDL、授权、任意表更新 | 检测到危险或超范围权限时 readiness 失败并拒绝写请求 |
| `recpro_worker` | MySQL `SELECT`、`INSERT`；Outbox/任务白名单状态更新；通过受控适配器追加索引版本 | 删除、DDL、任意 SQL/Cypher、切换未验证版本 | 每个处理器必须有幂等键和影响上限 |
| `recpro_migrator` | 创建新表；新增 nullable 列、新索引、新约束 | 数据删除、清空、对象移除、破坏性降级、业务 DML | 只执行审核过的 expand-only 迁移和固定 revision |
| `recpro_index_builder` | 创建唯一 Chroma/Neo4j 版本命名空间并追加记录 | 移除、reset、复用旧名称、改变事实源 | 只接受签名/哈希匹配的构建计划 |
| Agent / LLM | 调用类型化应用端口；输出结构化建议 | 文件系统、数据库驱动、Shell、Docker、管理 API、自由 SQL/Cypher | 所有输出经 Schema、策略和领域服务校验 |
| 前端 | 通过公开 API 发出业务命令 | 直连数据库或索引；物理删除入口 | 服务端重新鉴权和校验，不能信任 UI 状态 |
| CI | 静态检查、隔离测试、构建新产物 | 生产凭证、持久化卷管理、自动清理共享环境 | 使用唯一 `test_run_id` 和隔离身份 |
| 人工运维 | 经审查执行精确 ChangePlan | 复用批准、扩大目标、交互式临时改写计划 | 双重核对环境与目标，保存完整回执 |

root、admin、DBA 或宿主机高权限凭证不得进入应用 `.env`、Compose 环境、CI 日志或 Agent 上下文。凭证模板只能保存变量名，不保存秘密。

---

## 5. 分层保护措施

### 5.1 文件系统与 Git

- 修改前读取 `git status --short`，将已有变更视为用户资产；不得覆盖或撤销不属于当前任务的修改。
- 新产物使用唯一名称并采用“写入新文件 → 校验 → 原子发布新引用”的方式；发布不得替换没有可验证副本的原件。
- 禁止在脚本中实现自动清理、保留期删除或启动时重置。
- 文件清单必须记录绝对/仓库相对路径、大小、mtime 和 SHA-256；变更后证明受保护文件数量未减少。
- 所有必要代码纳入 Git。每个提交聚焦单一交付，提交正文详细说明目的、范围、关键设计、验证、安全影响、数据影响和已知限制。
- 发现 Git 中存在非预期删除项时停止提交；先恢复工作计划，若确需删除则走删除申请流程。

### 5.2 MySQL

- MySQL 是业务事实唯一来源；事务、Outbox 和审计事实必须可追溯。
- Schema 迁移仅允许 expand-only：新表、新 nullable 列、新索引和新约束；已执行 revision 不得修改。
- 外键使用 `RESTRICT` 或 `NO ACTION`；禁止级联删除语义。
- 不使用会隐式替换既有行的写法；业务键冲突时 no-op、返回冲突或追加新 `metadata_version`。
- 业务事实表默认 append-only。允许更新的仅是显式白名单状态/租约字段，并同时追加状态迁移日志。
- 用户撤回、资源停用和画像纠错写入新事件或新版本；查询按当前有效版本过滤。
- 失败迁移用新 revision 前向修复；备份恢复到新的数据库或 Schema，禁止覆盖源环境。
- readiness 检查连接目标身份、字符集、Schema revision 和授权；发现删除或管理权限即失败关闭写流量。

### 5.3 Chroma

- Chroma 是可重建的派生索引，不得成为业务事实源。
- collection 使用不可复用的版本名；记录 ID 包含 `resource_id:metadata_version:embedding_version`，只追加、不覆盖。
- 重建时创建影子 collection，校验记录数、抽样召回、输入哈希和资源版本后，追加活动版本记录。
- 构建失败保留失败 collection，标为 `NOT_ACTIVE`，主链继续读取最近一次健康版本或降级到 MySQL。
- 资源停用通过 MySQL 当前状态与查询过滤完成，不清理旧向量。
- 持久化目录、旧 collection 和失败证据均保留；容量压力只能告警并提交治理建议，不能触发自动删除。

### 5.4 Neo4j

- Neo4j 是派生知识图谱；节点和关系必须携带 `graph_version`、来源和证据。
- 图重建写入新 `graph_version`，校验后追加活动版本记录；旧版本保留可查询。
- 阅读路径发现环时只在本次计算中忽略选定边，并记录原因、关系 ID 和 Trace，不修改图事实。
- 关系纠错追加新证据、替代关系或失效状态，不移除原节点/关系。
- Agent 只能调用参数化图查询端口；不能直接生成并执行自由 Cypher。
- Neo4j 不可用、超时或版本不匹配时降级为 MySQL 主链，并在结果中记录降级码。

### 5.5 Docker 与运行环境

- Compose 使用具名持久卷和明确绑定挂载；不同环境使用唯一 project name、端口和数据库标识。
- “停止”只停止服务并保留卷；不得把卷移除或环境清理绑定到常规 stop/test 命令。
- 每次集成、E2E、演示和实验使用新 `test_run_id`/`fixture_generation`，结束时只封存 Manifest。
- 启动前校验环境标识、卷名、目标主机和凭证类型；生产/共享环境与本地测试标识不一致时拒绝启动。
- 镜像、容器、卷或缓存空间不足时报告容量和替代方案，不自动 prune。
- 容器健康检查不得修改业务数据；初始化脚本必须幂等、只追加且受 ChangePlan 控制。

---

## 6. 失败前向修复

| 失败场景 | 必须保留 | 前向修复方式 | 禁止的恢复方式 |
|---|---|---|---|
| 代码缺陷 | 失败提交、日志、复现输入 | 新修复提交；必要时创建显式 revert 提交 | 强制重置或清理用户工作区 |
| 迁移部分失败 | 已执行 revision、SQL 报告、错误和计数 | 新建更高 revision 修正；暂停后续写入 | 修改已执行 migration 或破坏性 downgrade |
| 导入部分失败 | 已提交批次、幂等键、失败行和输入哈希 | 同一计划幂等续跑或新 successor plan | 清空后重导、覆盖旧批次 |
| Outbox 消费失败 | 事件、尝试次数、错误和 Trace | 幂等重试；超限追加 `DEAD` 状态并人工处理 | 移除失败事件 |
| 画像/反馈错误 | 原事实、计算版本和审计链 | 追加撤回/补偿事件并重算新版本 | 改写或删除历史事件 |
| Chroma 构建失败 | 失败 collection、Manifest、日志 | 新 embedding/index 版本重建；沿用健康活动版本 | reset 或清除 collection |
| Neo4j 构建失败 | 失败 graph_version、证据和日志 | 新 graph_version 重建；降级到 MySQL | 移除图数据库或旧版本 |
| 实验配置错误 | 原 run、配置、随机种子和结果 | 新 run_id 重新执行并标记旧 run 无效 | 覆盖同名结果 |

恢复完成后必须生成报告，证明：受保护对象数量未减少；原事实仍可查询；新版本与失败版本可区分；活动指针只指向已校验版本；所有影响均在 ChangePlan 上限内。

---

## 7. 删除申请与批准边界

删除不是普通 ChangePlan 的一种可选模式。只要工具、依赖、迁移或人工判断提出任何删除，就必须：

1. 停止当前写操作并保持现场不变。
2. 使用 `docs/DELETE_REQUEST_TEMPLATE.md` 列出精确目标、原因、替代方案、影响、备份、恢复演练、dry-run 和拟执行动作。
3. 将报告交给用户；“继续”“处理一下”“按计划执行”等模糊表达不构成批准。
4. 只有用户明确回复“同意删除申请 `<申请编号>`”且申请尚未变化时，才获得该编号、目标、环境、操作者和时间窗口的一次性权限。
5. 目标、数量、哈希、环境、命令或依赖任何一项变化，原批准立即失效，必须重新申请。
6. 即使已批准，执行前再次验证备份、恢复演练、目标身份和影响上限；无法验证则拒绝执行。

未批准、已过期、已使用或范围不明的申请一律视为拒绝。实现阶段不得预先编写“便捷删除”脚本等待批准。

---

## 8. 审计、证据与交付门禁

每个写入阶段至少保留：

- ChangePlan、规范化 `plan_hash`、dry-run 报告和 apply 回执；
- Git 提交 SHA、依赖锁文件哈希、配置 Bundle 版本和环境身份；
- 写入前后对象计数、输入/输出 SHA-256、实际新增/更新/删除数；
- 数据库 revision、活动索引版本、Trace ID、执行者和 UTC 时间；
- 测试报告、失败注入结果、降级证据和前向恢复报告。

安全门禁至少验证：

1. Git 变更中没有未经批准的文件删除或覆盖。
2. 可执行文件静态扫描未发现危险行为。
3. 应用和 Worker 账号不具有删除、清空、对象移除或管理权限。
4. dry-run 前后文件哈希、数据库行数、Chroma 记录数和 Neo4j 节点/关系数不减少。
5. 重复 apply 由幂等键变为 no-op 或返回明确冲突，不产生重复事实。
6. 故障注入后旧活动版本仍可服务，失败现场和审计记录完整。
7. 实际 `delete_count` 和 `overwrite_file_count` 为零；否则发布门禁失败并启动事件汇报。

### 8.1 每次提交的详细日志格式

```text
<type>(<scope>): <明确结果>

目的：为什么需要本次变更
范围：新增/修改的模块与边界
设计：关键契约、依赖方向和取舍
验证：实际运行的检查与结果
安全：删除数、覆盖数、权限与dry-run结论
数据：数据库/索引是否写入及影响计数
限制：尚未完成或已知风险
关联：阶段、ChangePlan、ADR、测试或Issue
```

提交信息不得声称未实际验证的结果。提交前必须检查差异、未跟踪文件和敏感信息；不自动暂存无关文件。

---

## 9. 偏差处理

发现安全规则被违反或可能被违反时：

1. 停止新写入，不删除或改写现场。
2. 记录时间、环境、操作者、提交、计划、目标、实际影响和证据哈希。
3. 将相关对象标记为 `QUARANTINED` 或追加故障状态，不伪造成功。
4. 向用户报告事实、潜在影响和非删除恢复方案。
5. 创建前向修复 ChangePlan，经 dry-run 和门禁后再实施。
6. 完成后补充测试和 ADR，防止同类问题再次发生。

本政策只能通过新的、版本化的 ADR 加严或在用户明确批准后变更；不得静默修改或通过实现细节绕过。
