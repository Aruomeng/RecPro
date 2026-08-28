# LibraMAS：基于多智能体协同的动态智慧图书馆推荐模块实施文档（可运行版）

> [!IMPORTANT]
> **安全勘误与规范优先级（2026-08-02）**
>
> 本文档中凡与「不删除任何文件、不删除任何数据库数据」冲突的旧表述，均已失效且不得转化为代码、脚本、路由或 SQL。规范优先级为：[SAFETY_POLICY.md](SAFETY_POLICY.md) → [ADR-0002](adr/0002-zero-delete-data-policy.md) → [安全实施计划](LibraMAS_系统实施计划_安全低耦合版.md) → 本文档其余内容。
>
> - 「删除图关系」统一解释为追加 `DEACTIVATE` 事件或构建新图版本；旧关系和旧版本保留。
> - `demo-reset` 和「重置 smoke 用户」统一替换为新的 `fixture_generation`、`test_run_id` 和测试用户 ID；历史运行不复原、不覆盖。
> - 「删除兴趣标签」和「清除推荐历史」统一实现为追加更正/撤回事件、停止个性化使用与停止展示；不执行物理删除。
> - 「测试后销毁临时数据库或 Chroma 目录」统一替换为版本化命名、保留原对象并标记 `NOT_ACTIVE`；不安排自动清理。
> - 若未来确有删除需求，必须先停止实施，按 [DELETE_REQUEST_TEMPLATE.md](DELETE_REQUEST_TEMPLATE.md) 向用户完整汇报并等待明确批准。

> 文档版本：2.0
> 文档状态：可开发基线
> 适用范围：研究生论文原型、系统设计与实现章节、开发与测试依据
> 核心方向：多智能体系统 + 智慧图书馆知识资源推荐
> 技术基线：FastAPI、SQLAlchemy、MySQL、Neo4j、Chroma、Vue 3、Vite、Element Plus
> 默认运行方式：本地 Docker 基础设施 + MockLLMProvider
> 原则：保留多智能体研究主线，同时保证在没有真实大模型 API、Neo4j 暂时不可用或部分资源缺少向量时仍可运行

---

## 0. 文档目标与完成定义

本文档只描述 LibraMAS 中的知识资源推荐模块。目标不是堆叠 Agent 名称，而是实现一个具备以下特征的可运行多智能体原型：

1. 每个 Agent 有明确目标、观察范围、工具权限、输入输出契约和置信度。
2. Agent 之间通过结构化消息协作，而不是依赖无法验证的自然语言传递。
3. 推荐分数、画像更新和模式决策可复现、可测试、可追溯。
4. 大模型仅用于意图补充解析、文本反馈解析和受约束的解释表达，不直接制造推荐证据或最终分数。
5. 系统可以根据内部状态改变外部推荐交互，但不会把不同维度的交互状态混为一个枚举。
6. 用户反馈能够改变后续画像、排序和交互策略。
7. 任一非核心组件失败时，系统能够降级而不是整体不可用。

### 0.1 “真正实现并正常运行”的最低标准

只有同时满足以下条件，才认为模块完成：

```text
1. 使用脚本可以初始化数据库、演示资源、用户行为和索引。
2. 使用 MockLLMProvider 时不需要任何外部 API Key。
3. 用户输入明确需求后可以获得图书或论文推荐。
4. 用户意图模糊时系统返回结构化澄清问题。
5. 用户表达系统学习需求时系统返回阅读路径。
6. 每条结果可以追溯到候选来源、评分明细和证据引用。
7. 前端真实展示的推荐条目会写入曝光记录。
8. “不感兴趣”等反馈会导致下一次推荐发生可验证的变化。
9. Chroma、Neo4j或LLM单独不可用时，接口仍能返回降级结果。
10. 自动化测试覆盖核心公式、策略规则、Agent契约和六个论文演示场景。
```

### 0.2 论文研究对象

本论文原型研究的核心不是“用了多少个 Agent”，而是：

> 面向智慧图书馆知识资源推荐，构建一个由用户状态、任务意图、资源覆盖、反馈状态和证据置信共同驱动的多智能体协同决策机制，使推荐系统能够在直接推荐、引导补充和低置信降级之间自适应切换，并生成推荐流、主题资源、专题书单或阅读路径。

形式化表示为：

```text
内部状态：
S_t = (U_t, I_t, C_t, F_t, E_t)

交互策略：
D_t = π(S_t)

推荐结果：
R_t = Rank(Recall(U_t, I_t, D_t))

反馈更新：
(U_{t+1}, F_{t+1}) = Update(U_t, F_t, Y_t)
```

其中：

```text
U_t：用户画像与近期兴趣状态
I_t：当前任务意图
C_t：候选资源覆盖与匹配状态
F_t：正负反馈与曝光状态
E_t：证据完整度与Agent执行置信度
D_t：多维交互决策
R_t：推荐结果
Y_t：用户对本轮推荐的行为反馈
```

---

## 1. 模块边界

### 1.1 本模块包含

```text
1. 图书与论文元数据导入
2. 资源语义标签、向量和知识图谱索引
3. 检索、浏览、收藏、借阅、曝光、点击和负反馈采集
4. 用户兴趣画像、负偏好和阅读阶段更新
5. 当前任务意图识别
6. 候选资源轻量探测
7. 多维交互策略决策
8. 多通道候选召回与融合
9. 可复现排序与多样性重排
10. 个性化推荐流
11. 即时主题资源推荐
12. 专题书单生成
13. 阅读路径生成
14. 推荐理由、评分明细和证据路径
15. 反馈学习与曝光抑制
16. Agent结构化协作、执行日志和失败降级
17. 推荐前端、调试页和论文演示数据
18. 离线评估、策略评估、消融实验和用户实验支持
```

### 1.2 本模块不包含

```text
1. 座位与空间推荐
2. 活动策划
3. 馆藏采购与剔旧
4. 图书自动编目
5. 管理驾驶舱
6. 通用智能问答
7. 大规模分布式推荐平台
8. 在线训练深度推荐模型
9. 与真实图书馆业务系统的生产级账号和支付集成
```

### 1.3 推荐对象

基础资源只有两类：

```text
BOOK：图书
PAPER：论文
```

专题书单和阅读路径不是独立资源类型，而是由基础资源组合得到的推荐结果：

```text
BOOKLIST：围绕主题和子主题组织的资源集合
READING_PATH：按照学习阶段和先修关系排序的资源集合
```

这种设计避免为书单和路径重复存储资源元数据。

---

## 2. 核心设计原则

### 2.1 多智能体与确定性算法分工

Agent 负责：

```text
观察任务状态
选择和调用工具
基于局部目标作出决策
输出结构化结果和置信度
在失败时返回可处理的部分结果
```

确定性服务负责：

```text
数据库查询
画像公式计算
向量相似度计算
图谱路径查询
评分公式计算
多样性重排
事务写入
```

Agent 可以调用确定性服务，但不能任意修改服务输出的分数。

### 2.2 在线与离线分离

以下任务离线执行：

```text
资源清洗
主题标签提取
摘要向量生成
Neo4j资源图谱构建
热度统计
难度标注
索引一致性检查
```

以下任务在线执行：

```text
意图识别
画像读取与即时特征计算
轻量候选探测
交互策略选择
完整召回
排序与重排
解释生成
曝光和反馈处理
```

在线接口不应在每次请求中重新计算全部资源向量或重建图谱。

### 2.3 证据优先

任何推荐理由都必须引用已经存在的证据对象：

```text
用户行为事件ID
用户兴趣标签ID
资源标签ID
候选召回来源
向量相似度
知识图谱路径
评分特征
反馈记录ID
```

LLM 只能改写这些证据，不能创造新的作者、题名、用户行为或知识路径。

### 2.4 可降级运行

```text
LLM不可用 → 规则意图识别 + 模板解释
Neo4j不可用 → 不计算kg_score，其权重按比例分配给其他有效特征
Chroma不可用 → 画像标签、关键词和热门召回
资源摘要缺失 → 不使用semantic_score，并降低证据置信度
用户画像不足 → 引导式交互或冷启动推荐
```

MySQL 是核心状态存储。MySQL 不可用时接口返回 `503 CORE_STORAGE_UNAVAILABLE`，不尝试伪造结果。

---

## 3. 总体架构

### 3.1 逻辑架构

```mermaid
flowchart TB
    UI["Vue推荐界面"] --> API["FastAPI推荐接口"]
    API --> O["RecommendationOrchestratorAgent"]

    O --> IA["IntentUnderstandingAgent"]
    O --> UA["UserProfileAgent"]
    IA --> RS["ResourceSemanticAgent：轻量探测"]
    UA --> RS
    RS --> PA["RecommendationPolicyAgent"]

    PA -->|"需要澄清"| GUIDE["结构化澄清问题"]
    PA -->|"可以推荐"| CA["CandidateRecallAgent"]
    CA --> RA["RankingAgent"]
    RA --> EA["ExplanationAgent"]
    EA --> OUT["推荐流 / 主题资源 / 书单 / 阅读路径"]

    OUT --> IMP["曝光事件"]
    IMP --> FA["FeedbackLearningAgent"]
    FA --> UA

    CA --> MYSQL[("MySQL")]
    CA --> CHROMA[("Chroma")]
    CA --> NEO4J[("Neo4j")]
    UA --> MYSQL
    FA --> MYSQL
    O --> LOG["Agent执行日志与上下文快照"]
```

### 3.2 运行平面

系统分为三个平面：

| 平面 | 职责 | 核心组件 |
|---|---|---|
| 请求平面 | 接收推荐任务并返回结果 | FastAPI、Orchestrator、各在线Agent |
| 数据平面 | 保存业务状态并提供检索 | MySQL、Chroma、Neo4j |
| 观测平面 | 记录执行链、策略和错误 | task、context_snapshot、agent_execution_log |

### 3.3 部署原则

研究原型采用“模块化单体”：

```text
所有Agent运行在同一个FastAPI进程中
Agent之间使用Python结构化对象通信
不引入Kafka、RabbitMQ或多个Agent微服务
MySQL和Neo4j使用Docker
Chroma默认使用本地持久化客户端
前端单独运行
```

该方案保留多智能体的角色、目标、工具和协同过程，同时避免原型阶段的分布式运维负担。

---

## 4. 多智能体系统定义

### 4.1 Agent成立条件

本系统中的 Agent 必须同时具备：

```text
Role：独立职责
Goal：局部目标
Observation：可读取的任务状态
Tools：受限工具集合
Policy：局部决策规则
Action：对共享任务状态产生结构化输出
Confidence：对输出可靠性的量化
Trace：可追溯执行记录
```

仅封装一个数据库函数且没有局部决策的类称为 Service，不称为 Agent。

### 4.2 Agent清单

| Agent | 局部目标 | 主要观察 | 可用工具 | 核心输出 |
|---|---|---|---|---|
| RecommendationOrchestratorAgent | 完成推荐任务并协调失败 | 全局任务状态 | Agent注册表、状态机、日志仓库 | 最终任务状态、Agent调用链 |
| IntentUnderstandingAgent | 判断用户当前要完成的推荐任务 | 输入文本、场景、会话历史 | 规则分类器、LLMProvider | intent_type、主题、置信度 |
| UserProfileAgent | 形成当前时刻的用户推荐画像 | 行为、兴趣、负偏好、借阅 | ProfileService | 画像快照、近期关注、阅读阶段 |
| ResourceSemanticAgent | 评估资源是否足以支撑当前任务 | 意图、画像、资源索引状态 | MySQL、Chroma、Neo4j探测工具 | 候选数量、覆盖率、匹配度、证据置信 |
| RecommendationPolicyAgent | 选择多维交互策略并规划完整召回 | 意图、画像、探测、反馈、Agent状态 | PolicyEngine、RetrievalPlanBuilder | 四维交互决策、retrieval_plan或replan |
| CandidateRecallAgent | 从多个通道取得可解释候选 | 意图、画像、策略 | 画像、关键词、向量、图谱、热门召回工具 | 去重候选及来源 |
| RankingAgent | 生成稳定排序和组合结果 | 候选特征、策略、负偏好 | ScoringService、MMRService | 排名、评分明细、书单或路径结构 |
| ExplanationAgent | 生成忠实于证据的推荐解释 | 排名结果、证据引用、策略理由 | 模板、LLMProvider、EvidenceValidator | 摘要理由、详细解释 |
| FeedbackLearningAgent | 将用户反应转化为状态变化 | 曝光、点击、收藏、借阅、负反馈 | FeedbackService、OutboxRepository、消息总线 | 画像增量提案、资源状态和策略日志 |

本版将原先由 Orchestrator 内部承担的意图理解独立为 `IntentUnderstandingAgent`，因此共有 8 个业务 Agent；`RecommendationOrchestrator` 是独立控制平面，不计为第九个 Agent。拆分意图理解的原因是让其具备独立契约、工具回退和评价指标，而不是为了增加 Agent 数量。

### 4.2.1 各Agent的合法动作

| Agent | 可选择的动作 |
|---|---|
| Orchestrator | 继续、提前返回澄清、重规划一次、降级完成、失败终止 |
| IntentUnderstanding | 使用显式槽位、规则分类、LLM分类、返回UNCLEAR |
| UserProfile | 读取现有快照、增量重算、全量重放、生成冷启动快照、应用Delta |
| ResourceSemantic | 使用已有规范主题、扩展主题、执行轻量探测、报告索引不足 |
| Policy | 直接推荐、引导、降级、选择输出类型、生成或修订召回计划 |
| Recall | 选择可用通道、调整Top-K预算、融合、返回部分通道结果 |
| Ranking | 正常排序、RRF回退、请求一次重规划、降低输出质量级别 |
| Explanation | 模板摘要、证据解释、LLM改写、拒绝无证据解释 |
| FeedbackLearning | 资源级抑制、主题Delta、难度Delta、写Outbox、不改变长期画像 |

### 4.3 Agent消息协议

所有 Agent 使用同一消息信封：

```python
class AgentMessage(BaseModel):
    schema_version: str
    message_id: UUID
    trace_id: UUID
    task_id: UUID
    sender: str
    receiver: str
    message_type: str
    payload: dict
    causation_id: UUID | None
    deadline_at: datetime
    attempt: int
    idempotency_key: str
    context_version: int
    created_at: datetime


class AgentResult(BaseModel, Generic[T]):
    result_id: UUID
    input_message_id: UUID
    agent_name: str
    agent_version: str
    status: Literal["SUCCESS", "PARTIAL", "FAILED"]
    confidence: float              # 0.0 至 1.0
    payload: T | None
    evidence_refs: list[str]
    warnings: list[str]
    fallback_used: bool
    tool_calls: list[dict]
    error_code: str | None
    duration_ms: int
```

约束：

```text
1. 每种消息注册唯一payload_model，payload必须通过对应Pydantic模型校验。
2. confidence必须位于[0,1]。
3. PARTIAL必须列出缺失能力和降级原因。
4. FAILED不能返回伪造的业务结果。
5. 每次Agent调用都写入agent_execution_log。
6. 自然语言不能作为Agent之间唯一的数据交换格式。
7. 每条命令必须带deadline、idempotency_key和context_version。
8. 大型候选集通过agent_artifact引用，不在消息中重复复制。
```

建议消息名称：

```text
INTENT.RESOLVE / INTENT.RESOLVED
PROFILE.BUILD / PROFILE.READY
SEMANTIC.PROBE / SEMANTIC.PROBE_READY
POLICY.DECIDE / POLICY.DECIDED
RECALL.EXECUTE / RECALL.READY
RANK.EXECUTE / RANK.READY
RANK.REPLAN_REQUIRED
POLICY.REPLAN / POLICY.REPLANNED
POLICY.DOWNGRADE / POLICY.DOWNGRADED
EXPLAIN.EXECUTE / EXPLAIN.READY
FEEDBACK.ANALYZE / FEEDBACK.DELTA_PROPOSED
PROFILE.APPLY_DELTA / PROFILE.UPDATED
```

### 4.4 共享任务状态

```python
class RecommendationState(BaseModel):
    task_id: UUID
    trace_id: UUID
    user_id: int
    session_id: UUID
    context_version: int
    deadline_at: datetime
    request: RecommendationRequestSnapshot
    scene: TriggerScene
    input_text: str | None
    intent: IntentResult | None
    profile: ProfileSnapshot | None
    probe: ResourceProbeResult | None
    decision: InteractionDecision | None
    retrieval_plan: RetrievalPlan | None
    clarification_questions: list[ClarificationQuestion] = []
    replan_count: int = 0
    candidates: list[Candidate] = []
    ranked_items: list[RankedItem] = []
    explanations: list[Explanation] = []
    artifact_refs: dict[str, UUID] = {}
    warnings: list[str] = []
    agent_results: dict[str, AgentResult] = {}
    status: str
```

Orchestrator 是唯一可以推进全局状态机的 Agent。其他 Agent 只能返回局部结果，不能绕过 Orchestrator 直接修改任务状态。

`RecommendationRequestSnapshot` 保存用户明确约束：

```text
requested_resource_types
requested_output_type
source_resource_id
source_item_id
year_from/year_to
language
difficulty
limit
effective_limit
as_of_time
```

`TriggerScene` 是受控枚举，不能接受任意字符串：

```text
HOME
SEARCH_AFTER
RESOURCE_DETAIL
FEEDBACK_REFRESH
EXPLANATION
```

各场景的来源字段约束：

| scene | 必填字段 | 允许的来源字段 | 语义 |
|---|---|---|---|
| HOME | 无 | 无 | 首页或用户主动发起的通用推荐 |
| SEARCH_AFTER | input_text | 无 | 根据当前检索语句继续推荐 |
| RESOURCE_DETAIL | source_resource_id | source_resource_id | 围绕一个馆藏资源召回相近或进阶资源 |
| FEEDBACK_REFRESH | source_item_id | source_item_id | 用户完成反馈后刷新结果，来源项必须已有反馈事实 |
| EXPLANATION | source_item_id | source_item_id | 只解释既有推荐项，不新建无关推荐 |

不在表内的来源字段组合返回 `422 INVALID_SCENE_SOURCE`。`RESOURCE_DETAIL` 会读取来源资源的规范标签、关键词、向量和图谱锚点，交给既有 KEYWORD、VECTOR、GRAPH 通道使用；不另造一套不可追踪的“相似推荐”算法。

AgentMessage不直接携带整个可变 `RecommendationState`。Orchestrator为每个Agent构造专属Command DTO，只传该Agent允许观察的字段；画像、探测、候选和排序大对象通过 `agent_artifact` ID引用。

---

## 5. 在线编排流程

### 5.1 任务状态机

```text
CREATED
→ UNDERSTANDING
→ PROBING
→ DECIDING
→ WAITING_CLARIFICATION（补充后回到UNDERSTANDING）
  或 RECALLING → RANKING
→ REPLANNING（最多一次并回到RECALLING）
  或 EXPLAINING
→ PERSISTING
→ COMPLETED | DEGRADED_COMPLETED

不可恢复错误：
→ FAILED
```

```mermaid
stateDiagram-v2
    [*] --> CREATED
    CREATED --> UNDERSTANDING
    UNDERSTANDING --> PROBING
    PROBING --> DECIDING
    DECIDING --> WAITING_CLARIFICATION
    WAITING_CLARIFICATION --> UNDERSTANDING: 用户补充条件
    DECIDING --> RECALLING
    RECALLING --> RANKING
    RANKING --> REPLANNING: 质量不足且尚未重规划
    REPLANNING --> RECALLING: 新计划
    RANKING --> EXPLAINING
    EXPLAINING --> PERSISTING
    PERSISTING --> COMPLETED: 无降级
    PERSISTING --> DEGRADED_COMPLETED: 有组件或结果降级
    UNDERSTANDING --> FAILED: MySQL或任务数据不可用
    COMPLETED --> [*]
    DEGRADED_COMPLETED --> [*]
    FAILED --> [*]
```

图中只绘制了典型失败边。实际规则为任一非终态遇到不可恢复错误均进入 `FAILED`；若MySQL本身不可用，系统返回503并记录本地结构化错误日志，但不能声称已经把FAILED状态写入数据库。

### 5.2 两阶段资源评估

必须先进行轻量探测，再选择交互策略，避免“未召回就先知道资源匹配度”的数据循环。

轻量探测只获取：

```text
unique_candidate_count
usable_candidate_count
top5_match_mean
metadata_coverage
vector_coverage
kg_path_coverage
recall_channel_count
subtopic_group_count
covered_difficulty_levels
resource_type_distribution
```

探测阶段每个通道最多返回10个ID，不生成最终排序。

完整召回在交互策略确定后执行，每个通道按配置返回20至50条候选。

探测指标定义。令 `N` 为完成去重、访问状态和资源级硬过滤后的可用探测候选数：

