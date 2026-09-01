# LibraMAS 阶段 7：OIDC/JWKS 本地映射实现状态

状态：`CODE_COMPLETE / MIGRATION_NOT_APPLIED / PROVIDER_NOT_CONNECTED`

## 本次完成

- 新增 `MySQLOIDCIdentityMapper`：只执行参数化 `SELECT`，从本地有效角色事实构造浏览器 Principal；不接受外部 token 的角色声明。
- 新增 `OIDCSubjectHasher`：外部 issuer 使用 SHA-256 指纹，外部 subject 使用与 issuer 绑定的 HMAC-SHA256；数据库和日志路径不保存原始 subject、token 或外部角色。
- 新增配置 `RECPRO_OIDC_SUBJECT_PEPPER`（仅 OIDC/Hybrid 模式必填）。缺少该 Pepper 时应用配置 fail-closed。
- 新增前向迁移草案 `011_g14_oidc_identity_binding.sql`：仅创建 `iam_oidc_identity_binding` 和追加迁移标记；外键均为 `RESTRICT`，没有删除、更新、覆盖或自动创建绑定记录。
- 新增零连接静态检查器 `scripts/verify_g14_oidc_mapping_migration.py`。

## 验证结果

- OIDC/JWKS、映射器、迁移安全和生产门禁共 16 项标准库测试通过。
- 静态检查：1 张新表、2 个索引、0 个绑定行、1 条迁移标记预算；数据库连接/写入、DeepSeek 请求、文件删除和数据库物理删除均为 0。

## 尚未执行的外部前置条件

1. 学校或部署方提供真实 OIDC `issuer`、`audience`、HTTPS JWKS URI 与可用的签名测试 token；当前不得自行猜测或连接外部 IdP。
2. 为 OIDC mapper 配置仅有必要 `SELECT` 权限的 MySQL 身份，以及独立 Pepper 注入方式。
3. 生成并批准新的精确 ChangePlan 后，才可创建 `iam_oidc_identity_binding` 表；计划必须列出新表/索引、迁移标记、预期绑定行数（默认 0）、测试 subject 摘要、回读对账和回滚到独立目标的方式。
4. 在至少一条经授权的外部身份绑定以追加事实方式建立后，才能将生产认证切换为 `RECPRO_AUTH_MODE=oidc`。

因此，本阶段已补齐可审查代码和安全边界；**生产 OIDC 仍未启用**，本地 JWT 研究模式未受影响。
