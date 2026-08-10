# LibraMAS 论文实验协议

> 协议版本：1.0.0
> 状态：G0 预注册基线；正式实验前仅允许通过 Amendment 追加修订
> 日期：2026-08-02
> 研究对象：多智能体协同 + 智慧图书馆知识资源推荐
> 实现基线：`docs/LibraMAS_纯推荐模块实施文档_可运行版.md`
> 数据语义：`docs/data_dictionary.md`

## 1. 协议目标

本协议在实现和正式测试前冻结研究问题、比较系统、消融、评价单位、时间切分、指标、故障注入、统计方法和结果保留规则，减少数据泄漏、事后调参和选择性报告。

协议不预先断言 LibraMAS 优于基线。只有预注册指标、统计检验和效应量共同支持时，论文才能使用“提高”“改善”等因果或比较性表述。

## 2. 研究范围

### 2.1 纳入范围

- 图书 `BOOK` 和论文 `PAPER` 的个性化知识资源推荐；
- 推荐流、主题资源、专题书单和阅读路径；
- 动态澄清、低置信降级和一次重规划；
- 曝光—反馈—画像更新；
- 多智能体 Trace、故障恢复和解释证据。

### 2.2 不纳入范围

- 座位、空间、活动和采购推荐；
- 通用问答质量；
- 大规模分布式吞吐能力；
- 在线深度模型训练；
- 真实图书馆生产系统的账号、支付和借还集成。

### 2.3 评价对象分离

本研究使用四条相互区分的评价轨道：

| 轨道 | 核心对象 | 支持的结论 |
|---|---|---|
| E1 离线推荐 | 任务/用户—资源排序 | 相关性、覆盖和多样性 |
| E2 策略标注 | 内部状态—交互决策 | 动态策略适配性 |
| E3 故障注入 | 任务—组件故障 | 容错、重规划、Trace |
| E4 用户实验 | 参与者—检索/学习任务 | 任务体验、满意度和认知负担 |

合成行为只可用于功能、动态性和故障实验，不能单独支持“推荐准确率提高”的结论。

## 3. 研究问题与主要终点

### RQ1：推荐质量

> 多智能体协同的混合推荐方案能否提高智慧图书馆知识资源的相关性和列表质量？

- 主要终点：`NDCG@10`。
- 次要终点：`NDCG@5`、`Recall@5/10`、`MRR`、主题覆盖率、类型覆盖率、列表内多样性、重复曝光率。
- 主比较：`Proposed` 对 `B0`、`B1`；多通道组件价值由相应消融补充解释。
- 原假设 H0-RQ1：配对任务上的 Proposed 与比较系统 `NDCG@10` 差异为 0。

### RQ2：动态交互策略

> 内部状态驱动的交互策略是否比固定推荐列表更适合用户当前任务？

- 主要终点：`delivery_strategy` Macro-F1。
- 关键次要终点：`output_type` Macro-F1、两维联合准确率、不恰当主动推荐率、任务完成率和澄清轮数。
- 主比较：`Proposed` 对 `B2`。
- 原假设 H0-RQ2：两系统的策略正确率和任务完成率没有差异。

### RQ3：反馈适应

> 反馈学习能否减少被拒资源和被拒主题的后续曝光？

- 主要终点：同主题有效曝光下降率。
- 次要终点：被拒资源排名变化、重复曝光率、达到稳定抑制所需轮数。
- 主比较：`Proposed` 对 `Full - Feedback`。
- 原假设 H0-RQ3：反馈前后同主题有效曝光率没有下降。

### RQ4：多智能体执行机制

> 多智能体执行机制是否提高任务适应性、故障恢复能力和可追溯性？

- 主要终点：故障注入下的降级成功率。
- 次要终点：任务完成率、重规划成功率、错误定位率、Trace 完整率、平均工具调用数、Agent P95 延迟。
- 主比较：`Proposed` 对 `B3`。
- 原假设 H0-RQ4：两系统在故障条件下的降级成功率没有差异。

RQ4 不直接检验“Agent 数量提高推荐准确率”。多智能体论证聚焦可观察的自主决策、动态工具选择、失败处理、重规划和可追踪协作。

## 4. 比较系统

### 4.1 系统定义

| ID | 名称 | 冻结定义 |
|---|---|---|
| `B0` | 热门度推荐 | 仅使用类型内 `resource_popularity_snapshot` 排序；保持相同硬过滤和 `evaluation_at` |
| `B1` | 内容相似度推荐 | 使用任务文本/规范主题与资源文本的同一向量或确定性离线嵌入相似度；无长期画像和图谱 |
| `B2` | 固定输出列表 | 与 Proposed 使用完全相同的召回、硬过滤、融合、排序和候选快照，但固定 `PERSONALIZED_FEED + DIRECT + SUMMARY`；缺必要主题时使用预注册默认主题/热门回退，不执行策略澄清 |
| `B3` | 固定流水线 | 使用相同工具、硬过滤、排序、超时和数据快照；固定通道集合与调用顺序，不执行轻量探测、动态通道选择或重规划 |
| `Proposed` | 完整 LibraMAS | 九个逻辑 Agent、四维策略、两阶段探测、动态通道、一次重规划、证据解释和反馈闭环 |

