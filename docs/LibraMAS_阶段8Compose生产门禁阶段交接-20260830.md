# LibraMAS 阶段 8：单机 Compose 生产门禁交接

```text
交接 ID：PRODUCTION-COMPOSE-GATE-20260830-001
范围：单机 Docker Compose、TLS 边缘、OIDC-only 与最小权限预检
状态：POLICY_CODE_COMPLETE / DEPLOYMENT_NOT_ENABLED
```

## 已完成

- 新增 `backend.app.platform.production` 纯函数门禁，要求 production 环境、显式生产 HTTP 开关、OIDC-only、注入式 JWKS 与本地身份映射、TLS、Secure Cookie、MySQL/Neo4j 最小权限身份、Recommendation/Feedback/Behavior 完整 API、readiness、独立恢复目标和明确模型策略。
- 新增 `build_production_deployment_app()`。它先通过门禁，再调用既有 production HTTP 组合；构造阶段不连接数据库、不访问 JWKS、不调用 DeepSeek，也不启动容器。
- 保留 `build_production_http_app()` 作为兼容的 production-shaped 组合测试入口；它不是本计划的最终部署批准凭据。
- 新增 `scripts/verify_production_deployment.py`，只读取公开环境标志并生成不可覆盖的 JSON 预检结果。报告不读取或回显密码、令牌、证书内容。
- 新增未启用的 `compose.production.yaml` 和 `infra/proxy/nginx.production.conf`：后者提供 TLS 1.2/1.3、HSTS、CSP、Secure 转发头和只读证书挂载模板；覆盖文件不会自动加入默认 Compose。
- 默认 `compose.yaml`、`.env.compose.example`、health-only `backend.app.main:app` 和后台规划仍保持 fail-closed。

## 纯代码验证

- `tests/g14/test_production_gate.py`：门禁完整性、OIDC/TLS、最小权限、错误脱敏和环境预检共 6 项通过。
- 使用占位变量执行 `docker compose -f compose.yaml -f compose.production.yaml config --quiet`，配置解析通过；未创建或修改容器、网络、数据卷。
- 阶段 5/7 相关测试继续通过。

## 尚未启用的内容

以下动作均需要单独 successor ChangePlan 和精确批准，当前没有执行：

1. OIDC 外部 subject 映射表和本地映射 Adapter。
2. 生产 TLS 证书、域名、CORS 和 Secret 注入。
3. 生产版完整 Recommendation/Feedback/Behavior/Exploration/Workspace 组合入口。
4. 只读 Neo4j 副本在生产 Compose 中的正式绑定。
5. 独立目标的备份与恢复演练。
6. 生产 Worker、后台规划和真实 DeepSeek 请求预算。

## 安全计数

本阶段代码与预检：数据库读取 `0`、数据库写入 `0`、Neo4j 写入 `0`、Chroma 写入 `0`、DeepSeek 请求 `0`、容器变化 `0`、数据卷变化 `0`、文件/数据库事实删除 `0`。

生产门禁通过不等于生产已经上线；只有完成上述依赖、获得对应批准并保存 readiness、TLS、OIDC、备份和恢复证据后，才可把状态标为 `PRODUCTION_READY`。
