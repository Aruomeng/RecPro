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

当前本机运行配置已由用户提供并写入被 Git 忽略的 `.env.host` 和 `.env.compose`，两个文件权限均为 `0600`。配置使用 `deepseek`、`deepseek-v4-flash`、HTTPS `https://api.deepseek.com`、20 秒超时、512 个最大输出 token，并绑定 `prompt-v1` 与固定 Prompt Bundle SHA-256。密钥值不会在文档、命令输出或提交中显示。就绪预检阶段未发起网络请求；首次获批的固定 fixture 请求结果见下文。

当前就绪证据：`artifacts/verification/llm/llm-real-call-readiness-20260812-001/real-call-readiness.json`=`READY_FOR_EXPLICIT_OPT_IN`。该检查只读取 `.env.host`、构造 DeepSeek provider 并验证 Prompt Bundle；`network_requests=0`、`external_llm_requests=0`、数据库读写=0。它证明“可以进入一次明确授权的真实调用”，不证明已经调用，也不会改变默认 Mock/关闭状态。

要让 G4 HTTP 研究组合根使用真实 Intent 与证据解释能力，必须分别启用两个独立能力开关：

```dotenv
RECPRO_APP_ENV=demo
RECPRO_G4_HTTP_ENABLED=true
RECPRO_G4_LLM_INTENT_ENABLED=true
RECPRO_G4_LLM_EXPLANATION_ENABLED=true
RECPRO_LLM_PROVIDER=deepseek
```

入口只把 provider 注入明确启用的 `IntentUnderstandingAgent` 和/或 `ExplanationAgent`。Intent 在输入非空时调用一次；Explanation 仅消费排序项已有的证据引用，逐项执行引用白名单校验，失败立即回退模板。默认 `backend.app.main:app` 与 Worker 不读取这些能力开关来挂载业务路径。

因此，真实调用的最早时点是完成一次单独的外部调用审批之后，而不是配置文件写入之后。需要同时满足：

1. 上述就绪检查仍为 `READY_FOR_EXPLICIT_OPT_IN`，且 Prompt Bundle/模型/目标环境未变；
2. 使用显式 G4 入口并同时满足 demo、G4 HTTP、G4 LLM Intent 与 DeepSeek 四重配置；默认 `backend.app.main:app`、Compose backend 和 Worker不会自动启用；
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

当前已接入编排的 LLM Agent 是 `LLMIntentUnderstandingAgent` 与 `LLMExplanationAgent`：

1. 空输入直接走规则路径，不调用 provider。
2. 模型只返回意图枚举；主题词、资源类型和资源 ID 不由模型生成。
3. Provider 异常、超时或非法枚举返回规则意图，结果标记 `fallback_used=true` 和 `LLM_INTENT_FALLBACK`。
4. Explanation 只允许使用输入 Evidence Bundle 中的引用，越权、遗漏引用、空输出或超长输出均回退模板。
5. Feedback 的 Prompt 已冻结，但结构化反馈接口当前直接接收原因枚举，不需要把确定性事务改造成 LLM 调用；自由文本反馈解析仍未接入。

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

## 6. 首次真实调用结果

用户明确批准后，已按上述命令执行一次固定非敏感 `intent.classify` fixture。证据为 `artifacts/verification/llm/llm-fixture-call-20260812-001/real-call.json`：状态 `PASS`，`attempts=1`，延迟约 `1808ms`，返回意图 `BOOK_RECOMMENDATION`。安全计数为 `external_llm_requests=1`、`network_requests=1`，数据库/Neo4j/Chroma 读写、Outbox claim、删除和覆盖均为 `0`。该调用尚未接入默认 HTTP/Worker，也没有将 Explanation/Feedback 业务路径切换到 DeepSeek。

## 7. G4 选择性真实链路边界

为证明 provider 真正进入 G4 编排，同时控制外部请求数量，组合根新增 `llm_intent_provider` 与 `llm_explanation_provider` 两个 capability-specific 参数。`llm_provider` 旧参数仍表示同时启用两个 Agent；G4 只读探针只注入 Intent provider，Explanation 保持证据模板，因此一次编排最多触发一次 `intent.classify`。

离线 fake provider 回放已经验证：7 个 Agent、MySQL/Graph/Vector 三通道、候选投影和 MySQL/Chroma 计数不变断言均可通过。用户批准的真实探针命令为：

```bash
make PYTHON=.venv-g1-final-py311/bin/python \
  G4_REAL_LLM_READONLY_RUN_ID=g4-real-llm-readonly-<unique-id> \
  G4_REAL_LLM_READONLY_CONFIRM=YES_REAL_EXTERNAL_LLM \
  verify-g4-real-llm-readonly
```

`g4-real-llm-readonly-20260812-002` 已形成 PASS artifact：DeepSeek `deepseek-v4-flash` 实际处理一次 `intent.classify`，`attempts=1`、无 fallback，七 Agent 编排完成并返回 8 条三通道候选；MySQL/Neo4j/Chroma 写入、Outbox、删除和覆盖均为 0。G4 HTTP 入口支持 Intent 与 Explanation 独立注入；本机配置已准备同时启用，但 Explanation 的真实外部调用仍需新的只读/追加计划限定最大调用数并形成 PASS 证据。

## 8. 真实 HTTP 持久化审批边界

`build-g4-recommendation-projection-plan` 支持 `G4_PROJECTION_ENABLE_DEEPSEEK_INTENT=true`。生成器只读取 PASS 基线和本机配置，将 provider、模型、HTTPS origin、Prompt Bundle、超时、token 上限、最大两次尝试和 Intent-only 范围哈希到计划中；API key 不进入计划或日志，生成计划时不调用模型、不写数据库。

获批后的执行器使用实际 FastAPI `/api/v1/recommendation-tasks` 路由：第一次 POST 必须返回 201 并在一个事务中追加 G4/G3 事实；相同 request_id 的第二次 POST 必须返回同一 task、`Idempotency-Replayed=true`、数据库零增量且不再次调用 DeepSeek；最后 GET 回读持久化任务。执行器还会回读 `IntentUnderstandingAgent` 结果，要求 `intent-llm-prompt-v1`、provider=`deepseek`、无 fallback、prompt=`intent.classify`、尝试次数在 1–2 以内。任何提交、基线、计数、模型策略或请求漂移都会在执行前阻断。

## 9. 真实 HTTP 首次执行结果与下一能力

获批计划 `28d050ce-a922-5480-b326-38fdf8984fdf` 已通过真实 HTTP 执行和独立对账：首次 POST=`201`，DeepSeek Intent 调用 1 次、无 fallback，任务 `COMPLETED` 并返回 8 项；相同请求重放=`200`、零新增且未再次调用模型。MySQL 精确追加 56 行，Neo4j/Chroma 零写入，删除为 0。证据位于 `artifacts/verification/g4/g4-deepseek-http-apply-20260812-001/` 与 `g4-deepseek-http-reconcile-20260812-001/`。

下一 LLM Gate 是 `explanation.render`：代码和独立配置开关已接好，但在批准最大外部调用次数、输入 Evidence Bundle 和回退策略的新计划之前，不把它宣称为真实运行 PASS。画像、语义探测、召回、策略和排序 Agent 使用真实数据库/图/向量/确定性算法完成各自职责，不属于 Mock LLM，也不应为了“全 LLM”而把事实计算交给生成模型。
