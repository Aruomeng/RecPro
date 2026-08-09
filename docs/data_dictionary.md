# LibraMAS 核心数据字典

> 文档版本：1.2.0
> 状态：G5 反馈事实与画像 Outbox 第一切片
> 日期：2026-08-09
> 适用范围：MySQL 事实层、领域 DTO、Agent 契约和实验重放
> 架构依据：`docs/adr/0001-modular-monolith.md`
> 安全依据：`docs/LibraMAS_系统实施计划_安全低耦合版.md`

## 1. 使用方式与规范优先级

本文档冻结第一版领域语言、核心枚举、表所有权、字段语义和不可破坏约束。后续 ORM、迁移、Pydantic Schema、OpenAPI 和实验脚本必须引用相同名称，不得创建同义字段。

发生冲突时按以下顺序处理：

```text
用户最新明确指令
→ 零删除安全计划
→ 本数据字典
→ 可运行版实施文档
→ 代码默认值或框架惯例
```

本字典中的“停用”“撤回”“隐藏”“过期”和 `REMOVED` 都是保留原事实的逻辑状态，不代表物理移除记录。

## 2. 全局数据约定

### 2.1 类型和格式

| 概念 | 规范 |
|---|---|
| 自增事实 ID | MySQL `BIGINT`；只用于数据库内部关联 |
| 公共/幂等 ID | UUID，第一版存为 `CHAR(36)`，接口使用小写标准字符串 |
| 时间 | UTC `DATETIME(3)`；API 使用 ISO 8601，例如 `2026-08-02T10:30:00.000Z` |
| 日期 | `DATE`，只用于无时区的出版日期 |
| `[0,1]` 分数 | `DECIMAL(7,6)` 并设置边界检查 |
| 高精度中间分数 | `DECIMAL(12,8)` 或文中指定类型 |
| 金额 | 本模块不采集 |
| JSON | 只保存可变详情；用于筛选、排序或关联的字段必须独立成列 |
| 内容哈希 | SHA-256 小写十六进制，`CHAR(64)` |
| 版本 | 非空、不可变字符串，例如 `policy-v1`、`demo-v1` |
| 布尔值 | 语义必须明确，不能用 `NULL` 同时表示 false 和未知 |

### 2.2 时间语义

| 字段 | 语义 |
|---|---|
| `occurred_at` | 用户行为在业务上发生的时间 |
| `created_at` | 事实被本系统持久化的时间 |
| `updated_at` | 只用于允许更新的当前投影；不能代替历史版本 |
| `evaluation_at` | 推荐任务唯一冻结的评价时点；同一任务所有衰减和过滤都使用它 |
| `available_from` | 资源最早允许进入推荐候选的时间 |
| `cutoff_at` | 离线统计快照包含事实的最大时间边界 |
| `valid_from` | 版本开始生效的时间 |
| `suppress_until` | 资源级抑制到期时间；空值表示没有自动到期 |

历史任务必须排除 `occurred_at > evaluation_at`、`available_from > evaluation_at` 和 `cutoff_at > evaluation_at` 的数据。

### 2.3 可变性类别

| 类别 | 允许动作 | 示例 |
|---|---|---|
| F：不可变事实 | 只追加；纠错用补偿事实 | 行为、曝光、反馈、策略决策、推荐结果、执行日志 |
| V：版本历史 | 只新增更高版本；旧版本继续保留 | 配置、声明画像历史、解释、索引构建、实验运行 |
| P：当前投影 | 白名单字段更新；必须能由事实重建 | 当前画像、兴趣权重、资源状态、索引状态、Outbox 状态 |
| R：引用数据 | 追加新行或逻辑停用；不物理清理 | 资源、标签 |

所有外键使用 `RESTRICT` 或 `NO ACTION`。任何表、行、列、索引、集合、节点、关系和实验产物的物理删除都不属于本数据模型的正常操作。

## 3. 规范枚举

### 3.1 推荐与任务

| 枚举 | 允许值 |
|---|---|
| `ResourceType` | `BOOK`、`PAPER` |
| `OutputType` | `PERSONALIZED_FEED`、`TOPIC_RESOURCES`、`BOOKLIST`、`READING_PATH` |
| `DeliveryStrategy` | `DIRECT`、`GUIDED`、`DEGRADED` |
| `ExplanationLevel` | `SUMMARY`、`EVIDENCE`、`LIMITED` |
| `AdaptationState` | `NORMAL`、`FEEDBACK_ADJUSTED` |
| `TriggerScene` | `HOME`、`SEARCH_AFTER`、`RESOURCE_DETAIL`、`FEEDBACK_REFRESH`、`EXPLANATION` |
| `TaskStatus` | `CREATED`、`UNDERSTANDING`、`PROBING`、`DECIDING`、`WAITING_CLARIFICATION`、`RECALLING`、`RANKING`、`REPLANNING`、`EXPLAINING`、`PERSISTING`、`COMPLETED`、`DEGRADED_COMPLETED`、`FAILED` |
| `IntentType` | `GENERAL_RECOMMENDATION`、`TOPIC_RECOMMENDATION`、`PAPER_RECOMMENDATION`、`BOOK_RECOMMENDATION`、`BOOKLIST_RECOMMENDATION`、`READING_PATH_RECOMMENDATION`、`EXPLANATION_REQUEST`、`UNCLEAR` |
| `ReadingStage` | `BEGINNER`、`INTERMEDIATE`、`ADVANCED`、`RESEARCH` |
| `SnapshotMode` | `MATERIALIZED_CURRENT`、`REPLAY_AS_OF` |
| `SnapshotStage` | `PRE_PLAN`、`POST_RANK`、`POST_RUN` |

### 3.2 资源与索引

| 枚举 | 允许值 |
|---|---|
| `AvailabilityStatus` | `AVAILABLE_BORROW`、`AVAILABLE_ONLINE`、`REFERENCE_ONLY`、`TEMPORARILY_UNAVAILABLE`、`REMOVED` |
| `IndexTarget` | `VECTOR`、`GRAPH` |
| `IndexStatus` | `PENDING`、`READY`、`STALE`、`FAILED`、`SKIPPED` |
| `IndexBuildStatus` | `PLANNED`、`BUILDING`、`READY`、`FAILED`、`NOT_ACTIVE` |
| `IndexOperation` | `UPSERT`、`DEACTIVATE`、`REBUILD` |
| `TagSource` | `HUMAN`、`RULE`、`LLM`、`IMPORT` |
| `RecallChannel` | `PROFILE`、`KEYWORD`、`VECTOR`、`GRAPH`、`TRENDING`、`FEEDBACK` |
| `RecallPhase` | `PROBE`、`FULL` |
| `ChannelRunStatus` | `SUCCESS`、`SUCCESS_EMPTY`、`TIMEOUT`、`FAILED`、`SKIPPED` |

