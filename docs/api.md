# LibraMAS HTTP API 契约草案

> API 版本：v1
> 文档版本：1.0.0
> 状态：G0 冻结草案
> 日期：2026-08-02
> 基础路径：`/api/v1`
> 数据字典：`docs/data_dictionary.md`

## 1. 契约目标

本草案定义 G1—G7 实现和测试所依赖的 HTTP 边界。API 只调用应用用例，不直接暴露 ORM、数据库会话、Chroma 集合或 Neo4j 查询。

第一版 API 必须满足：

1. 推荐、澄清、查询、解释、曝光、反馈和画像更新形成闭环。
2. 所有写请求可幂等重放。
3. 普通在线请求不能伪造历史评价时点。
4. 降级、警告、配置版本和 Trace 对研究管理员可追溯。
5. 不提供文件、数据库记录、索引版本、实验运行或日志的物理删除接口。

## 2. 通用约定

### 2.1 内容与编码

```text
请求/响应：application/json; charset=utf-8
字段命名：snake_case
时间格式：UTC ISO 8601，保留毫秒
UUID：小写标准形式
数值分数：JSON number，范围遵循数据字典
```

未知请求字段默认返回 `422 UNKNOWN_FIELD`，防止客户端拼写错误被静默忽略。向后兼容的响应新增字段允许客户端忽略。

### 2.2 身份与角色

| 环境 | 身份来源 | 规则 |
|---|---|---|
| 正式/论文用户实验 | `Authorization: Bearer <token>` | `user_id` 从认证上下文读取；请求体不得冒充其他用户 |
| 本地演示 | `X-Demo-User-Id: <positive-int>` | 仅 `APP_ENV=demo` 且显式启用时接受 |
| 自动测试 | 测试身份注入 | 仅 `APP_ENV=test` |

`X-Demo-User-Id` 只适用于下列 user/owner 范围端点：推荐任务创建、澄清与查询，推荐记录与解释查询，曝光、反馈、行为，以及画像查询与刷新。健康检查不需要用户身份；`/debug/**` 始终要求 `research_admin` 的 Bearer 身份。Demo Header 不能授予或模拟 `research_admin`，正式环境收到该 Header 也不能用它替代认证。

角色：

| 角色 | 能力 |
|---|---|
| `user` | 创建和查看自己的推荐、上报自己的行为/曝光/反馈、查看自己的画像 |
| `research_admin` | 用户能力；指定历史时点；查看评分、Trace 和策略调试数据；执行受控画像重算 |
| `service_worker` | 只调用内部 Worker 端口，不通过公开浏览器 API |

调试端点只有在 `ENABLE_DEBUG_API=true` 且调用者为 `research_admin` 时注册。

### 2.3 请求追踪

客户端可以发送：

```http
X-Request-Id: 846b1454-54a0-4e2b-a744-c10e840a1c73
```

每个 operation 的每个响应（包括非 2xx）始终返回：

```http
X-Request-Id: 846b1454-54a0-4e2b-a744-c10e840a1c73
X-Trace-Id: 80e67683-4544-4ae7-b347-f8ffefc06054
```

非法或重复用于不同载荷的 Request ID 返回 `409 REQUEST_ID_CONFLICT`。

所有 POST 是幂等写接口，每个成功或错误响应还声明：

```http
Idempotency-Replayed: false
```

只有从第一次提交的已保存结果重放时该值为 `true`。`429` 另外返回 `Retry-After` 秒数。

### 2.4 幂等

以下写端点必须携带 `Idempotency-Key`：

- 创建推荐任务；
- 提交澄清；
- 批量曝光；
- 提交反馈；
- 提交行为；
- 请求画像刷新。

规则：

1. Key 长度 8—255，只在“身份 + 路由 + Key”范围内唯一。
2. 首次成功后保存请求体 SHA-256 和原响应引用。
3. 同 Key、同规范化载荷返回原业务结果，并设置 `Idempotency-Replayed: true`。
4. 同 Key、不同载荷返回 `409 IDEMPOTENCY_KEY_REUSED`。
5. 网络超时后的重试不得产生第二条事实或第二个 Outbox。
6. 任务请求体中的 `request_id` 必须与 `Idempotency-Key` 表示同一 UUID；不一致返回 `422 REQUEST_ID_MISMATCH`。

### 2.5 分页

当前只对未来的历史列表查询预留游标协议：

```json
{
  "items": [],
  "next_cursor": null
}
```

游标是服务器签名的不透明字符串。第一版单任务、单记录和单画像查询不分页；推荐最终 `limit` 最大值由配置 Bundle 限制。

### 2.6 错误响应

所有非 2xx 响应使用同一结构：

