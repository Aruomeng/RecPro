# LibraMAS LLM 与 Prompt 配置基线

本文件冻结当前原型的 LLM 配置边界。它只描述文本能力，不改变 MySQL、Neo4j 或 Chroma 的数据事实，也不会因为配置存在而自动发起外部请求。

## 1. 当前默认与显式启用

默认配置仍为：

```dotenv
RECPRO_LLM_PROVIDER=mock
RECPRO_PROMPT_BUNDLE_VERSION=prompt-v1
RECPRO_PROMPT_BUNDLE_PATH=contracts/prompts/rec-prompts-v1.0.0.json
RECPRO_PROMPT_BUNDLE_SHA256=bad547702e4c3b42395280ea44781e60992a85f981605afbcd29aa13d33db94a
```

DeepSeek 只有在本地被忽略的环境文件中显式设置 `RECPRO_LLM_PROVIDER=deepseek` 和 `RECPRO_LLM_API_KEY` 后才允许构造。密钥不能写入仓库、Prompt Bundle、Agent 消息、日志、实验 Manifest 或验证 artifact；仓库不保存真实密钥。

当前本机运行配置已由用户提供并写入被 Git 忽略的 `.env.host` 和 `.env.compose`，两个文件权限均为 `0600`。配置使用 `deepseek`、`deepseek-v4-flash`、HTTPS `https://api.deepseek.com`、20 秒超时、512 个最大输出 token，并绑定 `prompt-v1` 与固定 Prompt Bundle SHA-256。密钥值不会在文档、命令输出或提交中显示。已完成离线 provider 构造验证和 Compose 环境结构校验，尚未发起任何 DeepSeek 网络请求。

当前就绪证据：`artifacts/verification/llm/llm-real-call-readiness-20260812-001/real-call-readiness.json`=`READY_FOR_EXPLICIT_OPT_IN`。该检查只读取 `.env.host`、构造 DeepSeek provider 并验证 Prompt Bundle；`network_requests=0`、`external_llm_requests=0`、数据库读写=0。它证明“可以进入一次明确授权的真实调用”，不证明已经调用，也不会改变默认 Mock/关闭状态。

要让一个研究组合根使用文本能力，还必须显式传入 `enable_llm_provider=True`。默认规则编排、默认 FastAPI 和 Worker 都不因设置文件存在而改变：

```python
service = build_research_orchestration_service(
    settings,
    enable_llm_provider=True,
)
```

这一步只构造 provider 和 Agent；实际请求只会在编排运行到 Intent Agent 且输入非空时发生。

因此，真实调用的最早时点是完成一次单独的外部调用审批之后，而不是配置文件写入之后。需要同时满足：

1. 上述就绪检查仍为 `READY_FOR_EXPLICIT_OPT_IN`，且 Prompt Bundle/模型/目标环境未变；
2. 使用显式研究组合根并传入 `enable_llm_provider=True`；默认 `backend.app.main:app`、Compose backend、Worker 和 G4/G5 默认入口不会自动启用；
3. 本次请求先固定非敏感测试文本、允许发送的字段、预算/超时/重试上限、失败回退和审计字段；不发送完整用户画像、行为历史或数据库凭据；
4. 用户明确批准这一次真实外部请求。批准前只能做本地构造、Prompt 校验和 fake/离线测试。

## 2. Prompt Bundle 契约

主文件为 [`contracts/prompts/rec-prompts-v1.0.0.json`](../contracts/prompts/rec-prompts-v1.0.0.json)，Schema 为 [`contracts/prompts/prompt-bundle.schema.json`](../contracts/prompts/prompt-bundle.schema.json)。加载器 [`backend/app/llm/prompts.py`](../backend/app/llm/prompts.py) 会执行以下门禁：