`REMOVED` 仅表示馆藏不再进入候选；原资源、标签、推荐记录和索引历史仍保留。旧实施文档中的索引 `DELETE` 操作在本项目中统一实现为 `DEACTIVATE`。

### 3.3 行为与反馈

| 枚举 | 允许值 |
|---|---|
| `BehaviorEventType` | `SEARCH`、`VIEW_RESOURCE`、`VIEW_EXPLANATION`、`CLICK_RECOMMENDATION`、`FAVORITE_RESOURCE`、`BORROW_BOOK`、`ACCESS_PAPER_FULLTEXT`、`RATE_HIGH`、`RATE_NEUTRAL`、`RATE_LOW`、`REJECT_RECOMMENDATION`、`NOT_INTERESTED`、`RECOMMENDATION_IMPRESSION` |
| `FeedbackType` | `FAVORITE`、`BORROW`、`REJECT`、`NOT_INTERESTED`、`RATE` |
| `NegativeReasonCode` | `TOPIC_NOT_INTERESTED`、`ALREADY_READ`、`TOO_BASIC`、`TOO_ADVANCED`、`LOW_QUALITY`、`NOT_NOW`、`REPEATED`、`OTHER` |
| `ResourceStateType` | `READ`、`FAVORITED`、`BORROWED`、`HIDDEN`、`NOT_NOW`、`DUPLICATE_SUPPRESS` |

只有 `TOPIC_NOT_INTERESTED` 可以产生主题负偏好。其他负反馈只影响资源状态、阅读阶段或短期抑制。

### 3.4 Agent、解释与异步处理

| 枚举 | 允许值 |
|---|---|
| `AgentResultStatus` | `SUCCESS`、`PARTIAL`、`FAILED` |
| `AgentMessageStatus` | `CREATED`、`DISPATCHED`、`HANDLED`、`FAILED` |
| `OutboxStatus` | `PENDING`、`PROCESSING`、`DONE`、`DEAD` |
| `ExplanationProvider` | `TEMPLATE`、`MOCK_LLM`、`EXTERNAL_LLM` |
| `EvidenceValidatorStatus` | `PASSED`、`FALLBACK_TEMPLATE`、`REJECTED` |
| `ConfigStatus` | `DRAFT`、`ACTIVE`、`INACTIVE`、`REJECTED` |

允许的 Agent 消息类型：

```text
INTENT.RESOLVE / INTENT.RESOLVED
PROFILE.BUILD / PROFILE.READY
SEMANTIC.PROBE / SEMANTIC.PROBE_READY
POLICY.DECIDE / POLICY.DECIDED
RECALL.EXECUTE / RECALL.READY
RANK.EXECUTE / RANK.READY / RANK.REPLAN_REQUIRED
POLICY.REPLAN / POLICY.REPLANNED
POLICY.DOWNGRADE / POLICY.DOWNGRADED
EXPLAIN.EXECUTE / EXPLAIN.READY
FEEDBACK.ANALYZE / FEEDBACK.DELTA_PROPOSED
PROFILE.APPLY_DELTA / PROFILE.UPDATED
```

## 4. 表所有权总览

| 模块 | 表 | 类别 |
|---|---|---|
| Catalog | `resource_catalog`、`resource_book_detail`、`resource_paper_detail`、`tag_dictionary`、`resource_tag` | R |
| Catalog | `resource_index_state` | P |
| Catalog | `resource_index_build`、`resource_popularity_snapshot` | P（保留每个构建实体）/F |
| Catalog | `resource_index_outbox` | P + 保留历史 |
| Profile | `user_behavior_event`、`user_declared_profile_history`、`profile_change_log` | F/V |
| Profile | `user_declared_profile`、`user_profile`、`user_interest_tag`、`user_negative_preference` | P |
| Profile | `profile_update_outbox` | P + 保留历史 |
| Recommendation | `recommendation_task`、`recommendation_clarification`、`recommendation_context_snapshot`、`recommendation_policy_decision` | F + 受控状态转换 |
| Recommendation | `agent_message_log`、`agent_execution_log`、`agent_artifact`、`recommendation_channel_run`、`recommendation_candidate` | F |
| Recommendation | `recommendation_record`、`recommendation_group`、`recommendation_item`、`recommendation_item_explanation` | F/V |
| Recommendation | `recommendation_config_version` | V + 活动指针状态 |
| Feedback | `recommendation_impression`、`recommendation_feedback` | F |
| Feedback | `user_resource_state` | P |
| Observability | `domain_state_transition` | F |

## 5. Catalog 数据

### 5.1 `resource_catalog`

资源主表，一行代表一个图书或论文实体。

| 字段 | 类型 | 可空 | 语义与约束 |
|---|---|---:|---|
| `id` | BIGINT PK | 否 | 内部资源 ID |
| `resource_type` | VARCHAR(16) | 否 | `ResourceType` |
| `external_id` | VARCHAR(128) | 否 | 来源系统稳定 ID；与类型组成唯一键 |
| `title` | VARCHAR(500) | 否 | 原始题名，不用空字符串代替未知 |
| `authors_json` | JSON | 否 | 有序作者数组；未知时为空数组 |
| `abstract` | TEXT | 是 | 摘要或内容简介 |
| `keywords_json` | JSON | 是 | 去重关键词数组 |
| `category_code` | VARCHAR(64) | 是 | 馆藏或学科分类 |
| `publication_year` | SMALLINT | 是 | 出版年份 |
| `publication_date` | DATE | 是 | 可验证的完整出版日期 |
| `publisher_or_source` | VARCHAR(500) | 是 | 出版社、期刊或会议来源 |
| `language` | VARCHAR(16) | 是 | BCP 47 风格语言码 |
| `difficulty_level` | TINYINT | 是 | 1—4，对应阅读阶段 |
| `availability_status` | VARCHAR(24) | 否 | `AvailabilityStatus` |
| `available_from` | DATETIME(3) | 否 | 历史时间过滤下界 |
| `access_url` | VARCHAR(1000) | 是 | 合法访问链接；不存访问密钥 |
| `metadata_quality` | DECIMAL(7,6) | 否 | `[0,1]` |
| `is_classic` | BOOLEAN | 否 | 是否经典资源，默认 false |
| `metadata_version` | INT | 否 | 从 1 单调递增 |
| `created_at` | DATETIME(3) | 否 | 首次导入时间 |
| `updated_at` | DATETIME(3) | 否 | 当前投影更新时间 |