### 4.2 公平性约束

1. 同一评价任务的所有系统使用相同 `evaluation_at`、可见资源集合和候选时间过滤。
2. 同一比较中的资源元数据、标签、热度快照、向量和图谱版本保持一致。
3. B2 与 Proposed 的候选召回和排序必须逐字段相同，仅改变交互策略。
4. B3 与 Proposed 使用相同超时预算和通道实现；B3 也记录阶段级日志，不能因“没有 Agent Trace”而天然判负。
5. 所有系统使用相同最终 `effective_limit` 和相同硬过滤。
6. 若某基线无法生成结构化书单/路径，需按其冻结定义报告，不为改善结果临时添加 Proposed 的组件。
7. 任何系统失败都保留为失败结果，不能从该系统样本中单独排除。

### 4.3 配置文件

每个系统有独立不可变配置：

```text
experiments/configs/b0_popularity.json
experiments/configs/b1_content.json
experiments/configs/b2_fixed_output.json
experiments/configs/b3_fixed_pipeline.json
experiments/configs/proposed_full.json
```

配置必须继承同一公共数据/超时/过滤 Bundle，并显式列出差异。运行时合并后的完整配置和 SHA-256 写入 Run Artifact。

## 5. 消融实验

| ID | 相对 Full 唯一变化 | 归因目标 |
|---|---|---|
| `A_NO_POLICY` | 固定 `PERSONALIZED_FEED + DIRECT` | 动态策略价值 |
| `A_NO_FEEDBACK` | 不使用负偏好、资源抑制和曝光惩罚；仍记录反馈事实但不进入计算 | 反馈闭环价值 |
| `A_NO_KG` | 移除 GRAPH 通道和 `kg_score`，其余可用特征重归一化 | 图谱价值 |
| `A_NO_VECTOR` | 移除 VECTOR 通道和 `semantic_score`，其余可用特征重归一化 | 向量价值 |
| `A_NO_DIVERSITY` | 关闭 MMR，按相关性分数和稳定 Tie-break 排序 | 多样性重排价值 |
| `A_NO_REPLAN` | 质量不足时不进行第二计划 | 重规划价值 |
| `A_TEMPLATE_EXPLANATION` | 只用模板解释 | 解释表达比较 |
| `A_LLM_EXPLANATION` | 受约束 LLM 改写并执行 Evidence Validator | 解释表达比较 |

消融一次只改变一个组件。`Template vs LLM` 不改变候选、排序和条目集合，只评价表达、忠实性和用户感知。

## 6. 数据轨道与规模门槛

### 6.1 开发/演示数据

只用于冒烟、端到端和演示：

```text
最低：40本图书、60篇论文、10个主题、6个演示用户、300条行为
论文演示建议：300本图书、500篇论文、15—30个主题、20个以上演示用户、5000条以上行为
```

演示 Fixture 不能混入正式测试集。

### 6.2 E1 评价轨道选择

正式实验前必须在 `dataset_manifest.json` 中预注册以下之一为 RQ1 主轨道；选择后不能依据测试结果切换：

#### Track-I：真实隐式反馈

建议规模：

```text
资源 >= 5000
有效匿名用户 >= 200
有时间戳行为 >= 30000
```

用户纳入条件：

- 画像窗口至少 5 个有效正行为；
- 测试窗口至少 1 个收藏、借阅、合法全文访问或高评分正样本；
- 满足时间和身份质量门禁。

#### Track-J：人工相关性标注

适用于真实用户行为不足的情况：

```text
代表性推荐任务 >= 100
每个任务建立系统 Top-20 并集候选池
至少两名领域标注者独立给出 0—3 级相关性
```

候选池规则：

1. 收集所有参评系统 Top-20 的去重并集。
2. 标注者不看到资源来自哪个系统及其排名。
3. `relevance >= 2` 计为 Recall 相关；NDCG 使用 0—3 原等级。
4. 报告候选池判断覆盖率。
5. 未进入合并池的资源不参与该任务的离线比较；该限制写入论文威胁分析。

若两条轨道都满足条件，可以预注册一条为主要、另一条为稳健性分析；不能在看完结果后交换主次。

### 6.3 E2 策略标注集

不少于 150 个场景，每个场景冻结：

```text
scenario_id
用户声明画像摘要
截至 evaluation_at 的近期行为摘要
当前任务输入
资源 Probe 统计
反馈和组件状态
accepted_output_types
accepted_delivery_strategies
accepted_explanation_levels
expected_adaptation_state
reason_codes
```

至少两名标注者独立标注，分歧在冻结测试集之前仲裁。存在多种合理策略时保留 `accepted_*` 数组，命中任一允许标签视为正确。

### 6.4 数据排除规则

所有排除都在运行系统前由数据质量脚本产生清单和原因码：