```text
unique_candidate_count：通道合并去重后的数量，尚未硬过滤
usable_candidate_count = N
metadata_coverage = Σ metadata_quality(candidate) / N
vector_coverage = 有READY且版本匹配向量并成功获得相似度的候选数 / N
kg_path_coverage = 至少存在一条有效图谱路径的候选数 / N
recall_channel_count = 状态为SUCCESS且至少返回一条候选的通道数
subtopic_group_count = 至少包含2条可用候选的二级规范主题数量
covered_difficulty_levels = 可用候选中不同difficulty_level的数量
```

`N=0` 时上述coverage、分组数和难度层数均为0。`SUCCESS_EMPTY` 表示工具健康，但不增加 `recall_channel_count`。所有分母和通道状态保存到 `metric_detail_json`。

### 5.3 标准调用链

直接推荐：

```text
Orchestrator
├── IntentUnderstandingAgent ┐
├── UserProfileAgent         ├─ 可并行
└────────────────────────────┘
→ ResourceSemanticAgent
→ RecommendationPolicyAgent
→ CandidateRecallAgent
→ RankingAgent
→ ExplanationAgent
→ 保存结果与任务快照
```

引导式推荐：

```text
Orchestrator
→ IntentUnderstandingAgent + UserProfileAgent
→ ResourceSemanticAgent
→ RecommendationPolicyAgent
→ 返回澄清问题
→ 用户补充信息
→ 从UNDERSTANDING状态继续原任务
```

反馈链：

```text
曝光/点击/收藏/借阅/拒绝
→ FeedbackLearningAgent
→ 生成ProfileDeltaProposed
→ UserProfileAgent应用画像增量
→ 写入profile_change_log
→ 下一推荐任务读取新画像
```

### 5.4 Orchestrator伪代码

```python
async def dispatch_and_resolve(state, command, fallback):
    original_result = await agent_registry.dispatch(command)
    persist_agent_result_and_message(original_result)
    resolved_result = original_result

    if original_result.status == "FAILED":
        if fallback is None:
            raise UnrecoverableAgentError(original_result.error_code)
        resolved_result = await fallback(state, original_result)
        resolved_result.fallback_used = True
        persist_fallback_result(
            resolved_result,
            causation_id=original_result.result_id,
        )

    elif original_result.status == "PARTIAL":
        if original_result.payload is None and fallback is not None:
            resolved_result = await fallback(state, original_result)
            resolved_result.fallback_used = True
            persist_fallback_result(
                resolved_result,
                causation_id=original_result.result_id,
            )

    if resolved_result.status == "FAILED" or resolved_result.payload is None:
        raise UnrecoverableAgentError(resolved_result.error_code)

    state.agent_results[command.receiver] = resolved_result
    state.warnings.extend(resolved_result.warnings)
    return resolved_result


async def execute(task: RecommendationTask) -> RecommendationResponse:
    state = create_state(task)
    await transition(state, "UNDERSTANDING")

    intent_result, profile_result = await gather_with_timeout(
        dispatch_and_resolve(
            state,
            build_intent_command(state),
            fallback=rule_intent_fallback,
        ),
        dispatch_and_resolve(
            state,
            build_profile_command(state),
            fallback=cold_start_profile_fallback,
        ),
        timeout_seconds=3,
    )
    state.intent = intent_result.payload
    state.profile = profile_result.payload
    state.artifact_refs["intent"] = save_artifact(state.intent)
    state.artifact_refs["profile"] = save_artifact(state.profile)

    if state.intent.intent_type == "EXPLANATION_REQUEST":
        return await execute_existing_item_explanation(state)

    await transition(state, "PROBING")
    probe_result = await dispatch_and_resolve(
        state,
        build_probe_command(
            request=state.request,
            intent_ref=state.artifact_refs["intent"],
            profile_ref=state.artifact_refs["profile"],
        ),
        fallback=mysql_only_probe_fallback,
    )
    state.probe = probe_result.payload
    state.artifact_refs["probe"] = save_artifact(state.probe)

    await transition(state, "DECIDING")
    policy_agent_result = await dispatch_and_resolve(
        state,
        build_policy_command(state),
        fallback=deterministic_policy_fallback,
    )
    policy_result = policy_agent_result.payload
    state.decision = policy_result.decision
    state.retrieval_plan = policy_result.retrieval_plan
    state.clarification_questions = policy_result.clarification_questions
    state.artifact_refs["decision"] = save_artifact(state.decision)

    if state.decision.delivery_strategy == "GUIDED":
        persist_guided_checkpoint(
            state,
            decision_no=next_decision_no(state),
            final_state="WAITING_CLARIFICATION",
        )
        state.status = "WAITING_CLARIFICATION"
        return build_guided_response(state)

    persist_pre_plan_and_decision(
        state,
        decision_no=next_decision_no(state),
    )

    await transition(state, "RECALLING")
    recall_result = await dispatch_and_resolve(
        state,
        build_recall_command(
            request=state.request,
            intent_ref=state.artifact_refs["intent"],
            profile_ref=state.artifact_refs["profile"],
            plan_ref=save_artifact(state.retrieval_plan),
        ),
        fallback=mysql_recall_fallback,
    )
    state.candidates = recall_result.payload.candidates
    state.artifact_refs["candidates"] = save_artifact(state.candidates)

    await transition(state, "RANKING")
    ranking_result = await dispatch_and_resolve(
        state,
        build_ranking_command(
            request=state.request,
            candidates_ref=state.artifact_refs["candidates"],
            decision_ref=state.artifact_refs["decision"],
        ),
        fallback=rrf_ranking_fallback,
    )

    if ranking_result.payload.next_action == "REPLAN_REQUIRED" \
            and state.replan_count < 1:
        await transition(state, "REPLANNING")
        state.replan_count += 1
        replan_result = await dispatch_and_resolve(
            state,
            build_replan_command(state),
            fallback=deterministic_replan_fallback,
        )
        state.retrieval_plan = replan_result.payload.retrieval_plan
        persist_replan_count_and_plan(state)
        return await resume_from_recalling(state)

    state.ranked_items = ranking_result.payload.items
    state.artifact_refs["ranked_items"] = save_artifact(state.ranked_items)
    if ranking_result.payload.quality_gate_passed is False:
        downgrade_result = await dispatch_and_resolve(
            state,
            build_downgrade_command(state),
            fallback=deterministic_downgrade_fallback,
        )
        state.decision = downgrade_result.payload.decision
        state.artifact_refs["decision"] = save_artifact(state.decision)
        save_policy_decision(state, decision_no=next_decision_no(state))

    await transition(state, "EXPLAINING")
    explanation_result = await dispatch_and_resolve(
        state,
        build_explanation_command(
            ranked_items_ref=state.artifact_refs["ranked_items"],
            decision_ref=state.artifact_refs["decision"],
        ),
        fallback=template_explanation_fallback,
    )
    state.explanations = explanation_result.payload.explanations
    state.artifact_refs["explanations"] = save_artifact(state.explanations)

    await transition(state, "PERSISTING")
    final_status = (
        "COMPLETED"
        if not state.warnings
        and state.decision.delivery_strategy != "DEGRADED"
        else "DEGRADED_COMPLETED"
    )
    persist_final_result_and_status(state, final_status)
    state.status = final_status
    return build_response(state)
```

`transition()` 使用 `task_id + context_version + current_status` 乐观锁原子更新任务状态。`persist_final_result_and_status()` 在同一事务中写入record、groups、items、evidence和最终任务状态；事务失败时不返回成功结果。

GUIDED分支中的PRE_PLAN快照、`decision_no`、clarification问题和 `WAITING_CLARIFICATION` 状态也必须在一个Unit of Work中提交后才能返回；否则进程重启将无法恢复澄清任务。

### 5.5 超时与重试

| 组件 | 单次超时 | 重试 | 失败行为 |
|---|---:|---:|---|
| MySQL查询 | 2秒 | 1 | 核心查询失败则503 |
| Chroma查询 | 2秒 | 1 | 移除向量通道 |
| Neo4j查询 | 2秒 | 1 | 移除图谱通道 |
| LLM调用 | 5秒 | 1 | 规则或模板降级 |
| 单个Agent | 6秒 | 0 | 返回PARTIAL或FAILED |
| 完整同步任务 | 12秒 | 0 | 有合格ranked artifact时模板完成，否则返回504 TASK_DEADLINE_EXCEEDED |

重试只适用于幂等读操作。反馈写入不得自动重复提交，必须使用 `idempotency_key`。

Probe、Recall和Ranking结束后立即保存Artifact checkpoint。超时不能把未排序候选冒充最终推荐；只有已经通过质量门禁的ranked artifact可以用于模板解释和降级完成。

---

## 6. 多维推荐交互决策

### 6.1 不使用单一interaction_mode

每次决策返回四个正交维度：

```python
class InteractionDecision(BaseModel):
    output_type: Literal[
        "PERSONALIZED_FEED",
        "TOPIC_RESOURCES",
        "BOOKLIST",
        "READING_PATH",
    ]
    delivery_strategy: Literal[
        "DIRECT",
        "GUIDED",
        "DEGRADED",
    ]
    explanation_level: Literal[
        "SUMMARY",
        "EVIDENCE",
        "LIMITED",
    ]
    adaptation_state: Literal[
        "NORMAL",
        "FEEDBACK_ADJUSTED",
    ]
    decision_reason_codes: list[str]
    decision_reason: str
    policy_version: str
```

PolicyAgent的完整输出：

```python
class PolicyResult(BaseModel):
    decision: InteractionDecision
    retrieval_plan: RetrievalPlan | None
    clarification_questions: list[ClarificationQuestion]
```

当 `delivery_strategy=GUIDED` 时 `retrieval_plan` 可以为空，但必须返回至少一个缺失槽位问题；其他策略必须返回召回计划。

示例：

```json
{
  "decision": {
    "output_type": "READING_PATH",
    "delivery_strategy": "DIRECT",
    "explanation_level": "EVIDENCE",
    "adaptation_state": "FEEDBACK_ADJUSTED",
    "decision_reason_codes": [
      "EXPLICIT_LEARNING_INTENT",
      "SUFFICIENT_RESOURCE_COVERAGE",
      "RECENT_NEGATIVE_FEEDBACK_APPLIED"
    ],
    "decision_reason": "用户明确表达系统学习意图，候选资源覆盖四个难度层级；近期负反馈已参与过滤。",
    "policy_version": "policy-v1"
  },
  "retrieval_plan": {
    "plan_version": 1,
    "min_candidates": 12,
    "resource_quotas": {
      "BOOK": 6,
      "PAPER": 6
    },
    "channels": [
      {
        "name": "KEYWORD",
        "top_k": 50,
        "timeout_ms": 1000,
        "required": true,
        "weight": 0.25
      }
    ]
  },
  "clarification_questions": []
}
```

完整多通道 `channels` 结构见“10.2 召回计划”；非GUIDED结果至少包含一个可用通道。

### 6.2 决策优先级

```text
第一层：尊重用户明确任务意图
第二层：判断完成任务所需信息是否充分
第三层：选择结果组织形式
第四层：选择解释强度
第五层：标记是否经过反馈修正
```

“解释型推荐”和“反馈修正”不再与阅读路径、书单互斥。

### 6.3 可计算的内部驱动特征

所有特征必须保存原始分量、归一化结果和计算版本。

#### 6.3.1 有效行为量

```text
n_eff = Σ importance(event_type) × 2 ^ (-age_days / half_life_days)
```

`importance` 取行为绝对强度除以3并限制到 `[0,1]`。

#### 6.3.2 画像置信度

```text
volume_confidence = 1 - exp(-n_eff / 8)
source_diversity = min(1, unique_positive_event_types / 4)
profile_stability = 1 - JSD(topic_distribution_7d, topic_distribution_30d)
metadata_completeness = 已填写有效画像字段数 / 4

profile_confidence =
    clip(
        0.50 * volume_confidence
      + 0.20 * source_diversity
      + 0.20 * profile_stability
      + 0.10 * metadata_completeness,
      0,
      1
    )
```

`JSD` 使用以2为底的Jensen-Shannon散度，因此位于 `[0,1]`。当任一时间窗口行为不足3条时，`profile_stability` 取0.5，不能伪造高稳定性。

#### 6.3.3 近期主题集中度

```text
p_i = recent_positive_signal_i / Σ recent_positive_signal
concentration = 1 - H(p) / log(K)      # K > 1
sample_factor = min(1, Σ recent_positive_signal / 6)
topic_focus_strength = concentration × sample_factor
```

`recent_positive_signal_i` 只累计 `[evaluation_at - topic_focus_window_days, evaluation_at]` 内映射到主题 `i` 的正向行为，先按8.2节的事件半衰期衰减，再进行窗口截取；默认 `topic_focus_window_days=30`。负向、零分、未来时间和窗口外事件不进入分子或分母。只有一个主题时 `concentration=1`；没有有效行为时 `topic_focus_strength=0`。

#### 6.3.4 兴趣强度

```text
interest_strength = min(1, strongest_raw_positive_topic_signal / 6)
```

它表示最强主题的证据量，不与主题集中度混用。

#### 6.3.5 资源匹配度

轻量探测候选的匹配度：

```text
candidate_probe_match =
    available_weighted_mean(
        semantic_similarity: 0.50,
        profile_tag_similarity: 0.35,
        intent_tag_match: 0.15
    )

resource_match_score = top_5(candidate_probe_match)的均值
```

任何缺失分量均忽略并按剩余权重归一化，不只处理缺失向量。单个候选所有分量均缺失时其探测匹配度为0；没有可用候选时 `resource_match_score=0`。候选少于5条时对实际可用候选求均值。

#### 6.3.6 证据置信度

```text
evidence_confidence =
    0.25 * profile_confidence
  + 0.20 * intent_confidence
  + 0.20 * metadata_coverage
  + 0.15 * min(1, recall_channel_count / 3)
  + 0.10 * vector_coverage
  + 0.10 * kg_path_coverage
```

证据置信度衡量证据覆盖，不等同于推荐分数高低。

#### 6.3.7 流水线健康度

```text
Agent执行状态映射：
SUCCESS且fallback_used=false = 1.0
SUCCESS且fallback_used=true = 0.7
PARTIAL = 0.7
FAILED = 0.0

pipeline_health =
    Σ required_agent_importance × agent_status_value
    / Σ required_agent_importance
```

`AgentResult.confidence` 表示该Agent输出内容的可靠程度，`pipeline_health` 表示执行链的整体健康程度，两者分别记录。确定性Agent成功完成并通过数据校验时可返回1.0；使用LLM解析时必须根据结构校验、规则一致性和回退情况降低置信度。

Policy决策前只计算已经完成的三个上下文Agent：

```text
IntentUnderstandingAgent：0.30
UserProfileAgent：0.30
ResourceSemanticAgent：0.40
```

尚未执行的Policy、Recall、Ranking和Explanation不进入PRE_PLAN健康度，避免循环定义。完整任务结束后另计算POST_RUN健康度。`dispatch_and_resolve()` 必须把每次结果写入 `state.agent_results`，再由 ContextService计算。

### 6.4 决策规则

```python
def decide(context):
    output_type = map_explicit_intent(context.intent)

    if output_type is None:
        if context.topic_focus_strength >= 0.65:
            output_type = "TOPIC_RESOURCES"
        else:
            output_type = "PERSONALIZED_FEED"

    insufficient_user_context = (
        context.intent.intent_type in {"UNCLEAR", "GENERAL_RECOMMENDATION"}
        and context.intent.topic is None
        and context.profile_confidence < 0.45
        and context.topic_focus_strength < 0.55
    )

    insufficient_resources = (
        context.usable_candidate_count
            < config.limits.min_items_by_output[output_type]
        or context.evidence_confidence < 0.35
        or (
            output_type == "READING_PATH"
            and context.covered_difficulty_levels < 2
        )
        or (
            output_type == "BOOKLIST"
            and context.subtopic_group_count < 2
        )
        or context.pipeline_health < 0.50
    )

    missing_required_slots = required_slots_for(
        output_type=output_type,
        intent=context.intent,
    )

    if missing_required_slots:
        delivery = "GUIDED"
    elif insufficient_user_context:
        delivery = "GUIDED"
    elif insufficient_resources:
        delivery = "DEGRADED"
    else:
        delivery = "DIRECT"

    if context.evidence_confidence >= 0.65:
        explanation = "EVIDENCE"
    elif context.evidence_confidence >= 0.35:
        explanation = "SUMMARY"
    else:
        explanation = "LIMITED"

    adaptation = (
        "FEEDBACK_ADJUSTED"
        if context.recent_negative_feedback_count >= 2
        or context.applied_negative_preference_count > 0
        else "NORMAL"
    )

    return InteractionDecision(...)
```

额外约束：

```text
1. 明确要求论文时不得自动改成图书书单。
2. READING_PATH只由明确学习意图，或学习意图加高置信阅读阶段触发。
3. 不能只因reading_stage_confidence高就强制生成阅读路径。
4. 不能只因evidence_confidence高就改变output_type。
5. 明确任务证据不足时优先返回同类型降级结果，并说明缺口。
6. 用户明确要求先追问时，delivery_strategy固定为GUIDED。
```

默认必要槽位：

| output_type | 必要槽位 |
|---|---|
| PERSONALIZED_FEED | 高置信画像或至少一个当前主题 |
| TOPIC_RESOURCES | topic |
| BOOKLIST | topic |
| READING_PATH | topic；learning_stage可由用户确认或画像估计 |

缺少必要槽位时必须GUIDED，不能因为热门候选数量足够而绕过澄清。

### 6.5 会话稳定与防抖

同一 `session_id` 内：

```text
1. 明确新意图可以立即改变output_type。
2. 没有明确新意图时，output_type至少保持两轮。
3. 从DIRECT降为GUIDED必须出现新的信息缺口，不能因分数轻微波动触发。
4. 阈值使用0.05滞回区间，例如进入DIRECT要求0.65，退出DIRECT要求低于0.60。
5. 所有策略变化作为新的decision_no写入recommendation_policy_decision。
```

### 6.6 策略配置

阈值和权重不得散落在代码中。下面只是19.2节唯一配置Bundle的逻辑视图，不是运行时读取的第二份配置文件：

```yaml
policy_version: policy-v1

thresholds:
  profile_guided: 0.45
  topic_focus_infer: 0.65
  evidence_degraded: 0.35
  evidence_detailed: 0.65
  negative_feedback_adjustment_count: 2
  hysteresis_margin: 0.05

session:
  min_output_type_rounds: 2

limits:
  default_final_items: 10
  max_final_items: 20
  hydration_candidate_limit: 200
  min_items_by_output:
    PERSONALIZED_FEED: 5
    TOPIC_RESOURCES: 5
    BOOKLIST: 8
    READING_PATH: 6
```

完整Bundle内容计算SHA-256并记录到每个上下文快照中。

---

## 7. 意图识别

### 7.1 意图枚举

```text
GENERAL_RECOMMENDATION
TOPIC_RECOMMENDATION
PAPER_RECOMMENDATION
BOOK_RECOMMENDATION
BOOKLIST_RECOMMENDATION
READING_PATH_RECOMMENDATION
EXPLANATION_REQUEST
UNCLEAR
```

默认输出映射：

| intent_type | output_type |
|---|---|
| GENERAL_RECOMMENDATION | PERSONALIZED_FEED |
| TOPIC_RECOMMENDATION | TOPIC_RESOURCES |
| PAPER_RECOMMENDATION | TOPIC_RESOURCES，并限定PAPER |
| BOOK_RECOMMENDATION | TOPIC_RESOURCES，并限定BOOK |
| BOOKLIST_RECOMMENDATION | BOOKLIST |
| READING_PATH_RECOMMENDATION | READING_PATH |
| EXPLANATION_REQUEST | 沿用被解释记录的output_type |
| UNCLEAR | 暂定PERSONALIZED_FEED，通常进入GUIDED |

### 7.2 意图识别顺序

```text
1. 前端结构化按钮或requested_output_type
2. 高精度关键词和句式规则
3. Mock或真实LLM结构化分类
4. 规则与LLM冲突时，明确用户指令优先
5. 仍不确定时返回UNCLEAR
```

示例规则：

```text
包含“论文、文献、paper” → PAPER_RECOMMENDATION
包含“书单、专题列表” → BOOKLIST_RECOMMENDATION
包含“系统学习、从入门到、学习路线、阅读路径” → READING_PATH_RECOMMENDATION
包含“为什么推荐、推荐依据” → EXPLANATION_REQUEST
仅包含“找点资料、推荐一些”且无主题 → UNCLEAR
```

### 7.3 输出契约

```json
{
  "intent_type": "READING_PATH_RECOMMENDATION",
  "explicit": true,
  "topic": "多智能体推荐",
  "resource_types": ["BOOK", "PAPER"],
  "learning_goal": "系统学习",
  "source_item_id": null,
  "constraints": {
    "year_from": null,
    "language": null,
    "difficulty": null
  },
  "confidence": 0.94,
  "evidence": ["命中句式：系统学习"],
  "parser": "rule-v1"
}
```