唯一约束：`(resource_type, external_id)`。`REMOVED` 资源永不进入候选，但历史推荐引用仍有效。

### 5.2 `resource_book_detail`

| 字段 | 类型 | 可空 | 语义与约束 |
|---|---|---:|---|
| `resource_id` | BIGINT PK/FK | 否 | 必须引用 `BOOK` 资源 |
| `isbn` | VARCHAR(32) | 是 | 规范化 ISBN |
| `call_number` | VARCHAR(128) | 是 | 索书号 |
| `location` | VARCHAR(255) | 是 | 馆藏位置 |
| `borrowable_copies` | INT | 否 | 非负当前投影；默认 0 |

### 5.3 `resource_paper_detail`

| 字段 | 类型 | 可空 | 语义与约束 |
|---|---|---:|---|
| `resource_id` | BIGINT PK/FK | 否 | 必须引用 `PAPER` 资源 |
| `doi` | VARCHAR(255) | 是 | 规范化 DOI |
| `journal_or_conference` | VARCHAR(500) | 是 | 发表载体 |
| `open_access` | BOOLEAN | 否 | 是否有合法开放全文，默认 false |

### 5.4 `tag_dictionary`

| 字段 | 类型 | 可空 | 语义与约束 |
|---|---|---:|---|
| `id` | BIGINT PK | 否 | 标签 ID |
| `name` | VARCHAR(128) | 否 | 展示名称 |
| `normalized_name` | VARCHAR(128) | 否 | 归一化唯一名称 |
| `parent_id` | BIGINT FK | 是 | 父标签；必须防止环 |
| `status` | VARCHAR(16) | 否 | `ACTIVE` 或 `INACTIVE`；停用仍保留 |

### 5.5 `resource_tag`

| 字段 | 类型 | 可空 | 语义与约束 |
|---|---|---:|---|
| `resource_id` | BIGINT FK | 否 | 资源 |
| `tag_id` | BIGINT FK | 否 | 标签 |
| `weight` | DECIMAL(7,6) | 否 | `[0,1]` 关联强度 |
| `confidence` | DECIMAL(7,6) | 否 | `[0,1]` 来源置信度 |
| `source` | VARCHAR(24) | 否 | `TagSource` |
| `created_at` | DATETIME(3) | 否 | 证据产生时间 |

主键：`(resource_id, tag_id, source)`。公式只使用相同资源和标签下 `max(weight × confidence)`，防止多来源重复累计；其他来源行作为证据保留。

### 5.6 `resource_index_state`

每个资源的当前索引投影，不代替构建历史。

| 字段 | 类型 | 可空 | 语义与约束 |
|---|---|---:|---|
| `resource_id` | BIGINT PK/FK | 否 | 资源 |
| `content_hash` | CHAR(64) | 否 | 当前可索引内容哈希 |
| `embedding_id` | VARCHAR(128) | 是 | 当前活动向量记录引用 |
| `embedding_version` | VARCHAR(64) | 是 | 当前活动向量版本 |
| `embedding_status` | VARCHAR(16) | 否 | `IndexStatus` |
| `graph_version` | VARCHAR(64) | 是 | 当前活动图版本 |
| `graph_status` | VARCHAR(16) | 否 | `IndexStatus` |
| `last_indexed_at` | DATETIME(3) | 是 | 最近成功切换时间 |
| `last_error` | VARCHAR(1000) | 是 | 最近错误摘要，不含密钥 |

### 5.7 `resource_index_build`

这是为满足版本化保留而冻结的构建实体表；每次构建新增一行，确保失败版本和旧版本都可审计。构建行的输入、版本和命名空间不可变；技术状态以乐观锁前进，并把每次变化追加到 `domain_state_transition`。

| 字段 | 类型 | 可空 | 语义与约束 |
|---|---|---:|---|
| `id` | CHAR(36) PK | 否 | 构建 ID |
| `resource_id` | BIGINT FK | 否 | 资源 |
| `target` | VARCHAR(16) | 否 | `IndexTarget` |
| `index_version` | VARCHAR(64) | 否 | 构建目标版本 |
| `metadata_version` | INT | 否 | 输入元数据版本 |
| `content_hash` | CHAR(64) | 否 | 输入内容哈希 |
| `namespace` | VARCHAR(255) | 否 | 版本化集合/图命名空间 |
| `status` | VARCHAR(16) | 否 | `IndexBuildStatus` |
| `error_code` | VARCHAR(64) | 是 | 规范错误码 |
| `error_detail` | VARCHAR(1000) | 是 | 脱敏错误摘要 |
| `started_at` | DATETIME(3) | 是 | 开始时间 |
| `finished_at` | DATETIME(3) | 是 | 完成时间 |
| `created_at` | DATETIME(3) | 否 | 计划创建时间 |
| `state_version` | INT | 否 | 从 1 单调递增，用于状态乐观锁 |

唯一约束：`(resource_id, target, index_version, metadata_version)`。切换活动版本只更新 `resource_index_state`；旧构建行和旧命名空间继续保留。

### 5.8 `resource_popularity_snapshot`

| 字段 | 类型 | 可空 | 语义与约束 |
|---|---|---:|---|
| `resource_id` | BIGINT FK | 否 | 资源 |
| `cutoff_at` | DATETIME(3) | 否 | 最大事实时点 |
| `window_days` | SMALLINT | 否 | 统计窗口，正整数 |
| `valid_view_count` | INT | 否 | 非负 |
| `recommendation_click_count` | INT | 否 | 非负 |
| `favorite_count` | INT | 否 | 非负 |
| `borrow_or_access_count` | INT | 否 | 非负 |
| `popularity_raw` | DECIMAL(14,6) | 否 | 原始热度 |
| `type_p95_raw` | DECIMAL(14,6) | 否 | 同类型 P95 |
| `popularity_score` | DECIMAL(7,6) | 否 | `[0,1]` |
| `formula_version` | VARCHAR(64) | 否 | 公式版本 |
| `dataset_version` | VARCHAR(64) | 否 | 数据集版本 |
| `created_at` | DATETIME(3) | 否 | 作业写入时间 |

主键：`(resource_id, cutoff_at, window_days, formula_version, dataset_version)`。TRENDING 只能读取 `cutoff_at <= evaluation_at` 的最大合格快照。