| 原因码 | 条件 | 处理 |
|---|---|---|
| `DUPLICATE_EXTERNAL_RESOURCE` | 同类型同 external_id 多实体且无法可靠合并 | 整组隔离，不进入评价候选；原记录保留 |
| `INVALID_TIME_ORDER` | 发生时间明显晚于采集时间且超出预注册容差 | 隔离该事件 |
| `MISSING_EVALUATION_IDENTITY` | 无法稳定匿名关联用户/任务 | 不进入用户级评价 |
| `NO_TEST_POSITIVE` | Track-I 用户测试窗无正样本 | 不进入 Recall/NDCG；仍可用于功能统计 |
| `INSUFFICIENT_PROFILE_HISTORY` | Track-I 用户画像窗正行为少于 5 | 不进入个性化准确性评价 |
| `RESOURCE_AFTER_EVALUATION` | `available_from > evaluation_at` | 从该任务候选中时间过滤 |
| `FUTURE_BEHAVIOR` | `occurred_at > evaluation_at` | 不进入该任务画像/状态 |
| `LABEL_CONFLICT_UNRESOLVED` | 标注分歧未完成仲裁 | 任务不进入冻结测试集 |
| `DEMO_FIXTURE` | 演示或合成 Fixture | 不进入 RQ1 真实准确性评价 |

不得仅对 Proposed 有利或仅对失败系统不利地排除样本。排除前后数量和比例必须报告。

## 7. 时间切分与防泄漏

### 7.1 有时间戳行为的数据

对全局时间序列按时间边界切分：

```text
训练/画像窗口：最早 70%
验证窗口：随后 15%
测试窗口：最后 15%
```

切分脚本先按 `(occurred_at, event_uuid)` 稳定排序，再确定两个 UTC 边界。边界记录为绝对时间，不在每个系统运行时重新计算。

用户级纳入检查在全局边界确定后执行。不得把同一事件复制到多个 Split；同一时间戳落在边界时按以下规则：

```text
train: occurred_at < validation_start
validation: validation_start <= occurred_at < test_start
test: occurred_at >= test_start
```

### 7.2 静态人工标注任务

若没有行为时间序列：

1. 资源必须满足 `max(available_from) <= min(evaluation_at)`；否则逐任务时间过滤。
2. 任务按主题、资源类型、任务类型和难度分层。
3. 固定随机种子后切为开发 20%、验证 30%、测试 50%。
4. 同一来源任务的改写版本使用 Group ID，整组只能进入一个 Split。

### 7.3 历史重放

测试和论文任务一律使用 `REPLAY_AS_OF`：

- 只读取 `occurred_at <= evaluation_at` 的行为；
- 声明画像取 `valid_from <= evaluation_at` 的最高版本；
- 重算兴趣、负偏好、阅读阶段和资源状态；
- 禁止读取当前 `user_profile`、当前 `user_interest_tag` 或当前 `user_resource_state`；
- 热度取 `cutoff_at <= evaluation_at` 的最大匹配版本；
- 候选查询强制 `available_from <= evaluation_at`；
- 重放缓存键包含用户、数据集、公式版本和精确 `evaluation_at`。

### 7.4 调参与测试隔离

- 训练区用于构建历史画像、统计和模型拟合。
- 验证区用于阈值、权重、超时和候选预算选择。
- 测试区只在配置、代码和协议冻结后执行。
- 打开测试结果后不再调整当前实验的算法；修订必须产生新协议 Amendment 和新 Run 系列。

## 8. 标注协议

### 8.1 标注者

- 至少两名具有图书情报、计算机、推荐系统或任务主题知识的标注者；
- 标注前通过统一说明和练习集校准；
- 不向标注者暴露系统 ID、算法得分和排序来源；
- 标注者不能参与自己编写任务的最终仲裁。

### 8.2 相关性等级

| 等级 | 定义 |
|---:|---|
| 0 | 与任务无关或不可用 |
| 1 | 边缘相关，只提供少量背景 |
| 2 | 明确相关，可帮助完成任务 |
| 3 | 高度相关，是任务核心或学习路径关键资源 |

可用性、主题相关性和难度适配分别记录；总相关性不能用单一系统得分自动生成。

### 8.3 策略标签

标注者分别判断：

1. 可接受 `output_type`；
2. 可接受 `delivery_strategy`；
3. 可接受 `explanation_level`；
4. `adaptation_state` 是否与反馈事实一致；
5. 主要理由码。

不能把四个正交维度压缩为单一混合标签。

### 8.4 一致性

- 两名标注者的名义多分类报告 Cohen's kappa；多名标注者报告 Fleiss' kappa。
- 0—3 有序相关性同时报告加权 kappa。
- 报告原始一致率、置信区间和各类别分布。
- 测试集冻结前完成仲裁并保留初始标注与仲裁记录；不覆盖原标注。

## 9. 推荐指标

令任务 `q` 的第 `i` 个结果相关性为 `rel_i ∈ {0,1,2,3}`，相关集合阈值为 `rel >= 2`。

### 9.1 DCG 与 NDCG

```text
DCG@k(q) = Σ(i=1..k) (2^rel_i - 1) / log2(i + 1)
NDCG@k(q) = DCG@k(q) / IDCG@k(q)
```

若任务的候选池没有任何 `rel >= 1` 资源，则不进入 NDCG 主分析，并以 `NO_RELEVANT_JUDGMENT` 单独计数；不能记为 0 后隐藏原因。若系统返回少于 k 条，缺位按 0 相关处理。

### 9.2 Recall