LLM输出必须使用同一契约。JSON校验失败后最多重试一次，然后回退到规则结果。

`EXPLANATION_REQUEST` 必须带 `source_item_id`。没有目标时返回澄清问题“你想查看哪一条推荐的依据”，不能猜测用户指向的资源。已有推荐项也可直接使用 explanation GET 接口。

---

## 8. 用户画像与行为模型

### 8.1 行为事件类型

| 事件 | 基础分值 | 默认半衰期 | 是否要求曝光关联 |
|---|---:|---:|---|
| SEARCH | +1.0 | 14天 | 否 |
| VIEW_RESOURCE | +0.5 | 14天 | 否 |
| VIEW_EXPLANATION | +0.4 | 14天 | 是 |
| CLICK_RECOMMENDATION | +1.2 | 21天 | 是 |
| FAVORITE_RESOURCE | +2.0 | 60天 | 可选 |
| BORROW_BOOK | +3.0 | 120天 | 可选 |
| ACCESS_PAPER_FULLTEXT | +3.0 | 120天 | 可选 |
| RATE_HIGH | +2.0 | 60天 | 是 |
| RATE_NEUTRAL | 0 | — | 是 |
| REJECT_RECOMMENDATION | -1.5 | 30天 | 是 |
| NOT_INTERESTED | -3.0 | 45天 | 是 |
| RATE_LOW | -2.0 | 45天 | 是 |
| RECOMMENDATION_IMPRESSION | 0 | — | 自身即曝光 |

基础分值由 `profile-formula-v1` 配置管理。

### 8.2 事件到主题的贡献

事件可能关联多个主题，贡献按关联度分配：

```text
signal(e, tag) =
    base_score(event_type)
  × relevance(event_target, tag)
  × 2 ^ (-age_days / half_life(event_type))
```

`base_score=0` 的审计事件直接贡献0并跳过时间衰减计算；其 `half_life_days` 可以为NULL。配置校验要求所有非零score对应的half_life_days必须大于0，避免出现除零或NULL传播。

`ACCESS_PAPER_FULLTEXT` 只在用户通过系统访问可验证的合法全文链接时产生；查看论文题名或摘要仍属于 `VIEW_RESOURCE`，不能冒充全文访问。

正负信号分开累计：

```text
positive_signal(tag) = Σ max(0, signal)
negative_signal(tag) = Σ abs(min(0, signal))

positive_weight(tag) = 1 - exp(-positive_signal(tag))
negative_weight(tag) = 1 - exp(-negative_signal(tag))
```

正负权重分别位于 `[0,1]`。画像匹配只使用 `positive_weight`，负偏好只通过过滤和 `negative_penalty` 处理，避免同一负反馈被重复扣分。没有对应信号时权重为0。

负事件只有在 `reason_code=TOPIC_NOT_INTERESTED` 时才向资源主题标签贡献负信号。`ALREADY_READ`、`TOO_BASIC`、`TOO_ADVANCED`、`LOW_QUALITY`、`NOT_NOW` 和 `REPEATED` 的主题贡献强制为0，分别更新资源状态、阅读阶段或短期抑制状态。

### 8.3 负反馈原因

前端负反馈必须允许选择原因：

```text
TOPIC_NOT_INTERESTED：不喜欢该主题
ALREADY_READ：已经读过
TOO_BASIC：内容过于基础
TOO_ADVANCED：难度过高
LOW_QUALITY：资源质量不符合预期
NOT_NOW：当前暂时不需要
REPEATED：重复推荐
OTHER：其他
```

处理规则：

| 原因 | 影响 |
|---|---|
| TOPIC_NOT_INTERESTED | 增加主题负偏好 |
| ALREADY_READ | 写入state_type=READ并过滤该资源，不抑制主题 |
| TOO_BASIC | 提高阅读阶段估计 |
| TOO_ADVANCED | 降低阅读阶段估计 |
| LOW_QUALITY | 对当前用户隐藏该资源并记录质量反馈；v1不修改全局资源分 |
| NOT_NOW | 通过NOT_NOW状态抑制该资源7天，不改变长期画像 |
| REPEATED | 通过DUPLICATE_SUPPRESS抑制30天，并保留曝光证据 |
| OTHER | 保存文本，默认不泛化 |

### 8.4 阅读阶段

```text
BEGINNER = 1
INTERMEDIATE = 2
ADVANCED = 3
RESEARCH = 4
```

推断依据：

```text
显式用户选择
已借阅或已完成资源的difficulty_level
对TOO_BASIC和TOO_ADVANCED的反馈
阅读路径阶段完成状态
```

```text
reading_stage_confidence = min(1, valid_stage_evidence_count / 5)
```

没有至少2条有效证据时，系统可以展示估计值，但不能据此自动触发阅读路径。

### 8.5 画像更新方式

研究原型采用“事件写入后增量更新 + 定时全量校准”：

```text
任一非零画像事件写入后：通过profile_update_outbox增量更新受影响标签和当前会话缓存
每日或手动任务：从原始事件重新计算全部兴趣标签
```

行为事实和Outbox必须在同一MySQL事务提交，画像版本由Worker在独立事务更新；原始行为事件不可被画像计算覆盖，保证公式升级后可以重算。

### 8.6 历史时点画像与状态

`user_profile`、`user_interest_tag`、`user_negative_preference` 和 `user_resource_state` 都是在线查询使用的当前物化状态，不能直接用于过去 `evaluation_at` 的论文实验。ProfileService必须提供两种明确模式：

```text
MATERIALIZED_CURRENT：
  仅用于普通在线请求；evaluation_at由服务器固定为当前任务创建时刻。

REPLAY_AS_OF：
  用于一切允许自定义as_of_time的测试和论文实验；
  只读取occurred_at<=evaluation_at的user_behavior_event；
  声明画像读取valid_from<=evaluation_at的最新历史版本；
  按同一behavior_formula_version重算兴趣、负偏好、阅读阶段和资源状态；
  禁止读取当前物化画像与当前user_resource_state作为捷径。
```

重放得到的 `ProfileSnapshot` 和 `ResourceStateSnapshot` 保存为Agent Artifact，并记录 `snapshot_mode=REPLAY_AS_OF`、`max_source_event_at`、`evaluation_at` 和公式版本。事件发生时间晚于 `evaluation_at` 时，即使它已经写入数据库，也不能影响该任务。实验Runner可以按用户和时点缓存重放结果，但缓存键必须包含数据集、公式版本和 `evaluation_at`。

---

## 9. 资源语义与索引

### 9.1 统一资源模型

图书和论文共享基础字段：

```text
id
resource_type
external_id
title
authors_json
abstract
keywords_json
category_code
publication_year
publication_date
publisher_or_source
language
difficulty_level
availability_status
available_from
metadata_quality
popularity_raw
created_at
updated_at
```

图书扩展字段：

```text
isbn
call_number
location
borrowable_copies
```

论文扩展字段：

```text
doi
journal_or_conference
url
open_access
```

`availability_status` 枚举：

```text
AVAILABLE_BORROW：馆藏可借
AVAILABLE_ONLINE：有合法全文或访问链接
REFERENCE_ONLY：馆内阅览或仅元数据可查
TEMPORARILY_UNAVAILABLE：暂不可用
REMOVED：下架
```

默认推荐只保留前三类；用户明确允许候补资源时可以展示 `TEMPORARILY_UNAVAILABLE`，但必须标记。`REMOVED` 永不进入候选。

`available_from` 表示该资源最早可被当前系统推荐的UTC时刻，不等于出版日期；历史来源无法恢复该时间时，使用可验证的数据导入时刻，并在数据清单标记为估算值。

### 9.2 元数据质量

```text
metadata_quality =
    0.25 * has_title
  + 0.20 * has_abstract
  + 0.20 * has_keywords
  + 0.15 * has_author
  + 0.10 * has_year
  + 0.10 * has_category
```

`metadata_quality < 0.40` 的资源不能生成强证据解释。

### 9.3 Chroma索引

默认集合：

```text
library_resources__{embedding_version}
```

集合创建时固定使用 `hnsw:space=cosine`。不同embedding_version使用不同集合，禁止向同一集合写入不同维度或不同模型向量。

文档文本：

```text
title + "\n" + keywords + "\n" + abstract
```

metadata：

```json
{
  "resource_id": 123,
  "resource_type": "PAPER",
  "category_code": "TP18",
  "publication_year": 2025,
  "difficulty_level": 3,
  "embedding_version": "${EMBEDDING_VERSION}",
  "available_from_epoch": 1753574400
}
```

MySQL中的 `resource_index_state` 记录向量ID、内容哈希、嵌入版本和最近索引时间。内容哈希未变化时不得重复生成向量。

Chroma返回cosine distance时：

```text
cosine_similarity = 1 - distance
semantic_score = clip((cosine_similarity + 1) / 2, 0, 1)
```

资源未进入向量召回Top-K不代表余弦相似度为0。融合和硬过滤后必须执行10.6节的批量特征补全；索引不可用、资源缺少当前版本向量、查询向量生成失败或因性能预算未补算时 `semantic_score=NULL`，只有实际计算得到不匹配时才允许为0。

#### 可离线运行的演示嵌入

默认演示环境使用确定性的字符N-gram哈希向量，不下载模型：

```text
provider：HashingEmbeddingProvider
analyzer：char
ngram_range：(2, 4)
dimension：384
alternate_sign：false
normalization：L2
```

该Provider主要用于保证中文演示数据可以离线构建Chroma索引和重复实验，不宣称达到预训练语义模型的效果。正式论文效果实验可以切换经过记录的本地嵌入模型，但必须：

```text
更新embedding_version
全量重建向量索引
禁止在同一实验中混用不同版本
报告模型名称、维度和文本拼接方式
```

### 9.4 Neo4j资源图谱

节点：

```text
Resource
Topic
Author
Category
```

关系：

```text
Resource-[:HAS_TOPIC]->Topic
Resource-[:WRITTEN_BY]->Author
Resource-[:BELONGS_TO]->Category
Topic-[:RELATED_TO {weight}]->Topic
Resource-[:CITES]->Resource          # 仅论文数据具备时使用
Resource-[:PREREQUISITE_OF]->Resource
```

为降低隐私和同步复杂度，用户行为不写入Neo4j。查询时将用户兴趣标签作为起点参数，匹配 `Topic → Resource` 路径。

可进入推荐路径的关系置信度：

| 关系 | confidence来源 | 默认值 |
|---|---|---:|
| 虚拟UserInterest→Topic | user_interest_tag.positive_weight | 无固定默认 |
| HAS_TOPIC | effective_resource_tag_weight | 无固定默认 |
| RELATED_TO | 关系属性weight | 缺失时0.60 |
| CITES | 数据源可信且标识可验证 | 0.65 |
| PREREQUISITE_OF | 人工或规则标注置信度 | 0.85 |

`WRITTEN_BY` 和 `BELONGS_TO` 只用于过滤或展示，不进入默认 `kg_path_score`。边的confidence必须位于 `[0,1]`；无法验证来源的边不进入解释路径。

### 9.5 图谱路径分

允许的解释路径最大长度为3：

```text
用户兴趣标签 → Topic → Resource
用户兴趣标签 → Topic → RELATED_TO Topic → Resource
已读Resource → CITES/PREREQUISITE_OF → Resource
```

单条路径：

```text
path_score =
    relation_weight_product / path_length
```

`relation_weight_product` 包括虚拟兴趣锚点和实际图关系的confidence乘积。图谱成功查询但没有路径时为0；图谱不可用时为 `NULL`。

资源图谱分：

```text
kg_path_score = min(1, max_path_score + 0.1 × additional_valid_path_count)
```

路径必须保存节点ID和关系，不只保存展示字符串。

---

## 10. 候选召回与融合

### 10.1 召回通道

| 通道 | 数据源 | 输入 | 默认Top-K | 必需性 |
|---|---|---|---:|---|
| KEYWORD | MySQL资源标题、关键词、摘要 | 当前主题和扩展词 | 50 | 必需 |
| PROFILE | MySQL资源标签 | 用户兴趣标签 | 50 | 通用推荐必需 |
| VECTOR | Chroma | 需求文本或画像摘要向量 | 50 | 可选 |
| GRAPH | Neo4j | 兴趣主题和当前主题锚点 | 30 | 可选 |
| TRENDING | MySQL热度统计 | 资源类型、主题、时间窗口 | 20 | 冷启动备用 |
| FEEDBACK | MySQL反馈相似资源 | 正反馈资源与标签 | 30 | 有反馈时启用 |

明确主题查询不要求用户画像存在；冷启动用户仍可通过关键词和向量通道获得结果。

中文关键词通道默认优先匹配规范主题标签、关键词和题名；MySQL启用中文全文检索时使用经过验证的N-gram解析配置。若部署环境没有启用中文全文索引，则回退到规范标签精确匹配和参数化 `LIKE` 查询，并在通道日志中记录 `KEYWORD_FALLBACK`。

### 10.2 召回计划

PolicyAgent 在完整召回前生成计划：

```json
{
  "plan_version": 1,
  "resource_quotas": {
    "BOOK": 6,
    "PAPER": 6
  },
  "min_candidates": 12,
  "channels": [
    {
      "name": "PROFILE",
      "top_k": 50,
      "timeout_ms": 1000,
      "required": false,
      "weight": 0.15
    },
    {
      "name": "KEYWORD",
      "top_k": 50,
      "timeout_ms": 1000,
      "required": true,
      "weight": 0.25
    },
    {
      "name": "VECTOR",
      "top_k": 50,
      "timeout_ms": 1500,
      "required": false,
      "weight": 0.25
    },
    {
      "name": "GRAPH",
      "top_k": 30,
      "timeout_ms": 1500,
      "required": false,
      "weight": 0.20
    },
    {
      "name": "TRENDING",
      "top_k": 20,
      "timeout_ms": 1000,
      "required": false,
      "weight": 0.05
    },
    {
      "name": "FEEDBACK",
      "top_k": 30,
      "timeout_ms": 1000,
      "required": false,
      "weight": 0.10
    }
  ]
}
```

示例使用“明确任务”RRF配置。RecallAgent必须直接复制当前bundle中对应场景的通道权重；失败或不适用通道被移除后，再对剩余成功通道归一化。它可以调整非必需通道的Top-K预算，但不能擅自发明另一套权重或删除显式资源类型约束。

### 10.3 硬过滤

召回后、融合前执行：

```text
1. resource_type必须符合用户明确要求。
2. availability_status必须可借、可查看或有合法访问链接。
3. 标题或资源唯一标识缺失时过滤。
4. user_resource_state.state_type为HIDDEN、NOT_NOW或DUPLICATE_SUPPRESS且未过期时过滤。
5. user_resource_state.state_type=READ的资源默认过滤；用户要求复习时可以保留。
6. 明确年份、语言、类别等约束必须满足。
7. resource.available_from必须小于等于任务evaluation_at。
8. 非当前显式主题下，negative_weight>=0.85且标签相似度>=0.80时硬过滤；其余主题负偏好只施加negative_penalty。
```

当用户当前明确搜索历史负偏好主题时，当前显式意图优先，不进行主题硬过滤，但仍可保留轻度惩罚并在调试日志中记录 `EXPLICIT_INTENT_OVERRIDES_NEGATIVE_FILTER`。

时间过滤不能只依赖融合后的防线：MySQL各召回查询必须带 `available_from <= evaluation_at`，Chroma查询必须用 `available_from_epoch <= evaluation_at_epoch` 元数据过滤，Neo4j探测和路径查询必须对Resource节点应用同一条件。这样轻量Probe也不会因观察到未来资源而改变策略。

### 10.4 跨通道融合

BM25、余弦相似度和图谱路径分的原始量纲不同，禁止直接相加。

使用加权倒数排名融合：

```text
rrf_score(resource) =
    Σ channel_weight / (60 + rank_in_channel)
```

只对成功返回的通道求和。通道失败不等于资源得分为0。

候选必须保留：

```text
resource_id
supporting_channels
rank_by_channel
raw_score_by_channel
rrf_contribution_by_channel
matched_tags
matched_query_terms
vector_similarity
kg_paths
filter_flags
```

### 10.5 去重

```text
优先使用统一resource_id
图书可使用标准化ISBN辅助去重
论文可使用DOI辅助去重
缺少标准标识时使用标准化题名 + 第一作者 + 年份
```

去重后合并候选来源和证据，不丢弃其他通道的支持信息。

### 10.6 排序前特征补全

跨通道融合只决定候选集合，不能把“未进入某通道Top-K”解释为该通道特征为0。去重和硬过滤后，RecallAgent把不超过 `hydration_candidate_limit` 的候选按 `rrf_score` 截断，再由 ScoringService 批量补全排序特征：

```text
profile_score：对全部候选本地批量计算
semantic_score：当前embedding版本可用时，对全部候选向量批量计算真实余弦
kg_score：图服务可用且资源已入图时批量查询；成功查询但无有效路径为0
intent_score：对全部候选本地批量计算
feedback_score：对全部候选本地批量计算
popularity_score/freshness_score：从同一evaluation_at快照批量读取
```

补全结果保存为 `HYDRATED_CANDIDATES` Artifact，RankingAgent只读取该Artifact。字段语义固定为：

```text
真实计算且不匹配 → 0
工具故障、索引缺失、版本不匹配、不适用或未在预算内计算 → NULL
```

任何 `NULL` 都按11.3节进行缺失权重归一化。默认读取 `limits.hydration_candidate_limit=200`；超出部分不进入排序，且在召回通道日志中记录 `HYDRATION_LIMIT_TRUNCATED` 和截断数量。

### 10.7 一次重规划

RankingAgent发现以下情况时可请求重规划：

```text
可用候选少于输出类型最低数量
最高相关度低于0.35
阅读路径不足两个难度层级
书单无法形成至少两个有效子主题
最终列表同一标签占比超过80%
```

Orchestrator 最多允许一次：

```text
扩展同义主题
适度放宽年份
增加备用热门通道
降低非显式的难度限制
```

不得放宽用户明确指定的资源类型、语言或不可访问资源约束。第二次仍不足则返回降级结果，禁止循环重试。

---

## 11. 推荐排序

### 11.1 特征统一

所有相关度信号和质量审计字段位于 `[0,1]`：

```text
profile_score
semantic_score
kg_score
intent_score
feedback_score
popularity_score
freshness_score
recall_fusion_score
metadata_quality
```

工具故障或特征不适用时值为 `NULL`；工具成功但不匹配时值为 `0`。两者含义不能混用。

`metadata_quality` 不占用加权相关度权重，而作为最多10%的质量校准因子和平局字段。

### 11.2 特征定义

#### profile_score

用户兴趣标签和资源标签的加权余弦相似度：

```text
profile_score = cosine(user_interest_vector, resource_tag_vector)
```

用户没有正兴趣或兴趣向量范数为0时 `profile_score=NULL`；用户有画像且资源标签与其无交集时为0。所有加权Jaccard在并集为空时定义为0。

负偏好不在该分数内相减，而作为单独惩罚，便于解释。

#### semantic_score

```text
semantic_score = clip((cosine_similarity + 1) / 2, 0, 1)
```

若使用的嵌入模型保证余弦值非负，可直接限制到 `[0,1]`，但必须在算法版本中记录。

#### intent_score

```text
intent_score =
    0.60 * explicit_topic_tag_match
  + 0.25 * resource_type_match
  + 0.15 * explicit_constraint_match
```

硬约束已在过滤阶段处理，该分数反映软匹配。

#### popularity_score

图书和论文分别在各自类型内归一化：

```text
popularity_raw =
    3 * borrow_or_access_30d
  + 2 * favorite_30d
  + 1 * click_30d

popularity_score =
    log(1 + popularity_raw) / log(1 + p95_popularity_same_type)
```

超过P95的值截断为1。若同类型 `p95_popularity_same_type=0`，所有该类型资源的 `popularity_score=0`。

`borrow_or_access_30d` 对图书表示借阅，对论文表示合法全文访问；只浏览摘要不计全文访问。

#### freshness_score

```text
freshness_score = 2 ^ (-age_days / freshness_half_life)
```

`age_days` 优先使用 `publication_date`；只有年份时按该年7月1日估算，并限制最小为0。缺失年份和日期时该特征为 `NULL`。

默认半衰期：

```text
BOOK：1825天
PAPER：730天
```

经典资源可以配置 `is_classic=true`，此时最低新鲜度为0.4，避免基础著作被完全压制。

#### feedback_score

```text
feedback_score =
    available_weighted_mean(
        与近180天正反馈标签向量相似度: 0.50,
        与收藏资源标签向量的最大相似度: 0.25,
        与借阅或高评分资源标签向量的最大相似度: 0.25
    )
```

标签相似度使用加权Jaccard。没有对应反馈时该分量忽略；全部缺失时 `feedback_score=NULL`。

#### recall_fusion_score

RRF结果在当前候选集中使用Min-Max归一化。若所有值相同则统一取0.5。

### 11.3 资源类型权重

默认权重：