### 5.9 `resource_index_outbox`

| 字段 | 类型 | 可空 | 语义与约束 |
|---|---|---:|---|
| `id` | BIGINT PK | 否 | Outbox ID |
| `resource_id` | BIGINT FK | 否 | 资源 |
| `target` | VARCHAR(16) | 否 | `IndexTarget` |
| `operation` | VARCHAR(16) | 否 | `UPSERT`、`DEACTIVATE` 或 `REBUILD` |
| `metadata_version` | INT | 否 | 目标元数据版本 |
| `status` | VARCHAR(16) | 否 | `OutboxStatus` |
| `attempts` | INT | 否 | 非负 |
| `next_retry_at` | DATETIME(3) | 是 | 下次重试时间 |
| `locked_at` | DATETIME(3) | 是 | 租约开始时间 |
| `locked_by` | VARCHAR(64) | 是 | Worker ID |
| `last_error` | VARCHAR(1000) | 是 | 脱敏错误摘要 |
| `created_at` / `updated_at` | DATETIME(3) | 否 | 创建/状态更新时间 |

唯一约束：`(resource_id, target, operation, metadata_version)`。`DONE` 和 `DEAD` 行都保留。

## 6. Profile 数据

### 6.1 `user_behavior_event`

不可变行为事实。

| 字段 | 类型 | 可空 | 语义与约束 |
|---|---|---:|---|
| `id` | BIGINT PK | 否 | 内部事件 ID |
| `event_uuid` | CHAR(36) UNIQUE | 否 | 客户端/系统幂等键 |
| `user_id` | BIGINT | 否 | 用户 ID |
| `session_id` | CHAR(36) | 否 | 会话 ID |
| `task_id` | CHAR(36) | 是 | 关联推荐任务 |
| `event_type` | VARCHAR(40) | 否 | `BehaviorEventType` |
| `resource_id` | BIGINT | 是 | 目标资源 |
| `recommendation_item_id` | BIGINT | 是 | 来源推荐项 |
| `impression_uuid` | CHAR(36) | 是 | 来源曝光；点击和多数反馈行为必填 |
| `query_text` | VARCHAR(1000) | 是 | 搜索文本，敏感字段 |
| `rating` | DECIMAL(2,1) | 是 | 1—5 |
| `dwell_ms` | INT | 是 | 非负停留时间 |
| `visible_ratio` | DECIMAL(4,3) | 是 | `[0,1]` |
| `position` | SMALLINT | 是 | 1 开始的位置 |
| `reason_code` | VARCHAR(40) | 是 | `NegativeReasonCode` |
| `tag_evidence_json` | JSON | 是 | 当时使用的标签证据快照 |
| `occurred_at` | DATETIME(3) | 否 | 业务发生时间 |
| `created_at` | DATETIME(3) | 否 | 持久化时间 |

`event_uuid` 全局唯一。未来事件可以作为异常事实隔离保存，但不得进入早于其发生时点的画像或实验。

### 6.2 `user_declared_profile`

用户最新声明画像缓存。

| 字段 | 类型 | 可空 | 语义与约束 |
|---|---|---:|---|
| `user_id` | BIGINT PK | 否 | 用户 |
| `declared_version` | INT | 否 | 单调递增 |
| `major` | VARCHAR(128) | 是 | 专业 |
| `grade` | VARCHAR(32) | 是 | 年级 |
| `research_direction` | VARCHAR(255) | 是 | 研究方向 |
| `preferred_language` | VARCHAR(32) | 是 | 偏好语言 |
| `personalization_enabled` | BOOLEAN | 否 | false 时不读取长期行为画像 |
| `updated_at` | DATETIME(3) | 否 | 当前版本更新时间 |

修改当前缓存时必须在同一事务追加下一节的历史行。

### 6.3 `user_declared_profile_history`

字段与当前声明画像相同，另含：

| 字段 | 类型 | 可空 | 语义与约束 |
|---|---|---:|---|
| `id` | BIGINT PK | 否 | 历史 ID |
| `valid_from` | DATETIME(3) | 否 | 版本生效时间 |
| `created_at` | DATETIME(3) | 否 | 写入时间 |

唯一约束：`(user_id, declared_version)`。历史实验选取 `valid_from <= evaluation_at` 的最高版本。

### 6.4 `user_profile`

| 字段 | 类型 | 可空 | 语义与约束 |
|---|---|---:|---|
| `user_id` | BIGINT PK | 否 | 用户 |
| `profile_version` | INT | 否 | 单调递增 |
| `profile_confidence` | DECIMAL(7,6) | 否 | `[0,1]` |
| `recent_focus_tag_id` | BIGINT | 是 | 当前最强主题 |
| `topic_focus_strength` | DECIMAL(7,6) | 否 | `[0,1]` |
| `reading_stage` | VARCHAR(16) | 是 | `ReadingStage` |
| `reading_stage_confidence` | DECIMAL(7,6) | 否 | `[0,1]` |
| `updated_at` | DATETIME(3) | 否 | 投影更新时间 |

这是在线当前投影，历史实验不得直接使用。

### 6.5 `user_interest_tag`

| 字段 | 类型 | 可空 | 语义与约束 |
|---|---|---:|---|
| `user_id` / `tag_id` | BIGINT | 否 | 联合主键 |
| `positive_weight` | DECIMAL(7,6) | 否 | `[0,1]`，仅正信号 |
| `raw_positive_signal` | DECIMAL(12,6) | 否 | 非负未压缩信号 |
| `source_count` | INT | 否 | 非负证据数 |
| `last_event_at` | DATETIME(3) | 否 | 最大来源事件时间 |
| `profile_version` | INT | 否 | 对应画像版本 |

### 6.6 `user_negative_preference`

| 字段 | 类型 | 可空 | 语义与约束 |
|---|---|---:|---|
| `user_id` / `tag_id` / `reason_code` | 组合主键 | 否 | 原因必须为 `TOPIC_NOT_INTERESTED`；其余原因不泛化到主题 |
| `negative_weight` | DECIMAL(7,6) | 否 | `[0,1]` |
| `raw_negative_signal` | DECIMAL(12,6) | 否 | 非负绝对信号 |
| `source_count` | INT | 否 | 非负 |
| `expires_at` | DATETIME(3) | 是 | 可选到期时间 |
| `last_event_at` | DATETIME(3) | 否 | 最大来源事件时间 |
| `profile_version` | INT | 否 | 对应画像版本 |