```text
Recall@k(q) = |TopK(q) ∩ Relevant(q)| / |Relevant(q)|
Relevant(q) = {resource | relevance >= 2}
```

Relevant 为空的任务不进入 Recall 分母并单独报告数量。

### 9.3 MRR

```text
RR(q) = 1 / rank_of_first_item_with_relevance>=2
```

没有相关结果时为 0，MRR 为任务级 RR 的宏平均。

### 9.4 列表指标

| 指标 | 冻结定义 |
|---|---|
| 主题覆盖率 | Top-K 覆盖的目标相关主题数 / 任务标注目标主题数；无目标主题任务单独报告 |
| 类型覆盖率 | Top-K 中出现的合格资源类型数 / 任务允许且候选中存在的类型数 |
| 列表内多样性 | Top-K 所有资源对的 `1 - tag_weighted_jaccard` 平均值；无共同标签为 1 |
| 重复曝光率 | 用户滚动窗口内重复资源有效曝光数 / 全部有效曝光数；窗口默认 30 天并版本化 |
| 可用结果率 | Top-K 中在 `evaluation_at` 满足可用性过滤的比例，目标必须为 1 |

只有一个结果时列表内多样性记为 `NULL`，不记为 1。

### 9.5 聚合

- 主报告使用任务级宏平均，防止行为量大的用户支配结果。
- Track-I 的置信区间按用户聚类 Bootstrap。
- 同时报告均值、中位数、标准差/四分位距和有效样本数。
- 每个 K 值和资源类型子组都预先列出，不选择最好 K 才报告。

## 10. 策略指标

分别计算 `output_type`、`delivery_strategy` 和 `explanation_level`：

- Accuracy；
- Macro-Precision、Macro-Recall、Macro-F1；
- 每类 Precision/Recall/F1；
- 混淆矩阵。

若预测命中 `accepted_labels` 中任一标签即为正确。两维联合准确率要求输出类型和交付策略同时命中。

```text
不恰当主动推荐率 =
  标注要求GUIDED但系统输出DIRECT或DEGRADED的场景数
  / 标注允许的GUIDED场景数
```

`adaptation_state` 由反馈事实确定，单独报告规则正确率，不并入四类输出 Macro-F1。

## 11. 反馈指标

### 11.1 配对时间窗

每个明确负反馈定义：

```text
pre_window  = 反馈前最近 N 次合格推荐或 30 天，以先达到者为准
post_window = 反馈后接下来 N 次合格推荐或 30 天，以先达到者为准
默认 N = 5，由配置冻结
```

### 11.2 指标

```text
被拒资源排名变化 = post_rank - pre_rank
```

未再出现时按 `effective_limit + 1` 作为 post_rank，并进行敏感性分析。

```text
同主题曝光下降率 =
  (pre_topic_exposure_rate - post_topic_exposure_rate)
  / max(pre_topic_exposure_rate, epsilon)
```

只对 `reason_code=TOPIC_NOT_INTERESTED` 计算主题下降；`ALREADY_READ` 等资源级原因不得纳入。

```text
适应轮数 = 从反馈事实提交到目标资源首次不再出现在Top-K所需推荐轮数
```

同时报告 Outbox `PENDING` 时长和画像版本变化，区分反馈事实提交与派生画像生效。

## 12. 解释指标

| 指标 | 定义 |
|---|---|
| 证据覆盖率 | 解释中的可验证推荐主张数 / 全部推荐主张数 |
| 事实一致率 | 经 Evidence Validator 和人工抽检均可由 Evidence Bundle 支持的事实数 / 全部事实数 |
| 无依据陈述率 | 无合法 Evidence Ref 的具体事实陈述数 / 全部具体事实陈述数 |
| 可理解性 | 用户实验固定 Likert 题项 |
| 有用性 | 解释是否帮助判断资源适用性的固定 Likert 题项 |

LLM 输出校验失败后模板回退计入 `fallback_used`，不能从解释样本中排除。模板与 LLM 使用同一条目集合和 Evidence Bundle。

## 13. 多智能体与可靠性指标

### 13.1 定义

```text
Trace完整率 =
  具有全部预期阶段、输入摘要、结果状态和因果引用的任务数 / 全部任务数

降级成功率 =
  注入非核心故障后返回合法DEGRADED_COMPLETED且无伪造证据的任务数
  / 注入非核心故障的任务数

重规划成功率 =
  首计划不达质量门槛、重规划后达到门槛或形成合法同类型降级结果的任务数
  / 触发重规划的任务数

错误定位率 =
  Trace中的component和error_code同时命中预注册注入点的任务数
  / 注入故障任务数
```

### 13.2 Trace 完整条件

任务只有同时具备以下内容才算完整：

- `recommendation_task` 版本和时点；
- Intent、Profile、Probe 三个 PRE_PLAN Agent 结果；
- 策略决策和原因码；
- 每个计划通道的运行状态；
- 排序/重规划结果；
- 最终解释证据或明确模板回退；
- 完成/降级状态和 Warning；
- 消息因果链无断链。

### 13.3 延迟

报告任务端到端 P50/P95/P99、各 Agent P95、每通道 P95 和工具调用数。Mock LLM、真实 LLM、健康路径和故障路径分别报告，不混合计算一个无法解释的总体 P95。