```json
{
  "error": {
    "code": "STALE_CONTEXT_VERSION",
    "message": "提交的上下文版本已经过期。",
    "details": {
      "submitted_context_version": 1,
      "current_context_version": 2
    },
    "retryable": false
  },
  "request_id": "846b1454-54a0-4e2b-a744-c10e840a1c73",
  "trace_id": "80e67683-4544-4ae7-b347-f8ffefc06054"
}
```

`message` 可本地化，客户端逻辑只能依赖 `code`。生产错误不得包含 SQL、Cypher、文件绝对路径、凭证或完整堆栈。

OpenAPI 中所有非 2xx 状态均引用同一个 `ErrorResponse`；`503 /health/ready` 也使用该错误结构，不用就绪成功模型冒充错误体。

### 2.7 通用状态码

| HTTP | 语义 |
|---:|---|
| 200 | 查询成功、幂等重放或同步命令成功 |
| 201 | 新事实或新任务已创建 |
| 202 | 事实已安全提交，派生更新异步处理中 |
| 400 | JSON/协议格式错误 |
| 401 | 未认证 |
| 403 | 权限不足 |
| 404 | 资源不存在或不属于当前用户 |
| 409 | 幂等、上下文版本或状态冲突 |
| 422 | 领域字段和组合校验失败 |
| 429 | 速率限制或并发任务限制 |
| 503 | MySQL 核心事实层不可用或运行权限守卫失败 |
| 504 | 整个请求超过总截止时间且无法形成安全降级结果 |

状态码覆盖按操作类型冻结：

| 操作类型 | 必须声明的非 2xx 状态 |
|---|---|
| `GET /health/live` | 无业务错误响应 |
| `GET /health/ready` | `503` |
| 已认证 GET | `401`、`403`、`404`、`422`、`429`、`503`、`504` |
| 所有 POST | `400`、`401`、`403`、`404`、`409`、`422`、`429`、`503`、`504` |

所有 POST 至少声明 `409`，用于幂等键、状态或上下文冲突。具体 `error.code` 再区分冲突原因。

### 2.8 版本 Bundle

凡响应包含 `versions`，下列五个字段必须存在且为非空字符串：

```text
config_bundle
policy
ranking
behavior_formula
dataset
```

`embedding`、`graph`、`prompt` 是可选能力版本：能力未参与时可以省略，但不得省略上述五个确定性复现版本。

## 3. Endpoint 总览

| 方法 | 路径 | 用途 | 角色 | 幂等键 |
|---|---|---|---|---|
| GET | `/health/live` | 进程存活 | 公开/受网络限制 | 否 |
| GET | `/health/ready` | 服务就绪与组件状态 | 公开/受网络限制 | 否 |
| POST | `/recommendation-tasks` | 创建并执行推荐任务 | user | 是 |
| POST | `/recommendation-tasks/{task_id}/clarifications` | 继续原任务 | user | 是 |
| GET | `/recommendation-tasks/{task_id}` | 查询任务状态 | owner/admin | 否 |
| GET | `/recommendation-records/{record_id}` | 查询冻结推荐结果 | owner/admin | 否 |
| GET | `/recommendation-items/{item_id}/explanation` | 查询持久化解释 | owner/admin | 否 |
| POST | `/recommendation-impressions/batch` | 上报展示和可见度 | user | 是 |
| POST | `/recommendation-items/{item_id}/feedback` | 提交推荐反馈 | user | 是 |
| POST | `/behavior-events` | 提交非反馈行为 | user | 是 |
| GET | `/profiles/{user_id}` | 查询画像摘要 | owner/admin | 否 |
| POST | `/profiles/{user_id}/refresh` | 请求新画像版本 | owner/admin | 是 |
| GET | `/debug/tasks/{task_id}/context` | 查询上下文快照 | research_admin | 否 |
| GET | `/debug/tasks/{task_id}/trace` | 查询 Agent Trace | research_admin | 否 |
| GET | `/debug/tasks/{task_id}/policy-decision` | 查询策略决策 | research_admin | 否 |

第一版不注册 `DELETE` 路由。停用、撤回和过期均通过明确的追加事件或状态转换用例处理；任何确需物理删除的情况必须离开应用 API，进入项目规定的删除前详细汇报和单次审批流程。

## 4. 健康检查

### 4.1 `GET /health/live`

只检查进程事件循环，不连接外部服务。

成功 `200`：

```json
{
  "status": "UP",
  "service": "recpro-backend",
  "version": "0.1.0",
  "time": "2026-08-02T10:30:00.000Z"
}
```

### 4.2 `GET /health/ready`

检查：

- 配置 Bundle 可解析且哈希匹配；
- MySQL 可连接且 Schema 版本兼容；
- 运行账号不具备物理删除、清空、结构移除或授权扩张能力；
- 至少一个召回通道可用；
- Chroma、Neo4j 和 LLM 的状态可观察。