### 6.7 `profile_change_log`

| 字段 | 类型 | 可空 | 语义与约束 |
|---|---|---:|---|
| `id` | BIGINT PK | 否 | 变更日志 ID |
| `user_id` | BIGINT | 否 | 用户 |
| `source_event_id` | BIGINT | 否 | 触发事实 |
| `source_type` | VARCHAR(32) | 否 | 行为、反馈或校准来源 |
| `profile_version_before` / `profile_version_after` | INT | 否 | `after > before` |
| `delta_json` | JSON | 否 | 可验证的变化明细 |
| `formula_version` | VARCHAR(64) | 否 | 画像公式版本 |
| `created_at` | DATETIME(3) | 否 | 创建时间 |

唯一约束：`(source_event_id, source_type, formula_version)`。

### 6.8 `profile_update_outbox`

| 字段 | 类型 | 可空 | 语义与约束 |
|---|---|---:|---|
| `id` | BIGINT PK | 否 | Outbox ID |
| `user_id` | BIGINT | 否 | 用户 |
| `source_event_id` | BIGINT | 否 | 来源行为事实 |
| `source_type` | VARCHAR(32) | 否 | 来源类型 |
| `payload_json` | JSON | 否 | 版本化 Delta 输入 |
| `status` | VARCHAR(16) | 否 | `OutboxStatus` |
| `attempts` | INT | 否 | 非负 |
| `next_retry_at`、`locked_at` | DATETIME(3) | 是 | 重试和租约 |
| `locked_by` | VARCHAR(64) | 是 | Worker ID |
| `last_error` | VARCHAR(1000) | 是 | 脱敏错误 |
| `created_at` / `updated_at` | DATETIME(3) | 否 | 创建/状态更新时间 |

唯一约束：`(source_event_id, source_type)`。状态转为 `DEAD` 后保留原行和错误。

## 7. Recommendation 数据

### 7.1 `recommendation_task`

| 字段 | 类型 | 可空 | 语义与约束 |
|---|---|---:|---|
| `id` | CHAR(36) PK | 否 | `task_id` |
| `request_id` | CHAR(36) UNIQUE | 否 | 请求幂等 ID |
| `trace_id` | CHAR(36) | 否 | 全链路 Trace |
| `user_id` | BIGINT | 否 | 用户 |
| `session_id` | CHAR(36) | 否 | 会话 |
| `trigger_scene` | VARCHAR(32) | 否 | `TriggerScene` |
| `input_text` | TEXT | 是 | 用户输入，敏感字段 |
| `request_json` | JSON | 否 | 规范化请求快照 |
| `intent_type` | VARCHAR(48) | 是 | `IntentType` |
| `intent_confidence` | DECIMAL(7,6) | 是 | `[0,1]` |
| `status` | VARCHAR(32) | 否 | `TaskStatus` |
| `context_version` | INT | 否 | 从 1 单调递增 |
| `profile_version` | INT | 是 | 在线投影版本；重放时以 Artifact 为准 |
| `config_bundle_version` | VARCHAR(64) | 否 | 配置 Bundle |
| `policy_version` | VARCHAR(64) | 否 | 策略版本 |
| `ranking_version` | VARCHAR(64) | 否 | 排序版本 |
| `behavior_formula_version` | VARCHAR(64) | 否 | 画像公式版本 |
| `embedding_version` / `graph_version` / `prompt_version` | VARCHAR(64) | 是 | 可选能力版本 |
| `dataset_version` | VARCHAR(64) | 否 | 资源/评价数据版本 |
| `replan_count` | TINYINT | 否 | 0 或 1 |
| `evaluation_at` | DATETIME(3) | 否 | 任务唯一时点 |
| `started_at` / `finished_at` | DATETIME(3) | 否/是 | 生命周期 |
| `error_code` | VARCHAR(64) | 是 | 规范错误码 |

状态只允许按任务状态机前进。重试通过幂等键恢复或创建新尝试日志，不把已完成任务退回早期状态。

### 7.2 `recommendation_clarification`

| 字段 | 类型 | 可空 | 语义与约束 |
|---|---|---:|---|
| `id` | BIGINT PK | 否 | 澄清记录 |
| `task_id` | CHAR(36) | 否 | 原任务 |
| `context_version` | INT | 否 | 提问时版本 |
| `questions_json` | JSON | 否 | 结构化问题和选项 |
| `answers_json` | JSON | 是 | 用户原始答案，不覆盖问题 |
| `asked_at` / `answered_at` | DATETIME(3) | 否/是 | 生命周期 |

唯一约束：`(task_id, context_version)`。回答产生新的上下文版本。

### 7.3 `recommendation_context_snapshot`

| 字段组 | 类型 | 语义与约束 |
|---|---|---|
| `id`、`task_id`、`context_version` | ID | 快照身份 |
| `snapshot_stage` | VARCHAR(16) | `SnapshotStage` |
| `profile_confidence`、`interest_strength`、`topic_focus_strength`、`resource_match_score` | DECIMAL(7,6) | `[0,1]` 用户和匹配特征 |
| `usable_candidate_count`、`covered_difficulty_levels`、`subtopic_group_count` | INT/TINYINT | 非负资源覆盖 |
| `metadata_coverage`、`evidence_confidence`、`pipeline_health` | DECIMAL(7,6) | `[0,1]` 证据与健康度 |
| `recent_negative_feedback_count`、`applied_negative_preference_count`、`recall_channel_count` | INT | 非负 |
| `vector_coverage`、`kg_path_coverage` | DECIMAL(7,6) | `[0,1]` |
| `feedback_accept_rate`、`reject_rate` | DECIMAL(7,6) NULL | 样本不足时为空，不伪造 0 |
| `required_slots_json`、`dependency_status_json`、`metric_detail_json` | JSON | 结构化依据 |
| `config_hash` | CHAR(64) | 完整 Bundle 哈希 |
| `created_at` | DATETIME(3) | 创建时间 |

唯一约束：`(task_id, context_version, snapshot_stage)`。`PRE_PLAN` 不得读取排序后特征。

### 7.4 `recommendation_policy_decision`