## 14. 故障注入协议

### 14.1 注入矩阵

| ID | 注入点 | 故障 | 预期行为 |
|---|---|---|---|
| `F_VECTOR_TIMEOUT` | `VectorSearchPort` | 超时 | 移除 VECTOR；`semantic_score=NULL`；可继续 |
| `F_GRAPH_TIMEOUT` | `GraphSearchPort` | 超时 | 移除 GRAPH；解释无图路径 |
| `F_LLM_INVALID` | `LLMProviderPort` | 无效 JSON | 最多重试一次，规则/模板回退 |
| `F_LLM_TIMEOUT` | `LLMProviderPort` | 超时 | 规则意图或模板解释 |
| `F_CHANNEL_EMPTY` | 任一非核心 Recall Channel | 合法空集合 | 记录 `SUCCESS_EMPTY` 并按健康通道融合 |
| `F_LOW_RANK_QUALITY` | 排序质量门禁 | 候选不足/覆盖不足 | 最多重规划一次，然后合法降级 |
| `F_PROFILE_OUTBOX` | Profile Worker | 更新失败 | 反馈事实保留，Outbox 重试/DEAD，旧画像继续可读 |
| `F_MYSQL_DOWN` | 核心存储 | 不可用 | `503 CORE_STORAGE_UNAVAILABLE`，不返回孤立派生结果 |

### 14.2 实现限制

故障只通过 `FaultInjectingVectorStore`、`FaultInjectingGraphStore`、`FaultInjectingLLMProvider` 和受控 Worker 装饰器注入，并且仅在 `APP_ENV=test` 或签名实验配置下启用。不得通过破坏持久化目录、停止并清理数据卷或修改正式数据来制造故障。

### 14.3 运行设计

- B3 与 Proposed 对每个故障类型使用相同任务、时点、种子和持续时间。
- 每种故障至少覆盖明确任务、模糊任务、书单和阅读路径场景。
- 注入顺序使用冻结的随机排列，防止缓存/预热系统性偏向。
- 每次注入前后运行只读健康检查和对象计数；对象数量减少视为安全失败，实验立即停止。

## 15. 用户实验协议

### 15.1 设计

采用被试内交叉设计比较 B2 与 Proposed：

- 任务一：专题资料查找；
- 任务二：系统学习路径；
- 任务三：模糊需求澄清；
- 为两个系统准备难度匹配但主题不同的 A/B 任务集；
- 使用 AB/BA 或拉丁方平衡系统、主题和任务顺序。

不直接固定最终样本量。先以预实验估计主要终点效应量，再执行配对设计功效分析；24 人仅作为原型最低可行目标，不作为充分功效的先验保证。

### 15.2 参与者

正式招募前冻结：

- 纳入条件：在校研究生或具有文献检索/学习任务经验的同等用户；
- 排除条件：未完成核心任务、技术故障导致主要数据缺失、未通过注意力检查；
- 退出规则：参与者可随时停止，不影响其权益；
- 补偿方式、隐私说明和伦理审批/导师确认编号。

无效样本判定必须由与系统条件无关的规则产生，并报告排除数量及原因。

### 15.3 记录项

| 类别 | 指标 |
|---|---|
| 行为 | 任务完成率、完成时间、点击、收藏、追问轮数、主动修改次数 |
| 主观 | 满意度、信任度、解释有用性、认知负担 |
| 过程 | 系统顺序、任务主题、技术故障、是否使用降级 |

量表题项、量程、正反向计分和问卷顺序在首位正式参与者开始前冻结。

### 15.4 用户实验统计

- 配对二元任务完成率：McNemar 检验并报告配对差异置信区间。
- 连续/序数数据：先查看分布；正态近似合理时配对 t 检验，否则 Wilcoxon signed-rank。
- 报告效应量：配对 Cohen's dz 或 rank-biserial correlation。
- 对同一研究问题的次要终点执行 Holm 校正。
- 同时报告顺序效应和任务主题效应的敏感性分析。

## 16. 性能实验

### 16.1 固定健康路径

```text
数据：论文演示规模及预构建索引
状态：MySQL、Chroma、Neo4j健康，LLM=mock
预热：5分钟
采样：10分钟
并发用户：20
比例：推荐70%、反馈20%、画像读取10%
evaluation_at：固定
```

建议工程门槛：推荐接口 P95 < 2 秒、反馈接口 P95 < 500 毫秒、错误率 < 1%。这些是运行目标，不等同于研究假设。

### 16.2 分层报告

分别报告：

- Mock LLM 健康路径；
- 外部 LLM 路径；
- Vector/KG 单点故障路径；
- MySQL-only 降级路径。

报告硬件、操作系统、并发模型、数据规模、连接池、镜像摘要和索引版本。

## 17. 随机性与重复运行

默认固定五个种子：

```text
20260802
20260803
20260804
20260805
20260806
```

种子控制 Split、同分候选随机化（若有）、Bootstrap 和实验顺序。确定性 Mock 路径在相同快照、配置、索引、时点和种子下必须产生相同顺序与分数；同分最终使用 `resource_id` 升序稳定处理。