| 特征 | BOOK | PAPER |
|---|---:|---:|
| profile_score | 0.28 | 0.22 |
| semantic_score | 0.24 | 0.32 |
| kg_score | 0.14 | 0.12 |
| intent_score | 0.07 | 0.07 |
| feedback_score | 0.12 | 0.09 |
| popularity_score | 0.07 | 0.04 |
| freshness_score | 0.04 | 0.10 |
| recall_fusion_score | 0.04 | 0.04 |

权重总和为1。缺失特征采用可用权重归一化：

```text
base_relevance_score =
    Σ available(weight_i × feature_i)
    / Σ available(weight_i)

relevance_score =
    base_relevance_score
    × (0.90 + 0.10 × metadata_quality)
```

不得把不可用的图谱或向量特征记为0后继续使用原权重。

### 11.4 惩罚项

#### 有效曝光

只有同时满足以下条件才计为一次有效曝光：

```text
推荐卡片可视比例 >= 0.50
持续可视时间 >= 1000毫秒
```

#### 曝光惩罚

```text
exposure_penalty =
    min(0.18, visible_without_action_count_30d × 0.03)
```

对 `(user_id, resource_id)`：

```text
window_start =
    max(
        evaluation_at - 30天,
        最近一次CLICK/FAVORITE/BORROW/ACCESS_PAPER_FULLTEXT/RATE_HIGH发生时间
    )

visible_without_action_count_30d =
    window_start之后is_valid_exposure=true
    且该impression没有关联点击的曝光数
```

收藏、借阅和高评分通过 `resource_id` 关联；点击优先通过 `impression_uuid` 关联。该定义使正向行为后的旧无动作曝光自然不再计数，无需物理删除曝光记录。

#### 负偏好惩罚

```text
negative_penalty =
    min(
        0.35,
        0.35
        × negative_tag_similarity
    )
```

```text
negative_tag_similarity =
    Σ min(resource_tag_weight, user_negative_weight)
    / Σ max(resource_tag_weight, user_negative_weight)
```

分母为0或用户没有有效主题负偏好时，`negative_tag_similarity=0` 且 `negative_penalty=0`。

若负反馈原因只是 `ALREADY_READ` 或 `NOT_NOW`，不得计算主题负偏好惩罚。

#### 最终分数

```text
final_score =
    clip(
        relevance_score
        - exposure_penalty
        - negative_penalty,
        0,
        1
    )
```

### 11.5 多样性重排

先取得各资源类型内部前30名，再使用MMR：

```text
MMR(d) =
    λ × final_score(d)
    - (1 - λ) × max_similarity(d, selected_items)
```

默认 `λ=0.80`。

```text
similarity(a, b) =
    0.70 * weighted_jaccard(resource_tags_a, resource_tags_b)
  + 0.30 * same_primary_author(a, b)
```

作者缺失时第二项忽略并对第一项重新归一化。

选择第一条结果时 `selected_items` 为空，定义 `max_similarity=0`。

附加约束：

```text
同一作者在前10名最多2条
同一细粒度主题在前10名最多4条
用户明确只要一种资源时不强制混合
```

混合推荐流使用比例而不是固定条数。默认 `general_book_paper_ratio=[0.60, 0.40]`，以 `effective_limit` 乘比例后用最大余数法分配整数配额；`effective_limit>=2` 且两类资源均有合格候选时，每类至少1条。某一类候选不足时，空余配额按排序分数回填另一类，并记录 `DIVERSITY_QUOTA_RELAXED`；`effective_limit=1` 时只返回全局最高分项并记录 `DIVERSITY_QUOTA_INFEASIBLE`。用户明确只要一种资源时不计算混合配额。

### 11.6 排序可复现

同分时按以下顺序打破平局：

```text
1. evidence_confidence降序
2. metadata_quality降序
3. publication_year降序
4. resource_id升序
```

Mock模式下不得使用未固定种子的随机打散。

---

## 12. 专题书单与阅读路径

### 12.1 专题书单生成

输入为排序后的候选，不允许LLM直接创建不存在的资源。

步骤：

```text
1. 根据资源标签选择目标主题。
2. 对候选的二级主题标签进行分组。
3. 删除少于2条资源的孤立分组，必要时合并到“综合资源”。
4. 每组使用MMR选取2至5条。
5. 默认最多4组，总资源数8至16条。
6. 组名优先使用tag_dictionary中的规范名称。
7. LLM只可根据组内标签生成不超过30字的组说明。
```

若无法形成至少2组或总资源少于8条：

```text
output_type仍为BOOKLIST
delivery_strategy改为DEGRADED
返回现有分组并说明资源覆盖不足
```

### 12.2 阅读路径生成

阅读路径依赖：

```text
resource.difficulty_level
PREREQUISITE_OF关系（可选）
用户reading_stage
资源相关度与可访问性
```

阶段固定为：

```text
FOUNDATION：基础
INTERMEDIATE：进阶
ADVANCED：高级
RESEARCH：研究
```

生成步骤：

```text
1. 按difficulty_level划分候选。
2. 从用户当前阶段开始，但保留最多1条必要基础资源。
3. 每阶段选2至4条资源。
4. 有先修关系时进行拓扑排序。
5. 无图谱关系时按难度、主题覆盖和评分排序。
6. 每条资源保存stage、order_no和selection_reason_codes。
7. 至少覆盖2个阶段，否则标记DEGRADED。
```

发现先修关系环时：

```text
记录GRAPH_CYCLE_WARNING
删除置信度最低的环内关系
继续稳定排序
```

### 12.3 结果结构

```json
{
  "output_type": "READING_PATH",
  "title": "多智能体推荐系统阅读路径",
  "groups": [
    {
      "stage": "FOUNDATION",
      "goal": "掌握推荐系统与智能体基础概念",
      "items": [
        {
          "recommendation_item_id": 101,
          "resource_id": 11,
          "order_no": 1,
          "selection_reason_codes": [
            "FOUNDATION_DIFFICULTY",
            "TOPIC_CORE_RESOURCE"
          ]
        }
      ]
    }
  ]
}
```

---

## 13. 推荐解释

### 13.1 两类解释

每轮结果需分别解释：

```text
为什么推荐这个资源
为什么采用当前交互决策
```

### 13.2 证据包

RankingAgent为每条结果生成：

```json
{
  "resource_id": 11,
  "feature_values": {
    "profile_score": 0.82,
    "semantic_score": 0.88,
    "kg_score": 0.71
  },
  "top_positive_factors": [
    {
      "code": "RECENT_SEARCH_MATCH",
      "value": 0.88,
      "evidence_ref": "behavior:392"
    },
    {
      "code": "INTEREST_TAG_MATCH",
      "value": 0.82,
      "evidence_ref": "profile-tag:44"
    }
  ],
  "penalties": [],
  "kg_paths": [
    {
      "path_ref": "kg-path:task-id:resource-11:1",
      "nodes": ["topic:多智能体", "topic:推荐系统", "resource:11"]
    }
  ]
}
```

单条结果的证据置信度：

```text
feature_coverage =
    可用的profile/semantic/kg/intent/feedback特征数 / 5

channel_agreement =
    min(1, supporting_successful_channels / 3)

reference_coverage =
    已成功持久化的主要证据引用数
    / 计划展示的主要证据数

item_evidence_confidence =
    0.40 * metadata_quality
  + 0.20 * feature_coverage
  + 0.20 * channel_agreement
  + 0.20 * reference_coverage
```

计划展示证据数为0时 `reference_coverage=0`。该值决定解释级别，不参与推荐相关度分数，避免“为了获得高解释置信度而提高排名”的循环。

### 13.3 模板解释

默认解释不依赖LLM：

```text
推荐《{title}》，主要因为：
1. {optional_intent_reason}；
2. {optional_profile_reason}；
3. {optional_semantic_or_graph_reason}。
```

`optional_intent_reason` 可以根据本次显式查询写“符合你本次查询的主题”；`optional_profile_reason` 只有存在行为或画像 `evidence_ref` 时才能写“你近期关注”。语义理由只在 `semantic_score` 非NULL时出现，图谱理由同理。普通用户模板从有效因素中选2至3个，只表达因素，不显示内部数值分数；可用因素不足时减少条目，不输出“NULL分数”，也不使用“模型认为你一定喜欢”等确定性表述。`final_score` 和特征分解保留在持久化记录中，仅对研究管理员的授权评分视图和Debug页开放。

### 13.4 LLM解释

LLM输入只包含：

```text
资源真实元数据
允许使用的证据事实
交互决策代码
格式和字数限制
```

LLM输出必须包含引用标记，例如 `[behavior:392]`。EvidenceValidator执行：

```text
引用是否存在
题名、作者、年份是否与数据库一致
是否出现未授权的新事实
是否使用了证据不足的因果表达
```

校验失败后不继续让LLM自由修复，直接回退到模板解释。

### 13.5 解释级别

```text
SUMMARY：一句摘要理由 + 最主要因素
EVIDENCE：行为证据、排序因素、候选来源和图谱路径；数值评分仍只在授权视图显示
LIMITED：只说明当前可验证事实和缺失证据
```

`LIMITED` 不得生成完整知识路径或声称画像稳定。

Policy决策中的 `explanation_level` 是本轮允许的最高级别，单条结果根据 `item_evidence_confidence` 只能保持或下调：

```text
policy=LIMITED → item=LIMITED
policy=SUMMARY且item_evidence_confidence>=0.35 → item=SUMMARY
policy=SUMMARY且item_evidence_confidence<0.35 → item=LIMITED
policy=EVIDENCE且item_evidence_confidence>=0.55 → item=EVIDENCE
policy=EVIDENCE且0.35<=item_evidence_confidence<0.55 → item=SUMMARY
policy=EVIDENCE且item_evidence_confidence<0.35 → item=LIMITED
```

因此，高质量任务上下文不会让元数据缺失的单条资源获得强证据解释。

### 13.6 MockLLMProvider

Mock Provider 不是返回固定推荐结果，而是只模拟LLM的文本能力：

```text
classify_intent：调用同一规则分类器并返回合法IntentResult
parse_feedback_text：按关键词映射到反馈原因，无法判断时返回OTHER
render_explanation：按固定模板重组传入证据
render_group_summary：根据规范主题名称生成固定句式
```

要求：

```text
1. 不读取演示用户ID进行特殊判断。
2. 相同输入和版本返回完全一致的JSON。
3. 不生成resource_id、分数或知识路径。
4. 支持通过测试配置模拟超时、无效JSON和异常。
5. 每个方法返回provider=mock、model=mock-v1和prompt_version。
```

---

## 14. 反馈学习

### 14.1 反馈类型与行为映射

| feedback_type | 必要字段 | 写入event_type | 影响 |
|---|---|---|---|
| FAVORITE | impression_uuid可选 | FAVORITE_RESOURCE | 正兴趣 |
| BORROW | 图书必须可借；impression_uuid可选 | BORROW_BOOK | 强正兴趣 |
| REJECT | impression_uuid必填；reason_code可选 | REJECT_RECOMMENDATION | 默认短期隐藏当前资源 |
| NOT_INTERESTED | impression_uuid、reason_code必填 | NOT_INTERESTED | 按原因处理 |
| RATE | impression_uuid、rating必填 | rating>=4写RATE_HIGH；rating<=2写RATE_LOW；其余写RATE_NEUTRAL | 评分反馈 |

校验：

```text
TOPIC_NOT_INTERESTED只能用于REJECT或NOT_INTERESTED
TOO_BASIC/TOO_ADVANCED要求资源存在difficulty_level
BORROW只适用于BOOK
RATE范围为1至5
同一feedback_uuid只映射一次行为事件
REJECT、NOT_INTERESTED和RATE的impression_uuid必须属于同一用户、同一recommendation_item
```

点击和查看解释通过行为事件接口上报，不通过反馈接口。

资源状态映射：

| 输入 | state_type | suppress_until | 其他效果 |
|---|---|---|---|
| FAVORITE | FAVORITED | NULL | 正兴趣 |
| BORROW | BORROWED | NULL | 强正兴趣 |
| REJECT且无原因 | HIDDEN | 7天后 | 不产生主题负偏好 |
| TOPIC_NOT_INTERESTED | HIDDEN | 30天后 | 产生主题负偏好 |
| ALREADY_READ | READ | NULL | 不产生主题负偏好 |
| TOO_BASIC | HIDDEN | 30天后 | 更新阅读阶段证据 |
| TOO_ADVANCED | HIDDEN | 30天后 | 更新阅读阶段证据 |
| LOW_QUALITY | HIDDEN | NULL | 仅对当前用户隐藏 |
| NOT_NOW | NOT_NOW | 7天后 | 不改变长期画像 |
| REPEATED | DUPLICATE_SUPPRESS | 30天后 | 保留曝光证据 |
| OTHER | HIDDEN | 7天后 | 不进行主题泛化 |
| RATE_HIGH | 无新增状态 | NULL | 作为正兴趣事件，不抑制资源 |
| RATE_NEUTRAL | 无新增状态 | NULL | 只保存评分事实 |
| RATE_LOW | HIDDEN | 30天后 | 抑制当前资源，不泛化为主题负偏好 |

低评分本身不能证明用户不喜欢整个主题；只有用户另外明确选择 `TOPIC_NOT_INTERESTED` 时才更新主题负偏好。这样 `RATE_LOW` 会立即改变下一轮的资源级结果，但不会错误污染长期研究兴趣。

### 14.2 反馈事务

反馈写入必须在一个MySQL事务中完成：

```text
1. 校验recommendation_item属于当前用户可访问记录。
2. 使用feedback_uuid或Idempotency-Key去重。
3. 对要求曝光关联的反馈，校验impression_uuid属于当前用户和当前recommendation_item。
4. 写recommendation_feedback，并保存经过校验的impression_uuid。
5. 写对应user_behavior_event，原样复制impression_uuid。
6. 更新user_resource_state。
7. 产生profile_delta或outbox任务。
8. 提交事务。
```

固定边界为：

```text
反馈事实 + 行为事件 + 用户资源状态 + profile_update_outbox
→ 在同一事务提交
→ 事务提交后尝试处理一次画像Outbox
→ 成功则返回APPLIED
→ 超时或失败则返回PENDING，由Worker重试
```

画像版本在独立事务中更新。画像失败不回滚已经提交的反馈事实。

Worker应用画像时，新的user_profile版本、兴趣/负偏好行、profile_change_log和Outbox的DONE状态必须在同一事务提交；利用 `source_event_id + source_type + formula_version` 唯一约束防止Worker崩溃重取后重复加权。

### 14.3 通用行为事件事务

独立行为接口不能绕过反馈接口的领域校验。`POST /behavior-events` 只接受：

```text
SEARCH
VIEW_RESOURCE
VIEW_EXPLANATION
CLICK_RECOMMENDATION
ACCESS_PAPER_FULLTEXT
```

`FAVORITE_RESOURCE`、`BORROW_BOOK`、`REJECT_RECOMMENDATION`、`NOT_INTERESTED` 和 `RATE_*` 只能由反馈事务派生，`RECOMMENDATION_IMPRESSION` 只能由曝光批量接口派生。对于配置中 `base_score != 0` 的合法行为，以下事实必须在同一MySQL事务提交：

```text
user_behavior_event + profile_update_outbox
```

`CLICK_RECOMMENDATION` 还要在同一事务更新对应 `recommendation_impression.clicked_at`；`ACCESS_PAPER_FULLTEXT` 必须先验证系统记录的合法全文访问。零分曝光和中性评分只保留审计事实，可以不创建画像Outbox。提交后复用反馈链路的同一Worker和幂等约束：同步处理成功返回 `APPLIED`，否则返回 `PENDING`，不得因画像暂时失败回滚已经提交的行为事实。

### 14.4 FeedbackLearningAgent职责

```text
解释反馈原因
确定影响范围：资源、主题、难度或会话
生成ProfileDeltaProposed
请求UserProfileAgent应用增量
记录画像更新前后版本
```

FeedbackLearningAgent不得直接覆盖整份画像。

### 14.5 反馈后的可观察变化

反馈接口返回：

```json
{
  "accepted": true,
  "feedback_id": "fb-uuid",
  "effect_status": "APPLIED",
  "effect": {
    "resource_suppressed_until": "2026-08-03T00:00:00Z",
    "changed_interest_tags": [],
    "changed_negative_tags": [
      {
        "tag": "传统编目",
        "before": 0.20,
        "after": 0.43
      }
    ],
    "reading_stage_change": null
  },
  "profile_version_before": 7,
  "profile_version_after": 8
}
```

下一轮推荐必须记录实际应用了哪些反馈，不得只显示“已调整”文本。

若反馈事实已经提交但画像更新进入Outbox：

```json
{
  "accepted": true,
  "feedback_id": "fb-uuid",
  "effect_status": "PENDING",
  "effect": null,
  "profile_version_before": 7,
  "profile_version_after": null
}
```

前端不能在 `PENDING` 时显示“画像已调整”。

### 14.6 反馈过期与恢复

```text
主题负偏好按对应事件半衰期自然衰减
NOT_NOW默认7天后失效
REPEATED默认30天后允许再次探索
用户主动搜索被抑制主题时，当前明确意图优先，但界面可提示历史偏好
```

这避免一次反馈永久封锁整个知识领域。

---

## 15. 数据模型

### 15.1 数据存储原则

```text
MySQL：唯一事实源
Chroma：可重建的向量派生索引
Neo4j：可重建的资源关系派生索引
```

推荐结果必须能够仅根据MySQL快照、配置版本和派生索引版本进行审计。时间统一保存为UTC `DATETIME(3)`，接口返回ISO 8601。

### 15.2 资源表

#### resource_catalog

```text
id BIGINT PK
resource_type VARCHAR(16) NOT NULL
external_id VARCHAR(128) NOT NULL
title VARCHAR(500) NOT NULL
authors_json JSON NOT NULL
abstract TEXT NULL
keywords_json JSON NULL
category_code VARCHAR(64) NULL
publication_year SMALLINT NULL
publication_date DATE NULL
publisher_or_source VARCHAR(500) NULL
language VARCHAR(16) NULL
difficulty_level TINYINT NULL
availability_status VARCHAR(24) NOT NULL
available_from DATETIME(3) NOT NULL
access_url VARCHAR(1000) NULL
metadata_quality DECIMAL(7,6) NOT NULL
is_classic BOOLEAN NOT NULL DEFAULT FALSE
metadata_version INT NOT NULL DEFAULT 1
created_at DATETIME(3) NOT NULL
updated_at DATETIME(3) NOT NULL

UNIQUE(resource_type, external_id)
INDEX(resource_type, publication_year)
INDEX(category_code)
INDEX(available_from)
```

#### resource_book_detail

```text
resource_id BIGINT PK/FK
isbn VARCHAR(32) NULL
call_number VARCHAR(128) NULL
location VARCHAR(255) NULL
borrowable_copies INT NOT NULL DEFAULT 0
```

#### resource_paper_detail

```text
resource_id BIGINT PK/FK
doi VARCHAR(255) NULL
journal_or_conference VARCHAR(500) NULL
open_access BOOLEAN NOT NULL DEFAULT FALSE
```

#### tag_dictionary

```text
id BIGINT PK
name VARCHAR(128) NOT NULL
normalized_name VARCHAR(128) NOT NULL
parent_id BIGINT NULL
UNIQUE(normalized_name)
```

#### resource_tag

```text
resource_id BIGINT FK
tag_id BIGINT FK
weight DECIMAL(7,6) NOT NULL
confidence DECIMAL(7,6) NOT NULL
source VARCHAR(24) NOT NULL
PRIMARY KEY(resource_id, tag_id, source)
INDEX(tag_id, weight)
```

同一资源标签可以有人工、规则和LLM等多个来源。所有推荐公式统一使用：

```text
effective_resource_tag_weight =
    max(weight × confidence)
    over (resource_id, tag_id)
```

其他来源行只作为证据保留，SQL聚合后再进入画像匹配、图谱同步和负偏好计算，禁止多行Join重复累计。

#### resource_index_state

```text
resource_id BIGINT PK/FK
content_hash CHAR(64) NOT NULL
embedding_id VARCHAR(128) NULL
embedding_version VARCHAR(64) NULL
embedding_status VARCHAR(16) NOT NULL
graph_version VARCHAR(64) NULL
graph_status VARCHAR(16) NOT NULL
last_indexed_at DATETIME(3) NULL
last_error VARCHAR(1000) NULL
```

`embedding_status` 和 `graph_status` 独立使用：

```text
PENDING：等待首次构建
READY：当前内容哈希和版本可用
STALE：资源内容、模型或图版本已经变化
FAILED：最近一次构建失败
SKIPPED：该资源不适用于此索引
```

内容哈希或索引版本变化时先置 `STALE` 并写Outbox，成功后才能置 `READY`。

#### resource_popularity_snapshot

热门召回和 `popularity_score` 的离线落点：

