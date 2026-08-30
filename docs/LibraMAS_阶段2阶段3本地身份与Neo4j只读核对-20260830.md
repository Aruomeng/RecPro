# LibraMAS 阶段 2/3 本地身份与 Neo4j 只读核对

```text
核对 ID：IDENTITY-GRAPH-READONLY-20260830-001
状态：LOCAL_IDENTITY_ACTIVE / GRAPH_REPLICA_READY / NO_NEW_WRITE
```

## 阶段 2：账号与个性化前置条件

使用运行容器内现有应用账号执行了只读 `SELECT`，未使用 root 写入，也未修改任何表：

| 对象 | 当前事实 |
|---|---:|
| `iam_user_account` | 1 行 |
| `iam_password_credential` | 1 行 |
| `iam_auth_session` | 0 行 |
| `iam_user_role_fact` | 3 行 |
| `iam_security_event` | 2 行 |
| 首个管理员 | `user_id=10000`、`ACTIVE`、`must_change_password=0` |

管理员已经完成激活，未再次消费激活码，也没有复用合成画像用户 `1001/1002`。本阶段未创建测试读者、未生成新密码、未登录真实账号、未追加画像或行为事实；这些动作仍需独立精确 successor ChangePlan。

当前代码已支持本地登录、刷新令牌轮换、退出、密码变更、角色与个性化授权，但浏览器真实登录—画像—推荐链路尚未执行验收，以避免在没有独立业务写入计划时改变数据库事实。

## 阶段 3：Neo4j 只读副本

- 保留原有图数据库和两个历史副本，没有停止、删除、覆盖或重建任何现有对象。
- `recpro-neo4j-readonly-final-20260829-neo4j-readonly-final-1` 当前健康运行。
- `NEO4J_server_databases_default__to__read__only=true` 已在容器配置中生效；研究应用使用独立副本端口和凭据，不使用原图库管理员凭据。
- 副本只读计数：`141,517` 节点、`398,713` 关系，对应 `lib-books-v1-20260810` 与 `lib-books-v2-20260828` 冻结制品。
- 运行应用 readiness 报告 `neo4j=UP`、活动图版本 `lib-books-v2-20260828`；查询仍受 Label/Relationship 白名单、参数化 MATCH、3 跳、60 节点、120 边和超时限制。

为避免误读，默认 Compose 的历史 `neo4j` 服务当前仍是独立环境；本次只读计数核对使用 final 副本，不修改默认 Compose 绑定。

## 证据与安全计数

- Docker：现有容器均保持运行和健康；未执行 `compose down`、重启、替换或卷操作。
- MySQL：只读查询；数据库写入 `0`。
- Neo4j：只读计数查询；图事实写入 `0`。
- Chroma：写入 `0`。
- DeepSeek：请求 `0`。
- 文件删除、数据库记录删除、数据库删除、容器删除、数据卷删除：均为 `0`。

## 未闭环事项

1. 测试读者账号与个性化授权需单独 ChangePlan，不能在本核对中顺便创建。
2. Neo4j Community 仍不具备 Enterprise 级 RBAC；当前安全边界依赖独立只读副本 + 应用查询白名单。若迁移新副本或导入新图版本，必须重新生成并批准 Neo4j successor ChangePlan。
3. 六个浏览器业务场景涉及业务写入、反馈或模型请求，已准备独立 DRY_RUN successor 计划，批准前不执行。