主结果按五个种子整体报告均值和种子间方差。完全确定的系统可产生相同结果，但仍记录全部种子运行以验证稳定性。

## 18. 统计分析计划

### 18.1 配对原则

所有系统比较以相同任务/用户作为配对单位。不得把每个推荐条目误当成独立样本。

### 18.2 离线指标检验

- 主要方法：按任务配对差异的 Bootstrap 95% 置信区间，Track-I 按用户聚类抽样。
- 辅助检验：Wilcoxon signed-rank；大量全零差异时报告适用限制。
- 报告均值差、中位数差和效应量，不只报告 p 值。
- RQ1 的主要终点显著性阈值 `α=0.05`；次要比较按研究问题使用 Holm 校正。

### 18.3 分类指标检验

- Accuracy 配对比较使用 McNemar 检验。
- Macro-F1 使用场景级 Bootstrap 置信区间。
- 报告完整混淆矩阵和每类支持数，避免类别不平衡被总体 Accuracy 隐藏。

### 18.4 缺失与失败

- 系统无结果在排序指标中按空列表计，不作为缺失排除。
- 因全局数据问题排除的任务必须对全部系统同时排除。
- 组件故障属于实验自变量，不能当作异常值清除。
- 用户量表缺项不插补主要结果；报告 Complete-case 数量并执行预注册敏感性分析。

### 18.5 探索性分析

按资源类型、用户画像置信度、主题频率和任务类型的子组分析均标记为探索性，除非在正式测试前通过 Amendment 提升为确认性分析。

## 19. 冻结规则

### 19.1 冻结层级

| Freeze | 时点 | 必须冻结的内容 |
|---|---|---|
| F0 协议冻结 | 实现正式实验脚本前 | RQ、系统定义、消融、指标、排除和统计方法 |
| F1 数据冻结 | Split 生成前 | 输入文件、字段映射、匿名化、数据集 Manifest 与哈希 |
| F2 Split 冻结 | 调参前 | 时间边界、Group、train/validation/test 清单与哈希 |
| F3 模型配置冻结 | 首次测试运行前 | 代码提交、依赖锁、配置、Prompt、公式、索引、随机种子 |
| F4 预测冻结 | 指标计算前 | 每个系统的 `predictions.jsonl` 和 Trace 摘要 |
| F5 报告冻结 | 论文表图生成后 | 指标、统计输出、表、图和生成脚本版本 |

### 19.2 测试集开启规则

只有以下条件全部满足才允许运行测试集：

- 验证集调参日志完成；
- 主要配置状态为 `FROZEN`；
- 工作区代码已提交，且 Run 记录 Git Commit；
- 输入数据、Split、标注集、配置和依赖哈希均存在；
- A01—A25 中与实验相关的验收通过；
- dry-run 证明所有写入只进入新的 Run 目录，`expected_delete_count=0`；
- 同名 Run ID 不存在。

### 19.3 Amendment

冻结后发现问题时：

1. 保留原协议和原运行；
2. 新建 `experiments/amendments/{amendment_id}.md`；
3. 记录发现时间、是否已查看测试结果、原因、影响指标和修复；
4. 提升协议/配置版本并使用新的 Run ID；
5. 论文同时披露原结果与修订影响，不能覆盖原产物。

## 20. 实验产物

### 20.1 Run 目录

```text
experiments/runs/{run_id}/
├── run_manifest.json
├── config.json
├── environment.json
├── dataset_manifest.json
├── split_manifest.json
├── predictions.jsonl
├── metrics.json
├── statistical_tests.json
├── agent_metrics.json
├── exclusions.jsonl
├── checksums.sha256
├── logs/
└── tables/
```

### 20.2 `run_manifest.json` 必填内容

```text
run_id
protocol_version
system_id
ablation_id或null
evaluation_track
git_commit
git_worktree_dirty
dependency_lock_hash
container_image_digests
dataset_version和hash
split_version和hash
annotation_version和hash
config_version和hash
policy/ranking/profile/prompt/embedding/graph版本
evaluation_at或时间边界
random_seed
timezone
started_at/finished_at
runner_version
```

正式结果要求 `git_worktree_dirty=false`。开发 Dry-run 可以为 true，但不能进入论文确认性表格。

### 20.3 `predictions.jsonl` 最小字段

每行一个任务—系统结果：

```json
{
  "run_id": "proposed-test-seed-20260802-v1",
  "system_id": "Proposed",
  "task_id": "eval-task-0001",
  "user_research_id": "u-hash-001",
  "evaluation_at": "2026-06-01T00:00:00.000Z",
  "status": "COMPLETED",
  "output_type": "TOPIC_RESOURCES",
  "delivery_strategy": "DIRECT",
  "adaptation_state": "NORMAL",
  "resource_ids": [11, 52, 103],
  "scores": [0.91, 0.84, 0.77],
  "warnings": [],
  "trace_complete": true,
  "versions": {
    "config": "rec-1.0.0",
    "dataset": "evaluation-v1"
  }
}
```

研究导出使用不可逆研究 ID，不输出业务用户 ID。

### 20.4 不可覆盖规则

