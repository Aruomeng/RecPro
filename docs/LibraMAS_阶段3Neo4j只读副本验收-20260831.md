# LibraMAS 阶段 3：Neo4j 独立只读数据面验收

## 结论

阶段 3 已完成。此前批准的“最终清洁副本”计划已经成功创建独立 Neo4j Community 副本，导入冻结的 v1/v2 图制品，并在恢复默认只读配置后通过精确回读。当前不再重复创建容器、数据卷或导入图事实。

本阶段执行计划：

- `plan_id`：`6f3e03bd-ea67-522e-9a27-39743cda53e9`
- `plan_hash`：`1dc3f9353d34b8483b03df5d2785ee97b96791ffe280467bc52238bc1f08da08`
- 运行标识：`neo4j-readonly-final-20260829-001`
- 验收证据：`artifacts/verification/neo4j-readonly-replica/neo4j-readonly-final-20260829-001/acceptance.json`

## 实际产出

- 独立 Compose 项目：`recpro-neo4j-readonly-final-20260829`。
- 独立数据卷：`recpro_neo4j_readonly_final_20260829_data`。
- 独立日志卷：`recpro_neo4j_readonly_final_20260829_logs`。
- 独立本地凭据文件：`.env.neo4j-readonly-final.local`，权限为 `0600`，密码未进入 Git、日志或公开证据。
- 研究运行时使用副本端口 `62948/62968`，当前容器健康运行。
- 默认配置已恢复并验收：
  - `server.databases.default_to_read_only=true`
  - `server.databases.writable=`（空）

## 图数据对账

| 图版本 | 节点 | 关系 |
|---|---:|---:|
| `lib-books-v1-20260810` | 63,388 | 191,865 |
| `lib-books-v2-20260828` | 78,129 | 206,848 |
| 副本合计 | 141,517 | 398,713 |

副本导入前为空，导入后计数与冻结制品完全一致；原图库导入前后均为 v1 `63,388/191,865`、v2 `78,129/206,848`，源图变化为 0。

## 应用边界

- 后端绑定独立副本，不使用原图库管理员凭据作为研究读取身份。
- 公共图谱继续使用固定 Label/Relationship 白名单、参数化 `MATCH`、最多 3 跳、最多 60 个节点/120 条边和超时限制。
- Neo4j Community 不提供 Enterprise 级标签/关系 RBAC；当前安全边界由独立副本的数据库级只读配置与应用查询白名单共同提供。
- 旧的失败副本及其容器、数据卷和日志全部保留，未进行恢复性删除、日志截断或替换。

## 安全计数

- 原图库写入：`0`
- MySQL/Chroma 写入：`0`
- DeepSeek 请求：`0`
- 文件删除：`0`
- 数据库记录/数据库删除：`0`
- 容器删除：`0`
- 数据卷删除：`0`

## 当前阶段状态

- 阶段 1：已完成。
- 阶段 2：已完成，真实本地登录与个性化闭环已验收。
- 阶段 3：已完成，独立只读 Neo4j 数据面已验收。
- 阶段 4：下一阶段，六个浏览器业务场景需要基于当前提交重新生成 successor ChangePlan；涉及业务追加、反馈和真实模型请求的场景，在获得精确批准前只做 dry-run。