| 字段 | 类型 | 语义与约束 |
|---|---|---|
| `id` | BIGINT PK | 决策 ID |
| `task_id`、`decision_no`、`context_version` | ID/INT | 决策序号和上下文 |
| `plan_version` | TINYINT NULL | GUIDED 可为空，其余必填 |
| `output_type`、`delivery_strategy`、`explanation_level`、`adaptation_state` | VARCHAR | 规范枚举 |
| `decision_reason_codes_json` | JSON | 非空受控理由码数组 |
| `decision_reason` | VARCHAR(1000) | 人类可读解释 |
| `degraded_components_json` | JSON NULL | 降级组件和原因 |
| `policy_version` | VARCHAR(64) | 策略版本 |
| `created_at` | DATETIME(3) | 决策时间 |

唯一约束：`(task_id, decision_no)`。策略变化新增一行，不覆盖旧决策。

### 7.5 G3 澄清与 Debug 追加事实

G3 MySQL-only 垂直切片使用以下前向表承载澄清和研究审计，不回写
`recommendation_task` 根请求事实：

| 表 | 用途 | 关键不变量 |
|---|---|---|
| `recommendation_task_context` | 每个任务的请求/问题/答案/响应上下文版本 | `(task_id, context_version)` 唯一；澄清幂等键在任务内唯一；只 INSERT |
| `recommendation_clarification` | 每轮问题和原始答案事实 | `(task_id, context_version)` 唯一；答案不覆盖问题 |
| `recommendation_policy_decision` | 按决策序号保存策略输入结果 | `(task_id, decision_no)` 唯一；策略变化追加新行 |
| `recommendation_trace_revision` | 澄清后 Trace 版本 | `(task_id, context_version)` 唯一；旧 Trace 保留 |

普通用户只能读取自己的任务状态；研究管理员 Debug API 读取经过角色校验的
context、policy 和 trace 文档，敏感输入默认只返回摘要或哈希。上述表的外键均为
`ON DELETE RESTRICT`，迁移为前向 `CREATE TABLE IF NOT EXISTS`，不提供删除接口。

### 7.6 Agent 可追踪表

#### `agent_message_log`

核心字段：`message_id` PK、`task_id`、`trace_id`、`causation_id`、`sender`、`receiver`、`message_type`、`schema_version`、`payload_ref`、`deadline_at`、`attempt`、`idempotency_key`、`context_version`、`status`、`created_at`。

约束：`(idempotency_key, attempt)` 唯一；Payload 大对象只能用 Artifact 引用。

#### `agent_execution_log`

核心字段：`id` PK、`result_id` UNIQUE、`input_message_id`、`task_id`、`trace_id`、`step_no`、`agent_name`、`agent_version`、`status`、`confidence`、`fallback_used`、`input_digest`、`tool_calls_json`、`output_ref`、`warnings_json`、`error_code`、`started_at`、`finished_at`、`duration_ms`。

约束：`(task_id, step_no)` 唯一；`confidence ∈ [0,1]`；工具调用参数必须脱敏。

#### `agent_artifact`

字段：`id` UUID PK、`task_id`、`artifact_type`、`schema_version`、`content_json`、`content_hash`、`created_at`。Artifact 不可被原地改写；内容变化创建新 ID。

### 7.6 召回和候选

#### `recommendation_channel_run`

字段：`id`、`task_id`、`phase`、`plan_version`、`channel`、`status`、`latency_ms`、`candidate_count`、`timeout_ms`、`error_code`、`created_at`。

唯一约束：`(task_id, phase, plan_version, channel)`。`SUCCESS_EMPTY` 是健康查询但不贡献资源；`TIMEOUT`、`FAILED`、`SKIPPED` 的权重从本次 RRF 中移除后重归一化。

#### `recommendation_candidate`

字段：`task_id`、`plan_version`、`resource_id`、`channel`、`channel_rank`、`raw_score`、`normalized_score`、`rrf_contribution`、`evidence_json`、`created_at`。

主键：`(task_id, plan_version, resource_id, channel)`。候选证据保存当时快照，不在展示时重新猜测。

### 7.7 最终推荐结果

#### `recommendation_record`

字段：`id` PK、`task_id` UNIQUE、`user_id`、`context_version`、`decision_id`、`plan_version`、`output_type`、`delivery_strategy`、`ranking_version`、`created_at`。

#### `recommendation_group`

字段：`id`、`record_id`、`group_type`、`group_key`、`title`、`goal`、`order_no`。`(record_id, order_no)` 唯一。覆盖不足的分组只在本次结果中不输出并记录理由，不改变资源事实。

#### `recommendation_item`

| 字段组 | 语义 |
|---|---|
| `id`、`record_id`、`group_id`、`resource_id` | 身份和引用 |
| `rank_no`、`group_order_no` | 全局和分组位置 |
| `relevance_score`、`final_score`、`mmr_score` | 最终排序分解 |
| `profile_score`、`semantic_score`、`kg_score`、`intent_score`、`feedback_score`、`popularity_score`、`freshness_score` | 可空特征；缺失不等于 0 |
| `recall_fusion_score`、`metadata_quality` | 必填基础特征 |
| `exposure_penalty`、`negative_penalty` | `[0,1]` 惩罚项 |
| `evidence_confidence` | `[0,1]` 证据覆盖 |
| `selection_reason_codes_json`、`reason_evidence_json` | 受控理由和证据引用 |
| `diversity_relaxed` | 多样性约束是否放宽 |
| `created_at` | 结果冻结时间 |

唯一约束：`(record_id, resource_id)` 和 `(record_id, rank_no)`。

#### `recommendation_item_explanation`

字段：`id`、`recommendation_item_id`、`explanation_version`、`regenerated_from_id`、`explanation_text`、`effective_explanation_level`、`provider`、`model_version`、`prompt_version`、`evidence_refs_json`、`validator_status`、`created_at`。

唯一约束：`(recommendation_item_id, explanation_version)`。重新生成只能追加更高版本并引用来源版本，不能静默改写历史解释。

### 7.8 `recommendation_config_version`

字段：`config_bundle_version` PK、`policy_version`、`ranking_version`、`behavior_formula_version`、`prompt_version`、`bundle_json`、`config_hash`、`status`、`created_at`。

规则：

- Bundle 内容一经写入不可变；内容变化创建新版本。
- 同一环境同一时刻最多一个 `ACTIVE` 版本。
- 状态切换保留审计记录；旧版本继续可被历史任务引用。
- 任务必须同时记录 Bundle 版本和哈希。

## 8. Feedback 数据

### 8.1 `recommendation_impression`