- `run_id` 对应目录已存在时，任何脚本立即失败。
- 修复或复算使用新的 Run ID，并在 Manifest 引用前一 Run。
- 不自动清理失败运行、旧预测、日志、索引或图表。
- 构建报告只读冻结预测和指标，不修改它们。
- 若确需物理删除任何产物，必须先按项目安全规则向用户提交精确目标、哈希、影响、备份和恢复报告，并获得单次明确批准。

## 21. 执行命令职责

计划提供以下互不混淆的脚本：

```bash
python scripts/prepare_evaluation_split.py \
  --manifest data/evaluation/dataset_manifest.json \
  --output data/evaluation/splits/v1

python scripts/run_experiment.py \
  --config experiments/configs/proposed_full.json \
  --split data/evaluation/splits/v1 \
  --run-id proposed-test-seed-20260802-v1 \
  --seed 20260802

python scripts/evaluate_results.py \
  --run-id proposed-test-seed-20260802-v1

python scripts/build_experiment_report.py \
  --run-id proposed-test-seed-20260802-v1
```

职责：

| 脚本 | 唯一职责 |
|---|---|
| `prepare_evaluation_split.py` | 校验数据、按协议生成并冻结 Split |
| `run_experiment.py` | 执行一个系统/消融，写冻结预测和运行环境 |
| `evaluate_results.py` | 只读预测与标注，计算指标和统计检验 |
| `build_experiment_report.py` | 只读指标，生成论文表格与图 |

每个脚本默认 Dry-run 或只读；涉及新产物写入时必须检查目标不存在、输入哈希匹配和预计物理删除数为 0。

## 22. 可复现性检查

每个正式 Run 必须通过：

```text
REP-01 独立环境可从锁文件安装依赖
REP-02 Git Commit和工作区状态已记录
REP-03 数据、Split、标注、配置和Prompt均有SHA-256
REP-04 相同输入与种子重复运行，Mock路径结果完全一致
REP-05 指标可由冻结predictions.jsonl独立复算
REP-06 报告可由metrics.json独立生成
REP-07 历史时点测试证明未来行为、资源和热度不泄漏
REP-08 每个最终推荐项至少有一个召回证据
REP-09 所有排除均有预注册原因码
REP-10 运行前后受保护对象数量未减少
```

## 23. 伦理与隐私

1. 数据使用前记录来源、许可、用途和保存范围。
2. 用户实验取得知情同意，并说明推荐系统为研究原型。
3. 研究导出进行去标识化，映射密钥与实验结果分开保管。
4. 不采集与研究问题无关的敏感属性。
5. LLM 请求不得包含不必要的用户身份和完整历史行为。
6. 公开论文只发布聚合指标；小样本子组避免可识别披露。
7. 用户撤回后先停止新增处理并记录撤回状态；涉及物理删除时遵循项目的删除前汇报和审批流程。

## 24. 威胁与限制的预注册披露

论文至少讨论：

- 候选池标注只能比较并集内资源；
- 合成行为不能替代真实偏好；
- 原型数据规模和单校样本限制外部效度；
- B2/B3 的实现选择可能影响基线强度；
- 模板与外部 LLM 的表达质量受模型版本影响；
- 时间过滤依赖 `available_from` 的可信度；
- 用户实验存在学习、顺序和主题偏好效应；
- 多智能体与模块化编排同时变化时，准确区分机制贡献需要消融支持。

## 25. 正式实验启动门禁

```text
[ ] 选择并记录RQ1主要评价轨道
[ ] 数据来源和伦理条件明确
[ ] dataset_manifest及全部输入哈希冻结
[ ] train/validation/test边界冻结
[ ] 相关性和策略标注一致性达到预注册报告要求
[ ] B0—B3及Proposed配置可独立运行
[ ] 全部消融只改变一个组件
[ ] 历史重放A25通过
[ ] 幂等、确定性和故障注入验收通过
[ ] 主要终点和统计脚本在测试集前冻结
[ ] Git工作区已提交且正式Run为clean
[ ] Run ID唯一且输出目录不存在
[ ] dry-run证明expected_delete_count=0
[ ] 备份/输入原件和旧Run不被覆盖
```

任一门禁未通过时只能执行开发/验证 Run，不能将结果标记为论文确认性实验。

仓库提供只读前置检查：

```bash
FREEZE_RUN_ID=freeze-<unique-id> make verify-experiment-freeze \
  PYTHON=.venv-g1-release-py311/bin/python
```

检查器只读取协议、数据 Manifest、种子和 Git 状态，并把一份新的
`freeze-preflight.json` 写入 `artifacts/verification/experiment/<run_id>/`；
同名目录存在时直接失败，不覆盖旧证据，也不连接数据库。当前仓库的
`synthetic-demo-2026-08` 仅用于开发/演示，因此预期报告为
`PASS_WITH_BLOCKERS`，明确标记 `DEMO_FIXTURE`、缺少正式 Split/标注和配置
Manifest；在真实数据来源、许可、匿名化、标注和 Split 完成前，不能把它升级为
论文确认性实验。

### 25.1 五类输入 Manifest 契约

正式数据入口不直接接受散落的 CSV、JSONL 或人工说明，而是接受以下五类独立
Manifest。每个 Manifest 使用严格 JSON Schema，未知字段、路径穿越、缺少哈希或
版本字段都会阻断门禁：