```text
resource_id BIGINT
cutoff_at DATETIME(3)
window_days SMALLINT NOT NULL
valid_view_count INT NOT NULL
recommendation_click_count INT NOT NULL
favorite_count INT NOT NULL
borrow_or_access_count INT NOT NULL
popularity_raw DECIMAL(14,6) NOT NULL
type_p95_raw DECIMAL(14,6) NOT NULL
popularity_score DECIMAL(7,6) NOT NULL
formula_version VARCHAR(64) NOT NULL
dataset_version VARCHAR(64) NOT NULL
created_at DATETIME(3) NOT NULL
PRIMARY KEY(resource_id, cutoff_at, window_days, formula_version, dataset_version)
INDEX(cutoff_at, popularity_score)
```

`PopularityJob` 在明确的UTC `cutoff_at` 按资源类型分别计算P95，只聚合 `occurred_at <= cutoff_at` 的事件；作业实际运行时间晚于cutoff不改变数据边界。TRENDING通道读取满足 `cutoff_at <= evaluation_at` 且 `window_days/formula_version/dataset_version` 与任务Bundle一致的最大cutoff；没有符合快照时返回 `SKIPPED`，不得读取未来数据、使用同日未来事件或在线扫描全量行为表。

### 15.3 行为与画像表

#### user_behavior_event

```text
id BIGINT PK
event_uuid CHAR(36) NOT NULL
user_id BIGINT NOT NULL
session_id CHAR(36) NOT NULL
task_id CHAR(36) NULL
event_type VARCHAR(40) NOT NULL
resource_id BIGINT NULL
recommendation_item_id BIGINT NULL
impression_uuid CHAR(36) NULL
query_text VARCHAR(1000) NULL
rating DECIMAL(2,1) NULL
dwell_ms INT NULL
visible_ratio DECIMAL(4,3) NULL
position SMALLINT NULL
reason_code VARCHAR(40) NULL
tag_evidence_json JSON NULL
occurred_at DATETIME(3) NOT NULL
created_at DATETIME(3) NOT NULL

UNIQUE(event_uuid)
INDEX(user_id, occurred_at)
INDEX(task_id)
INDEX(impression_uuid)
```

行为事件只追加，不原地修改。

`CLICK_RECOMMENDATION` 必须携带产生点击的 `impression_uuid`。后端在写入点击事件的同时更新对应曝光的 `clicked_at`；找不到曝光时仍可记录点击，但写入 `ORPHAN_CLICK_WARNING`，且不能用它清除其他曝光的惩罚。

#### user_declared_profile

用户主动提供且可以自行修改的冷启动信息：

```text
user_id BIGINT PK
declared_version INT NOT NULL
major VARCHAR(128) NULL
grade VARCHAR(32) NULL
research_direction VARCHAR(255) NULL
preferred_language VARCHAR(32) NULL
personalization_enabled BOOLEAN NOT NULL DEFAULT TRUE
updated_at DATETIME(3) NOT NULL
```

`metadata_completeness` 的四个字段固定为 `major`、`grade`、`research_direction` 和 `preferred_language`。`personalization_enabled=false` 时不读取长期行为画像，只使用当前会话和明确输入。

每次修改当前表时，还必须在同一事务追加 `user_declared_profile_history`：

```text
id BIGINT PK
user_id BIGINT NOT NULL
declared_version INT NOT NULL
major VARCHAR(128) NULL
grade VARCHAR(32) NULL
research_direction VARCHAR(255) NULL
preferred_language VARCHAR(32) NULL
personalization_enabled BOOLEAN NOT NULL
valid_from DATETIME(3) NOT NULL
created_at DATETIME(3) NOT NULL
UNIQUE(user_id, declared_version)
INDEX(user_id, valid_from)
```

历史实验选择 `valid_from <= evaluation_at` 的最高版本；不存在时使用空声明画像。当前表只是最新版本缓存，不能代替历史查询。

#### user_profile

```text
user_id BIGINT PK
profile_version INT NOT NULL
profile_confidence DECIMAL(7,6) NOT NULL
recent_focus_tag_id BIGINT NULL
topic_focus_strength DECIMAL(7,6) NOT NULL
reading_stage VARCHAR(16) NULL
reading_stage_confidence DECIMAL(7,6) NOT NULL
updated_at DATETIME(3) NOT NULL
```

#### user_interest_tag

```text
user_id BIGINT
tag_id BIGINT
positive_weight DECIMAL(7,6) NOT NULL
raw_positive_signal DECIMAL(12,6) NOT NULL
source_count INT NOT NULL
last_event_at DATETIME(3) NOT NULL
profile_version INT NOT NULL
PRIMARY KEY(user_id, tag_id)
```

#### user_negative_preference

```text
user_id BIGINT
tag_id BIGINT
reason_code VARCHAR(40)
negative_weight DECIMAL(7,6) NOT NULL
raw_negative_signal DECIMAL(12,6) NOT NULL
source_count INT NOT NULL
expires_at DATETIME(3) NULL
last_event_at DATETIME(3) NOT NULL
profile_version INT NOT NULL
PRIMARY KEY(user_id, tag_id, reason_code)
```

#### user_resource_state

```text
user_id BIGINT
resource_id BIGINT
state_type VARCHAR(32) NOT NULL
suppress_until DATETIME(3) NULL
source_event_id BIGINT NOT NULL
last_feedback_at DATETIME(3) NOT NULL
PRIMARY KEY(user_id, resource_id, state_type)
```

允许同一资源同时具有多个状态：

```text
READ
FAVORITED
BORROWED
HIDDEN
NOT_NOW
DUPLICATE_SUPPRESS
```

`NOT_NOW` 默认7天失效，`DUPLICATE_SUPPRESS` 默认30天失效；`READ/FAVORITED/BORROWED` 无自动失效。过滤器只读取尚未过期的状态。

### 15.4 任务与Agent日志表

#### recommendation_task

```text
id CHAR(36) PK
request_id CHAR(36) NOT NULL
trace_id CHAR(36) NOT NULL
user_id BIGINT NOT NULL
session_id CHAR(36) NOT NULL
trigger_scene VARCHAR(32) NOT NULL
input_text TEXT NULL
request_json JSON NOT NULL
intent_type VARCHAR(48) NULL
intent_confidence DECIMAL(7,6) NULL
status VARCHAR(32) NOT NULL
context_version INT NOT NULL DEFAULT 1
profile_version INT NULL
config_bundle_version VARCHAR(64) NOT NULL
policy_version VARCHAR(64) NOT NULL
ranking_version VARCHAR(64) NOT NULL
behavior_formula_version VARCHAR(64) NOT NULL
embedding_version VARCHAR(64) NULL
graph_version VARCHAR(64) NULL
prompt_version VARCHAR(64) NULL
dataset_version VARCHAR(64) NOT NULL
replan_count TINYINT NOT NULL DEFAULT 0
evaluation_at DATETIME(3) NOT NULL
started_at DATETIME(3) NOT NULL
finished_at DATETIME(3) NULL
error_code VARCHAR(64) NULL

UNIQUE(request_id)
INDEX(user_id, started_at)
```

`status` 只允许：

```text
CREATED
UNDERSTANDING
PROBING
DECIDING
WAITING_CLARIFICATION
RECALLING
RANKING
REPLANNING
EXPLAINING
PERSISTING
COMPLETED
DEGRADED_COMPLETED
FAILED
```

#### recommendation_clarification

保存引导问题和用户补充信息：

```text
id BIGINT PK
task_id CHAR(36) NOT NULL
context_version INT NOT NULL
questions_json JSON NOT NULL
answers_json JSON NULL
asked_at DATETIME(3) NOT NULL
answered_at DATETIME(3) NULL
UNIQUE(task_id, context_version)
```

收到回答后新增上下文版本，不覆盖原请求和原问题。

#### recommendation_context_snapshot

```text
id BIGINT PK
task_id CHAR(36) NOT NULL
context_version INT NOT NULL
snapshot_stage VARCHAR(16) NOT NULL
profile_confidence DECIMAL(7,6) NOT NULL
interest_strength DECIMAL(7,6) NOT NULL
topic_focus_strength DECIMAL(7,6) NOT NULL
resource_match_score DECIMAL(7,6) NOT NULL
usable_candidate_count INT NOT NULL
covered_difficulty_levels TINYINT NOT NULL
metadata_coverage DECIMAL(7,6) NOT NULL
evidence_confidence DECIMAL(7,6) NOT NULL
pipeline_health DECIMAL(7,6) NOT NULL
subtopic_group_count INT NOT NULL
recent_negative_feedback_count INT NOT NULL
applied_negative_preference_count INT NOT NULL
recall_channel_count INT NOT NULL
vector_coverage DECIMAL(7,6) NOT NULL
kg_path_coverage DECIMAL(7,6) NOT NULL
feedback_accept_rate DECIMAL(7,6) NULL
reject_rate DECIMAL(7,6) NULL
required_slots_json JSON NULL
dependency_status_json JSON NOT NULL
metric_detail_json JSON NOT NULL
config_hash CHAR(64) NOT NULL
created_at DATETIME(3) NOT NULL

UNIQUE(task_id, context_version, snapshot_stage)
```

`PRE_PLAN` 快照用于证明策略依据，`POST_RANK` 快照用于记录实际候选质量，不能用排序后的证据反向解释先前策略。

#### recommendation_policy_decision

```text
id BIGINT PK
task_id CHAR(36) NOT NULL
decision_no TINYINT NOT NULL DEFAULT 1
context_version INT NOT NULL
plan_version TINYINT NULL
output_type VARCHAR(32) NOT NULL
delivery_strategy VARCHAR(24) NOT NULL
explanation_level VARCHAR(24) NOT NULL
adaptation_state VARCHAR(24) NOT NULL
decision_reason_codes_json JSON NOT NULL
decision_reason VARCHAR(1000) NOT NULL
degraded_components_json JSON NULL
policy_version VARCHAR(64) NOT NULL
created_at DATETIME(3) NOT NULL

UNIQUE(task_id, decision_no)
```

#### agent_message_log

```text
message_id CHAR(36) PK
task_id CHAR(36) NOT NULL
trace_id CHAR(36) NOT NULL
causation_id CHAR(36) NULL
sender VARCHAR(64) NOT NULL
receiver VARCHAR(64) NOT NULL
message_type VARCHAR(48) NOT NULL
schema_version VARCHAR(16) NOT NULL
payload_ref VARCHAR(255) NULL
deadline_at DATETIME(3) NOT NULL
attempt TINYINT NOT NULL
idempotency_key VARCHAR(255) NOT NULL
context_version INT NOT NULL
status VARCHAR(16) NOT NULL
created_at DATETIME(3) NOT NULL
INDEX(task_id, created_at)
UNIQUE(idempotency_key, attempt)
```

#### agent_execution_log

```text
id BIGINT PK
result_id CHAR(36) NOT NULL
input_message_id CHAR(36) NOT NULL
task_id CHAR(36) NOT NULL
trace_id CHAR(36) NOT NULL
step_no SMALLINT NOT NULL
agent_name VARCHAR(64) NOT NULL
agent_version VARCHAR(64) NOT NULL
status VARCHAR(16) NOT NULL
confidence DECIMAL(7,6) NOT NULL
fallback_used BOOLEAN NOT NULL
input_digest CHAR(64) NOT NULL
tool_calls_json JSON NULL
output_ref VARCHAR(255) NULL
warnings_json JSON NULL
error_code VARCHAR(64) NULL
started_at DATETIME(3) NOT NULL
finished_at DATETIME(3) NOT NULL
duration_ms INT NOT NULL
UNIQUE(task_id, step_no)
UNIQUE(result_id)
INDEX(task_id, started_at)
```

#### agent_artifact

较大的画像快照、探测结果、候选集和排序结果使用Artifact保存，消息日志只引用ID：

```text
id CHAR(36) PK
task_id CHAR(36) NOT NULL
artifact_type VARCHAR(40) NOT NULL
schema_version VARCHAR(16) NOT NULL
content_json JSON NOT NULL
content_hash CHAR(64) NOT NULL
created_at DATETIME(3) NOT NULL
INDEX(task_id, artifact_type)
```

#### recommendation_channel_run

```text
id BIGINT PK
task_id CHAR(36) NOT NULL
phase VARCHAR(8) NOT NULL
plan_version TINYINT NOT NULL
channel VARCHAR(24) NOT NULL
status VARCHAR(16) NOT NULL
latency_ms INT NOT NULL
candidate_count INT NOT NULL
timeout_ms INT NOT NULL
error_code VARCHAR(64) NULL
created_at DATETIME(3) NOT NULL
UNIQUE(task_id, phase, plan_version, channel)
```

`status` 枚举：

```text
SUCCESS：查询成功且有候选
SUCCESS_EMPTY：查询成功但无候选
TIMEOUT：超时
FAILED：调用失败
SKIPPED：通道不适用、熔断或版本不匹配
```

RRF只把 `SUCCESS` 和 `SUCCESS_EMPTY` 视为健康通道；后三种移除权重。`SUCCESS_EMPTY` 不贡献资源，但保留其权重状态用于说明“查询成功但无匹配”，随后对实际健康通道权重归一化。

### 15.5 候选、结果、曝光与反馈

#### recommendation_candidate

```text
task_id CHAR(36)
plan_version TINYINT
resource_id BIGINT
channel VARCHAR(24)
channel_rank INT NOT NULL
raw_score DECIMAL(12,6) NULL
normalized_score DECIMAL(7,6) NULL
rrf_contribution DECIMAL(12,8) NOT NULL
evidence_json JSON NULL
created_at DATETIME(3) NOT NULL
PRIMARY KEY(task_id, plan_version, resource_id, channel)
```

#### recommendation_record

```text
id BIGINT PK
task_id CHAR(36) NOT NULL
user_id BIGINT NOT NULL
context_version INT NOT NULL
decision_id BIGINT NOT NULL
plan_version TINYINT NOT NULL
output_type VARCHAR(32) NOT NULL
delivery_strategy VARCHAR(24) NOT NULL
ranking_version VARCHAR(64) NOT NULL
created_at DATETIME(3) NOT NULL
UNIQUE(task_id)
```

#### recommendation_group

书单和阅读路径分组：

```text
id BIGINT PK
record_id BIGINT NOT NULL
group_type VARCHAR(24) NOT NULL
group_key VARCHAR(64) NOT NULL
title VARCHAR(255) NOT NULL
goal VARCHAR(500) NULL
order_no SMALLINT NOT NULL
UNIQUE(record_id, order_no)
```

#### recommendation_item

```text
id BIGINT PK
record_id BIGINT NOT NULL
group_id BIGINT NULL
resource_id BIGINT NOT NULL
rank_no SMALLINT NOT NULL
group_order_no SMALLINT NULL
relevance_score DECIMAL(7,6) NOT NULL
final_score DECIMAL(7,6) NOT NULL
mmr_score DECIMAL(9,8) NULL
profile_score DECIMAL(7,6) NULL
semantic_score DECIMAL(7,6) NULL
kg_score DECIMAL(7,6) NULL
intent_score DECIMAL(7,6) NULL
feedback_score DECIMAL(7,6) NULL
popularity_score DECIMAL(7,6) NULL
freshness_score DECIMAL(7,6) NULL
recall_fusion_score DECIMAL(7,6) NOT NULL
metadata_quality DECIMAL(7,6) NOT NULL
exposure_penalty DECIMAL(7,6) NOT NULL
negative_penalty DECIMAL(7,6) NOT NULL
evidence_confidence DECIMAL(7,6) NOT NULL
selection_reason_codes_json JSON NOT NULL
diversity_relaxed BOOLEAN NOT NULL DEFAULT FALSE
reason_evidence_json JSON NOT NULL
created_at DATETIME(3) NOT NULL

UNIQUE(record_id, resource_id)
UNIQUE(record_id, rank_no)
```

#### recommendation_item_explanation

保存当时实际返回的解释，而不是后续临时重新生成：

```text
id BIGINT PK
recommendation_item_id BIGINT NOT NULL
explanation_version INT NOT NULL
regenerated_from_id BIGINT NULL
explanation_text TEXT NOT NULL
effective_explanation_level VARCHAR(24) NOT NULL
provider VARCHAR(32) NOT NULL
model_version VARCHAR(64) NOT NULL
prompt_version VARCHAR(64) NOT NULL
evidence_refs_json JSON NOT NULL
validator_status VARCHAR(24) NOT NULL
created_at DATETIME(3) NOT NULL
UNIQUE(recommendation_item_id, explanation_version)
```

`persist_final_result_and_status()` 将解释Artifact、版本1解释和推荐结果在同一事务持久化。解释GET接口默认读取持久化版本1或用户指定版本；只有管理员显式请求重新生成时才创建递增版本并填写 `regenerated_from_id`，不能静默改写历史解释。

#### recommendation_impression

```text
id BIGINT PK
impression_uuid CHAR(36) NOT NULL
recommendation_item_id BIGINT NOT NULL
user_id BIGINT NOT NULL
position SMALLINT NOT NULL
rendered_at DATETIME(3) NOT NULL
visible_started_at DATETIME(3) NULL
visible_ms INT NOT NULL DEFAULT 0
max_visible_ratio DECIMAL(4,3) NOT NULL DEFAULT 0
is_valid_exposure BOOLEAN NOT NULL DEFAULT FALSE
clicked_at DATETIME(3) NULL
UNIQUE(impression_uuid)
INDEX(user_id, rendered_at)
```

#### recommendation_feedback

```text
id BIGINT PK
feedback_uuid CHAR(36) NOT NULL
recommendation_item_id BIGINT NOT NULL
user_id BIGINT NOT NULL
impression_uuid CHAR(36) NULL
feedback_type VARCHAR(32) NOT NULL
reason_code VARCHAR(40) NULL
rating DECIMAL(2,1) NULL
content VARCHAR(1000) NULL
created_at DATETIME(3) NOT NULL
UNIQUE(feedback_uuid)
INDEX(impression_uuid)
```

`impression_uuid` 不通过“最近一次曝光”猜测。对于要求曝光关联的反馈，它必须指向 `recommendation_impression` 中相同 `user_id` 和 `recommendation_item_id` 的行；这样负反馈、评分、曝光惩罚和画像变化才可审计。

#### profile_change_log

```text
id BIGINT PK
user_id BIGINT NOT NULL
source_event_id BIGINT NOT NULL
source_type VARCHAR(32) NOT NULL
profile_version_before INT NOT NULL
profile_version_after INT NOT NULL
delta_json JSON NOT NULL
formula_version VARCHAR(64) NOT NULL
created_at DATETIME(3) NOT NULL
UNIQUE(source_event_id, source_type, formula_version)
```

### 15.6 配置与派生索引同步

#### recommendation_config_version

```text
config_bundle_version VARCHAR(64) PK
policy_version VARCHAR(64) NOT NULL
ranking_version VARCHAR(64) NOT NULL
behavior_formula_version VARCHAR(64) NOT NULL
prompt_version VARCHAR(64) NOT NULL
bundle_json JSON NOT NULL
config_hash CHAR(64) NOT NULL
status VARCHAR(16) NOT NULL
created_at DATETIME(3) NOT NULL
```

同一时刻只有一个 `ACTIVE` 版本。

#### resource_index_outbox

```text
id BIGINT PK
resource_id BIGINT NOT NULL
target VARCHAR(16) NOT NULL
operation VARCHAR(16) NOT NULL
metadata_version INT NOT NULL
status VARCHAR(16) NOT NULL
attempts INT NOT NULL DEFAULT 0
next_retry_at DATETIME(3) NULL
locked_at DATETIME(3) NULL
locked_by VARCHAR(64) NULL
last_error VARCHAR(1000) NULL
created_at DATETIME(3) NOT NULL
updated_at DATETIME(3) NOT NULL
UNIQUE(resource_id, target, operation, metadata_version)
```

Chroma和Neo4j索引失败不回滚MySQL资源写入；Outbox负责重试和全量重建。

#### profile_update_outbox

任一非零画像行为或反馈事实提交成功后，用于可靠触发增量画像更新：

```text
id BIGINT PK
user_id BIGINT NOT NULL
source_event_id BIGINT NOT NULL
source_type VARCHAR(32) NOT NULL
payload_json JSON NOT NULL
status VARCHAR(16) NOT NULL
attempts INT NOT NULL DEFAULT 0
next_retry_at DATETIME(3) NULL
locked_at DATETIME(3) NULL
locked_by VARCHAR(64) NULL
last_error VARCHAR(1000) NULL
created_at DATETIME(3) NOT NULL
updated_at DATETIME(3) NOT NULL
UNIQUE(source_event_id, source_type)
```

两个Outbox的 `status` 均只允许：

```text
PENDING
PROCESSING
DONE
DEAD
```

资源索引Outbox额外冻结：

```text
target：VECTOR | GRAPH
operation：UPSERT | DELETE | REBUILD
```

### 15.7 数据库约束