- 文件必须位于仓库根目录以内，并通过 strict JSON 和 Draft 2020-12 Schema；
- `prompt_id`、能力、Agent、版本必须唯一且可追溯；
- 模板只能使用 `variables` 中声明的 `{{name}}`，变量缺失或多余都会 fail-closed；
- 系统/用户上下文总长度受 Bundle 和任务双重上限约束；
- Prompt Bundle 不授予工具，明确禁止文件写入/删除、数据库管理、自由 SQL/Cypher、Shell 和凭据访问；
- 返回内容先按允许字段和任务输出 Schema 校验，之后才进入 LLMResult/AgentResult。

当前四个任务如下：

| prompt_id | Agent | 能力 | 输出边界 | 故障策略 |
|---|---|---|---|---|
| `intent.classify` | IntentUnderstandingAgent | 意图分类 | 仅三种推荐意图 | 规则意图 |
| `feedback.parse` | FeedbackLearningAgent | 反馈原因 | 五种原因代码，未知为 `OTHER` | `OTHER` |
| `explanation.render` | ExplanationAgent | 证据解释改写 | 只能使用因素和引用白名单 | 模板解释 |
| `group_summary.render` | ExplanationAgent | 主题组摘要 | 仅根据已验证主题名称 | 模板摘要 |

版本信息同时出现在 `LLMResult.prompt_version`、`prompt_id` 和模板 SHA-256 中。审计元数据不保存渲染后的用户输入。

## 3. DeepSeek 调用和降级边界

DeepSeek 使用 HTTPS OpenAI-compatible `/chat/completions` 端点，固定 `temperature=0`。每个能力最多两次尝试：一次正常请求加一次结构/临时网络故障重试；4xx 鉴权或配置错误不会无限重试。超时、不可用、无效 JSON、未知字段和证据引用越权均会进入 Agent 的规则/模板降级。

当前已接入编排的 LLM Agent 是 `LLMIntentUnderstandingAgent`：

1. 空输入直接走规则路径，不调用 provider。
2. 模型只返回意图枚举；主题词、资源类型和资源 ID 不由模型生成。
3. Provider 异常、超时或非法枚举返回规则意图，结果标记 `fallback_used=true` 和 `LLM_INTENT_FALLBACK`。
4. Explanation/Feedback 的 Prompt 已冻结，但仍由既有模板/规则链路负责最终业务接线，避免在 EvidenceValidator 和反馈事务边界完成前扩大外部调用面。

## 4. 本地验证

只读验证 Prompt Bundle（不连接数据库、不写文件）：

```bash
PYTHONPATH=. .venv-g1-final-py311/bin/python -m scripts.verify_prompt_bundle
```

定向测试：

```bash
PYTHONPATH=. .venv-g1-final-py311/bin/python -m unittest \
  tests.g1.backend.test_prompt_bundle \
  tests.g1.backend.test_deepseek_llm \
  tests.g4.test_llm_intent_agent
```

验证本机 Compose 配置（只检查结构，不显示密钥）：

```bash
PYTHONPATH=. .venv-g1-final-py311/bin/python scripts/validate_runtime_env.py \
  --mode compose --env-file .env.compose
```

验证失败时不得修改旧 artifact 或旧 Prompt Bundle；应新建版本文件和新的验证记录。任何真实 DeepSeek 调用都必须先记录数据脱敏、学校/论文伦理要求、费用上限、超时、回退和审计方案，再由用户明确授权。

获批后的首个真实调用只允许使用固定非敏感 fixture，并且必须显式提供确认字符串；该命令只调用 `intent.classify`，不连接任何数据库：

```bash
make PYTHON=.venv-g1-final-py311/bin/python \
  LLM_REAL_CALL_ENV_FILE=.env.host \
  LLM_FIXTURE_CALL_RUN_ID=llm-fixture-call-<unique-id> \
  LLM_FIXTURE_CALL_CONFIRM=YES_REAL_EXTERNAL_LLM \
  execute-llm-fixture-call
```

命令不会保存原始响应或密钥，只保存校验后的意图枚举、Prompt/请求审计字段、延迟和安全计数；运行前后不执行 MySQL/Neo4j/Chroma 操作、不 claim Outbox。