可服务但部分降级时仍返回 `200`：

```json
{
  "status": "DEGRADED",
  "can_recommend": true,
  "components": {
    "mysql": {
      "status": "UP",
      "required": true
    },
    "chroma": {
      "status": "UP",
      "required": false,
      "active_version": "hash-char-ngram-v1"
    },
    "neo4j": {
      "status": "DOWN",
      "required": false,
      "error_code": "KG_CHANNEL_UNAVAILABLE"
    },
    "llm": {
      "status": "MOCK",
      "required": false,
      "provider": "MockLLMProvider"
    }
  },
  "config_bundle_version": "rec-1.0.0",
  "checked_at": "2026-08-02T10:30:00.000Z"
}
```

MySQL 不可用、Schema 不兼容或权限过宽时返回 `503`，`can_recommend=false`。

## 5. 推荐任务

### 5.1 `POST /recommendation-tasks`

创建一个任务，冻结 `evaluation_at`、请求快照和全部版本，然后同步执行到以下终态之一：

- `WAITING_CLARIFICATION`
- `COMPLETED`
- `DEGRADED_COMPLETED`
- `FAILED`

请求：

```json
{
  "request_id": "846b1454-54a0-4e2b-a744-c10e840a1c73",
  "user_id": 1,
  "session_id": "7b727a4a-c4f3-47c7-ae13-3b25535f547a",
  "scene": "SEARCH_AFTER",
  "input_text": "我想系统学习多智能体推荐",
  "requested_resource_types": ["BOOK", "PAPER"],
  "requested_output_type": null,
  "source_resource_id": null,
  "source_item_id": null,
  "as_of_time": null,
  "constraints": {
    "year_from": 2020,
    "year_to": null,
    "language": "zh-CN",
    "difficulty": null,
    "include_waitlist": false
  },
  "limit": 10
}
```

字段规则：

| 字段 | 规则 |
|---|---|
| `request_id` | 必填 UUID，并与 `Idempotency-Key` 一致 |
| `user_id` | demo 必填；正式环境省略或必须与认证用户一致 |
| `session_id` | 必填 UUID |
| `scene` | `TriggerScene` |
| `input_text` | `SEARCH_AFTER` 必填；最大 2000 字符 |
| `requested_resource_types` | 去重后的 `BOOK`/`PAPER`；空或未填表示两类均可 |
| `requested_output_type` | 用户显式选择，优先于文本推断 |
| `source_resource_id` / `source_item_id` | 必须符合场景矩阵 |
| `as_of_time` | 普通请求必须为空；研究管理员可以指定非未来时点 |
| `limit` | 1 至 Bundle 的 `max_final_items`；省略使用默认值 |

场景矩阵：

| 场景 | 必填 | 禁止组合 |
|---|---|---|
| `HOME` | 无 | 两个来源字段均禁止 |
| `SEARCH_AFTER` | `input_text` | 两个来源字段均禁止 |
| `RESOURCE_DETAIL` | `source_resource_id` | `source_item_id` 禁止 |
| `FEEDBACK_REFRESH` | `source_item_id` 且已有反馈事实 | `source_resource_id` 禁止 |
| `EXPLANATION` | `source_item_id` | `source_resource_id` 禁止；只解释既有项 |

组合输出的 Limit 规则：

- 显式 `BOOKLIST` 小于最小条数：`422 LIMIT_TOO_SMALL_FOR_BOOKLIST`。
- 显式 `READING_PATH` 小于最小条数：`422 LIMIT_TOO_SMALL_FOR_READING_PATH`。
- 自动推断组合输出但 Limit 不足：保持 `TOPIC_RESOURCES`，不悄悄增加 Limit。

新任务返回 `201`；幂等重放返回 `200`。

直接完成响应：