```text
所有[0,1]分数使用CHECK约束
所有外键必须明确ON DELETE行为
反馈、行为和曝光使用UUID幂等
JSON字段只保存可变详情，查询和关联字段必须独立成列
所有枚举在Python和数据库迁移中保持一致
生产或论文实验数据禁止物理删除行为事件
```

---

## 16. 接口设计

### 16.1 接口原则

```text
统一前缀：/api/v1
统一推荐入口，不为图书、论文、书单、路径复制四套流程
user_id在正式环境从认证上下文读取
演示环境允许X-Demo-User-Id
写接口支持Idempotency-Key
调试接口只在ENABLE_DEBUG_API=true时启用
```

### 16.2 健康检查

```text
GET /api/v1/health/live
GET /api/v1/health/ready
```

`ready` 示例：

```json
{
  "status": "DEGRADED",
  "components": {
    "mysql": "UP",
    "chroma": "UP",
    "neo4j": "DOWN",
    "llm": "MOCK"
  },
  "can_recommend": true
}
```

### 16.3 创建推荐任务

```text
POST /api/v1/recommendation-tasks
```

请求：

```json
{
  "request_id": "uuid",
  "user_id": 1,
  "session_id": "uuid",
  "scene": "SEARCH_AFTER",
  "input_text": "我想系统学习多智能体推荐",
  "requested_resource_types": ["BOOK", "PAPER"],
  "requested_output_type": null,
  "source_resource_id": null,
  "source_item_id": null,
  "as_of_time": null,
  "constraints": {
    "year_from": 2020,
    "language": "zh-CN"
  },
  "limit": 10
}
```

`requested_output_type`存在时视为用户明确选择，优先级高于文本推断。

普通请求的 `as_of_time` 必须为空，由服务器固定为任务创建时刻；只有测试和论文实验权限可以指定。画像衰减、新鲜度和统计窗口全部读取任务的 `evaluation_at`，不得在同一任务中多次调用系统当前时间。

`limit` 必须位于1至 `limits.max_final_items`，默认读取Bundle的 `limits.default_final_items`：

```text
PERSONALIZED_FEED/TOPIC_RESOURCES：
effective_limit = min(request.limit或默认值, limits.max_final_items)

显式BOOKLIST：
limit < limits.min_items_by_output.BOOKLIST时返回422 LIMIT_TOO_SMALL_FOR_BOOKLIST

显式READING_PATH：
limit < limits.min_items_by_output.READING_PATH时返回422 LIMIT_TOO_SMALL_FOR_READING_PATH

系统自动推断组合输出但用户limit小于结构最小数：
不自动切换为该组合输出，保持TOPIC_RESOURCES
```

`effective_limit` 写入 `RecommendationRequestSnapshot`。资源配额、MMR选择数量和最终API响应均使用同一个值；召回通道Top-K是候选池预算，不等于最终limit。

直接结果：

```json
{
  "task_id": "uuid",
  "record_id": 21,
  "trace_id": "uuid",
  "status": "COMPLETED",
  "decision": {
    "output_type": "READING_PATH",
    "delivery_strategy": "DIRECT",
    "explanation_level": "EVIDENCE",
    "adaptation_state": "NORMAL",
    "decision_reason_codes": [
      "EXPLICIT_LEARNING_INTENT",
      "SUFFICIENT_RESOURCE_COVERAGE"
    ]
  },
  "groups": [],
  "items": [],
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

引导结果：

```json
{
  "task_id": "uuid",
  "status": "WAITING_CLARIFICATION",
  "decision": {
    "output_type": "PERSONALIZED_FEED",
    "delivery_strategy": "GUIDED",
    "explanation_level": "LIMITED",
    "adaptation_state": "NORMAL"
  },
  "questions": [
    {
      "slot": "resource_types",
      "question": "你更需要图书、论文，还是两者都需要？",
      "options": ["BOOK", "PAPER", "BOOK_AND_PAPER"]
    },
    {
      "slot": "output_type",
      "question": "你希望得到普通资源列表、专题书单，还是系统学习路径？",
      "options": ["TOPIC_RESOURCES", "BOOKLIST", "READING_PATH"]
    },
    {
      "slot": "topic",
      "question": "你主要关注哪个主题？",
      "options": ["多智能体", "推荐系统", "知识图谱"]
    }
  ]
}
```

### 16.4 补充澄清信息

```text
POST /api/v1/recommendation-tasks/{task_id}/clarifications
```

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

必须继续原任务并增加 `context_version`，不能创建一个无法关联的新任务。提交过期版本返回 `409 STALE_CONTEXT_VERSION`；相同幂等键重复提交返回已生成的新版本。

### 16.5 查询任务和记录

```text
GET /api/v1/recommendation-tasks/{task_id}
GET /api/v1/recommendation-records/{record_id}
GET /api/v1/recommendation-items/{item_id}/explanation?include_scores=false
```

解释接口默认返回自然语言和结构化证据，不向普通用户暴露内部数值评分。只有研究管理员可以设置 `include_scores=true`，此时响应才包含 `final_score` 和特征分解；Debug接口保持研究管理员专用。无权限请求评分返回 `403 SCORE_VIEW_FORBIDDEN`，不能悄悄忽略参数造成实验误判。

### 16.6 曝光上报

```text
POST /api/v1/recommendation-impressions/batch
```

```json
{
  "impressions": [
    {
      "impression_uuid": "uuid",
      "recommendation_item_id": 101,
      "position": 1,
      "rendered_at": "2026-07-27T10:00:00Z",
      "visible_started_at": "2026-07-27T10:00:01Z",
      "visible_ms": 2500,
      "max_visible_ratio": 0.92
    }
  ]
}
```

后端根据可视比例和时长计算 `is_valid_exposure`，不信任前端直接提交布尔值。

每条上报在同一事务中写入：

```text
recommendation_impression
user_behavior_event(event_type=RECOMMENDATION_IMPRESSION, event_uuid=impression_uuid)
```

无论是否达到有效曝光门槛都保存事实和零分行为事件，`is_valid_exposure` 决定是否进入曝光惩罚统计。`visible_ms>0` 时必须提交 `visible_started_at`；否则该字段为空。

### 16.7 反馈

```text
POST /api/v1/recommendation-items/{item_id}/feedback
```

```json
{
  "feedback_uuid": "uuid",
  "impression_uuid": "uuid",
  "feedback_type": "NOT_INTERESTED",
  "reason_code": "TOPIC_NOT_INTERESTED",
  "rating": null,
  "content": null
}
```

### 16.8 行为、画像与调试

```text
POST /api/v1/behavior-events
GET  /api/v1/profiles/{user_id}
POST /api/v1/profiles/{user_id}/refresh
GET  /api/v1/debug/tasks/{task_id}/context
GET  /api/v1/debug/tasks/{task_id}/trace
GET  /api/v1/debug/tasks/{task_id}/policy-decision
```

画像和调试接口在正式环境需要用户本人或研究管理员权限。

点击行为示例：

```json
{
  "event_uuid": "uuid",
  "session_id": "uuid",
  "event_type": "CLICK_RECOMMENDATION",
  "resource_id": 11,
  "recommendation_item_id": 101,
  "impression_uuid": "uuid",
  "occurred_at": "2026-07-27T10:00:03Z"
}
```

该接口按14.3节执行事件与画像Outbox的原子写入，响应包含 `profile_update_status=APPLIED|PENDING`。相同 `event_uuid` 重放返回第一次提交的事件与处理状态，不创建第二条Outbox；派生型事件或缺少必需关联字段时返回422。

---

## 17. 前端设计

### 17.1 页面

```text
/recommendations                  推荐主页
/recommendations/tasks/:taskId    推荐任务与澄清
/recommendations/records/:id      书单或阅读路径详情
/recommendations/history          历史推荐与反馈
/recommendations/debug/:taskId    论文演示调试页
/profile                          用户可见画像与偏好管理
```

### 17.2 推荐主页

页面根据四维决策分别渲染：

```text
output_type决定主组件
delivery_strategy决定结果、追问或降级提示
explanation_level决定可展开的证据内容
adaptation_state决定是否显示“已根据近期反馈调整”
```

不得根据一个 `interaction_mode` 在前端写大型条件分支。

组件建议：

```text
RecommendationHeader
DecisionBanner
GuidedQuestionPanel
DegradedNotice
ResourceCard
TopicResourceList
BooklistGroups
ReadingPathTimeline
ExplanationDrawer
FeedbackDialog
AgentTracePanel
ProfileChangePanel
```

### 17.3 推荐卡片

必须展示：

```text
题名
作者
资源类型
年份
可访问或馆藏状态
一句推荐理由
查看证据
收藏/借阅或访问入口
不感兴趣入口
```

推荐分数默认不直接显示给普通用户，但在调试页显示。

### 17.4 曝光采集

使用 `IntersectionObserver`：

```text
threshold >= 0.5
连续可视达到1000ms后提交
页面卸载前批量提交未发送事件
每次卡片展示生成唯一impression_uuid
```

后端重新计算是否为有效曝光，前端不能直接指定 `is_valid_exposure=true`。

### 17.5 引导式交互

澄清问题必须是推荐任务槽位，不扩展为通用问答：

```text
topic：关注主题
resource_types：BOOK、PAPER或BOOK_AND_PAPER
output_type：TOPIC_RESOURCES、BOOKLIST或READING_PATH
learning_stage：入门、进阶或研究
time_scope：年份范围
language：语言
```

回答后调用原 `task_id` 的 clarifications 接口。

### 17.6 推荐调试页

调试页是论文演示的重要组成，应展示：

```text
任务状态机
Agent消息和执行时间轴
PRE_PLAN上下文快照
四维交互决策及原因代码
各召回通道状态和候选数量
RRF融合贡献
最终评分明细和MMR顺序
解释证据引用
降级组件
反馈前后画像版本与标签变化
配置、嵌入、提示词和算法版本
```

调试页不得在生产配置中公开。

### 17.7 前后端连接

```dotenv
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

开发环境也可以由Vite Proxy把 `/api` 转发到后端。FastAPI CORS必须使用配置中的明确Origin白名单，不允许在携带认证信息时配置通配符 `*`。Compose环境由前端反向代理访问backend服务，浏览器不直接使用Docker服务名。

---

## 18. 后端与前端目录结构

```text
RecPro/
├── README.md
├── Makefile
├── compose.yaml
├── .env.example
├── docs/
│   ├── LibraMAS_纯推荐模块实施文档_可运行版.md
│   ├── api.md
│   ├── data_dictionary.md
│   ├── experiment_protocol.md
│   └── thesis_demo_script.md
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── requirements.lock
│   ├── alembic.ini
│   ├── alembic/
│   │   └── versions/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   │   └── v1/
│   │   │       ├── health.py
│   │   │       ├── behaviors.py
│   │   │       ├── recommendations.py
│   │   │       ├── feedback.py
│   │   │       ├── profiles.py
│   │   │       └── debug.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   ├── errors.py
│   │   │   ├── logging.py
│   │   │   └── telemetry.py
│   │   ├── db/
│   │   │   ├── models/
│   │   │   ├── session.py
│   │   │   └── unit_of_work.py
│   │   ├── domain/
│   │   │   ├── enums.py
│   │   │   ├── entities.py
│   │   │   ├── agent_messages.py
│   │   │   ├── recommendation_state.py
│   │   │   └── policy_models.py
│   │   ├── agents/
│   │   │   ├── base.py
│   │   │   ├── registry.py
│   │   │   ├── orchestrator.py
│   │   │   ├── intent_understanding_agent.py
│   │   │   ├── user_profile_agent.py
│   │   │   ├── resource_semantic_agent.py
│   │   │   ├── recommendation_policy_agent.py
│   │   │   ├── candidate_recall_agent.py
│   │   │   ├── ranking_agent.py
│   │   │   ├── explanation_agent.py
│   │   │   └── feedback_learning_agent.py
│   │   ├── services/
│   │   │   ├── behavior_service.py
│   │   │   ├── profile_service.py
│   │   │   ├── intent_service.py
│   │   │   ├── probe_service.py
│   │   │   ├── recall_service.py
│   │   │   ├── scoring_service.py
│   │   │   ├── mmr_service.py
│   │   │   ├── policy_engine.py
│   │   │   ├── evidence_service.py
│   │   │   └── feedback_service.py
│   │   ├── tools/
│   │   │   ├── keyword_search.py
│   │   │   ├── profile_search.py
│   │   │   ├── vector_search.py
│   │   │   ├── graph_search.py
│   │   │   └── popularity_search.py
│   │   ├── providers/
│   │   │   ├── llm/
│   │   │   │   ├── base.py
│   │   │   │   ├── mock.py
│   │   │   │   └── external.py
│   │   │   └── embedding/
│   │   │       ├── base.py
│   │   │       └── local.py
│   │   ├── repositories/
│   │   │   ├── behavior_repository.py
│   │   │   ├── profile_repository.py
│   │   │   ├── resource_repository.py
│   │   │   ├── task_repository.py
│   │   │   └── recommendation_repository.py
│   │   ├── infrastructure/
│   │   │   ├── mysql.py
│   │   │   ├── chroma.py
│   │   │   ├── neo4j.py
│   │   │   └── circuit_breaker.py
│   │   ├── jobs/
│   │   │   ├── resource_index_job.py
│   │   │   ├── profile_rebuild_job.py
│   │   │   ├── popularity_job.py
│   │   │   └── outbox_worker.py
│   │   ├── worker.py
│   │   └── configs/
│   │       ├── policy-v1.yaml
│   │       ├── ranking-v1.yaml
│   │       └── behavior-v1.yaml
│   └── tests/
│       ├── unit/
│       ├── contract/
│       ├── integration/
│       ├── e2e/
│       ├── fault_injection/
│       ├── performance/
│       └── fixtures/
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── package-lock.json
│   ├── vite.config.ts
│   ├── playwright.config.ts
│   ├── e2e/
│   └── src/
│       ├── api/
│       ├── components/
│       ├── views/
│       ├── stores/
│       ├── router/
│       ├── types/
│       └── tests/
├── scripts/
│   ├── bootstrap.sh
│   ├── seed_demo_data.py
│   ├── build_vector_index.py
│   ├── build_knowledge_graph.py
│   ├── smoke_test.py
│   ├── export_experiment.py
│   ├── prepare_evaluation_split.py
│   ├── run_experiment.py
│   ├── evaluate_results.py
│   └── build_experiment_report.py
├── data/
│   ├── raw/
│   ├── processed/
│   ├── demo/
│   └── evaluation/
└── experiments/
    ├── configs/
    ├── baselines/
    ├── ablations/
    ├── metrics/
    ├── runs/
    └── reports/
```

### 18.1 依赖方向

```text
api → agents → services → repositories/infrastructure
agents → domain
services → domain
repositories/infrastructure → domain interfaces
domain不依赖FastAPI、SQLAlchemy、Chroma或Neo4j
```

Agent 之间不直接导入对方实例，通过 AgentRegistry 和 Orchestrator 发送结构化消息。

---

## 19. 配置与版本管理

### 19.1 必须版本化

```text
policy_version
ranking_version
behavior_formula_version
embedding_version
graph_version
prompt_version
agent_version
dataset_version
```

每个任务固定使用创建时的版本；任务执行中配置更新不影响已开始任务。

唯一事实源为 `recommendation_config_version` 中的 `config_bundle_version`。仓库内 YAML/JSON 是用于迁移和初始化该配置的源文件，运行时不同时读取多套配置。启动时：

```text
读取CONFIG_BUNDLE_VERSION
→ 从MySQL加载对应bundle
→ 校验config_hash和所有子版本
→ 缓存为不可变运行配置
→ recommendation_task同时保存bundle和子版本
```

环境变量只选择版本，不直接覆盖权重和阈值；测试如需覆盖，必须创建独立测试bundle。

### 19.2 默认算法配置

```json
{
  "config_bundle_version": "rec-1.0.0",
  "sub_versions": {
    "policy": "policy-v1",
    "ranking": "ranking-v1",
    "behavior_formula": "behavior-v1",
    "prompt": "prompt-v1"
  },
  "probe": {
    "per_channel_k": 10,
    "metadata_min": 0.40
  },
  "limits": {
    "default_final_items": 10,
    "max_final_items": 20,
    "hydration_candidate_limit": 200,
    "min_items_by_output": {
      "PERSONALIZED_FEED": 5,
      "TOPIC_RESOURCES": 5,
      "BOOKLIST": 8,
      "READING_PATH": 6
    }
  },
  "policy": {
    "profile_guided_threshold": 0.45,
    "topic_focus_infer_threshold": 0.65,
    "evidence_degraded_threshold": 0.35,
    "evidence_detailed_threshold": 0.65,
    "item_evidence_summary_threshold": 0.35,
    "item_evidence_detailed_threshold": 0.55,
    "negative_feedback_adjustment_count": 2,
    "hysteresis_margin": 0.05,
    "min_output_type_rounds": 2,
    "feedback_window_days": 30,
    "topic_focus_window_days": 30
  },
  "formula_constants": {
    "profile_confidence": {
      "volume": 0.50,
      "source_diversity": 0.20,
      "stability": 0.20,
      "declared_metadata": 0.10,
      "volume_scale": 8.0
    },
    "topic_focus_sample_scale": 6.0,
    "probe_match": {
      "semantic": 0.50,
      "profile": 0.35,
      "intent": 0.15
    },
    "run_evidence": {
      "profile": 0.25,
      "intent": 0.20,
      "metadata": 0.20,
      "channel_count": 0.15,
      "vector_coverage": 0.10,
      "kg_coverage": 0.10
    },
    "item_evidence": {
      "metadata_quality": 0.40,
      "feature_coverage": 0.20,
      "channel_agreement": 0.20,
      "reference_coverage": 0.20
    },
    "pre_plan_pipeline_health": {
      "IntentUnderstandingAgent": 0.30,
      "UserProfileAgent": 0.30,
      "ResourceSemanticAgent": 0.40
    },
    "intent_score": {
      "topic": 0.60,
      "resource_type": 0.25,
      "constraint": 0.15
    },
    "feedback_score": {
      "positive_tag": 0.50,
      "favorite_similarity": 0.25,
      "borrow_or_high_rating_similarity": 0.25
    },
    "mmr_similarity": {
      "tag_similarity": 0.70,
      "same_primary_author": 0.30
    },
    "valid_impression": {
      "min_visible_ratio": 0.50,
      "min_visible_ms": 1000
    }
  },
  "rrf": {
    "k0": 60,
    "general": {
      "PROFILE": 0.35,
      "KEYWORD": 0.10,
      "VECTOR": 0.15,
      "GRAPH": 0.10,
      "TRENDING": 0.20,
      "FEEDBACK": 0.10
    },
    "explicit": {
      "PROFILE": 0.15,
      "KEYWORD": 0.25,
      "VECTOR": 0.25,
      "GRAPH": 0.20,
      "TRENDING": 0.05,
      "FEEDBACK": 0.10
    }
  },
  "ranking": {
    "book": {
      "profile_score": 0.28,
      "semantic_score": 0.24,
      "kg_score": 0.14,
      "intent_score": 0.07,
      "feedback_score": 0.12,
      "popularity_score": 0.07,
      "freshness_score": 0.04,
      "recall_fusion_score": 0.04
    },
    "paper": {
      "profile_score": 0.22,
      "semantic_score": 0.32,
      "kg_score": 0.12,
      "intent_score": 0.07,
      "feedback_score": 0.09,
      "popularity_score": 0.04,
      "freshness_score": 0.10,
      "recall_fusion_score": 0.04
    }
  },
  "diversity": {
    "mmr_lambda": 0.80,
    "max_same_author": 2,
    "max_same_primary_tag": 4,
    "general_book_paper_ratio": [0.60, 0.40]
  },
  "behavior": {
    "SEARCH": {"score": 1.0, "half_life_days": 14},
    "VIEW_RESOURCE": {"score": 0.5, "half_life_days": 14},
    "VIEW_EXPLANATION": {"score": 0.4, "half_life_days": 14},
    "CLICK_RECOMMENDATION": {"score": 1.2, "half_life_days": 21},
    "FAVORITE_RESOURCE": {"score": 2.0, "half_life_days": 60},
    "BORROW_BOOK": {"score": 3.0, "half_life_days": 120},
    "ACCESS_PAPER_FULLTEXT": {"score": 3.0, "half_life_days": 120},
    "RATE_HIGH": {"score": 2.0, "half_life_days": 60},
    "RATE_NEUTRAL": {"score": 0.0, "half_life_days": null},
    "REJECT_RECOMMENDATION": {"score": -1.5, "half_life_days": 30},
    "NOT_INTERESTED": {"score": -3.0, "half_life_days": 45},
    "RATE_LOW": {"score": -2.0, "half_life_days": 45},
    "RECOMMENDATION_IMPRESSION": {"score": 0.0, "half_life_days": null}
  },
  "penalties": {
    "exposure_window_days": 30,
    "exposure_free_count": 0,
    "exposure_step": 0.03,
    "exposure_max": 0.18,
    "negative_max": 0.35,
    "negative_hard_filter_weight": 0.85,
    "negative_hard_filter_similarity": 0.80
  },
  "freshness": {
    "book_half_life_days": 1825,
    "paper_half_life_days": 730,
    "classic_floor": 0.40
  },
  "popularity": {
    "window_days": 30,
    "click_weight": 1.0,
    "favorite_weight": 2.0,
    "borrow_weight": 3.0,
    "normalization": "LOG_P95_BY_RESOURCE_TYPE"
  },
  "timeouts_ms": {
    "mysql": 2000,
    "chroma": 2000,
    "neo4j": 2000,
    "llm": 5000
  },
  "circuit_breaker": {
    "failure_threshold": 3,
    "open_seconds": 60
  }
}
```