| 字段 | 类型 | 可空 | 语义与约束 |
|---|---|---:|---|
| `id` | BIGINT PK | 否 | 曝光 ID |
| `impression_uuid` | CHAR(36) UNIQUE | 否 | 幂等键 |
| `recommendation_item_id` | BIGINT | 否 | 推荐项 |
| `user_id` | BIGINT | 否 | 必须与推荐记录用户一致 |
| `position` | SMALLINT | 否 | 1 开始 |
| `rendered_at` | DATETIME(3) | 否 | 渲染时间 |
| `visible_started_at` | DATETIME(3) | 是 | `visible_ms > 0` 时必填 |
| `visible_ms` | INT | 否 | 非负 |
| `max_visible_ratio` | DECIMAL(4,3) | 否 | `[0,1]` |
| `is_valid_exposure` | BOOLEAN | 否 | 由后端计算 |
| `clicked_at` | DATETIME(3) | 是 | 同曝光点击时间 |

每条曝光都保留，无论是否达到有效阈值；同时追加 `RECOMMENDATION_IMPRESSION` 零分行为事实。

### 8.2 `recommendation_feedback`

| 字段 | 类型 | 可空 | 语义与约束 |
|---|---|---:|---|
| `id` | BIGINT PK | 否 | 反馈 ID |
| `feedback_uuid` | CHAR(36) UNIQUE | 否 | 幂等键 |
| `recommendation_item_id` | BIGINT | 否 | 推荐项 |
| `user_id` | BIGINT | 否 | 必须与推荐项用户一致 |
| `impression_uuid` | CHAR(36) | 是 | REJECT、NOT_INTERESTED、RATE 必填 |
| `feedback_type` | VARCHAR(32) | 否 | `FeedbackType` |
| `reason_code` | VARCHAR(40) | 是 | 受控原因 |
| `rating` | DECIMAL(2,1) | 是 | RATE 时必填，1—5 |
| `content` | VARCHAR(1000) | 是 | 其他说明，敏感字段 |
| `created_at` | DATETIME(3) | 否 | 提交时间 |

曝光关联必须同时匹配 `user_id` 和 `recommendation_item_id`，不能使用“最近一次曝光”猜测。

### 8.3 `user_resource_state`

| 字段 | 类型 | 可空 | 语义与约束 |
|---|---|---:|---|
| `user_id` / `resource_id` / `state_type` | 组合主键 | 否 | 同一资源可并存多种状态 |
| `suppress_until` | DATETIME(3) | 是 | 自动到期时间 |
| `source_event_id` | BIGINT | 否 | 最近形成当前投影的事实 |
| `last_feedback_at` | DATETIME(3) | 否 | 最近反馈时间 |
| `state_version` | INT | 否 | 单调递增，便于投影审计 |

过期状态不参与过滤，但原状态投影和来源事件继续保留。撤回状态通过新的行为/补偿事实形成新版本，不物理清理旧事实。

## 9. Observability 审计数据

### 9.1 `domain_state_transition`

所有 Current Projection 和技术任务状态变化的追加式审计事实。它不决定业务是否合法，只记录由领域状态机已经验证并提交的变化。

| 字段 | 类型 | 可空 | 语义与约束 |
|---|---|---:|---|
| `id` | BIGINT PK | 否 | 迁移事实 ID |
| `transition_uuid` | CHAR(36) UNIQUE | 否 | 幂等键 |
| `module_name` | VARCHAR(32) | 否 | 所有者模块 |
| `aggregate_type` | VARCHAR(64) | 否 | 例如 `RECOMMENDATION_TASK`、`PROFILE_OUTBOX` |
| `aggregate_id` | VARCHAR(128) | 否 | 目标业务键的规范字符串 |
| `transition_type` | VARCHAR(64) | 否 | 领域受控迁移类型 |
| `from_state` | VARCHAR(64) | 是 | 首次创建时可空 |
| `to_state` | VARCHAR(64) | 否 | 新状态 |
| `version_before` | INT | 是 | 首次创建时可空 |
| `version_after` | INT | 否 | 必须大于 before |
| `causation_ref` | VARCHAR(255) | 否 | Command、事件、Plan 或消息引用 |
| `actor_type` | VARCHAR(32) | 否 | `USER`、`SYSTEM`、`WORKER`、`MIGRATOR` |
| `actor_ref` | VARCHAR(128) | 是 | 脱敏操作者引用 |
| `detail_json` | JSON | 是 | 版本化、无密钥的补充证据 |
| `created_at` | DATETIME(3) | 否 | 与状态变化同事务写入 |

约束：`(aggregate_type, aggregate_id, version_after)` 唯一。若审计事实写入失败，对应状态更新必须整体失败；不能出现“状态已变但没有迁移证据”。

### 9.2 G4 Agent 执行事实

以下四张表均为追加式事实，外键使用 `RESTRICT`，由调用方把消息、结果、产物和最终编排结果放在同一事务中提交。重复提交必须保持内容一致；冲突身份必须失败，不能覆盖旧事实。

| 表 | 关键字段 | 语义 |
|---|---|---|
| `recommendation_agent_message` | `message_id`、`task_id`、`idempotency_key`、`attempt` | Orchestrator 发出的结构化消息；保存路由、上下文版本、截止时间和 JSON Payload |
| `recommendation_agent_result` | `result_id`、`message_id`、`agent_name`、`status` | Agent 对消息的结构化结果；保存置信度、证据引用、警告、回退和工具调用摘要 |
| `recommendation_agent_artifact` | `artifact_id`、`content_hash`、`artifact_type` | 内容寻址的证据/产物引用；只保存 SHA-256 与元数据，不在此表覆盖内容 |
| `recommendation_orchestration_result` | `task_id`、`context_version`、`status`、`replan_count` | G4 Orchestrator 的最终状态、转移、Trace 和公开 Payload 快照 |

G4 第一实现使用 `g4-orchestrator-v1` 与八个规则 Agent 版本。当前运行态仍是显式隔离验证；未接入默认 API、外部 LLM、向量库或图数据库。

## 10. 核心 DTO 字典

### 10.1 `AgentMessage`

| 字段 | 必填 | 语义 |
|---|---:|---|
| `schema_version` | 是 | 消息 Payload Schema 版本 |
| `message_id`、`trace_id`、`task_id` | 是 | 消息、Trace、任务 UUID |
| `sender`、`receiver`、`message_type` | 是 | 受控路由信息 |
| `payload` | 是 | 必须通过消息类型对应 Schema 校验 |
| `causation_id` | 否 | 直接原因消息 |
| `deadline_at` | 是 | Agent 必须在此之前完成或返回超时 |
| `attempt` | 是 | 从 1 开始 |
| `idempotency_key` | 是 | 调用幂等键 |
| `context_version` | 是 | 防止使用过期上下文 |
| `created_at` | 是 | UTC |