```json
{
  "task_id": "e19da71f-f56b-4ef0-841f-ff98cbc79542",
  "record_id": 21,
  "trace_id": "80e67683-4544-4ae7-b347-f8ffefc06054",
  "status": "COMPLETED",
  "context_version": 1,
  "evaluation_at": "2026-08-02T10:30:00.000Z",
  "decision": {
    "output_type": "READING_PATH",
    "delivery_strategy": "DIRECT",
    "explanation_level": "EVIDENCE",
    "adaptation_state": "NORMAL",
    "decision_reason_codes": [
      "EXPLICIT_LEARNING_INTENT",
      "SUFFICIENT_RESOURCE_COVERAGE"
    ],
    "decision_reason": "用户明确表达系统学习意图，资源覆盖满足路径要求。",
    "policy_version": "policy-v1"
  },
  "groups": [
    {
      "group_id": 31,
      "group_type": "READING_STAGE",
      "group_key": "BEGINNER",
      "title": "入门",
      "goal": "建立核心概念",
      "order_no": 1
    }
  ],
  "items": [
    {
      "item_id": 101,
      "resource": {
        "resource_id": 11,
        "resource_type": "BOOK",
        "title": "多智能体系统导论",
        "authors": ["示例作者"],
        "publication_year": 2024,
        "availability_status": "AVAILABLE_BORROW"
      },
      "rank_no": 1,
      "group_id": 31,
      "reason_summary": "与当前学习主题和入门阶段匹配。",
      "evidence_confidence": 0.83
    }
  ],
  "warnings": [],
  "versions": {
    "config_bundle": "rec-1.0.0",
    "policy": "policy-v1",
    "ranking": "ranking-v1",
    "behavior_formula": "behavior-v1",
    "embedding": "hash-char-ngram-v1",
    "graph": "graph-v1",
    "prompt": "prompt-v1",
    "dataset": "demo-v1"
  }
}
```

普通用户响应不返回内部 `final_score` 和工具参数。

需要澄清响应：

```json
{
  "task_id": "e19da71f-f56b-4ef0-841f-ff98cbc79542",
  "trace_id": "80e67683-4544-4ae7-b347-f8ffefc06054",
  "status": "WAITING_CLARIFICATION",
  "context_version": 1,
  "decision": {
    "output_type": "PERSONALIZED_FEED",
    "delivery_strategy": "GUIDED",
    "explanation_level": "LIMITED",
    "adaptation_state": "NORMAL",
    "decision_reason_codes": ["MISSING_REQUIRED_SLOTS"],
    "decision_reason": "当前主题和资源类型不足以形成可靠推荐。",
    "policy_version": "policy-v1"
  },
  "questions": [
    {
      "slot": "resource_types",
      "question": "你更需要图书、论文，还是两者都需要？",
      "options": ["BOOK", "PAPER", "BOOK_AND_PAPER"],
      "required": true
    },
    {
      "slot": "topic",
      "question": "你主要关注哪个主题？",
      "options": ["多智能体", "推荐系统", "知识图谱"],
      "required": true
    }
  ],
  "warnings": []
}
```

### 5.2 `POST /recommendation-tasks/{task_id}/clarifications`

继续同一个任务，不创建不可关联的新任务。

请求：

```json
{
  "context_version": 1,
  "answers": {
    "resource_types": "BOOK_AND_PAPER",
    "output_type": "READING_PATH",
    "topic": "多智能体推荐"
  }
}
```

规则：

1. 任务必须属于当前用户且处于 `WAITING_CLARIFICATION`。
2. `context_version` 必须等于当前版本。
3. 答案只包含本轮已询问槽位；自定义文本长度不超过 500。
4. 成功后创建下一上下文版本，保留原问题和答案事实。
5. 相同幂等键重放返回第一次生成的下一版本。

成功 `200` 返回与任务创建相同的完成或再次澄清结构。过期版本返回 `409 STALE_CONTEXT_VERSION`。

### 5.3 `GET /recommendation-tasks/{task_id}`

返回任务当前状态。查询不触发任务推进、重算或解释再生成。

```json
{
  "task_id": "e19da71f-f56b-4ef0-841f-ff98cbc79542",
  "trace_id": "80e67683-4544-4ae7-b347-f8ffefc06054",
  "status": "DEGRADED_COMPLETED",
  "context_version": 1,
  "record_id": 21,
  "evaluation_at": "2026-08-02T10:30:00.000Z",
  "started_at": "2026-08-02T10:30:00.000Z",
  "finished_at": "2026-08-02T10:30:01.208Z",
  "error_code": null,
  "warnings": ["KG_CHANNEL_UNAVAILABLE"],
  "versions": {
    "config_bundle": "rec-1.0.0",
    "policy": "policy-v1",
    "ranking": "ranking-v1",
    "behavior_formula": "behavior-v1",
    "dataset": "demo-v1"
  }
}
```

### 5.4 `GET /recommendation-records/{record_id}`

返回已经冻结的分组、条目、理由摘要、版本和警告。它不得用当前画像、当前馆藏状态或新模型改写历史结果。

Query：

| 参数 | 默认 | 规则 |
|---|---:|---|
| `include_unavailable_now` | false | true 时仅增加“当前已不可用”标记，不改变历史入选事实 |

成功 `200` 使用 5.1 的完成响应中 `record_id`、`decision`、`groups`、`items`、`warnings` 和 `versions` 结构。

## 6. 推荐解释

### 6.1 `GET /recommendation-items/{item_id}/explanation`

Query：