启动时必须校验：

```text
阈值位于[0,1]
每组ranking权重和为1
每组RRF权重和为1
general_book_paper_ratio长度为2、各值非负且和为1
1<=default_final_items<=max_final_items<=20
各min_items_by_output为正且不大于max_final_items
hydration_candidate_limit不小于max_final_items
所有时间窗口和半衰期满足各自的正值或NULL约束
超时为正整数
配置版本唯一
枚举值合法
```

### 19.3 环境变量

`.env.example` 至少包含：

```dotenv
APP_ENV=development
APP_TIMEZONE=UTC
APP_RANDOM_SEED=20260727

MYSQL_DSN=mysql+asyncmy://recpro:recpro@localhost:3306/recpro?charset=utf8mb4
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=change_me
CHROMA_PATH=./data/chroma

LLM_PROVIDER=mock
LLM_API_KEY=
LLM_MODEL=
LLM_TIMEOUT_SECONDS=5

EMBEDDING_PROVIDER=hashing
EMBEDDING_MODEL_PATH=
EMBEDDING_VERSION=hash-char-ngram-v1

CONFIG_BUNDLE_VERSION=rec-1.0.0
POLICY_VERSION=policy-v1
RANKING_VERSION=ranking-v1
BEHAVIOR_FORMULA_VERSION=behavior-v1
PROMPT_VERSION=prompt-v1
GRAPH_VERSION=graph-v1
AGENT_VERSION=agents-v1
DATASET_VERSION=demo-v1

ENABLE_DEBUG_API=true
DEMO_AUTH_ENABLED=true
```

真实密钥不得进入仓库或Agent执行日志。

相对路径统一以仓库根目录解析，不以启动命令的当前目录解析。配置加载器通过代码位置确定 `PROJECT_ROOT`，显式读取根目录 `.env`；因此 `CHROMA_PATH=./data/chroma` 始终表示 `RecPro/data/chroma`。

仓库提供：

```text
.env.host.example：后端运行在主机，DSN使用localhost
.env.compose.example：后端运行在Compose网络，DSN使用mysql和neo4j服务名
```

Compose覆盖值：

```dotenv
MYSQL_DSN=mysql+asyncmy://recpro:recpro@mysql:3306/recpro?charset=utf8mb4
NEO4J_URI=bolt://neo4j:7687
CHROMA_PATH=/app/data/chroma
```

`make backend`加载host配置，`make up`加载compose配置，不允许共用含localhost的容器配置。

---

## 20. 本地运行与部署

### 20.1 运行配置

提供两个配置：

```text
demo：MySQL + 本地Chroma + 可选Neo4j + MockLLMProvider
full：MySQL + Chroma + Neo4j + 可配置真实LLMProvider
```

默认 `demo` 必须完整跑通推荐闭环。Neo4j 在demo配置中仍建议启动，以演示知识路径；即使未启动也不影响基本推荐。

### 20.2 基础设施

`compose.yaml` 至少启动：

```text
mysql
neo4j
```

可选将 backend 和 frontend 也放入 Compose。所有镜像必须固定主版本或摘要，禁止使用 `latest`。

Chroma 原型阶段使用本地持久化目录，避免额外网络服务。

最终交付的 `compose.yaml` 必须在以下最小基础设施片段上增加 `backend`、`worker` 和 `frontend` 服务，使 `make up` 可以后台启动完整系统。单独执行 `make infra-up` 只用于开发者准备依赖。

完整Compose骨架：

```yaml
services:
  mysql:
    image: mysql:8.4
    environment:
      MYSQL_DATABASE: recpro
      MYSQL_USER: recpro
      MYSQL_PASSWORD: recpro
      MYSQL_ROOT_PASSWORD: local_root_only
      TZ: UTC
    ports:
      - "3306:3306"
    command:
      - --character-set-server=utf8mb4
      - --collation-server=utf8mb4_0900_ai_ci
      - --default-time-zone=+00:00
    volumes:
      - mysql_data:/var/lib/mysql
    healthcheck:
      test: ["CMD-SHELL", "mysqladmin ping -h 127.0.0.1 -uroot -plocal_root_only"]
      interval: 5s
      timeout: 3s
      retries: 20

  neo4j:
    image: neo4j:5-community
    environment:
      NEO4J_AUTH: neo4j/change_me
      TZ: UTC
    ports:
      - "7474:7474"
      - "7687:7687"
    volumes:
      - neo4j_data:/data
    healthcheck:
      test: ["CMD-SHELL", "cypher-shell -u neo4j -p change_me 'RETURN 1' >/dev/null 2>&1"]
      interval: 10s
      timeout: 5s
      retries: 20

  backend:
    build:
      context: ./backend
    env_file:
      - .env.compose
    depends_on:
      mysql:
        condition: service_healthy
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
    command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

  worker:
    build:
      context: ./backend
    env_file:
      - .env.compose
    depends_on:
      mysql:
        condition: service_healthy
    volumes:
      - ./data:/app/data
    command: ["python", "-m", "app.worker"]

  frontend:
    build:
      context: ./frontend
    depends_on:
      - backend
    ports:
      - "5173:80"

volumes:
  mysql_data:
  neo4j_data:
```

实际提交仓库时应验证镜像标签，并在论文实验环境进一步记录镜像摘要。

Worker运行 `python -m app.worker`，负责消费资源索引和画像更新Outbox：

```text
每批最多50条
使用SELECT ... FOR UPDATE SKIP LOCKED抢占
处理前PENDING→PROCESSING
成功→DONE
失败按5秒、30秒、2分钟、10分钟指数退避
最多8次，之后→DEAD并记录last_error
进程重启后回收超过10分钟的PROCESSING记录
```

`GET /api/v1/health/ready` 报告Worker最后心跳和DEAD任务数量。

### 20.3 最小依赖

后端锁文件至少包含：

```text
fastapi
uvicorn
pydantic
pydantic-settings
sqlalchemy
alembic
asyncmy
neo4j
chromadb
numpy
scikit-learn
httpx
structlog
pytest
pytest-asyncio
testcontainers
locust
```

前端至少包含：

```text
vue
vue-router
pinia
axios
element-plus
typescript
vite
vitest
@vue/test-utils
@playwright/test
```

所有实际版本通过后端和前端锁文件固定。文档不依赖未经锁定的全局包。

`pyproject.toml` 是后端依赖声明源，`requirements.lock` 是通过统一锁定命令导出的、可被 `pip -r` 直接安装的文件；CI校验两者同步。前端同理只提交一种包管理器锁文件，不同时维护npm和pnpm锁。

FastAPI在线链使用 SQLAlchemy `AsyncSession` 和 Neo4j异步Driver。Chroma本地客户端与HashingVectorizer为同步调用，必须通过容量受限的线程池执行，不得直接阻塞事件循环。线程池上限和排队时间写入性能配置。

### 20.4 后端启动

```bash
python -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.lock
pip install -e backend --no-deps
alembic -c backend/alembic.ini upgrade head
python scripts/seed_demo_data.py
python scripts/build_vector_index.py
python scripts/build_knowledge_graph.py
uvicorn app.main:app --reload --port 8000
```

`backend/pyproject.toml` 必须声明可编辑安装包，根目录脚本只能导入已安装的 `app` 包，禁止依赖临时修改 `sys.path`。

### 20.5 前端启动

```bash
cd frontend
npm ci
npm run dev
```

### 20.6 统一命令

最终仓库应提供：

```bash
make bootstrap
make up
make infra-up
make migrate
make seed
make demo-reset
make index
make backend
make frontend
make worker
make smoke
make test
make test-unit
make test-integration
make test-contract
make test-e2e
make test-fault
make test-performance
make verify
make experiment
make report
make down
make infra-down
```

命令语义：

```text
bootstrap：检查Python、Node、Docker并复制开发环境文件
up：构建并在后台启动MySQL、Neo4j、backend和frontend
infra-up：启动MySQL和Neo4j
migrate：只通过Alembic建表
seed：幂等导入演示数据
demo-reset：只重置专用smoke用户和六个演示Fixture，不删除其他用户数据
index：幂等构建Chroma和Neo4j索引
backend/frontend：用于开发的前台进程，不用于最终串行验收
worker：用于开发的前台Outbox消费者；make up会后台启动worker服务
smoke：执行推荐—曝光—反馈—再次推荐闭环
test：执行unit、contract和不依赖长期负载的integration测试
test-e2e：使用Playwright执行前端到后端场景
test-fault：执行FaultInjecting Provider测试
test-performance：执行固定Locust负载配置
verify：依次执行smoke、unit、integration、contract、e2e和fault；性能测试单独运行
experiment：执行指定实验配置并写入runs目录
report：从既有run生成指标表和图表，不重新训练或改写结果
down：停止完整系统但保留数据卷
```

启动代码不得使用 `Base.metadata.create_all()` 替代迁移。

### 20.7 启动完成检查

```text
GET /api/v1/health/live → 200
GET /api/v1/health/ready → can_recommend=true
前端能够读取演示用户
明确主题请求返回至少5条资源
MockLLM模式无需API Key
```

---

## 21. 演示数据

### 21.1 冒烟测试最低数据

```text
图书不少于40条
论文不少于60条
主题不少于10个
每个核心主题不少于8条资源
演示用户不少于6个
行为事件不少于300条
```

该规模只用于开发和自动化测试。

### 21.2 论文演示建议数据

```text
图书不少于300条
论文不少于500条
主题15至30个
演示用户20个以上
行为事件5000条以上
知识图谱关系3000条以上
```

### 21.3 论文评价数据建议

如果论文要报告推荐准确性，建议评价数据达到：

```text
资源不少于5000条
有效匿名用户不少于200个
时间戳行为不少于30000条
人工相关性标注任务不少于100个
交互策略标注场景不少于150个
```

若无法取得该规模的真实用户行为，不把规模门槛硬凑成合成日志。可以改用：

```text
真实或公开资源语料
不少于100个代表性推荐任务
每个任务建立候选池
由至少两名领域标注者进行0至3级相关性标注
```

评价数据、候选池构造、标注说明和一致性统计单独保存在 `data/evaluation` 与 `dataset_manifest.json`。演示数据不得混入最终测试集。

两条评价轨道二选一并在实验方案中预注册：

```text
隐式反馈轨道：
- 每个评价用户在画像窗口至少5个有效正行为；
- 测试窗口至少1个收藏、借阅或高评分正样本；
- 没有测试正样本的用户不进入Recall/NDCG统计。

人工标注轨道：
- 对所有参评系统Top-20结果的并集建立候选池；
- 相关性分为0、1、2、3；
- relevance>=2计为Recall相关；
- NDCG使用0至3原始等级；
- 报告候选池判断覆盖率；
- 未进入合并池的文档不参与该任务的离线比较。
```

### 21.4 六个固定演示用户

| 用户 | 状态 | 预期行为 |
|---|---|---|
| demo_cold | 无历史行为 | 模糊输入进入GUIDED |
| demo_clear | 知识图谱与推荐系统画像清晰 | 展示PERSONALIZED_FEED |
| demo_topic | 近期连续关注多智能体 | 展示TOPIC_RESOURCES或书单 |
| demo_path | 明确系统学习需求 | 展示READING_PATH |
| demo_negative | 连续拒绝传统编目主题 | 标记FEEDBACK_ADJUSTED并降权 |
| demo_degraded | 查询主题资源很少 | 返回DEGRADED和缺口说明 |

种子脚本必须幂等，并使用相对于固定基准时间生成的事件。论文演示前通过一个命令恢复演示状态。

Fixture资源门禁：

```text
demo_clear：硬过滤后至少6本图书和4篇论文
demo_topic：至少2个子主题，每个子主题至少3条可访问资源，书单总候选至少8条
demo_path：至少8条可访问资源并覆盖至少2个难度层
demo_negative：至少6条命中目标负偏好标签的候选，便于比较降权
demo_degraded：硬过滤后严格少于 `limits.min_items_by_output[output_type]`
```

“明确主题返回至少5条”只用于满足门禁的固定演示主题，不作为任意长尾查询的验收要求。

### 21.5 数据导入质量门禁

```text
resource_type和external_id唯一
题名完整率100%
摘要完整率建议不低于80%
关键词或主题标签完整率建议不低于90%
年份合法
资源访问状态合法
向量数与READY索引状态一致
Neo4j无悬空Resource节点
```

数据授权、来源、采集时间和许可证写入 `dataset_manifest.json`。

---

## 22. 故障降级与运行保障

### 22.1 故障矩阵

| 故障 | 运行行为 | 分数字段 | 用户可见警告 |
|---|---|---|---|
| Chroma超时或版本不匹配 | 跳过VECTOR，使用其他通道 | semantic_score=NULL | VECTOR_CHANNEL_UNAVAILABLE |
| Neo4j超时或版本不匹配 | 跳过GRAPH，不展示图谱路径 | kg_score=NULL | KG_CHANNEL_UNAVAILABLE |
| Chroma和Neo4j同时失败 | 使用PROFILE、KEYWORD、TRENDING、FEEDBACK | 两项为NULL | PARTIAL_RECALL |
| LLM意图解析失败 | 使用规则分类；仍不明确则追问 | 排序不受影响 | RULE_INTENT_FALLBACK |
| LLM解释失败 | 使用模板解释 | 排序不受影响 | TEMPLATE_EXPLANATION |
| 用户画像读取失败 | 明确查询使用当前输入；通用请求追问 | profile_score=NULL | SESSION_ONLY_PROFILE |
| 排序服务异常 | 使用过滤后的RRF顺序 | 仅保留融合分 | RRF_RANKING_FALLBACK |
| 元数据不足 | 降低解释级别 | 缺失项为NULL | LIMITED_EVIDENCE |
| 反馈画像更新失败 | 反馈入库，Outbox重试 | 当前推荐不受影响 | FEEDBACK_PENDING |
| MySQL不可用 | 停止任务并返回503 | 不生成结果 | CORE_STORAGE_UNAVAILABLE |

Chroma或Neo4j单独故障不自动意味着 `delivery_strategy=DEGRADED`。只有最终可用候选或证据低于输出要求时才降级。

### 22.2 熔断

```text
同一派生服务连续失败3次
→ 熔断60秒
→ 期间直接跳过该通道
→ 60秒后健康检查进入半开
→ 成功后恢复
```

所有熔断和恢复事件写入结构化日志。

### 22.3 幂等

```text
request_id防止重复推荐任务
event_uuid防止重复行为
impression_uuid防止重复曝光
feedback_uuid防止重复反馈
resource content_hash防止重复索引
```

### 22.4 事务边界

```text
推荐记录、分组、结果项和证据：同一事务
反馈事实、行为事件、资源状态和Outbox：同一事务
画像计算：新版本整体提交
Chroma/Neo4j索引：通过Outbox最终一致
```

启动恢复任务扫描超过10分钟的 `PERSISTING`：

```text
完整record/items/explanation均存在 → 补写最终状态
结果事务不存在或不完整 → 标记FAILED并记录PERSISTENCE_INTERRUPTED
```

不得把半个推荐记录返回给用户。

### 22.5 可观测性

每个任务至少记录：

```text
trace_id
每个Agent耗时与状态
每个工具调用耗时
通道候选数量
过滤数量及原因
是否重规划
是否降级
最终候选数量
任务总耗时
版本信息
```

日志不得保存API Key、借阅账号、真实姓名或未脱敏的用户输入。

---

## 23. 安全、隐私与研究伦理

### 23.1 最小化采集

只采集推荐所需数据：

```text
匿名用户ID
检索和资源交互事件
用户主动填写的研究方向
推荐反馈
```

不采集与推荐无关的身份证号、联系方式或空间轨迹。

### 23.2 用户权利

原型应提供：

```text
查看主要兴趣标签
删除或纠正兴趣标签
清除推荐历史
关闭个性化推荐
对“不感兴趣”反馈进行撤销
```

### 23.3 访问控制

```text
普通用户只能查看自己的画像、推荐和反馈
研究管理员只能访问匿名化实验数据
Debug API在非演示环境关闭
资源导入和索引接口需要管理员权限
```

### 23.4 实验伦理

用户实验前说明：

```text
研究目的
采集内容
保存期限
退出方式
数据匿名化方式
是否调用外部大模型
```

真实输入发送外部LLM前需脱敏，并遵守所在学校的伦理和数据管理要求。

---

## 24. 测试策略

### 24.1 测试层级

| 层级 | 测试内容 | 通过标准 |
|---|---|---|
| 单元测试 | 时间衰减、画像、策略、RRF、缺失权重、惩罚、MMR | 核心领域代码覆盖率不低于85% |
| Agent契约测试 | 输入输出Schema、状态、置信度、错误和降级 | 所有Agent均通过契约快照 |
| 数据质量测试 | 唯一性、字段完整性、向量和图谱同步 | 无阻断级数据错误 |
| 集成测试 | MySQL事务、Chroma查询、Neo4j路径、Alembic | 使用真实测试容器 |
| API契约测试 | OpenAPI、状态码、幂等、鉴权、错误结构 | Schema稳定且错误可识别 |
| 端到端测试 | 推荐—解释—曝光—反馈—再次推荐 | 六个演示场景全部通过 |
| 故障注入 | 注入Chroma、Neo4j、LLM不可用和超时 | 按故障矩阵降级 |
| 确定性测试 | 固定数据、配置和随机种子重复运行 | Mock模式下结果顺序与分数一致 |
| 性能测试 | 推荐、反馈和画像刷新 | 达到记录环境下的性能目标 |

### 24.2 必须通过的自动化验收

| 编号 | 场景 | 预期结果 |
|---|---|---|
| A01 | 相同事件以不同顺序重放 | 画像结果一致 |
| A02 | 相同request_id重复提交 | 返回同一任务，不重复生成记录 |
| A03 | 相同event_uuid重复提交 | 只产生一条行为事件 |
| A04 | 相同feedback_uuid重复提交 | 反馈只生效一次 |
| A05 | 新用户输入“帮我找点资料” | GUIDED，不是因低证据直接DEGRADED |
| A06 | 低画像用户输入“推荐Agentic RAG论文” | 保留明确论文意图并召回论文 |
| A07 | 用户选择ALREADY_READ | 只过滤资源，不降低主题兴趣 |
| A08 | 用户选择TOPIC_NOT_INTERESTED | 目标negative_weight增加；反事实同配置下negative_penalty>0且final_score严格下降 |
| A09 | 卡片可视比例低于0.5 | 不计有效曝光 |
| A10 | 卡片可视少于1000ms | 不计有效曝光 |
| A11 | Chroma超时 | semantic_score=NULL，任务可继续 |
| A12 | Neo4j超时 | kg_score=NULL，解释中无伪造路径 |
| A13 | Chroma与Neo4j同时离线 | MySQL候选充足时仍返回结果 |
| A14 | MySQL离线 | HTTP 503，不从派生索引孤立返回结果 |
| A15 | 缺失任意可选特征 | 不出现除零、NaN或越界分数 |
| A16 | 同一数据快照、配置、索引、随机种子和evaluation_at重复执行 | 结果稳定，同分按resource_id处理 |
| A17 | 候选池具备足够独立作者和主题的Top-10 | 同作者和同主题数量符合约束；不足时记录diversity_relaxed |
| A18 | 阅读路径只有一个难度层 | 返回DEGRADED，不伪造其他阶段 |
| A19 | LLM生成不存在的事实 | 校验失败并回退模板 |
| A20 | 每个最终推荐项 | 至少能追溯一个召回通道 |
| A21 | 命中10.7任一质量门槛 | 最多重规划一次，replan_count<=1 |
| A22 | 模糊任务在策略阶段早停 | 不调用完整Recall和Ranking |
| A23 | 反馈更新成功 | profile_version增加且有change_log |
| A24 | 输出类型自动推断接近阈值 | 两轮最小保持期内不自动切换；显式新意图除外 |
| A25 | 历史evaluation_at之后存在行为、状态、资源和热度快照 | REPLAY_AS_OF结果不受这些未来数据影响 |

### 24.3 性能基线

在论文中记录测试硬件、数据规模和是否使用真实LLM。

Mock模式建议目标：

```text
20并发
推荐接口P95 < 2秒
反馈接口P95 < 500毫秒
错误率 < 1%
```

