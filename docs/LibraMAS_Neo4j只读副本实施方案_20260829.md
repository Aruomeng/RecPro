# LibraMAS Neo4j Community 只读副本实施方案

## 1. 决策结论

当前独立图书馆 Neo4j 为 Community 5.26.28。Community 可以创建用户，但不存在 RBAC，所有用户都具有隐含管理员能力，因此仅创建名为 `recpro_graph_reader` 的用户不能形成真实最小权限边界。

本阶段采用独立只读副本：

- 保留现有 `recpro-library-neo4j` 容器、数据卷、端口、用户和全部 v1/v2 图事实不变。
- 新建一个仅监听 `127.0.0.1` 的 Community 容器和独立数据卷。
- 正常启动配置固定为 `server.databases.default_to_read_only=true`。
- 通过 system 数据库临时把 `neo4j` 加入 writable 集合，导入冻结的 v1/v2 制品后立即移除。
- 导入异常时也执行移除；若动态移除失败，则只重启新副本容器，使动态设置消失并恢复 Compose 中的默认只读配置。
- 后端只有在副本图计数、源图零变化和只读配置全部通过后，才能使用副本凭据。

该方案不能提供 Enterprise 的标签/关系级 RBAC，但可在不替换现有数据库的条件下，将数据写入能力从数据库实例层面关闭。后端仍保留固定 Cypher、Label/Relationship 白名单、参数化查询、3秒超时和结果上限，形成数据库只读配置与应用查询白名单两层边界。

## 2. 新增组件

- `compose.neo4j-readonly.yaml`
  - 固定 Neo4j Community 5.26.28 镜像摘要。
  - 新项目 `recpro-neo4j-readonly-20260829`。
  - 新数据卷 `recpro_neo4j_readonly_20260829_data`。
  - HTTP/Bolt 默认使用 `62748/62768`，均只监听本机。
  - 数据库正常启动默认只读。
- `scripts/build_neo4j_readonly_replica_plan.py`
  - 不连接 Docker、Neo4j、MySQL 或公网。
  - 验证 v1/v2 图制品并计算精确节点、关系和基础设施增量。
  - 绑定 Compose、执行器、导入器和所有图制品哈希。
- `scripts/execute_neo4j_readonly_replica_plan.py`
  - 默认仅 dry-run。
  - Apply 必须同时匹配计划文件、`plan_id` 和 `plan_hash`。
  - 只允许创建一个新容器、一个新卷和一个权限为0600的新凭据文件。
  - 不提供 down、删除容器、删除卷、删除图事实或覆盖现有数据库的路径。

## 3. 精确数据预算

| 图版本 | 节点 | 关系 |
|---|---:|---:|
| `lib-books-v1-20260810` | 63,388 | 191,865 |
| `lib-books-v2-20260828` | 78,129 | 206,848 |
| 新副本合计 | 141,517 | 398,713 |

其他预算：

- 新容器：1。
- 新数据卷：1。
- 新本地凭据文件：1，文件名 `.env.neo4j-readonly.local`，权限0600。
- 动态运行配置动作：最多2次，临时开放和关闭新副本的 writable 集合。
- 现有 Neo4j 写入：0。
- MySQL、Chroma 写入：0。
- DeepSeek 请求：0。
- 文件、数据库、容器、数据卷删除：0。

## 4. Fail-forward 边界

- 执行前目标项目、容器、卷、端口凭据文件必须全部不存在。
- 任一对象已经存在时停止，不接管、不覆盖、不清理。
- 导入失败时保留已追加事实用于调查，不补偿删除。
- 临时 writable 例外的清除位于 `finally` 边界；清除失败时重启新副本以恢复静态默认只读配置。
- 执行器不删除失败容器、失败数据卷或凭据文件，后续只能通过新的影响报告和精确计划继续处理。
- 原图库在执行前后分别读取 v1/v2 计数，任何变化均使验收失败。

## 5. 当前状态

- Compose 静态解析通过。
- dry-run 精确返回141,517节点、398,713关系，Docker连接和数据库连接均为0。
- G13 四项专项测试通过。
- 全量后端683项测试通过；本阶段新增范围的安全与架构扫描违规为0。
- 尚未启动新容器、创建新卷、生成密码或导入任何图事实。
- 代码冻结并提交后生成最终 ChangePlan；只有用户精确批准最终 `plan_id + plan_hash` 才能执行。

## 6. 官方能力依据

- Neo4j Community 没有角色，用户具有隐含管理员权限：<https://neo4j.com/docs/operations-manual/current/authentication-authorization/manage-users/>
- `server.databases.default_to_read_only` 和 `server.databases.read_only` 用于阻止数据库写查询：<https://neo4j.com/docs/operations-manual/current/configuration/configuration-settings/>
- system 数据库始终可写，因此运行时后端仍禁止连接 system 数据库，只能连接固定的 `neo4j` 数据库：<https://neo4j.com/docs/operations-manual/current/database-administration/standard-databases/configuration-parameters/>