| 参数 | 默认 | 权限/语义 |
|---|---:|---|
| `version` | 1 | 读取指定持久化解释版本 |
| `include_scores` | false | 仅 `research_admin` 可设 true |

普通响应 `200`：

```json
{
  "item_id": 101,
  "explanation_version": 1,
  "explanation_level": "EVIDENCE",
  "text": "该资源与您近期关注的多智能体主题一致，并适合作为入门阶段材料。",
  "evidence": [
    {
      "type": "USER_INTEREST_TAG",
      "ref": "interest:1:tag:42:profile-v7",
      "summary": "近期关注：多智能体"
    },
    {
      "type": "RESOURCE_TAG",
      "ref": "resource:11:tag:42",
      "summary": "资源主题：多智能体"
    },
    {
      "type": "RECALL_CHANNEL",
      "ref": "task:e19da71f:channel:KEYWORD",
      "summary": "关键词通道命中"
    }
  ],
  "provider": "TEMPLATE",
  "validator_status": "PASSED",
  "created_at": "2026-08-02T10:30:01.100Z"
}
```

研究管理员请求 `include_scores=true` 时附加：

```json
{
  "scores": {
    "final_score": 0.812345,
    "profile_score": 0.88,
    "semantic_score": null,
    "kg_score": 0.72,
    "intent_score": 0.90,
    "recall_fusion_score": 0.61,
    "exposure_penalty": 0.00,
    "negative_penalty": 0.00
  }
}
```

无权查看评分返回 `403 SCORE_VIEW_FORBIDDEN`，不静默忽略参数。解释查询只读持久化版本；第一版不向普通 API 暴露重新生成命令。

## 7. 曝光

### 7.1 `POST /recommendation-impressions/batch`

请求最多 100 条：

```json
{
  "impressions": [
    {
      "impression_uuid": "e141c1ef-b331-452c-b3ad-ec5d118afda2",
      "recommendation_item_id": 101,
      "position": 1,
      "rendered_at": "2026-08-02T10:30:02.000Z",
      "visible_started_at": "2026-08-02T10:30:03.000Z",
      "visible_ms": 2500,
      "max_visible_ratio": 0.92
    }
  ]
}
```

校验：

- 推荐项必须属于当前用户；
- `position >= 1`、`visible_ms >= 0`、比例在 `[0,1]`；
- `visible_ms > 0` 时 `visible_started_at` 必填；
- 客户端不能提交 `is_valid_exposure`；
- 时间明显早于推荐结果或超出允许时钟偏差时逐项拒绝。

同一事务为每个合法新 UUID 写入曝光事实和零分行为事实。响应 `200`：

```json
{
  "accepted_count": 1,
  "replayed_count": 0,
  "rejected_count": 0,
  "results": [
    {
      "impression_uuid": "e141c1ef-b331-452c-b3ad-ec5d118afda2",
      "status": "ACCEPTED",
      "is_valid_exposure": true,
      "error_code": null
    }
  ]
}
```

批次允许逐项结果；只有整个请求 JSON 非法、身份无效或 MySQL 事务失败时整体失败。部分非法项不能阻止其他合法项，但单项的两条事实必须原子提交。

## 8. 反馈

### 8.1 `POST /recommendation-items/{item_id}/feedback`

请求：

```json
{
  "feedback_uuid": "695e1702-53c2-4b65-a23f-a8d74c1cf4e0",
  "impression_uuid": "e141c1ef-b331-452c-b3ad-ec5d118afda2",
  "feedback_type": "NOT_INTERESTED",
  "reason_code": "TOPIC_NOT_INTERESTED",
  "rating": null,
  "content": null
}
```

字段矩阵：

| `feedback_type` | 必填 | 主要结果 |
|---|---|---|
| `FAVORITE` | `feedback_uuid`；曝光可选 | 收藏状态、正向行为、画像 Outbox |
| `BORROW` | `feedback_uuid`；资源必须为可借 BOOK | 借阅状态、强正向行为、画像 Outbox |
| `REJECT` | `feedback_uuid`、`impression_uuid` | 资源级隐藏；原因可进一步调整 |
| `NOT_INTERESTED` | `feedback_uuid`、`impression_uuid`、`reason_code` | 按原因形成资源状态；仅主题原因泛化 |
| `RATE` | `feedback_uuid`、`impression_uuid`、`rating` | 1—5 映射高/中/低评分行为 |

额外规则：

- 曝光必须属于同一用户和同一推荐项；
- `TOPIC_NOT_INTERESTED` 只用于 `REJECT` 或 `NOT_INTERESTED`；
- `TOO_BASIC`/`TOO_ADVANCED` 要求资源有难度；
- 低评分不自动泛化为主题负偏好；
- 一个 `feedback_uuid` 只映射一次反馈事实、行为事实和 Outbox。