真实LLM延迟单独报告，不与确定性推荐链混合。LLM超时后使用模板返回。

固定负载协议：

```text
数据：论文演示规模数据及预构建索引
状态：MySQL、Chroma、Neo4j健康，LLM=mock
工具：Locust固定脚本
预热：5分钟
采样：10分钟
并发用户：20
请求比例：推荐70%、反馈20%、画像读取10%
evaluation_at：固定
```

Chroma、Neo4j故障路径和真实LLM路径单独报告，不计入健康Mock路径的P95门槛。完整召回通道必须并行执行并遵守总截止时间。

Chroma在默认配置中是进程内持久化客户端，不能通过停止独立容器模拟故障。因此测试环境必须提供装饰器：

```text
FaultInjectingVectorStore
FaultInjectingGraphStore
FaultInjectingLLMProvider
```

装饰器根据测试用例注入 `TIMEOUT`、`UNAVAILABLE`、`EMPTY` 或 `INVALID_RESPONSE`，且仅在 `APP_ENV=test` 或专用故障实验配置中启用。论文故障注入实验记录注入点、持续时间和预期错误码。

### 24.4 冒烟测试脚本

`scripts/smoke_test.py` 必须自动完成：

```text
1. 将专用smoke用户重置到固定Fixture；不得使用论文演示用户积累状态。
2. 检查健康状态。
3. 使用smoke_path创建阅读路径任务。
4. 校验任务、结果和Agent Trace。
5. 上报第一条资源有效曝光。
6. 提交TOPIC_NOT_INTERESTED反馈。
7. 再次发起同主题推荐。
8. 校验画像版本增加。
9. 校验被反馈资源消失或同主题分数下降。
10. 输出PASS/FAIL和证据ID。
```

测试环境优先使用独立数据库和临时Chroma目录，并在测试结束后销毁。`seed` 的幂等性不等于恢复被反馈修改的用户状态。

---

## 25. 六个论文演示用例

### 25.1 画像清晰的个性化推荐

输入：

```text
用户长期检索、收藏和借阅知识图谱与推荐系统资源
无明确输入，从首页触发
```

预期：

```text
output_type=PERSONALIZED_FEED
delivery_strategy=DIRECT
profile_confidence高于配置阈值
结果包含图书和论文
每条结果含画像标签证据
```

### 25.2 模糊意图引导

输入：

```text
冷启动用户：“帮我找点资料”
```

预期：

```text
delivery_strategy=GUIDED
返回topic、resource_types和output_type问题
完整召回与排序Agent不执行
用户补充后继续同一task_id
```

### 25.3 主题集中形成专题书单

输入：

```text
近期连续检索“多智能体、Agentic RAG、动态推荐”
用户请求专题书单
```

预期：

```text
output_type=BOOKLIST
至少2个主题分组
每组至少2条资源
组内资源均来自真实候选
```

### 25.4 系统学习形成阅读路径

输入：

```text
“我想系统学习多智能体推荐”
```

预期：

```text
output_type=READING_PATH
至少覆盖2个阶段
路径顺序可以追溯难度或先修关系
画像不足不改变用户明确输出意图
```

### 25.5 负反馈修正

输入：

```text
对两条“传统编目”资源选择TOPIC_NOT_INTERESTED
```

预期：

```text
adaptation_state=FEEDBACK_ADJUSTED
负偏好标签增加
同主题资源最终分数下降
界面显示实际生效的调整，不只显示固定文案
```

### 25.6 资源或组件不足

输入：

```text
查询一个数据稀少主题，或通过故障注入使Neo4j/Chroma不可用
```

预期：

```text
单组件故障但候选充足：仍可DIRECT并显示组件警告
候选数量不足：delivery_strategy=DEGRADED
解释只包含可验证证据
任务Trace可定位降级原因
```

---

## 26. 论文实验设计

### 26.1 研究问题

```text
RQ1：多智能体协同混合推荐能否提高知识资源的相关性和列表质量？
RQ2：内部状态驱动的交互策略是否比固定推荐列表更适合用户当前任务？
RQ3：反馈学习能否减少被拒主题和重复资源的后续曝光？
RQ4：多智能体执行机制是否提高系统的任务适应性、故障恢复能力和可追溯性？
```

论文不应预先断言结果。实验结果显著后才能把“提高”写入结论。

### 26.2 基线

| 编号 | 方法 | 用途 |
|---|---|---|
| B0 | 热门度推荐 | 最弱基线 |
| B1 | 内容相似度推荐 | 验证个性化和多通道价值 |
| B2 | 相同召回与排序、固定输出列表 | 单独验证动态交互策略 |
| B3 | 固定流水线、无探测和重规划 | 验证多智能体自适应编排 |
| Proposed | 多智能体 + 四维策略 + 反馈闭环 | 完整方案 |

B2必须与Proposed使用相同候选召回和排序公式，否则无法把差异归因于交互策略。

B3也必须记录与Proposed等价的阶段级系统日志，并使用相同候选工具、硬过滤、排序、超时和数据快照；它只移除轻量探测、动态通道选择和重规划。错误定位率定义为“日志是否正确指出预先注入的故障组件和错误码”，不能用“B3没有Agent Trace”作为Proposed天然胜出的依据。

### 26.3 消融

```text
Full - Policy：固定输出PERSONALIZED_FEED
Full - Feedback：不更新负偏好和曝光惩罚
Full - KG：移除图谱召回和kg_score
Full - Vector：移除向量召回和semantic_score
Full - Diversity：移除MMR
Full - Replan：禁止候选不足后的重规划
Template vs LLM：只比较解释表达，不改变排序
```

### 26.4 数据划分

有真实时间戳时：

```text
训练/画像窗口：最早70%
验证窗口：之后15%
测试窗口：最后15%
```

原则：

```text
画像只能读取推荐时刻之前的事件
历史任务必须使用REPLAY_AS_OF重算画像和资源状态，不能读取当前物化表
候选、Probe、向量和图谱查询只能读取available_from<=evaluation_at的资源
热度只能读取cutoff_at<=evaluation_at的快照
阈值和权重只在验证集调整
测试集只用于最终报告
论文记录数据版本和划分脚本
```

若评价语料是一次性冻结的静态馆藏，也可以在预注册中声明“所有参评资源在最早评价时刻前已经可用”，并用数据门禁验证 `max(available_from) <= min(evaluation_at)`；否则必须保留逐资源时间过滤。资源索引可以预先包含未来资源，但查询过滤不可省略。

如果真实用户行为不足：

```text
合成行为只用于功能与动态性测试
推荐相关性由领域人员对“任务—资源”进行0至3级标注
至少报告两名标注者的一致性
不得仅凭合成用户宣称推荐准确率提高
```

### 26.5 指标

| 对象 | 指标 |
|---|---|
| 排序 | NDCG@5、NDCG@10、Recall@5、Recall@10、MRR |
| 列表 | 主题覆盖率、类型覆盖率、列表内多样性、重复曝光率 |
| 策略 | Accuracy、Macro-F1、混淆矩阵、不恰当主动推荐率 |
| 反馈 | 被拒资源排名变化、同主题曝光下降率、适应轮数 |
| 解释 | 证据覆盖率、事实一致率、无依据陈述率、可理解性 |
| 多智能体 | Trace完整率、降级成功率、重规划成功率、Agent P95延迟 |
| 用户体验 | 任务完成率、完成时间、满意度、信任度、认知负担 |

### 26.6 策略标注集

构建不少于150个推荐场景，每个场景包含：

```text
用户画像摘要
近期行为
任务输入
资源探测统计
反馈状态
正确output_type
正确delivery_strategy
允许的explanation_level
理由标签
```

至少两名标注者独立标注，分歧通过讨论解决。报告一致性指标。

标注集在评估前冻结并分层划分为开发、验证和测试，建议比例20%/30%/50%；样本较少时使用预注册的分层交叉验证。阈值只在验证数据上调整。分别报告 `output_type` 和 `delivery_strategy` 指标；`adaptation_state` 是由反馈事实确定的规则字段，单独报告规则正确率。存在多种合理策略时保存 `accepted_labels`，预测命中任一可接受标签均视为正确。

### 26.7 故障注入实验

分别注入：

```text
Chroma超时
Neo4j超时
LLM无效JSON
LLM超时
单召回通道空结果
排序质量不足
反馈画像更新失败
```

比较 B3 固定流水线和 Proposed：

```text
任务完成率
降级正确率
平均工具调用数
P95延迟
错误定位率
Trace完整率
```

多智能体更适合主张“提升任务适应性、容错性和可追溯性”。除非实验数据支持，不直接声称 Agent 数量提高了推荐准确率。

### 26.8 用户实验

建议采用被试内交叉设计，比较 B2 和 Proposed：

```text
先根据预实验效应量进行功效分析；24人只作为原型最低可行目标
专题资料查找任务
系统学习路径任务
模糊需求澄清任务
为两个系统准备难度匹配但主题不同的A/B任务集
使用AB/BA或拉丁方平衡系统和任务顺序
```

记录：

```text
任务完成率
完成时间
点击与收藏
追问轮数
用户主动修改推荐的次数
满意度
信任度
认知负担
```

实验前定义参与者条件、每项任务的完成标准、固定量表题项、无效样本和退出规则。二元完成率使用配对二元检验，连续或序数数据使用适合分布的配对检验；报告95%置信区间、效应量和多重比较校正，不能只报告均值。

### 26.9 可复现实验目录

```text
experiments/runs/{run_id}/
├── config.json
├── environment.json
├── dataset_manifest.json
├── predictions.jsonl
├── metrics.json
├── agent_metrics.json
└── tables/
```

`environment.json` 至少记录：

```text
Git commit
Git工作区是否dirty
依赖锁文件哈希
Docker镜像摘要
操作系统与硬件
数据集版本与哈希
标注集哈希
实验配置哈希
随机种子
evaluation_at
时区
策略、排序、嵌入和提示词版本
```

### 26.10 实验执行命令

实验脚本职责必须分离：

```bash
python scripts/prepare_evaluation_split.py \
  --manifest data/evaluation/dataset_manifest.json \
  --output data/evaluation/splits/v1

python scripts/run_experiment.py \
  --config experiments/configs/full.json \
  --split data/evaluation/splits/v1 \
  --run-id full-v1

python scripts/evaluate_results.py \
  --run-id full-v1

python scripts/build_experiment_report.py \
  --run-id full-v1
```

```text
prepare_evaluation_split：按时间生成并冻结train/validation/test
run_experiment：运行一个基线、完整方案或消融配置，输出predictions.jsonl
evaluate_results：只读取冻结预测和标注，计算metrics.json
build_experiment_report：生成论文表格和图，不修改预测
```

`make experiment CONFIG=... RUN_ID=...` 封装前两步，`make report RUN_ID=...` 封装后两步。缺少配置、数据清单或已存在同名不可覆盖run时必须失败并给出明确错误。

---

## 27. 多智能体研究论证

### 27.1 形式化描述

单个智能体表示为：

```text
A_i = <G_i, O_i, B_i, P_i, T_i, M_i>
```

```text
G_i：局部目标
O_i：可观察信息
B_i：当前任务中的局部信念状态
P_i：在合法动作中选择动作的策略
T_i：可调用工具集合
M_i：可发送和接收的结构化消息
```

### 27.2 为什么不是固定服务流水线

系统执行图存在真实动态分支：

```text
模糊意图：画像/意图 → 探测 → 策略 → 追问，跳过完整召回
明确推荐：完整协同链
已有结果解释：直接读取证据并调用ExplanationAgent
候选不足：RankingAgent请求一次重规划
向量故障：RecallAgent调整召回通道预算
证据不足：ExplanationAgent拒绝LLM自由生成，使用受限模板
用户反馈：FeedbackLearningAgent提出增量，UserProfileAgent应用新版本
```

Agent协作的研究价值体现在：

```text
任务分解
局部自主决策
动态协作路径
工具选择
失败隔离
结构化消息
状态和证据可追溯
```

### 27.3 不应做的论证

```text
不以Agent数量作为创新
不把每个数据库查询包装成Agent
不声称所有Agent都必须使用LLM
不声称多智能体天然提高准确率
不把固定函数调用链称为自主协作
```

---

## 28. 开发里程碑

| 阶段 | 工作 | 退出标准 |
|---|---|---|
| M0 规格冻结 | 枚举、Agent契约、数据字典、策略和实验协议 | Schema与规则测试样例评审通过 |
| M1 基础设施 | 项目骨架、Compose、迁移、健康检查 | 新环境能启动MySQL和后端 |
| M2 数据与索引 | 资源导入、标签、Chroma、Neo4j、种子数据 | 数据门禁和索引校验通过 |
| M3 基线推荐 | 行为、画像、关键词/画像召回、基础排序 | B0和B1可以重复运行 |
| M4 多智能体主链 | Agent消息、探测、策略、召回、排序、解释 | 一条推荐Trace完整 |
| M5 动态反馈闭环 | 曝光、反馈原因、画像版本、模式稳定 | 反馈前后结果按预期改变 |
| M6 前端与演示 | 推荐页、书单、路径、解释、调试页 | 六个演示场景E2E通过 |
| M7 稳定性 | 契约、故障注入、性能和安全测试 | 达到测试矩阵目标 |
| M8 论文实验 | 基线、消融、策略集、用户实验 | 输出指标、置信区间和运行记录 |
| M9 发布冻结 | 镜像、演示脚本、数据清单、论文图表 | 全新环境可复现演示 |

M5完成后冻结论文核心功能。之后不再加入与研究问题无关的图书馆模块。

### 28.1 推荐实现顺序

```text
1. 枚举、配置模型和Agent消息契约
2. MySQL表和Alembic迁移
3. 演示资源与行为种子
4. 画像重算和单元测试
5. MySQL关键词/画像召回
6. RRF、排序、缺失权重和MMR
7. MockLLM与模板解释
8. Orchestrator状态机和策略Agent
9. 曝光、反馈和画像版本
10. Chroma向量通道
11. Neo4j图谱通道
12. 前端与调试页
13. 故障注入和实验脚本
```

先让MySQL基础链路工作，再接入可选通道。不要一开始同时调试三个数据存储和真实LLM。

---

## 29. 风险与控制

| 风险 | 控制 |
|---|---|
| 多智能体被认为只是服务改名 | 使用严格Agent定义、动态分支、消息日志和故障实验 |
| 范围过大无法完成 | 推荐闭环为核心，真实LLM和复杂图谱为增强 |
| 数据不足 | 演示数据与评价数据分离，必要时进行人工相关性标注 |
| 阈值主观 | 验证集调参、配置版本化、测试集冻结 |
| LLM幻觉 | LLM不排序，证据白名单，校验失败回退模板 |
| Neo4j和Chroma带来运维风险 | 派生索引、独立超时、熔断和权重重归一化 |
| 负反馈过度泛化 | 强制反馈原因，默认只抑制资源 |
| 模式频繁跳变 | 会话保持、显式意图优先和阈值滞回 |
| 曝光统计不真实 | 记录可视比例与时长，不把返回接口视为曝光 |
| 数据泄漏 | REPLAY_AS_OF重算画像与状态，并对行为、资源和热度快照统一应用evaluation_at边界 |
| 实验不可复现 | 固定代码、数据、配置、种子和提示词版本 |
| 隐私风险 | 匿名化、最小采集、访问控制和撤销入口 |

---

## 30. 论文系统实现章节建议

### 30.1 总体描述

```text
LibraMAS推荐模块采用监督式多智能体协同架构。系统将推荐任务分解为意图理解、用户画像、资源语义探测、交互策略决策、候选召回、排序重排、证据解释和反馈学习等局部任务。各智能体通过结构化消息交换任务结果、证据引用、置信度和执行状态，由推荐总控智能体维护全局任务状态并根据局部结果选择后续动作。该协同过程不是固定调用链：意图模糊时任务在策略阶段进入澄清状态，候选不足时允许一次重规划，可选通道失败时召回智能体调整工具组合，解释证据不足时解释智能体使用受限模板。
```

### 30.2 动态交互描述

```text
系统没有使用单一互斥模式表示所有推荐状态，而是将推荐交互表示为结果组织形式、交付策略、解释强度和反馈修正状态四个正交维度。推荐策略智能体首先根据用户明确意图确定结果组织形式，再结合画像置信度、候选资源覆盖和证据完整度判断直接输出、引导补充或低置信降级，最后设置解释级别和反馈修正标记。因此，阅读路径可以同时包含证据解释并应用近期反馈，避免传统单模式规则中的语义冲突。
```

### 30.3 推荐计算描述

```text
候选召回采用画像、关键词、向量、知识图谱、热门趋势和正反馈六个通道。由于各通道原始分数量纲不同，系统先在通道内排序，再使用加权倒数排名融合。排序阶段分别计算画像匹配、语义相似、知识路径、任务意图、反馈相似、热度、新鲜度和融合分数，并对不可用特征执行权重重归一化，而不是将组件故障视为零匹配。最终结果在曝光与负偏好惩罚后使用MMR进行多样性重排。
```

### 30.4 可解释与反馈描述

```text
每条推荐结果保存候选来源、评分特征、行为证据、标签证据和知识路径。解释智能体只使用这些已持久化事实生成说明，并通过证据验证器阻止无依据陈述。用户反馈按照主题不感兴趣、已经阅读、难度不合适、资源质量、当前不需要和重复推荐等原因分别处理，避免一次拒绝永久压制整个主题。曝光、反馈和画像变化均使用版本化记录，使下一轮推荐变化可以追溯到具体事件。
```

---

## 31. 面向开发Agent的实施提示词

```text
你只实现LibraMAS智慧图书馆系统中的知识资源推荐模块。必须严格遵循本实施文档，不开发座位、空间、活动、采购、剔旧、分类和管理驾驶舱。

开发顺序必须从MySQL可运行闭环开始，再接入Chroma、Neo4j和真实LLM。默认LLM_PROVIDER=mock时系统必须完整运行。

系统采用多智能体架构，但Agent与Service必须区分：
- Agent具备局部目标、观察、工具、决策、结构化输出和置信度；
- Service负责确定性数据库、公式和检索操作；
- Agent之间通过AgentMessage/AgentResult契约协作；
- 所有Agent调用写入执行日志；
- LLM不得生成资源ID、分数、行为证据或知识图谱路径。

必须实现以下 8 个核心业务 Agent：
1. IntentUnderstandingAgent
2. UserProfileAgent
3. ResourceSemanticAgent
4. RecommendationPolicyAgent
5. CandidateRecallAgent
6. RankingAgent
7. ExplanationAgent
8. FeedbackLearningAgent

另设唯一的 `RecommendationOrchestrator` 负责全局状态推进、调度和重规划，但它不作为业务 Agent 计数。

交互决策必须包含四个独立字段：
1. output_type
2. delivery_strategy
3. explanation_level
4. adaptation_state

流程必须是：
意图与画像 → 轻量资源探测 → 交互策略 → 完整召回 → RRF融合 → 确定性排序 → MMR → 基于证据的解释 → 曝光与反馈。

实现时必须保证：
- 用户明确意图优先于画像推断；
- 模糊意图进入GUIDED；
- 明确意图但资源不足进入DEGRADED；
- Chroma或Neo4j失败时相关特征为NULL并重新归一化权重；
- MySQL失败时返回503；
- 用户看到卡片才记录有效曝光；
- 反馈写入具备幂等性；
- ALREADY_READ不产生主题负偏好；
- 所有阈值和权重从版本化配置读取；
- Mock模式同一输入可以得到可复现结果；
- 任何自然语言推荐理由都能反查evidence_ref。

每完成一个阶段，先运行对应单元和集成测试，再继续下一阶段。不得为通过测试而硬编码演示用户ID或固定推荐结果。
```

---

## 32. 最终交付物

```text
1. 可运行前后端源码
2. compose.yaml和环境变量示例
3. Alembic完整迁移
4. 演示数据与数据说明
5. Chroma和Neo4j索引脚本
6. MockLLMProvider
7. 版本化策略、排序和行为配置
8. Agent消息、执行和错误日志
9. 六个演示场景
10. 自动化测试与故障注入测试
11. OpenAPI文档
12. 论文演示脚本
13. 基线、消融与评价脚本
14. 实验配置、原始结果和指标表
15. 数据来源、许可证与伦理说明
```

### 32.1 最终验收命令

一个全新环境应能够执行：

```bash
make bootstrap
make up
make migrate
make seed
make index
make verify
```

并得到：

```text
基础设施健康
演示数据和索引一致
推荐闭环通过
六个演示场景通过
关键算法测试通过
可选组件故障可降级
Agent执行链可追溯
```

---

## 33. 一句话概括

LibraMAS推荐模块以结构化多智能体协作为执行机制，以用户状态、任务意图、资源准备度、反馈和证据状态为内部驱动，以四维交互策略为动态核心，通过可复现的多通道召回、排序、多样性、证据解释和反馈学习，为智慧图书馆提供可运行、可降级、可追溯、可验证的图书与论文推荐服务。
