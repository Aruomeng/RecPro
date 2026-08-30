# LibraMAS OIDC/JWKS 适配器阶段交接

```text
交接 ID：OIDC-JWKS-20260830-001
范围：阶段 7 的纯代码适配器与配置门禁
状态：CODE_COMPLETE / INJECTED_PROVIDER_REQUIRED / NOT_ENABLED
```

## 产出

- 新增 `backend/app/platform/oidc.py`，提供 `OIDCBearerTokenResolver`、`JWKSCache`、`OIDCIdentityBinding` 和 `OIDCIdentityMapper`。
- JWT 仅接受 `RS256`、`PS256`、`ES256`，必须具备 `typ=JWT`、`kid`、签名、精确 `iss`、匹配 `aud`、`exp`、`iat`；多 audience 必须匹配 `azp`。RSA 小于2048位、非 P-256 EC、未知 `kid`、非法 `crit`、JWKS 超时或刷新失败全部拒绝。
- JWKS 缓存默认15分钟；未知 `kid`触发一次受限刷新，并设置短暂冷却，避免任意 kid 形成远程请求放大。刷新失败清空旧钥匙，fail-closed。
- 外部 `sub` 只交给注入的本地映射端口，角色来自本地映射而不是外部 token。`service_worker` 明确禁止浏览器身份。
- 新增配置 `RECPRO_AUTH_MODE=local|oidc|hybrid`、OIDC issuer/audience/JWKS URI 和缓存 TTL。默认仍为 `local`；OIDC/Hybrid 缺少 provider 配置时应用构造直接失败。
- `build_configured_auth_resolver` 和生产组合支持注入 OIDC fetcher/mapper；构造阶段不联网。Hybrid 先尝试 OIDC，再使用本地研究 JWT。

## 验证

- `tests/g14/test_oidc_jwks.py`：RSA 签名、角色不信任、未知 kid 冷却、时间与 audience、azp、service_worker 和配置门禁共 6 项通过。
- 生产与本地既有认证测试通过；当前未切换任何环境到 OIDC。
- 未访问外部 IdP/JWKS、未创建映射表、未执行数据库写入、未修改历史身份事实。

## 启用前置条件

生产启用还需要一个独立 successor ChangePlan，明确 OIDC 映射表（仅保存 Pepper 摘要）、索引、注入式 HTTPS JWKS 客户端超时、TLS/CORS/Cookie 策略、测试 subject、回滚到独立目标、最大请求预算和 `plan_id + plan_hash`。未批准前不得填写生产密钥、连接真实 IdP 或执行迁移。

文件、数据库记录、数据库、容器和数据卷删除数量均为 0。