事实和 Outbox 提交成功但画像尚未应用时返回 `202`：

```json
{
  "feedback_uuid": "695e1702-53c2-4b65-a23f-a8d74c1cf4e0",
  "feedback_id": 901,
  "status": "ACCEPTED",
  "behavior_event_id": 1201,
  "resource_state": {
    "state_type": "HIDDEN",
    "suppress_until": "2026-09-01T10:31:00.000Z"
  },
  "profile_update_status": "PENDING",
  "profile_version_before": 7,
  "profile_version_after": null
}
```

若同一事务内已应用确定性投影，可返回 `201` 且状态为 `APPLIED`；客户端必须同时支持两种状态，不通过 HTTP 成功码猜测画像版本。

## 9. 通用行为

### 9.1 `POST /behavior-events`

点击示例：

```json
{
  "event_uuid": "df2752fa-9799-4434-99d4-196f425087d7",
  "session_id": "7b727a4a-c4f3-47c7-ae13-3b25535f547a",
  "task_id": "e19da71f-f56b-4ef0-841f-ff98cbc79542",
  "event_type": "CLICK_RECOMMENDATION",
  "resource_id": 11,
  "recommendation_item_id": 101,
  "impression_uuid": "e141c1ef-b331-452c-b3ad-ec5d118afda2",
  "query_text": null,
  "dwell_ms": null,
  "occurred_at": "2026-08-02T10:30:05.000Z"
}
```

客户端允许直接上报的类型：

```text
SEARCH
VIEW_RESOURCE
VIEW_EXPLANATION
CLICK_RECOMMENDATION
ACCESS_PAPER_FULLTEXT
```

收藏、借阅、评分、拒绝和不感兴趣必须走反馈端点；曝光必须走批量曝光端点。派生事件直接提交返回 `422 DERIVED_EVENT_NOT_ALLOWED`。

`CLICK_RECOMMENDATION` 和 `VIEW_EXPLANATION` 必须关联同一用户的推荐项与曝光。找不到合法曝光的点击可以在受控数据导入场景以 `ORPHAN_CLICK_WARNING` 保留，但公开在线 API 默认返回 `422 INVALID_IMPRESSION_REFERENCE`。

成功新建事实且画像更新待处理返回 `202`：

```json
{
  "event_uuid": "df2752fa-9799-4434-99d4-196f425087d7",
  "event_id": 1202,
  "status": "ACCEPTED",
  "profile_update_status": "PENDING"
}
```

零分审计事件不创建无意义的画像 Delta，但仍返回 `profile_update_status=NOT_REQUIRED`。

## 10. 画像

### 10.1 `GET /profiles/{user_id}`

普通用户只能查看自己的当前画像摘要。Query：

| 参数 | 默认 | 权限 |
|---|---:|---|
| `as_of_time` | 空 | 只有 `research_admin` 可指定；指定后使用 `REPLAY_AS_OF` |
| `include_evidence` | false | owner 可查看摘要证据，admin 可查看 ID 级证据 |

响应 `200`：

```json
{
  "user_id": 1,
  "snapshot_mode": "MATERIALIZED_CURRENT",
  "evaluation_at": "2026-08-02T10:32:00.000Z",
  "profile_version": 7,
  "profile_confidence": 0.73,
  "topic_focus_strength": 0.68,
  "recent_focus": {
    "tag_id": 42,
    "name": "多智能体系统"
  },
  "reading_stage": "INTERMEDIATE",
  "reading_stage_confidence": 0.60,
  "interests": [
    {
      "tag_id": 42,
      "name": "多智能体系统",
      "positive_weight": 0.81
    }
  ],
  "negative_preferences": [],
  "personalization_enabled": true,
  "formula_version": "behavior-v1",
  "max_source_event_at": "2026-08-01T12:00:00.000Z"
}
```

禁用个性化时返回空长期兴趣，并明确 `personalization_enabled=false`，不以空数组伪装计算失败。

### 10.2 `POST /profiles/{user_id}/refresh`

请求新的画像版本或历史重放 Artifact，不重置、不覆盖原始事件。

```json
{
  "mode": "INCREMENTAL_RECONCILE",
  "as_of_time": null,
  "formula_version": "behavior-v1",
  "reason": "USER_REQUESTED_REFRESH"
}
```

允许模式：

| 模式 | 权限 | 结果 |
|---|---|---|
| `INCREMENTAL_RECONCILE` | owner/admin | 检查尚未应用的事实并创建新投影版本 |
| `FULL_REPLAY_CURRENT` | research_admin | 从全部合格历史事实产生新的当前版本 |
| `REPLAY_AS_OF` | research_admin | 生成指定时点 Artifact，不写当前画像投影 |

返回 `202`：