| Manifest | Schema | 关键冻结内容 |
|---|---|---|
| Dataset | `contracts/experiment/dataset-manifest.schema.json` | 来源、Track、输入文件哈希、匿名化状态、规模和确认性资格 |
| License | `contracts/experiment/license-manifest.schema.json` | 每个来源的许可范围、证据引用、署名和限制、审批状态 |
| Annotation | `contracts/experiment/annotation-manifest.schema.json` | 盲标注、至少两名独立标注者、一致性、仲裁和测试集冻结 |
| Split | `contracts/experiment/split-manifest.schema.json` | train/validation/test 文件哈希、时间边界、Group 泄漏和不重叠约束 |
| Config | `contracts/experiment/config-manifest.schema.json` | Git Commit、依赖锁、配置 Bundle、策略/公式/索引版本、输入引用和随机种子 |

`data/evaluation/` 只放经授权、脱敏且由项目负责人确认可用于研究的数据及其
Manifest；本仓库不把任何真实用户数据、身份映射或许可证凭证提交到 Git。配置
Manifest 的 `input_refs` 必须同时匹配四个输入 Manifest 的路径和 SHA-256，避免
运行时悄悄替换数据或标注。

### 25.2 输入冻结前置检查

```bash
EVAL_INPUT_RUN_ID=eval-inputs-<unique-id> make verify-evaluation-freeze-inputs \
  PYTHON=.venv-g1-release-py311/bin/python
```

`scripts/verify_evaluation_freeze_inputs.py` 只读五类 Manifest 及其引用文件，
在 `artifacts/verification/experiment-inputs/<run_id>/input-freeze-report.json`
追加一份新证据；同名目录直接失败，不覆盖历史报告，不连接数据库，不删除或
更新任何输入。默认使用已提交的 G2 演示 Manifest 以便立即发现 `SYNTHETIC_DATASET`
阻断；正式数据准备完成后用 `--dataset data/evaluation/dataset_manifest.json`
显式切换。只有报告为 `READY_FOR_FORMAL_RUN` 且 F1、F2、F3、盲标注门禁全部通过，
才允许继续生成预测产物。

### 25.3 智慧图书馆书目接入门禁

论文演示所需的书目数据与正式评价数据分开管理。用户提供的爬取结果先放在本地
`data/incoming/books/`（该目录被 `.gitignore` 保护，不进入提交），不得直接执行
SQL/Cypher 导入。接入前必须准备：

| 输入 | 契约/要求 |
|---|---|
| 规范化记录 | `contracts/data/intake/book-record.schema.json`；JSONL、UTF-8、无用户身份，未知字段拒绝 |
| Intake Manifest | `contracts/data/intake/book-intake-manifest.schema.json`；来源、许可证据、输入文件字节数/SHA-256、解析/映射版本、隐私状态和 MySQL/Neo4j 目标 |
| 许可证据 | 许可证文件的 SHA-256 或可审计的 HTTP/DOI 引用；来源不明、超出许可范围或无法核验时阻断 |
| 安全审查 | `verify-book-intake` 只读校验路径、哈希、重复 `source_record_id`/ISBN/标签、规范化状态和用户数据标记 |

执行命令：

```bash
BOOK_INTAKE_RUN_ID=books-intake-<unique-id> make verify-book-intake \
  PYTHON=.venv-g1-release-py311/bin/python
```

检查器把新报告写入 `artifacts/verification/data-intake/<run_id>/`，不连接数据库，
同名目录直接失败；当前未提供书目时预期为 `PASS_WITH_BLOCKERS`，不能伪造示例数据
来消除阻断。只有报告 `can_import=true`、工作区已提交且用户确认来源/许可后，才可
为 MySQL `resource_catalog` 生成新的 append-only 导入 ChangePlan；Neo4j 必须写入
新的 `graph_version` 影子图，校验节点/关系计数、输入哈希和抽样结果后才允许登记
活动版本，旧图版本不可删除或覆盖。

数据平面只读健康检查：

```bash
DATA_PLANE_RUN_ID=data-plane-<unique-id> make verify-data-plane-runtime \
  PYTHON=.venv-g1-release-py311/bin/python
```

该命令只读取 Compose 服务健康状态、MySQL 表数量和 Neo4j 节点/关系数量；不会启动、
停止、迁移、导入、清空或删除任何服务、卷和数据。当前证据显示 MySQL 40 张表、
Neo4j 0/0，说明数据库容器可用但图召回链路尚未完成。

## 26. 结果解释边界

- RQ1 显著：可以主张在当前数据、任务和配置下改善相应排序指标，不能自动外推到所有图书馆。
- RQ2 显著：可以主张动态策略更符合标注/用户任务，不能仅凭策略准确率声称推荐相关性提高。
- RQ3 显著：可以主张反馈闭环减少特定拒绝原因下的后续曝光，需同时报告长期主题误伤风险。
- RQ4 显著：可以主张编排机制提升适应性、容错或可追踪性；不能声称“Agent 越多越准确”。
- 不显著或效应很小的结果同样完整报告，并分析功效、样本和实现限制。