### 10.2 `AgentResult[T]`

| 字段 | 必填 | 语义 |
|---|---:|---|
| `result_id`、`input_message_id` | 是 | 结果和输入引用 |
| `agent_name`、`agent_version` | 是 | Agent 身份版本 |
| `status` | 是 | `SUCCESS`、`PARTIAL`、`FAILED` |
| `confidence` | 是 | `[0,1]` 内容可靠性 |
| `payload` | 条件 | `FAILED` 时必须为空 |
| `evidence_refs`、`warnings`、`tool_calls` | 是 | 可为空数组但字段必须存在 |
| `fallback_used` | 是 | 是否采用回退 |
| `error_code` | 条件 | `FAILED` 必填，其他可空 |
| `duration_ms` | 是 | 非负 |

### 10.3 `RecommendationRequestSnapshot`

规范字段：`requested_resource_types`、`requested_output_type`、`source_resource_id`、`source_item_id`、`year_from`、`year_to`、`language`、`difficulty`、`limit`、`effective_limit`、`as_of_time`。

来源字段约束：

| `scene` | 必填 | 允许来源字段 |
|---|---|---|
| `HOME` | 无 | 无 |
| `SEARCH_AFTER` | `input_text` | 无 |
| `RESOURCE_DETAIL` | `source_resource_id` | `source_resource_id` |
| `FEEDBACK_REFRESH` | `source_item_id` | `source_item_id` |
| `EXPLANATION` | `source_item_id` | `source_item_id` |

不合法组合返回 `INVALID_SCENE_SOURCE`。

### 10.4 `InteractionDecision`

字段：`output_type`、`delivery_strategy`、`explanation_level`、`adaptation_state`、`decision_reason_codes`、`decision_reason`、`policy_version`。

`GUIDED` 必须包含至少一个结构化澄清问题；非 `GUIDED` 必须包含至少一个可用召回通道。

## 11. 跨表不变量

1. `recommendation_record.task_id` 只引用 `COMPLETED` 或 `DEGRADED_COMPLETED` 的任务；结果和完成状态在同一事务提交。
2. 一个任务只有一条最终 `recommendation_record`，但可以有多条上下文快照、策略决策和通道运行记录。
3. `replan_count <= 1`，`plan_version` 只允许 1 或 2。
4. 推荐项的 `resource_id` 在任务 `evaluation_at` 时必须可用；`REMOVED` 永远不入选。
5. 所有推荐条目的版本字段可追溯到任务冻结的配置和索引版本。
6. 解释的每个 Evidence Ref 必须指向已持久化证据；校验失败时使用模板回退或拒绝解释。
7. 点击曝光的 `clicked_at` 只更新被引用的曝光，不影响其他曝光。
8. 每个反馈 UUID 最多映射一次行为事实和一次画像 Outbox。
9. `personalization_enabled=false` 时在线快照不读取长期行为画像。
10. 自定义 `as_of_time` 只能在研究/测试权限下使用，并强制 `REPLAY_AS_OF`。
11. `feedback_accept_rate` 等样本不足指标使用 `NULL` 表示未知，不能用 0 冒充。
12. Worker 失败不回滚已经提交的事实；通过同一 Outbox 行重试并保留完整状态历史。
13. 每个白名单状态更新与对应 `domain_state_transition` 在同一事务提交，并使用 `version_before` 做乐观锁。

## 12. 允许更新的白名单

仅以下投影字段允许受控更新：

| 表 | 白名单字段 |
|---|---|
| `resource_catalog` | 当前元数据投影、`metadata_version`、`updated_at`；必须同时保留导入/变更审计 |
| `resource_index_state` | 当前活动版本、状态、最近错误和时间 |
| `user_declared_profile` | 当前声明投影；同事务追加历史 |
| `user_profile`、`user_interest_tag`、`user_negative_preference` | 当前公式版本产生的投影字段 |
| `user_resource_state` | 当前有效投影和递增 `state_version` |
| 两个 Outbox | `status`、`attempts`、租约、重试时间、错误、`updated_at` |
| `recommendation_task` | 合法状态前进、上下文版本、完成时间和错误码 |
| `recommendation_impression` | 同一曝光的可见度聚合和 `clicked_at`，必须单调且有幂等保护 |
| `recommendation_config_version` | 活动状态转换；Bundle 内容和哈希不可变 |

事实表和版本历史不在白名单内。所有白名单状态更新必须同时追加 `domain_state_transition`；任何新 UPDATE 场景必须先修改本字典、给出重建依据并通过架构评审。

## 13. 隐私、审计与保留

敏感字段至少包括：`input_text`、`query_text`、`content`、声明画像字段、用户 ID 和行为时间线。

要求：

1. 日志只记录摘要或哈希，不输出完整敏感文本、访问令牌和数据库凭证。
2. 调试接口默认关闭，仅研究管理员可访问。
3. 实验导出使用不可逆研究标识，不直接输出业务用户 ID。
4. 研究数据使用目的、范围和保存期限写入数据清单。
5. 用户撤回研究授权时，先停止后续处理并追加撤回/隔离状态；若依法或依伦理要求需要物理删除，必须进入用户规定的删除前详细汇报流程，不能由应用自动执行。

## 14. 迁移验收清单

后续 G2 数据迁移必须证明：

- 表名、字段名和枚举与本字典一致；
- 全部外键为 `RESTRICT`/`NO ACTION`；
- 没有级联物理删除、清空或降级迁移逻辑；
- `[0,1]`、非负数、唯一键和幂等键存在数据库约束；
- 事实表没有通用更新 Repository；
- Current Projection 的更新字段在白名单内；
- 白名单状态更新与 `domain_state_transition` 具备同事务测试；
- 时间字段统一 UTC 且保留毫秒；
- 历史时点查询有越界测试；
- dry-run 的 `expected_delete_count` 恒为 0；
- 迁移失败通过新的前向修复迁移处理，不覆盖既有迁移文件。

## 15. 版本演进

本字典冻结后：

1. 新增字段优先 nullable 或带可证明安全的默认值。
2. 重命名采用“新增字段 → 双写/回填 → 切换读取 → 旧字段保留”的前向路径。
3. 枚举退役使用逻辑停用和读取兼容，不从历史数据中移除旧值。
4. 公式和 JSON Schema 变化必须提升版本并保留旧解析器用于历史重放。
5. 每次变更记录影响表、DTO、API、实验和回放兼容性。