```json
{
  "refresh_id": "ba4c5c81-e669-420d-b9a5-9119b762c8d8",
  "status": "PENDING",
  "mode": "INCREMENTAL_RECONCILE",
  "profile_version_before": 7,
  "requested_at": "2026-08-02T10:35:00.000Z"
}
```

同名刷新不覆盖任何画像或运行记录；Worker 成功后产生更高版本和 `profile_change_log`。

## 11. 调试 API

### 11.1 `GET /debug/tasks/{task_id}/context`

返回任务的 `PRE_PLAN`、`POST_RANK` 和 `POST_RUN` 上下文快照、公式分量、配置哈希及 Artifact 引用。敏感输入默认只返回哈希。

### 11.2 `GET /debug/tasks/{task_id}/trace`

响应：

```json
{
  "task_id": "e19da71f-f56b-4ef0-841f-ff98cbc79542",
  "schema_version": "debug-trace-v1",
  "payload": {
    "trace_id": "80e67683-4544-4ae7-b347-f8ffefc06054",
    "complete": true,
    "steps": [
      {
        "step_no": 1,
        "agent_name": "IntentUnderstandingAgent",
        "agent_version": "intent-v1",
        "status": "SUCCESS",
        "confidence": 0.94,
        "fallback_used": false,
        "duration_ms": 18,
        "warnings": [],
        "error_code": null,
        "input_digest": "sha256:...",
        "output_ref": "artifact:..."
      }
    ]
  }
}
```

不得返回访问凭证、完整工具请求或未脱敏的用户文本。

### 11.3 `GET /debug/tasks/{task_id}/policy-decision`

返回按 `decision_no` 排序的全部策略决策、对应上下文版本、召回计划版本和受控理由码。查询不重新运行 Policy。

## 12. 领域错误码

### 12.1 请求与权限

| Code | HTTP | 语义 |
|---|---:|---|
| `INVALID_JSON` | 400 | JSON 无法解析 |
| `UNKNOWN_FIELD` | 422 | 请求包含未知字段 |
| `AUTHENTICATION_REQUIRED` | 401 | 缺少有效身份 |
| `RESOURCE_ACCESS_FORBIDDEN` | 403 | 无权访问对象 |
| `SCORE_VIEW_FORBIDDEN` | 403 | 无权查看内部评分 |
| `DEBUG_API_DISABLED` | 404 | 调试路由未启用 |
| `NOT_FOUND` | 404 | 对象不存在或对当前用户不可见 |

### 12.2 幂等和状态

| Code | HTTP | 语义 |
|---|---:|---|
| `REQUEST_ID_MISMATCH` | 422 | Header 与请求体 Request ID 不一致 |
| `REQUEST_ID_CONFLICT` | 409 | Request ID 被不同请求使用 |
| `IDEMPOTENCY_KEY_REUSED` | 409 | 同 Key 载荷不一致 |
| `STALE_CONTEXT_VERSION` | 409 | 澄清上下文过期 |
| `TASK_STATE_CONFLICT` | 409 | 当前任务状态不接受该命令 |

### 12.3 推荐校验

| Code | HTTP | 语义 |
|---|---:|---|
| `INVALID_SCENE_SOURCE` | 422 | 场景与来源字段不匹配 |
| `AS_OF_TIME_FORBIDDEN` | 403 | 普通用户指定历史时点 |
| `FUTURE_EVALUATION_TIME` | 422 | 历史时点位于未来 |
| `LIMIT_OUT_OF_RANGE` | 422 | Limit 超出 Bundle 范围 |
| `LIMIT_TOO_SMALL_FOR_BOOKLIST` | 422 | 显式书单条数不足 |
| `LIMIT_TOO_SMALL_FOR_READING_PATH` | 422 | 显式路径条数不足 |
| `MISSING_EXPLANATION_TARGET` | 422 | 解释请求无来源推荐项 |

### 12.4 行为与反馈

| Code | HTTP | 语义 |
|---|---:|---|
| `INVALID_IMPRESSION_REFERENCE` | 422 | 曝光不匹配用户和推荐项 |
| `DERIVED_EVENT_NOT_ALLOWED` | 422 | 客户端直接提交派生事件 |
| `INVALID_FEEDBACK_REASON` | 422 | 反馈类型与原因不匹配 |
| `RATING_OUT_OF_RANGE` | 422 | 评分不在 1—5 |
| `RESOURCE_TYPE_MISMATCH` | 422 | 对非图书提交借阅等行为 |

### 12.5 运行故障

| Code | HTTP | 语义 |
|---|---:|---|
| `CORE_STORAGE_UNAVAILABLE` | 503 | MySQL 不可用 |
| `UNSAFE_DATABASE_PRIVILEGES` | 503 | 运行账号权限超出白名单 |
| `CONFIG_BUNDLE_INVALID` | 503 | 配置无法通过 Schema/哈希校验 |
| `REQUEST_DEADLINE_EXCEEDED` | 504 | 无法在截止时间形成结果 |

以下通常作为成功响应中的 Warning，不直接使请求失败：

```text
VECTOR_CHANNEL_UNAVAILABLE
KG_CHANNEL_UNAVAILABLE
LLM_FALLBACK_USED
PARTIAL_METADATA_COVERAGE
REPLAN_EXHAUSTED
INSUFFICIENT_RESOURCE_COVERAGE
```

## 13. 限流与负载边界

第一版默认值由配置 Bundle 管理，建议起点：

| 对象 | 限制 |
|---|---:|
| 单用户并发推荐任务 | 2 |
| 推荐最终条目 | 1—20 |
| 单曝光批次 | 100 |
| 输入文本 | 2000 字符 |
| 反馈文本 | 1000 字符 |
| 澄清单槽文本 | 500 字符 |
| Agent Artifact JSON | 由后端配置，超限转对象存储端口或拒绝 |

`429` 响应包含 `Retry-After`。限流失败不得先写一半业务事实。

## 14. CORS 与浏览器安全

- 非开发环境使用显式 Origin 白名单，不允许带凭证的通配 Origin。
- 仅允许实际使用的方法和 Header。
- 调试 API 不对公共前端 Origin 开放。
- 输出用户文本时由前端按文本渲染，不拼接为 HTML。
- 访问链接只能使用批准的 `https` Scheme；拒绝 `javascript:`、`data:` 等危险 Scheme。
- 错误和 Trace 中的输入文本默认哈希或截断脱敏。

## 15. 契约测试清单

```text
API-01 所有示例 JSON 可解析并通过 Schema
API-02 所有未知字段被拒绝
API-03 所有写端点验证 Idempotency-Key
API-04 同 Key 同载荷返回相同业务对象
API-05 同 Key 不同载荷返回 409
API-06 正式环境从认证上下文读取 user_id
API-07 普通用户指定 as_of_time 返回 403
API-08 场景与来源字段组合严格校验
API-09 过期 clarification 返回 409
API-10 解释评分只对 research_admin 可见
API-11 曝光有效性只由后端计算
API-12 反馈曝光同时匹配用户和推荐项
API-13 行为派生事件不能从通用端点提交
API-14 Chroma/Neo4j/LLM 单点故障能返回带 Warning 的结果
API-15 MySQL 不可用时返回 503 且没有推荐记录
API-16 路由表不包含物理删除端点
API-17 查询历史记录不触发重算或改写
API-18 生产错误响应不泄漏内部堆栈和凭证
API-19 每个operation的每个响应声明X-Request-Id和X-Trace-Id
API-20 所有POST响应声明Idempotency-Replayed且至少声明409
API-21 所有非2xx响应引用统一ErrorResponse
API-22 X-Demo-User-Id只出现在user/owner端点且不能授予research_admin
API-23 VersionBundle必填config_bundle、policy、ranking、behavior_formula和dataset
API-24 operationId保持15个且符合<domain>_<action>_v1
```

## 16. OpenAPI 生成规则

G1 实现时由 FastAPI Pydantic 模型生成 `/openapi.json`，但生成结果必须通过以下门禁：

1. 15 个公开路由都带唯一 `operationId`，格式为 `<domain>_<action>_v1`。
2. 每个 operation 的每个响应声明 `X-Request-Id` 和 `X-Trace-Id`。
3. 每个 POST 声明 `Idempotency-Key`，全部响应声明 `Idempotency-Replayed`，并至少提供 `409`。
4. 每个非 2xx 响应引用统一 `ErrorResponse`。
5. `X-Demo-User-Id` 只用于已列明的 user/owner 路由；Debug 不接受该身份。
6. `VersionBundle` 的五个确定性复现字段保持必填。
7. 枚举必须引用数据字典中的单一 Schema，不能复制自由字符串。
8. `additionalProperties=false` 对应请求模型的未知字段拒绝策略。
9. Debug 路由在关闭配置时不出现在 OpenAPI。
10. 生成的 OpenAPI JSON 作为构建产物校验，不手工覆盖历史版本；契约变化提升文档版本并记录兼容性。

## 17. 兼容性规则

兼容变更：新增可选请求字段、新增响应字段、新增错误 Detail 字段。

需评审变更：新增枚举值、改变默认 Limit、改变幂等范围。

破坏性变更：移除/重命名字段、改变字段含义、缩小允许值、改变状态机；必须发布新的 API 主版本或提供完整兼容期。

历史响应、推荐记录和解释版本始终按产生时的 Schema 与版本读取，不用新代码静默改写。
