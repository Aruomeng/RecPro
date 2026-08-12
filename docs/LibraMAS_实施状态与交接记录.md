# LibraMAS 实施状态与交接记录

> 状态版本：4.0
> 更新时间：2026-08-12
> 用途：保存长期任务主干和当前工作集，避免多阶段实施过程中目标、约束和证据漂移

---

## Task Spine

- `objective`：依据最新版实施文档，安全实现一个可运行、可降级、可追溯、可验证的多智能体智慧图书馆推荐原型。
- `success_criteria`：完成G0—G10；A01—A25、安全测试、六场景E2E和新环境复现全部通过；论文实验可以独立复算。
- `constraints`：
  - 未经用户查看详细报告并明确批准，不得删除任何文件。
  - 未经用户查看详细报告并明确批准，不得物理删除任何数据库数据或对象。
  - 不得运行自动清理、删卷、降级迁移、强制Git还原或覆盖实验run的操作。
  - 每个阶段必须有真实产出、验证证据、安全检查和退出门禁。
  - 架构采用模块化单体与端口适配器，保持低耦合、高内聚。
- `environment`：
  - 工作区：`/Users/tianyuhang/Documents/RecPro`
  - Git 分支：`codex/g1-runnable-skeleton`；G0 主提交：`cb926d910e8253a8b88c30ecdd656e51b1789594`；G0 交接提交：`e1c4bae03659ef43ebb81c6a6472e74ce189eef5`；远程：`https://github.com/Aruomeng/RecPro.git`。
  - 当前验证环境：Python 3.11.14、Node 25.6.0、npm 11.8.0、MySQL 客户端 9.3.0、Docker 29.3.1、Docker Compose 5.1.1、GitHub CLI 2.97.0。Docker Desktop 位于 `/Applications/编程/Docker.app`，当前需显式加入其资源目录到 PATH；`gh` 已安装但尚未认证。
  - macOS 元数据文件已保留并由 `.gitignore` 忽略，未删除、未提交；Finder 可自动更新或新建这类文件，本项目不对其执行清理或哈希回写。
  - 当前 Compose 项目为 `recpro-g2-tianyuhang-20260809a`。本轮只读检查了该隔离项目：MySQL 健康、业务库共有 40 张表；Neo4j 健康、节点数 0、关系数 0。未连接或修改用户未明确授权的其他业务数据库，未执行迁移、导入、清空或删除。
  - 用户提供的 MySQL/Neo4j 管理凭据已保存至本机 `.env.user-secrets`（`0600`、Git 忽略、未提交）；不会在日志、报告或 Agent 上下文中输出密码。MySQL 运行时仍使用最小权限账号，root 仅用于后续受控管理/迁移。
  - 只读盘点发现本机另有 Homebrew Neo4j（`127.0.0.1:7474/7687`），默认 `neo4j` 库有 59,301 个节点、185,238 条关系；只读查询后未写入、清空、删除或停用该实例。RecPro 不使用该实例。
  - 已创建新的 RecPro Neo4j 隔离实例 `recpro-library-neo4j-20260810a`，独立数据卷 `recpro-library-neo4j-20260810a_neo4j_data`、端口 `62475/62688`，用户凭据认证成功，初始节点/关系为 0/0；旧 RecPro 空实例未删除或复用。
  - `Lib` 已完成只读 CSV 结构审查与版本化图计划：76 个文件、15,538 条来源记录、63,388 个节点、191,865 条关系；图版本 `lib-books-v1-20260810` 已追加到独立 RecPro Neo4j，当前计数与计划一致。
- `decisions`：
  - 用户最新零删除要求优先于旧实施文档中的reset、destroy和clear语义。
  - `demo-reset`替换为新 `fixture_generation/test_run_id`。
  - 数据纠错、撤销和停用使用版本或补偿事件。
  - Chroma和Neo4j重建使用新版本构建与活动指针，不删除旧版本。
  - 代码按Catalog、Profile、Recommendation、Feedback、Observability、Platform等业务域组织。
  - 正式论文实验只能在G8发布候选通过后开始。
  - Neo4j 图导入使用独立实例、显式 `graph_version`、节点/关系唯一键和 `MERGE` + `ON CREATE SET`；不使用本机已有图，也不执行删除/清空/覆盖。
  - DeepSeek 仅作为显式 opt-in 的 LLM 适配器；默认仍为 MockLLM，缺少本地 API key 时配置 fail-closed。
- `completed_work`：
  - 已完成最新版可运行实施文档。
  - 已完成安全、低耦合、高内聚的系统实施计划。
  - 已建立本交接记录。
  - 已验证计划文档代码围栏成对、JSON示例合法、相对链接目标存在，且需求基线哈希未变化。
  - 已完成零删除政策、删除前汇报模板、G0 基线清单和两份架构 ADR。
  - 已完成 `book-graph-plan-v1` Schema、实体/关系模型、确定性节点/三元组构建器、SHA-256 绑定和只读 Neo4j 导入预演；已生成 `lib-graph-plan-20260810-002`，预演读取目标 0/0 且数据库写入 0。
  - 已完成用户授权后的 Neo4j 追加导入：首轮导入 63,388 个节点、191,865 条关系和 10 个唯一约束；同一 graph_version 第二次幂等复验前后计数不变，未产生重复数据。
  - 已完成 MySQL 书目事实层的数据库无关 ChangePlan：映射 `resource_catalog`、`resource_book_detail`、`tag_dictionary`、`resource_tag`、`resource_index_state` 五张现有表；计划包含 14,983 本书、8,516 个标签和 70,750 条资源标签关系，状态 `PASS_WITH_WARNINGS`，安全计数为 0 读/0 写。
  - 已完成 MySQL 计划严格 Schema、行级校验和显式双确认导入器；默认干跑不连接数据库，实际写入必须同时提供 `--apply --confirm-mysql-write`，非空目标还需单独 `--allow-nonempty-target`。用户确认后已在隔离 Compose MySQL 追加 14,983 本书、8,516 个标签和 70,750 条标签关系，并完成幂等复跑与独立只读计数核验。
  - 已完成 Neo4j 只读图召回端口与可选 Agent 通道：使用参数化 Cypher、固定 `graph_version` 和外部稳定 ID 映射，不提供任何图写操作；对独立图目标的只读查询已返回命中结果，未写入 Neo4j。
  - 已完成确定性向量索引 ChangePlan 与离线构建器：从已审核 MySQL ChangePlan 生成 14,983 条 `hash-char-ngram-v1`/384 维向量记录；两次独立构建哈希一致，质量提示和向量完整性均有证据；本阶段未写入 MySQL、Chroma 或 Neo4j。
  - 已完成向量计划 Schema、逐行哈希/维度校验器和数据库无关完整性报告；已新增版本化只读 `VectorRecallPort`/`ChromaVectorReader`、cosine 分数映射、元数据版本隔离和故障降级测试；MySQL `embedding_status` 仍保持 `PENDING`。
  - 已完成数据库无关的 Chroma collection ChangePlan 与独立校验器：冻结 `library_resources__hash_char_ngram_v1`、cosine、`hash-char-ngram-v1`、`lib-books-vector-v1-20260811`、14,983 条记录、metadata 版本过滤和 append-only/零破坏策略；客户端已锁定 `chromadb==1.5.9` 并仅用于隔离 operator venv。
  - 已在用户明确授权后创建正式 Chroma collection 并追加 14,983 条向量；全量回读验证、版本/元数据验证、数值容差验证、召回冒烟、幂等复跑和独立只读 verifier 均 PASS。首次验证因 Chroma 1.5.9 的 NumPy 返回类型兼容性阻断，现场和失败证据均保留，未执行任何清理或覆盖。
  - 已准备 DeepSeek OpenAI-compatible 适配器、HTTPS/密钥 fail-closed 配置、Mock 默认和适配器契约测试；用户提供的 DeepSeek 密钥已写入本机被 Git 忽略且权限为 `0600` 的 `.env.host`/`.env.compose`，未写入仓库，未发起外部请求。
  - 已完成版本化 Prompt Bundle：`contracts/prompts/rec-prompts-v1.0.0.json`（`prompt-v1`）及严格 Schema、变量白名单、上下文上限、输出 Schema、工具零授权和 SHA-256 绑定；新增只读 `verify_prompt_bundle` 门禁与 Prompt 配置文档。
  - 已完成 DeepSeek Prompt 接入：四个能力统一使用 Prompt Bundle，LLMResult 增加 `prompt_id/prompt_sha256/request_id/attempts` 审计字段；无效 JSON/结构输出最多一次重试，证据引用越权 fail-closed。
  - 已完成显式 LLM Intent Agent：`LLMIntentUnderstandingAgent` 只消费文本分类结果，主题词/资源类型仍由规则生成；外部 provider 异常、超时或空输入自动降级，默认规则编排和默认 HTTP/Worker 不改变。
  - 已完成 G6 低耦合只读检索融合接线：新增 `QueryEmbeddingPort`/`HashCharNgramQueryEmbedder`，`CatalogCandidateRecallAgent` 可通过显式组合根融合 Neo4j GraphRecall 与 Chroma VectorRecall；版本、超时、证据引用和故障降级均由 fake/隔离测试覆盖，默认 MySQL-only 路径不变。
  - 已冻结数据字典、HTTP API、OpenAPI、Agent/Policy/状态机、配置 Bundle、ChangePlan 和错误码契约。
  - 已冻结 RQ1—RQ4、B0—B3、Proposed、消融、指标、时间切分和实验产物协议。
  - 已冻结 A01—A25 的首次实现 Gate、最终复验 Gate 和证据要求。
  - 已建立安全、架构、文档、Schema/枚举一致性门禁和 GitHub Actions 工作流。
  - `make verify-g0` 已通过：安全扫描 28 个可执行文件、架构扫描 8 个后端文件、13 个 Markdown/42 个结构化示例、8 个 JSON 契约和 125 个自动化测试均无失败。
  - G0 全量工作集已由详细本地提交 `cb926d910e8253a8b88c30ecdd656e51b1789594` 版本化，提交后逐历史零删除检查通过。
  - 已完成 G1 后端健康切片：只提供 live/ready，配置 Bundle 执行严格 JSON、固定 Schema 哈希、JSON Schema 与跨字段语义校验；MySQL readiness 校验数据库身份、项目探针、字符集、最小读写能力和危险授权；MockLLM 与 Worker 骨架不产生推荐结果。
  - 已完成 G1 Vue 只读状态页、严格 API 响应校验、请求超时/取消、追加式构建/预览和非 root Nginx 容器；领域、API、展示和组件边界保持单向依赖。
  - 已完成五服务隔离 Compose、新卷专用最小权限初始化、create-only 配置引导、严格环境校验及双次安全停止/复启验收器；验收器不包含删容器、删卷或删数据操作。
  - G1 实现已拆分为后端 `5c2eb55063ab8f01af2de925993440b27d584c2c`、前端 `c9e780e0a2a76b7c75d9b12108551bb1132769e0`、编排 `6be3e27274f752e9e86ba4039aeb4dccd68285d2` 三个详细提交。
  - G1 本地门禁已通过：当前 G0 回归 131 项、G1 Python 103 项、前端 33 项、编排定向 47 项；全新 Python/Node 隔离安装、`pip check`、npm 审计、类型检查、生产构建和桌面/移动浏览器验收均通过。
  - G1 真实运行态验收已通过：证据 run `g1-runtime-20260802-014` 绑定提交 `6f7d6581d5087ce02b26542f8d3ce20df5e52b98`；五个服务两轮均 healthy、restart_count=0，三卷身份不变，探针计数重启前后均为 1，验证器数据库动作仅 4 次 SELECT，删除、UPDATE、DDL、验证器写入和破坏性动作均为 0。
  - G2 已完成：新增 Catalog Repository/UoW 端口与 MySQL 适配器、确定性 dataset manifest/质量报告、VECTOR/GRAPH 版本化索引计划与 Outbox 骨架；全新卷运行证据覆盖迁移、seed、画像重放、索引计划两次幂等。
  - G3 已开始：新增 MySQL-only 推荐前向迁移、规则意图、三路 MySQL 召回、RRF/有界 MMR、模板解释和可幂等 CLI 持久化演示；全新卷已产生 5 条带证据推荐项和 Trace。
  - G3 API 首个垂直切片已完成：严格 DTO、场景/Limit 校验、演示身份、请求幂等键、统一错误映射和可注入 `RecommendationTaskService` 端口已接入；默认运行配置仍不挂载推荐路由。
  - G3 API MySQL 适配已通过真实运行态：新增前向任务状态转移审计表，API 新建/重放/状态查询和 Trace 读取均在隔离 MySQL 上通过；全程只追加写入。
  - G3 受控调试与澄清分支已完成：新增正式 Bearer 身份注入边界、research-admin Debug context/trace/policy HTTP、澄清问题与答案的版本化追加表；普通用户和 Demo 身份不能提升为 `research_admin`。
  - G3 澄清运行态已通过：隔离 MySQL 上验证 `WAITING_CLARIFICATION -> context_version=2 -> COMPLETED`、澄清幂等重放、任务状态、Trace、上下文和策略查询；新增事实全部为 INSERT，destructive_actions=0。
  - G4 第一垂直切片已启动并通过：新增进程内 Agent Registry、结构化 AgentMessage/AgentResult dispatch 边界和唯一 Orchestrator；确定性规则 Agents 已覆盖 DIRECT、GUIDED 早停、DEGRADED 和最多一次 REPLANNING 四条路径。
  - G4 Agent 执行日志持久化小步已通过：新增 append-only message/result/artifact/最终编排结果表、事务端口和 MySQL 适配器；隔离 MySQL 验证同一事务提交、幂等重放不增行、回滚不留行。
  - G4 真实只读端口小步已通过：新增 ProfileSnapshotReader 与 MySQL 画像投影适配器，Catalog/Profile/Semantic/Recall Agent 只依赖端口；显式组合根接入真实只读查询，固定 `evaluation_at`，并以最多两次无退避重试和 deadline fail-closed 处理依赖异常。
  - G4 真实端口隔离运行态已通过：7 次 Agent dispatch 完成，画像 event_count=4、Catalog resource_count=5、candidate_count=5；运行前后六张资源/画像事实表行数一致，端口路径 INSERT/UPDATE/DELETE 均为 0。
  - G4 显式 Demo/Research 组合根与持久化 service 已通过：根级 builder 才能装配 MySQL adapters，默认 FastAPI 不调用；持久化 service 要求冻结 `evaluation_at/deadline_at`，同一事务追加 7 message、7 result、1 trace artifact、1 final orchestration result，异常回滚且不提交。
  - G5 第一反馈垂直切片已通过：新增曝光、反馈、资源状态的前向表和严格领域命令；反馈 UUID/行为 event UUID 幂等，曝光与行为事实同事务追加，反馈可生成受控 Profile outbox。
  - G5 Profile outbox worker 已通过隔离 MySQL 运行态：使用显式受控写凭据 claim/apply/mark-done，基于固定 `as_of` 调用确定性画像重放；9 条待处理 outbox 全部完成，负向主题画像被物化，重复消费不增事实行。
  - G5 Worker retry/DEAD 边界已补齐：重复 claim 不回收 DONE，失败保留同一 Outbox 行并可重试，达到最大次数进入 DEAD；新增故障契约测试。
  - G5 opt-in Interaction HTTP 已接入独立路由：曝光批量、反馈、直接行为 DTO、演示/正式身份边界、Idempotency-Key、错误码映射和派生行为拒绝均已实现；默认 FastAPI 不挂载交互服务，因此仍保持关闭。
  - G5 运行账号权限已收敛：G5 前向迁移后由操作脚本只授予 `user_resource_state` 四个投影列的 UPDATE；readiness 白名单同步校验，应用不持有 root 或 migration 凭据。
  - G5 HTTP/MySQL 真实运行态已通过：`g5-http-20260810-004` 验证曝光/反馈/直接行为首写与重放、状态投影更新、15 条 Outbox 全部 DONE、受保护资源表计数不变；全程无删除、DROP、ALTER 或清空。
  - G5 Worker 故障/恢复真实运行态已通过：`g5-worker-recovery-20260810-001` 在真实 MySQL 上将 Outbox 20 注入三次失败并保留为 `DEAD/attempts=3`，Outbox 21 在 MySQL 重启后仍为 `PENDING`，随后由真实 Worker 消费为 `DONE`；重启前后事实计数一致，Outbox 行数未改变。
  - G5 状态迁移审计与历史画像真实运行态已通过：`g5-audit-replay-20260810-001` 新增 `domain_state_transition`，覆盖 Outbox 创建/claim/DONE 和画像版本迁移；`MySQLProfileSnapshotReader` 按 `as_of` 只读重算，早/晚快照事件数 20/21、重复读取哈希一致且读取阶段计数不变；HTTP 资源状态审计和 Worker 故障恢复均在后续运行中复验通过。
  - 正式 Bearer 身份最小切片已完成：新增 Platform HS256 JWT 验证适配器，严格校验 `typ/alg/iss/aud/sub/roles/exp` 及可选 `nbf/iat/jti`，只向 API 注入 `AuthenticatedPrincipal`；`RECPRO_AUTH_ENABLED`、Secret、issuer、audience 和时钟偏差均由配置显式控制，默认关闭。
  - 正式认证安全运行态已通过：`g5-formal-auth-20260810-001/runtime.json` 验证默认业务路由 404、合法用户 Bearer 201、非法 Token 401、Bearer 与 Demo Header 混用 403、research-admin Debug 200、普通用户/混用身份 Debug 403；该验证不连接数据库，数据库读写和破坏性动作均为 0。
  - 生产 HTTP 组合根门禁已完成：`build_production_http_app()` 只接受 production 环境、`RECPRO_PRODUCTION_HTTP_ENABLED=true`、正式 Bearer Secret 和 Recommendation/Feedback/Behavior 完整服务图；默认模块级 FastAPI 与 Compose 仍关闭，构造阶段不连接数据库。
  - 论文实验冻结前置检查已完成：`verify_experiment_freeze` 校验协议/Manifest/seed 哈希与 Git clean 状态，并以新证据报告当前 `synthetic-demo-2026-08` 只能开发/演示，缺少正式 F2 Split、标注和 F3 配置 Manifest；该检查不连接数据库、不覆盖旧 Run。
  - 已完成正式评价输入契约第一小步：新增 Dataset、License、Annotation、Split、Config 五类严格 JSON Schema；所有关键路径、输入文件、哈希、匿名化、盲标注、一致性、时间边界、Group 泄漏和 F3 配置引用均以独立 Manifest 表达，未知字段默认拒绝。
  - 已完成只读评价输入冻结校验器：`verify_evaluation_freeze_inputs` 验证五类 Manifest 的 JSON Schema、引用文件 SHA-256、跨 Manifest dataset_version、许可覆盖、标注仲裁、Split 安全属性、配置 Commit/依赖/Bundle 哈希和输入引用一致性；同名证据目录直接失败，不连接数据库、不删除或覆盖输入。
  - 已完成数据平面只读健康门禁：`verify_data_plane_runtime` 只读取 Compose 服务状态、MySQL 表数量和 Neo4j 节点/关系数量；干净工作区证据 `data-plane-20260810-003` 为 PASS，MySQL=40 张表、Neo4j=0/0，database_writes=0、actual_delete_count=0、service_start_stop_actions=0。
  - 已完成图书数据接入前置契约：`book-record.schema.json` 固化脱离用户身份的规范化书目记录，`book-intake-manifest.schema.json` 固化来源、许可、文件 SHA-256、规范化、隐私和 MySQL/Neo4j 目标；`inspect_book_intake` 只读校验 JSONL、重复主键/ISBN/标签、许可引用和路径安全，在没有用户数据时明确阻断，不连接数据库。
  - 已完成 G5 Worker 运行态接线：`backend.app.worker` 以配置包校验和 `RECPRO_WORKER_ENABLED`/`RECPRO_WORKER_MODE` 双闸门启动；默认 Compose worker 保持 `false/disabled` 健康等待，不创建数据库连接。显式非 production `profile_outbox` 模式才装配受控 MySQL connection factory、batch/lease/retry/poll 参数和固定画像公式；新增只读 wiring verifier 与入口/配置测试。
  - 已完成 G5 Worker 真实隔离空队列只读探针：先以运行账号验证无 `PENDING/PROCESSING`，再使用既有受控 migration 身份调用真实 `run_once(limit=1)`，receipts=`0`、40 张表计数与 Outbox 状态前后不变；运行账号首次 `SELECT ... FOR UPDATE` 被最小权限正确拒绝且未产生写入，修正为既有受控 Worker 凭据后通过。
  - 已完成 G5 第二个真实推荐项的受控交互链尝试：用户批准 `plan_id=4bb3a297-1f93-58e8-a476-b82b32c50b50`、`plan_hash=fa19aca430597d6b13486ecfd2f5c657d4e3e0348b0c727dd25b5383842611eb` 后，item=`129`/resource=`6850` 的 impression、feedback、direct behavior、2 条 Outbox、2 次画像重放和 9 条状态转移均落库；执行器最终计数断言发现真实标签集合使正/负画像新增各为 3 行而计划静态预算为各 2 行，未重试、未回滚、未删除任何数据。
  - 已完成该次受控链的独立只读 reconciliation：`recommendation_impression/feedback/user_behavior_event/profile_update_outbox/user_resource_state/profile_replay_run/profile_change_log/domain_state_transition` 分别为 `+1/+1/+3/+2/+1/+2/+3/+9`，正/负画像为 `+3/+3`，Outbox=`33/34` 均 `DONE`、全局无 `PENDING/PROCESSING`，非目标表 delta=`0`；证据状态为 `PARTIAL_APPLY_RECONCILED`，不是原计划 `PASS`。
  - 已修正 G5 计划/执行器：计划快照现在冻结用户已有画像键集合，动态计算 upsert 表的真实新增行数；执行器在任何业务写入前核对计划 delta 与实时画像键集合，避免再次出现“写入完成后才发现预算漂移”。新增纯只读 reconciliation verifier 与 Make 目标，默认仍不启用 Worker。
  - 已完成 G7 前端 G5 交互工作台代码切片：新增 `frontend/src/domain/interaction.ts`、`frontend/src/api/interactionClient.ts` 与 `InteractionPanel.vue`，严格校验 impression/feedback/behavior 响应，要求先显式曝光再允许反馈/点击；`VITE_G5_INTERACTION_ENABLED` 默认关闭，未启用时不会发送网络请求。前端测试 46 项通过，构建 `g7-interaction-ui-20260812-001` 通过。
  - 已完成 G7 G4+G5 独立后端入口：新增 `backend.app.g4_feedback_demo_main:app` 与 `RECPRO_G5_INTERACTION_HTTP_ENABLED` 双闸门；只有显式入口同时注入 G4 Graph/Vector 推荐、G5 Feedback/Behavior 服务时才挂载真实交互 POST，默认 Compose backend、Worker、DeepSeek 仍关闭；后端镜像补齐冻结 Prompt Bundle 文件。
  - 已开始 G8 发布候选前置：新增 `scripts/verify_g8_release_preflight.py`、`tests/g8/test_release_preflight.py` 与 `make verify-g8-release-preflight`，将默认安全配置、静态门禁、后端/前端测试、追加式前端构建、本地后端镜像检查和 Git 源码哈希清单固化为不可覆盖报告；本工具不启动服务、不连接数据库、不 claim Outbox、不调用 DeepSeek。
  - 已完成 G8 发布候选前置首次运行：`artifacts/verification/g8/g8-release-preflight-20260812-001/release-preflight.json`=`PASS_WITH_BLOCKERS`；契约、文档、架构、安全、G1/G4/G5/G7/G8 测试、前端测试/构建、默认 fail-closed 配置和后端镜像检查共 12 项技术检查全部 PASS；源码清单 402 个文件，root_sha256=`3733f3963e2a18985517e65b566d40537e71300d4cc5cb1c7e5340edc8c88e2c`。
  - 已完成 G8 发布候选前置扩展运行：`artifacts/verification/g8/g8-release-preflight-20260812-002/release-preflight.json`=`PASS_WITH_BLOCKERS`；G0 合约/架构/安全测试、G1—G9 测试、契约/文档/架构/安全脚本、Compose config、前端测试/构建、默认 fail-closed 配置和后端镜像检查共 20 项技术检查全部 PASS；源码清单 402 个文件，root_sha256=`1c4ed1df042989fbacae81c09e1f7949155e7e72320fe516e5c7fa312815b0b5`。
  - 已完成 A01—A25 离线覆盖审计：新增 `scripts/verify_g8_acceptance_coverage.py`、`tests/g8/test_acceptance_coverage.py` 和 `make verify-g8-acceptance-coverage`；`artifacts/verification/g8/g8-acceptance-coverage-20260812-003/acceptance-coverage.json` 为 `PASS_WITH_BLOCKERS`，25 项映射全部有效，9 项直接覆盖、14 项相关覆盖、2 项缺少直接测试（A12、A24），25 项最终 G8/G9 复验仍为 `PENDING`。审计只读源码/测试/既有 artifact，数据库、Neo4j、Chroma、外部 LLM、删除和覆盖计数均为 0。
  - 已补齐 A12/A24 直接离线覆盖：`CatalogCandidateRecallAgent` 在 Neo4j 有界超时后输出 `kg_score=null`、无虚构图路径且保留故障尝试证据；新增纯领域输出类型稳定策略，自动类型在最小两轮/滞回区间内保持，显式输出类型可立即覆盖，并由规则 Policy Agent 输出稳定性原因码。新增测试 `tests/g6/test_retrieval_fusion.py::test_graph_timeout_is_null_and_explanation_cannot_invent_graph_path` 与 `tests/g4/test_output_type_stability.py`；本阶段不连接或写入任何数据存储。
  - 已完成新的追加式 A01—A25 覆盖审计：`artifacts/verification/g8/g8-acceptance-coverage-20260812-004/acceptance-coverage.json` 为 `PASS_WITH_BLOCKERS`，25 项映射全部有效，11 项直接覆盖、14 项相关覆盖、0 项缺少直接测试，最终 G8/G9 复验 25 项仍为 `PENDING`；报告绑定提交 `e066b990c3d2baed777b5e98fd18759c428d40af`，生成前工作区 clean，所有安全计数为 0。
  - 已完成新的追加式 A01—A25 覆盖审计：`artifacts/verification/g8/g8-acceptance-coverage-20260812-005/acceptance-coverage.json` 为 `PASS_WITH_BLOCKERS`，25 项映射全部有效，13 项直接覆盖、12 项相关覆盖、0 项缺少直接测试，最终 G8/G9 复验 25 项仍为 `PENDING`；报告绑定提交 `cc861d8e613b8846a40cbb850d782a26c6bcc6c8`，生成前工作区 clean，所有安全计数为 0。
  - 已补齐 A11/A13 可选检索故障矩阵直接覆盖：向量超时的候选 `semantic_score` 明确为 `null`；Neo4j 与 Chroma 同时超时仍保留足量 MySQL 候选，两个依赖独立标记 `UNAVAILABLE`，不产生图/向量证据引用，并记录各自有界重试信息。新增测试 `tests/g6/test_retrieval_fusion.py::test_graph_and_vector_outage_keeps_sufficient_mysql_candidates`，审计映射已将 A11/A13 标记为 `DIRECT`。
  - 已补齐 A15/A18 缺失特征分数安全与单难度阅读路径降级：空标签、空画像、空行为和空目录矩阵中的所有分数均保持有限且在 `[0,1]`；显式 `READING_PATH` 仅覆盖一个难度层时返回 `DEGRADED`，发出策略原因码并明确不伪造其他阅读阶段。新增测试 `tests/g3/test_recommendation_service.py::test_missing_optional_features_keep_all_scores_finite_and_bounded` 与 `tests/g4/test_orchestrator.py::test_reading_path_with_one_difficulty_level_is_degraded_without_fake_stages`。
  - 已完成新的追加式 A01—A25 覆盖审计：`artifacts/verification/g8/g8-acceptance-coverage-20260812-006/acceptance-coverage.json` 为 `PASS_WITH_BLOCKERS`，25 项映射全部有效，15 项直接覆盖、10 项相关覆盖、0 项缺少直接测试，最终 G8/G9 复验 25 项仍为 `PENDING`；报告绑定提交 `5cd6aa48be419fc9602cf00256cdce808013c646`，生成前工作区 clean，所有安全计数为 0。
  - 已补齐 A19/A23/A25 直接离线覆盖：越权 Evidence Ref 经 `LLMExplanationAgent` 校验失败后回退有界模板；反馈→Outbox→Worker 链路断言画像版本增长、Outbox=`DONE` 和 `profile_change_log` 追加；历史重放选择器按 `evaluation_at` 同时冻结资源、行为、资源状态和热度，未来事实不改变快照内容哈希。新增测试分别位于 `tests/g6/test_evidence_bounded_explanation.py`、`tests/g5/test_feedback_profile_version_change_log.py`、`tests/g9/test_historical_replay_boundary.py`。
  - 已完成新的追加式 A01—A25 覆盖审计：`artifacts/verification/g8/g8-acceptance-coverage-20260812-007/acceptance-coverage.json` 为 `PASS_WITH_BLOCKERS`，25 项映射全部有效，18 项直接覆盖、7 项相关覆盖、0 项缺少直接测试，最终 G8/G9 复验 25 项仍为 `PENDING`；报告绑定提交 `eea67d88beb8eff58b47e5696e33aa72e2ea8e5c`，生成前工作区 clean，所有安全计数为 0。
  - 已补齐 A01/A02/A03/A08/A09/A10/A16 的直接离线证据：画像快照内容哈希重放稳定、同一 request_id 只保留一个推荐记录、同一 behavior event_uuid 只保留一个行为事实、主题负反馈反事实严格降分、曝光 `visible_ms=1000` 与 `max_visible_ratio=0.5` 闭区间边界、固定配置/数据集/seed/evaluation_at 的推荐输出指纹均有独立测试；A09/A10 的阈值由纯领域函数复用到 MySQL 适配器，A16 指纹模块不依赖存储或外部服务。
  - 已完成新的追加式 A01—A25 覆盖审计：`artifacts/verification/g8/g8-acceptance-coverage-20260812-008/acceptance-coverage.json` 为 `PASS_WITH_BLOCKERS`，25 项映射全部有效，25 项直接覆盖、0 项相关覆盖、0 项缺少直接测试，最终 G8/G9 复验 25 项仍为 `PENDING`；报告绑定提交 `78bfc451300a3e24347323d3d1fb296826ef16ff`，生成前工作区 clean，所有安全计数为 0。
  - 已新增最终复验计划契约和生成器：`contracts/verification/g8-final-revalidation-plan.schema.json`、`scripts/build_g8_final_revalidation_plan.py`、`tests/g8/test_final_revalidation_plan.py` 与 `make build-g8-final-revalidation-plan`；计划严格绑定 acceptance matrix SHA、Git commit 和 canonical `plan_hash`，冻结 A01—A25 的运行态证据要求及 `demo_cold/demo_clear/demo_topic/demo_path/demo_negative/demo_degraded` 六个浏览器场景，默认 `READ_ONLY`，禁止业务 POST、Outbox claim、Neo4j/Chroma 写入和 DeepSeek 请求。
  - 已生成追加式最终复验计划：`artifacts/verification/g8/g8-final-revalidation-plan-20260812-002/final-revalidation-plan.json`=`PLAN_READY_WITH_BLOCKERS`，绑定 commit=`dc178c15bbc5bcf56745aa1448c469ffff975462`、`plan_hash=c9ba9d61e264accc34605fe7a5dea22a982b8dfaa998040b5ec2565a57666ca2`；25 项案例和 6 个浏览器场景均为 `PENDING`，该计划不等同于最终运行态通过。
  - 已完成最终复验就绪审计器：新增 `contracts/verification/g8-final-revalidation-audit.schema.json`、`contracts/verification/g8-final-runtime-evidence.schema.json`、`scripts/verify_g8_final_revalidation_plan.py`、`tests/g8/test_final_revalidation_audit.py` 与 `make verify-g8-final-revalidation-plan`；审计验证计划 hash、Git 绑定、测试/验证器引用和历史 artifact 清单，严格不把历史证据提升为 final 通过。
  - 已生成追加式最终复验计划与就绪审计：计划 `artifacts/verification/g8/g8-final-revalidation-plan-20260812-003/final-revalidation-plan.json`=`PLAN_READY_WITH_BLOCKERS`，绑定 commit=`ccdf71f981a223db26cc54ca561480cf1f3ecf01`、`plan_hash=00a21f9f9c58737186fa4949e1a13c2318a37d9a82ed17b77d5ce9ff6fedba87`；审计 `artifacts/verification/g8/g8-final-revalidation-audit-20260812-001/final-revalidation-audit.json`=`READY_FOR_RUNTIME`，25 项计划有效，17 项只读路径、8 项需要独立 ChangePlan，历史 artifact cases=25，final_pass=0、final_pending=25；审计前工作区 clean，安全计数全部为 0。
  - 已在当前提交完成首批真实只读运行态复验：`data-plane-20260812-004` 验证隔离 Compose 的 backend/frontend/mysql/neo4j 均 healthy、MySQL=40 张表、Neo4j=0/0；`g4-orchestrator-20260812-006` 验证 direct/guided/degraded/replanning 四分支；`g4-readonly-fusion-20260812-012` 验证 7 Agent、8 候选、`MYSQL+GRAPH+VECTOR`、MySQL/Chroma 计数不变；`g4-clarification-readonly-20260812-004` 验证 HOME 空请求为 `WAITING_CLARIFICATION`、4 Agent、19 张相关表计数不变；`g6-retrieval-fusion-readonly-20260812-012` 验证三通道融合和 Chroma=14,983；`g7-mysql-http-readonly-20260812-006` 验证 live/ready health-only、13 张相关表前后不变、业务 POST/数据库写入=0。G7 的 readiness 仍为 `DEGRADED`，未被误报为生产就绪；以上证据均未调用 DeepSeek、claim Outbox 或执行任何数据库/图/向量写入、删除、覆盖。
  - 已基于提交 `a490652664306d4fe89bcbc9a16a608e02f6ff5b` 重新生成最终复验计划 `artifacts/verification/g8/g8-final-revalidation-plan-20260812-004/final-revalidation-plan.json`（`plan_hash=0cac04a818e9ff61ae2df7c3a6e4f90a414462ff7f755aa9d7171cfd528d9dfb`）和审计 `artifacts/verification/g8/g8-final-revalidation-audit-20260812-002/final-revalidation-audit.json`；计划 Git 匹配当前提交，25/25 有效，17 项只读、8 项需独立 ChangePlan，final_pass=0、final_pending=25，审计安全计数仍全为 0。
- `open_issues`：
  - G1 已关闭，但推荐链路仍按设计保持 `can_recommend=false`；必须完成 G2/G3 后才能声称推荐系统可用。
  - 演示数据和论文评价数据来源、许可证仍需在G2前确认并形成版本化清单。
  - 人工标注与伦理流程需要在正式用户实验前完成。
  - `gh` 已安装但尚未登录 GitHub；Git HTTPS 凭据已成功推送 `codex/g1-runnable-skeleton`，Draft PR 仍需 `gh` 认证或在 GitHub 网页创建。
  - G3 前端集成、正式环境 Token 验证器的外部部署配置和默认 Compose API 仍未启用；默认运行配置仍保持 `can_recommend=false`，不能宣称系统已对外提供推荐服务。
  - Docker CLI 的 `/usr/local/bin/docker` 是失效链接；实际 Docker Desktop 位于 `/Applications/编程/Docker.app`，本次已用绝对路径完成隔离 MySQL 验证，未删除容器、卷或数据。
  - G4 真实端口仍读取当前 Profile 投影，尚未提供历史画像重算；超时后的跨 Agent 持久化恢复、正式 HTTP 组合根和正式 Token 部署参数仍待后续 Gate。
  - 持久化 service 的数据库重启恢复读取和 HTTP/API 正式接入仍未实现；Worker 级重试、DEAD 和 MySQL 重启后的 Outbox 恢复已在 G5 隔离运行态验证；当前组合根仅在明确调用时创建连接，默认 API 继续关闭。
  - G5 当前仍未接入默认 HTTP；本轮完成的是带显式门禁的 production HTTP 组合根、可替换 HS256 身份适配器和默认安全的 Worker 运行态接线，外部 OIDC/JWKS、默认 Compose API、正式 Worker 受控消费审批和发布凭据流程仍需 Gate 评审；状态迁移审计与历史画像重算已完成隔离运行态验证。
  - MySQL 已有隔离历史事实；本轮经用户授权后已将书目 ChangePlan 追加写入同一隔离 Compose 项目并完成幂等复验。Neo4j 图构建、实际导入和只读图召回端口均已完成；确定性向量与 Chroma collection 已完成版本化导入和独立只读核验，但图/向量召回尚未接入默认 HTTP/Worker。
  - Neo4j Community 版本只显示 `neo4j` 与 `system` 两个数据库，不能在同一实例中安全提供独立命名库；RecPro 的隔离边界是独立 Compose 实例、容器和数据卷。已有 Homebrew Neo4j 的 `neo4j` 库视为受保护外部数据源，禁止复用。
  - Neo4j Community 版本只显示 `neo4j` 与 `system` 两个数据库，不能在同一实例中安全提供独立命名库；RecPro 的隔离边界是新的 `recpro-library-neo4j-20260810a` Compose 实例、容器和数据卷。已有 Homebrew Neo4j 的 `neo4j` 库视为受保护外部数据源，禁止复用。
  - Chroma 正式运行态位于本地忽略路径 `data/chroma`，仅包含计划 collection `library_resources__hash_char_ngram_v1`；此前 API 签名探查留下的空 collection `probe_signature_20260811` 位于独立路径 `data/chroma-probe-g6-20260811`，0 条向量，未删除、未合并、未纳入正式索引。
  - DeepSeek 密钥已在本机配置，但没有启用默认 HTTP/Worker，也没有发起真实外部 LLM 请求；MockLLM/规则路径仍是安全默认。外部 Provider、密钥、模型和 Base URL 必须在组合根通过被 `.gitignore` 保护的本地环境配置注入，不能写入 Git、Manifest、日志或 Agent 消息。Prompt Bundle 已有本地 SHA-256 绑定，真实请求仍需单独的数据脱敏、伦理、费用和调用范围评审。
  - G5 计划 `4bb3a297-1f93-58e8-a476-b82b32c50b50` 的原执行器返回最终计数失败，但已确认链路事实完整且无受保护表变化；该计划不得再次执行或重试。后续任何 G5 业务追加必须基于新的只读基线、新 Git 提交和新的 plan_id/hash。
  - G7 前端交互工作台已完成默认关闭浏览器验收；真实浏览器写入仍需显式启用新的 G4+G5 opt-in 后端、单独的用户/伦理范围和新的业务 ChangePlan，不得把 `VITE_G5_INTERACTION_ENABLED=true` 当作数据库写入授权。
  - `next_step`：依据与当前提交匹配的 `g8-final-revalidation-plan-20260812-004` 与 `g8-final-revalidation-audit-20260812-002`，补齐尚未有当前提交证据的只读/故障案例并保持追加式审计；A02/A03/A04/A07/A08/A09/A10/A23、任何浏览器业务流、非空 Worker claim、索引写入和 DeepSeek 请求必须另行生成精确 ChangePlan、plan_id/hash 并获批。25 项 final_revalidation 仍为 `PENDING`，随后再完成生产 OIDC/JWKS、G9 正式输入冻结与发布凭据复核。

---

## Gate 状态

| Gate | 状态 | 完成证据 | 备注 |
|---|---|---|---|
| 计划制定 | COMPLETED | `docs/LibraMAS_系统实施计划_安全低耦合版.md` | 本轮完成 |
| G0 安全与规格基线 | COMPLETED | 原始 Gate 125 tests；当前回归 131 tests；安全/架构/文档/契约均 PASS | 未连接数据库 |
| G1 可启动工程骨架 | COMPLETED | `docs/G1_RUNNABLE_SKELETON_MANIFEST.md`；本地 266 项测试；`artifacts/verification/g1/g1-runtime-20260802-014` 运行态证据 PASS | 五服务双次健康启动、三卷身份与探针计数保持一致；破坏性动作 0 |
| G2 数据与持久化 | COMPLETED | `artifacts/verification/g2/g2-runtime-20260809-012/runtime.json`；13 项测试、manifest/质量报告、Repository/UoW、索引计划 | 全新卷首次导入与第二次幂等均 PASS；Chroma/Neo4j 仅保留版本化计划，不写外部存储 |
| G3 MySQL-only推荐闭环 | IN_PROGRESS | `artifacts/verification/g3/g3-runtime-20260809-003/runtime.json`、`artifacts/verification/g3/g3-api-runtime-20260809-004/api-runtime.json`、`artifacts/verification/g3/g3-clarification-runtime-20260809-002/clarification-runtime.json`、`artifacts/verification/g5/g5-formal-auth-20260810-001/runtime.json`；27 项 G3/认证测试 | CLI、opt-in API、HS256 正式身份边界、research-admin Debug、澄清状态分支、MySQL 追加持久化 PASS；外部 IdP/JWKS、前端集成和 production service deployment 待 Gate 评审 |
| G4 动态多智能体闭环 | IN_PROGRESS | `artifacts/verification/g4/g4-orchestrator-20260809-001/orchestrator.json`；`artifacts/verification/g4/g4-agent-runtime-20260809-002/agent-runtime.json`；`artifacts/verification/g4/g4-real-ports-20260809-001/real-ports-runtime.json`；`artifacts/verification/g4/g4-composition-20260809-001/composition-runtime.json`；28 项 G4 测试 | Registry、结构化消息、四路径、真实 Catalog/Profile 只读端口、bounded retry、显式组合根和同事务持久化 PASS；重放 delta=0、失败回滚、受保护事实不变；正式 HTTP/Worker 接入、恢复读取和历史画像重算待完成 |
| G5 曝光反馈画像闭环 | IN_PROGRESS | `artifacts/verification/g5/g5-feedback-20260809-001/g5-runtime.json`；`artifacts/verification/g5/g5-http-20260810-005/http-runtime.json`；`artifacts/verification/g5/g5-worker-recovery-20260810-002/runtime.json`；`artifacts/verification/g5/g5-audit-replay-20260810-001/runtime.json`；`artifacts/verification/g5/g5-formal-auth-20260810-001/runtime.json`；`artifacts/verification/g5/g5-worker-wiring-20260812-001/worker-wiring.json`；`artifacts/verification/g5/g5-worker-readonly-runtime-20260812-002/readonly.json`；`artifacts/verification/g5/g5-feedback-worker-reconcile-20260812-003/reconciliation.json`；25 项 G5 测试、5 项认证测试；`g5-audit-migration-20260810-001/audit-migration.json` | 前向迁移、Worker retry/DEAD 契约、opt-in HTTP、HS256 正式身份、身份/幂等/错误映射、资源状态受控 UPDATE 与同事务审计、真实 MySQL HTTP 链路、故障/重启恢复、历史 `as_of` 只读重算、默认安全 Worker 接线和空队列探针 PASS；第二个真实交互链已完成事实追加但原计划预算出现画像 upsert 行数漂移，独立 reconciliation=`PARTIAL_APPLY_RECONCILED`；动态 delta 预检已补；production HTTP、外部 IdP/JWKS、正式 Worker 非空队列受控消费审批和发布凭据流程待补 |
| G6 可选检索与解释 | IN_PROGRESS | 图计划/导入、MySQL 书目导入、向量计划/验证、`chroma-collection-plan-20260811-002`/`chroma-collection-verify-20260811-002`、`chroma-import-idempotency-20260811-002`、独立只读 `chroma-import-integrity-20260811-001`；`artifacts/verification/g6/g6-retrieval-fusion-readonly-20260811-002/readonly.json`；`backend/app/catalog/adapters/embedding.py`、`backend/app/catalog/adapters/chroma.py`、`backend/app/catalog/adapters/neo4j.py`、`tests/g6/test_retrieval_fusion.py` | Neo4j 63,388/191,865、MySQL 书目追加与幂等、确定性向量 14,983/384 维、Chroma collection 追加 14,983 并最终 14,983/14,983、幂等新增 0、独立只读 verifier PASS；图/向量显式组合根真实隔离只读融合与故障降级 fake PASS；MySQL `embedding_status` 仍 PENDING，默认 HTTP/Worker 接线和真实写入授权待完成；DeepSeek 外部调用仍为 0 |
| G7 前端与论文演示 | IN_PROGRESS | G1 Vue 状态页、健康客户端、组件测试和追加式构建证据；`artifacts/verification/g4/g4-frontend-browser-apply-20260812-001/g4-recommendation-projection-apply.json`；`artifacts/verification/g4/g4-frontend-browser-reconcile-20260812-002/reconciliation.json`；`artifacts/verification/g7/g7-frontend-api-browser-20260811-001/frontend.json`；前端 `InteractionPanel`/`InteractionClient` 46 项测试；`dist/g7-interaction-ui-20260812-001` 构建；G7 默认关闭浏览器验收（390×844 无横向溢出、无交互 POST） | 推荐工作台、澄清交互、真实浏览器推荐幂等重放和视觉验收已完成；G4+G5 独立入口已具备，真实浏览器写入、正式部署接线和论文演示冻结流程仍待新的 ChangePlan/opt-in Gate |
| G8 可靠性与发布候选 | IN_PROGRESS | `artifacts/verification/g8/g8-release-preflight-20260812-002/release-preflight.json`=`PASS_WITH_BLOCKERS`；20 项技术检查 PASS；`artifacts/verification/g8/g8-acceptance-coverage-20260812-008/acceptance-coverage.json` 完成 A01—A25 映射；`artifacts/verification/g8/g8-final-revalidation-plan-20260812-003/final-revalidation-plan.json` 与 `g8-final-revalidation-audit-20260812-001/final-revalidation-audit.json` 冻结并审计最终复验范围 | 25 项映射无陈旧引用；25 项直接覆盖、0 项相关覆盖、0 项缺失；17 项可先只读验证、8 项需独立 ChangePlan；最终 A01—A25、六场景浏览器 E2E、故障矩阵、生产认证和发布凭据仍未完成 |
| G9 冻结实验 | NOT_STARTED | `artifacts/verification/experiment-inputs/eval-inputs-20260810-002/input-freeze-report.json`（当前为 PASS_WITH_BLOCKERS） | 契约和输入门禁已建立；真实数据、许可、标注、Split、F3 配置和 G8 仍未完成 |
| G10 最终发布 | NOT_STARTED | — | 依赖G9 |

允许的状态：`NOT_STARTED / IN_PROGRESS / BLOCKED / COMPLETED`。状态只能在证据存在后更新为COMPLETED。

---

## Working Set

- `current_subtask`：G8 发布候选只读/构建前置已通过，A01—A25 已全部达到 DIRECT 离线覆盖；当前计划 `g8-final-revalidation-plan-20260812-004` 与审计 `g8-final-revalidation-audit-20260812-002` 已与提交 `a490652` 匹配，当前提交已补充数据平面、G4 编排/融合/澄清、G6 融合和 G7 health-only 证据。17 项只读路径继续逐项补证，8 项及六个浏览器场景仍需独立 ChangePlan；G7 readiness=`DEGRADED` 仍是公开阻塞项。所有本轮数据库/Neo4j/Chroma 写入、Outbox claim、DeepSeek、删除/覆盖均为 0。
- `current_evidence`：MySQL 五张目标表总数保持 `14,989/14,986/8,522/70,762/14,989`；幂等复跑前后计数一致，独立只读核验重复外部 ID=0、`resolved_resource_tags=70,750`。向量计划 `vector-index-plan-20260811-001` 生成 14,983 条、384 维记录，产物 SHA-256=`7714919f8e57902002d42fb39dc0ba8b2f6106c4f8c1594a691e5ea180c944ae`；第二次构建哈希一致，验证器 PASS。Chroma plan `...-002` 为 PINNED `chromadb==1.5.9`；正式 collection `library_resources__hash_char_ngram_v1` 位于 `data/chroma`，追加 14,983 条、幂等新增 0、最终 14,983/14,983；独立只读 verifier PASS，源向量 SHA 全量核验 14,983、最大数值误差 2.98e-8、query top-1 score=1.0。首次回读失败证据已保留且未清理；空探查 collection `probe_signature_20260811` 位于独立路径、0 条向量，同样未删除。MySQL `embedding_status` 仍 PENDING，Neo4j 最终计数 63,388/191,865。
- `active_files_or_commands`：
  - `Makefile`
  - `backend/app/`
  - `frontend/`
  - `compose.yaml`
  - `.env.host.example`
  - `.env.compose.example`
  - `contracts/`
  - `scripts/`
  - `tests/`
  - `docs/SAFETY_POLICY.md`
  - `docs/api.md`
  - `docs/data_dictionary.md`
  - `docs/experiment_protocol.md`
  - `docs/acceptance_matrix.md`
  - `docs/LibraMAS_纯推荐模块实施文档_可运行版.md`
  - `docs/LibraMAS_系统实施计划_安全低耦合版.md`
  - `docs/LibraMAS_实施状态与交接记录.md`
  - `immediate_risk`：G3/G4/G5 HTTP 仍未进入默认生产配置；G6 图/向量已完成显式组合根的真实只读融合但尚未接入默认 Agent/HTTP，MySQL embedding 状态仍 PENDING，DeepSeek 本机密钥虽已配置但尚未联网调用；Prompt Bundle 已冻结但 Explanation/Feedback 的真实 LLM 接线仍待 EvidenceValidator/事务边界评审；G7 推荐工作台与浏览器幂等闭环已完成，feedback/behavior 页面和论文演示冻结仍待完成。任何默认环境仍不得自动开启推荐。Chroma operator 依赖只用于显式导入/校验，不进入默认 backend/worker 镜像。
- `database_boundary`：本机 Homebrew Neo4j `neo4j` 库是受保护外部数据（59,301 节点/185,238 关系）；RecPro 只能使用独立 Compose Neo4j 实例/卷，禁止复用 `127.0.0.1:7474/7687`。
- `next_action`：先对照 G8 计划补齐剩余只读/故障运行证据并生成追加审计；不执行真实 Worker 消费。若需非空 Worker、业务 POST、澄清续跑、索引写入或 DeepSeek，先生成对应 DRY_RUN/精确 ChangePlan 并等待用户批准 hash，再做隔离追加和独立回读。

---

## 删除与破坏性操作台账

| 申请编号 | 状态 | 目标 | 用户批准 | 执行结果 |
|---|---|---|---|---|
| G1-INC-20260802-001 | 已发生安全偏差；已遏制 | 移除 Git ignored 生成物 `frontend/dist/assets/index-BI6Zj5t6.js`；重写 `frontend/dist/index.html` 与 `frontend/dist/assets/index--TNcMmyO.css` | 未获预先批准；Vite 首次生产构建的默认 `emptyOutDir=true` 触发 | 旧 JS 生成物被构建器移除并由 `index-CKdk1LLM.js` 替代；源码/Git 文件/数据库删除均为0；已固定 `build.emptyOutDir=false`，禁止后续自动清空输出目录 |

该偏差不属于已批准删除，也不得作为未来删除先例。旧生成物无独立备份，不能声称字节级恢复；其输入源码仍完整，当前产物可由锁定工具链复现。数据库删除与受版本管理文件删除仍为0。

---

## G0 阶段交接记录

```text
交接ID：G0-20260802-001
Gate：G0 安全与规格基线
状态：COMPLETED
时间：2026-08-02（Asia/Shanghai）
目标：冻结零删除约束、领域语言、模块依赖、API/Agent/配置契约、实验协议和验收映射。
新增文件：安全政策与模板、ADR、数据/API/实验/验收文档、Python契约、JSON Schema/OpenAPI、门禁脚本、测试、Makefile、CI工作流。
修改文件及原版本保存位置：README.md 与 .gitignore；原版本位于提交 2f529febc922c69d3bf72cc10fa25fbee2d518df。
新增数据库对象和行数：0；未连接数据库。
受控UPDATE对象和审计ID：0；不适用。
文件删除数量：0。
数据库物理删除数量：0。
执行命令：make verify-g0；git diff --check；Git状态/差异/哈希只读检查。
测试结果：125 tests OK；安全、架构、文档、契约四类报告均 PASS。
验证证据：命令输出、本交接记录、docs/G0_BASELINE_MANIFEST.md 和主提交 cb926d910e8253a8b88c30ecdd656e51b1789594。
配置/数据/索引版本：config=rec-1.0.0；数据与索引未创建。
未解决风险：HTTP服务、MySQL、Neo4j、Chroma和前端尚未实现；本机缺少gh，远程推送暂停。
下一步唯一动作：用户确认G0后进入G1，先做只读环境探测与可启动健康检查垂直切片。
```

---

## G1 阶段本地交接记录

```text
交接ID：G1-LOCAL-20260802-001
Gate：G1 可启动工程骨架
状态：IN_PROGRESS / LOCAL_PASS, RUNTIME_PENDING
时间：2026-08-02（Asia/Shanghai）
目标：形成只报告真实状态、推荐能力默认关闭、可在全新隔离运行时验证的五服务工程骨架。
新增文件：FastAPI 健康切片、Worker/MockLLM、Vue 状态页、Dockerfile、Compose、环境模板、新卷初始化、bootstrap/runtime verifier、G1 测试与本地验收清单。
修改文件及原版本保存位置：README、Makefile、G0 门禁与契约文档；原版本位于 G0 交接提交 e1c4bae03659ef43ebb81c6a6472e74ce189eef5。
新增数据库对象和行数：0；未运行 Docker，未连接任何数据库。Compose 初始化脚本只会在未来全新卷首次创建时建立 1 张平台探针表和 1 行项目标记。
受控UPDATE对象和审计ID：0；不适用。
文件删除数量：Git 受跟踪文件 0；首次 Vite 默认构建自动删除 1 个被忽略的旧生成物，事故编号 G1-INC-20260802-001，已改为追加式构建且未再发生。
数据库物理删除数量：0。
执行命令：三锁 --require-hashes 安装；make verify-g0；make test-g1-python；pip check；全新 npm ci；Vitest；vue-tsc；追加式 Vite build；本地只读 mock 健康接口浏览器验收；Git 差异/删除/历史安全审计。
测试结果：G0 131 tests OK；G1 Python 100 tests OK；frontend 33 tests OK；编排定向 47 tests OK；安全、架构、文档、契约、类型检查、依赖审计和浏览器验收 PASS。
验证证据目录：docs/G1_RUNNABLE_SKELETON_MANIFEST.md；运行态 artifact 尚不存在且不得伪造。
配置/数据/索引版本：config=rec-1.0.0；配置 Schema SHA-256=2783a75736fe21d39f2ef3101fa9f9849f1ac3757d0a05c50d656b5169ab6bd1；数据与索引未创建。
未解决风险：本机无 Docker，真实五服务双次启停、最小权限 MySQL 和三卷持久性均为 RUNTIME_PENDING；本机无 gh，三个实现提交尚未推送。
下一步唯一动作：在具备 Docker Compose 的隔离新环境，以全新项目名执行 verify-g1-runtime；通过前不得关闭 G1 或进入 G2。
```

---

## G1 阶段运行态完成记录

```text
交接ID：G1-RUNTIME-20260802-014
Gate：G1 可启动工程骨架
状态：COMPLETED / LOCAL_PASS, RUNTIME_PASS
时间：2026-08-02（Asia/Shanghai）
目标：在全新隔离 Compose 项目中验证五服务真实启动、双次安全停止/复启、最小权限探针读取和命名卷持久性。
新增文件：无受版本管理新增文件；追加式证据位于 artifacts/verification/g1/g1-runtime-20260802-014。
修改文件及原版本保存位置：Compose worker 健康契约、运行验证器 Docker Compose v5/慢初始化/本机代理兼容性及对应测试；原版本均可由 Git 提交历史恢复。
新增数据库对象和行数：仅全新隔离 MySQL 卷初始化 1 张 recpro_runtime_probe 表和 1 行项目标记；未连接任何既有业务数据库。
受控UPDATE对象和审计ID：0；验证器 UPDATE=0。
文件删除数量：0。
数据库物理删除数量：0。
执行命令：Docker/Compose 健康检查；make test-g1-python；make verify-g0；python -m scripts.verify_g1_runtime --run-id g1-runtime-20260802-014 --deadline-seconds 600；Git 差异与删除项审计。
测试结果：G0 131 tests OK；G1 Python 102 tests OK；五服务两轮均 healthy 且 restart_count=0；三卷 Name/CreatedAt 前后一致；探针 total_rows=1、matching_probe_rows=1 前后一致。
验证证据目录：artifacts/verification/g1/g1-runtime-20260802-014；manifest 绑定 git commit 6f7d6581d5087ce02b26542f8d3ce20df5e52b98；destructive_actions=0。
配置/数据/索引版本：config=rec-1.0.0；隔离探针项目 recpro-g1-tianyuhang-20260802f；业务数据与推荐索引未创建。
未解决风险：推荐链路仍按 G1 边界禁用；分支已推送，gh 2.97.0 尚未认证，因此 Draft PR 尚未创建。
下一步唯一动作：按 G2 Gate 冻结数据来源、许可证和版本清单；如需 Draft PR，先完成 gh auth login。
```

---

## G2 阶段启动记录

```text
交接ID：G2-START-20260809-001
Gate：G2 数据与持久化
状态：IN_PROGRESS / CONTRACT_PASS, RUNTIME_PENDING
时间：2026-08-09（Asia/Shanghai）
目标：在不删除历史事实的前提下，建立可前向迁移、可幂等导入、可按 evaluation_at 重放的 MySQL 数据基础。
新增文件：infra/mysql/migrations/001_g2_core.sql；contracts/data/g2/seed-v1.json；backend/app/profile/replay.py；scripts/migrate_g2.py、seed_g2.py、replay_g2_profile.py、verify_g2_runtime.py；tests/g2/。
修改文件及原版本保存位置：Makefile 增加 G2 门禁命令；安全扫描器放行 SQL 外键 `ON DELETE RESTRICT` 的安全声明；原版本由 Git 提交历史保留。
新增数据库对象和行数：尚未执行 G2 运行态迁移；代码只声明新对象，未连接既有业务数据库。
受控UPDATE对象和审计ID：运行态尚未执行；画像重放设计只允许更新当前投影，不覆盖事实历史。
文件删除数量：0。
数据库物理删除数量：0。
执行命令：G2 单元/契约测试；JSON/Python 编译；安全扫描；架构扫描；文档检查。
测试结果：G2 8 项通过；安全扫描 107 个文件 PASS；架构扫描 35 个文件 PASS；文档检查 PASS。
验证证据目录：运行态证据待写入 artifacts/verification/g2/<run-id>。
配置/数据/索引版本：seed=g2-demo-v1；画像公式=profile-g2-v1；索引状态仅创建 PENDING 投影，不写入 Chroma/Neo4j。
未解决风险：全新 Docker 数据库迁移、seed 两次幂等和 profile replay 两次幂等尚未验证；G3 推荐 API 不在本阶段范围。
下一步唯一动作：使用新的 Compose 项目名执行 G2 runtime verifier；通过后再关闭 G2 并进入 G3。
```

---

## G2 首个垂直切片运行记录

```text
交接ID：G2-RUNTIME-20260809-008
Gate：G2 数据与持久化（首个垂直切片）
状态：IN_PROGRESS / CONTRACT_PASS, RUNTIME_PASS
时间：2026-08-09（Asia/Shanghai）
目标：在全新 Compose 项目和全新 MySQL 卷上证明前向迁移、合成 seed、as-of 画像重放均可安全重复执行。
新增文件：backend/requirements-g2-tools.in；backend/requirements-g2-tools.lock；其余 G2 文件见 G2 启动记录。
修改文件及原版本保存位置：Compose 新增独立迁移账号；迁移/seed/replay/verify 使用最小迁移权限和精确 Decimal 绑定；原版本由 Git 提交历史保留。
新增数据库对象和行数：新卷创建 20 张 G2 表；首次 seed 写入 6 个资源、6 个标签、12 个资源标签关系、6 个 PENDING 索引状态、8 个行为事实、8 个 Profile Outbox、2 个声明画像历史、1 个配置版本和 1 个 seed 标记；画像 replay 写入 1 个 profile replay run、4 条 change log、5 个正向标签投影和 2 个主题负偏好投影。
受控UPDATE对象和审计ID：仅更新 user_profile、user_interest_tag、user_negative_preference 当前投影；profile_replay_run 以 (user_id, as_of, formula_version, input_hash) 幂等；本次运行无重复 UPDATE，destructive_actions=0。
文件删除数量：0。
数据库物理删除数量：0。
执行命令：`make PYTHON=.venv-g1-release-py311/bin/python verify-g0 test-g1-python test-g2`；`python -m scripts.verify_g2_runtime --run-id g2-runtime-20260809-008 --env-file .env.compose`；运行后仅执行 `docker compose stop mysql`，未删除容器、网络、卷或数据。
测试结果：G0 67+28+36 项、G1 102 项、G2 8 项通过；安全扫描 107 个文件 PASS；架构扫描 35 个文件 PASS；文档/契约检查 PASS；G2 runtime PASS。
验证证据目录：`artifacts/verification/g2/g2-runtime-20260809-008/runtime.json`；旧隔离卷重复运行证据为 `artifacts/verification/g2/g2-runtime-20260809-007/runtime.json`。
配置/数据/索引版本：seed=g2-demo-v1；画像公式=profile-g2-v1；index state=6 条 PENDING；未写入 Chroma/Neo4j。
未解决风险：G2 全量 Repository/UoW、dataset manifest、可选索引构建骨架仍待实现；合成数据不得用于正式论文评价。
下一步唯一动作：补齐 G2 剩余适配器、数据质量清单和索引构建状态机，并为每项添加独立门禁证据；通过后再进入 G3。
```

---

## G2 阶段完成记录

```text
交接ID：G2-COMPLETE-20260809-012
Gate：G2 数据与持久化
状态：COMPLETED / CONTRACT_PASS, RUNTIME_PASS
时间：2026-08-09（Asia/Shanghai）
目标：完成事实层、版本化数据清单、Repository/UoW 端口和可选索引构建骨架。
新增文件：backend/app/catalog/；scripts/build_g2_dataset_report.py；scripts/plan_g2_indexes.py；contracts/data/g2/dataset_manifest.json；contracts/data/g2/data-quality-report-v1.json；tests/g2/ 新增 5 项。
修改文件及原版本保存位置：G2 verifier/Make 门禁纳入数据质量、索引计划和重复运行断言；原版本由 Git 提交历史保留。
新增数据库对象和行数：全新卷 20 张 G2 表；6 资源、6 标签、12 标签边、8 行为、8 Profile Outbox、2 声明画像历史、12 索引构建计划、12 索引 Outbox、1 配置版本。
受控UPDATE对象和审计ID：画像当前投影仅由既有 replay 规则更新；索引计划只 INSERT IGNORE；无物理删除。
文件删除数量：0。
数据库物理删除数量：0。
执行命令：`python -m scripts.verify_g2_runtime --run-id g2-runtime-20260809-012 --env-file .env.compose`；运行后仅 `docker compose stop mysql`。
测试结果：G0 131 项、G1 102 项、G2 13 项、前端 33 项通过；安全扫描 140 文件 PASS；架构扫描 56 文件 PASS；文档/契约 PASS；G2 runtime PASS。
验证证据目录：`artifacts/verification/g2/g2-runtime-20260809-012/runtime.json`。
配置/数据/索引版本：seed=g2-demo-v1；manifest=g2-manifest-v1；index=g2-index-v1；外部 Chroma/Neo4j 写入 0。
未解决风险：合成数据仅为演示；G3 HTTP/API 层未完成。
下一步唯一动作：进入 G3 MySQL-only 推荐闭环 API 接入，不修改 G2 历史事实。
```

---

## G3 阶段启动记录

```text
交接ID：G3-START-20260809-003
Gate：G3 MySQL-only 推荐闭环
状态：IN_PROGRESS / CONTRACT_PASS, CORE_RUNTIME_PASS
时间：2026-08-09（Asia/Shanghai）
目标：在不依赖 Chroma、Neo4j 和外部 LLM 的情况下，完成规则意图、MySQL 召回、RRF/MMR 排序、模板解释和结果 Trace 持久化。
新增文件：infra/mysql/migrations/002_g3_recommendation.sql；scripts/migrate_g3.py；scripts/run_g3_demo.py；scripts/verify_g3_runtime.py；backend/app/recommendation/；tests/g3/。
修改文件及原版本保存位置：Makefile 增加 G3 迁移、demo、runtime 门禁；原版本由 Git 提交历史保留。
新增数据库对象和行数：全新卷创建 6 张推荐表；首次 demo 写入 1 task、15 candidate、1 record、5 item、5 explanation、1 trace。
受控UPDATE对象和审计ID：推荐结果采用 task/request 唯一键；重复请求只读已有结果，不更新或删除历史记录。
文件删除数量：0。
数据库物理删除数量：0。
执行命令：`python -m scripts.verify_g3_runtime --run-id g3-runtime-20260809-003 --env-file .env.compose`。
测试结果：G3 6 项确定性/迁移测试 PASS；G3 runtime PASS；默认 HTTP 推荐能力仍关闭。
验证证据目录：`artifacts/verification/g3/g3-runtime-20260809-003/runtime.json`。
配置/数据/索引版本：config=rec-1.0.0；policy=policy-g3-v1；ranking=ranking-g3-v1；dataset=synthetic-demo-2026-08；optional_store_writes=0。
未解决风险：尚未接入 FastAPI、鉴权、任务状态机和前端；结果只适用于合成演示。
下一步唯一动作：实现 G3 API DTO/端口/异常处理和 Debug Trace 查询，保持默认 fail-closed。
```

---

## G3 API 阶段记录

```text
交接ID：G3-API-20260809-004
Gate：G3 MySQL-only 推荐闭环（API 垂直切片）
状态：IN_PROGRESS / API_CONTRACT_PASS, RUNTIME_PENDING
时间：2026-08-09（Asia/Shanghai）
目标：先冻结 HTTP 输入/输出边界、用户身份、场景组合和幂等规则，再接入真正的 MySQL 应用服务。
新增文件：backend/app/api/recommendation.py；backend/app/recommendation/ports/；tests/g3/test_recommendation_api.py。
修改文件及原版本保存位置：main composition root 增加显式注入的 opt-in router；Recommendation domain/application 增加 transport-neutral command/result/port；原版本由 Git 提交历史保留。
新增数据库对象和行数：0；本切片未连接数据库。
受控UPDATE对象和审计ID：0；API fake service 仅内存返回，不写库。
文件删除数量：0。
数据库物理删除数量：0。
执行命令：`python -m unittest -v tests.g3.test_recommendation_api tests.g3.test_recommendation_service tests.g3.test_migration_contract`；G1 API 回归测试；`python scripts/architecture_guard.py --root .`。
测试结果：G3 API 4 项、G3 核心/迁移 6 项 PASS；G1 API 回归 22 项 PASS；架构扫描 59 文件、0 violation；默认 app 未注入服务时推荐路由不存在，显式旗标关闭时返回 503。
验证证据目录：测试输出与本交接记录；尚未生成 G3 API 运行态证据。
配置/数据/索引版本：API contract=v1；pipeline default=DISABLED；无新增数据版本。
未解决风险：尚无 MySQL-backed service、状态机、Trace 查询和真实 Compose API 验证；推荐结果仅适用于合成演示。
下一步唯一动作：从现有 CLI 事务提取 MySQL 应用服务，接入状态迁移与 Trace 查询，随后用全新隔离卷做两次 API 幂等运行态验证。
```

---

## G3 API 运行态记录

```text
交接ID：G3-API-RUNTIME-20260809-003
Gate：G3 MySQL-only 推荐闭环（MySQL API 运行态）
状态：IN_PROGRESS / RUNTIME_PASS
时间：2026-08-09（Asia/Shanghai）
目标：验证 opt-in FastAPI API 通过最小权限 runtime 用户完成推荐结果 INSERT、重复请求 replay、任务状态读取和 Trace 读取。
新增文件：backend/app/recommendation/adapters/mysql.py；infra/mysql/migrations/003_g3_task_transition.sql；scripts/migrate_g3_transition.py；scripts/verify_g3_api_runtime.py；tests/g3/test_mysql_adapter_contract.py、test_transition_migration.py。
修改文件及原版本保存位置：RecommendationTaskService 扩展任务/Trace 查询；API 增加 GET task 状态；Makefile 增加 transition migration 与 API runtime 门禁；原版本由 Git 提交历史保留。
新增数据库对象和行数：仅新增 `recommendation_task_transition` 表；本次成功运行前后新增 1 task、8 transition、15 candidate、1 record、5 item、5 explanation、1 trace；此前两次验证器自身故障留下的追加记录未删除。
受控UPDATE对象和审计ID：0；runtime 用户授权仅 SELECT/INSERT，结果与状态转移均为 INSERT-only。
文件删除数量：0。
数据库物理删除数量：0。
执行命令：`python -m scripts.verify_g3_api_runtime --run-id g3-api-runtime-20260809-003 --user-id 1001 --input-text 多智能体推荐系统论文与图书 --env-file .env.compose`；运行后仅 `docker compose stop mysql`。
测试结果：G3 16 项测试 PASS；API 真实运行新建 201、重放 200、`Idempotency-Replayed=true`、任务状态 200、Trace 4 步；安全扫描 150 文件 PASS；架构扫描 61 文件 PASS；destructive_actions=0。
验证证据目录：`artifacts/verification/g3/g3-api-runtime-20260809-003/api-runtime.json`。
配置/数据/索引版本：config=rec-1.0.0；policy=policy-g3-v1；ranking=ranking-g3-v1；dataset=synthetic-demo-2026-08；pipeline=explicit opt-in demo only。
未解决风险：Debug HTTP 仍需 research-admin 鉴权；Clarification 分支和正式认证适配未完成；默认 Compose API 仍关闭。
下一步唯一动作：完成受控 Debug API 与 Clarification 状态分支后，再执行 G3 Gate 关闭评审。
```

---

## G3 Debug、鉴权与 Clarification 阶段记录

```text
交接ID：G3-DEBUG-CLARIFICATION-20260809-001
Gate：G3 MySQL-only 推荐闭环（Debug、正式鉴权、Clarification）
状态：IN_PROGRESS / LOCAL_PASS, RUNTIME_PASS
时间：2026-08-09（Asia/Shanghai）
目标：在默认关闭推荐能力的前提下，提供研究管理员受控 Debug HTTP、正式 Bearer 身份边界和可恢复的澄清状态分支。
新增文件：backend/app/api/auth.py；backend/app/api/debug.py；backend/app/shared_kernel/contracts/auth.py；infra/mysql/migrations/004_g3_clarification_debug.sql；scripts/migrate_g3_clarification.py；scripts/verify_g3_clarification_runtime.py；tests/g3/test_auth_debug_clarification_api.py。
修改文件及原版本保存位置：recommendation API 增加 Bearer/演示身份分流、Clarification DTO/幂等接口；MySQL 适配器增加上下文、澄清、策略决策和 Trace revision 追加事实；main composition root 增加显式 Debug/Resolver 注入；原版本由 Git 提交历史保留。
新增数据库对象和行数：新增 4 张前向表；本次独立运行新增 1 个 WAITING 任务、12 条状态转移、15 条候选、1 条记录、5 个条目、5 条解释、1 条基础 Trace、2 个上下文版本、2 条澄清事实、2 条策略决策、1 条 Trace revision。
受控UPDATE对象和审计ID：0；Clarification 不更新 recommendation_task 根事实，使用 context_version、transition、policy、trace revision 追加行；运行用户只需 SELECT/INSERT。
文件删除数量：0。
数据库物理删除数量：0。
执行命令：`make verify-g3-local`；`python -m scripts.migrate_g3_clarification --run-id g3-clarification-migration-20260809-001 --env-file .env.compose --apply`；`python -m scripts.verify_g3_api_runtime --run-id g3-api-runtime-20260809-004 --user-id 1001 --input-text 多智能体推荐系统论文与图书 --env-file .env.compose`；`python -m scripts.verify_g3_clarification_runtime --run-id g3-clarification-runtime-20260809-002 --user-id 1001 --env-file .env.compose`；验证后仅 `docker compose stop mysql`。
测试结果：G3 22 项测试 PASS；正式 Bearer 无 resolver 返回 401，普通 user 访问 Debug 返回 403，Demo Header 不能提升权限；澄清首请求 201 WAITING、恢复 200、重放 200 且 `Idempotency-Replayed=true`；Debug context/trace/policy 均 200；安全扫描 159 文件 PASS；架构扫描 64 文件 PASS；`destructive_actions=0`。
验证证据目录：`artifacts/verification/g3/g3-api-runtime-20260809-004/api-runtime.json`；`artifacts/verification/g3/g3-clarification-runtime-20260809-002/clarification-runtime.json`；`artifacts/verification/g3/g3-clarification-migration-20260809-001/clarification-migration.json`。
配置/数据/索引版本：config=rec-1.0.0；policy=policy-g3-v1；ranking=ranking-g3-v1；dataset=synthetic-demo-2026-08；Debug/API/推荐均为显式注入，默认 Compose 仍关闭。
未解决风险：正式环境 JWT/OIDC 验签器和密钥轮换参数尚未接入部署配置；前端澄清交互与研究 Debug 页面尚未接入；合成数据仍不得用于正式论文评价。
下一步唯一动作：完成正式认证部署参数的安全审查和 G3 Gate 关闭评审，再进入 G4 多智能体编排。
```

## G4 Agent Registry 与动态分支第一垂直切片记录

```text
交接ID：G4-ORCHESTRATOR-20260809-001
Gate：G4 动态多智能体闭环（第一垂直切片）
状态：IN_PROGRESS / CONTRACT_PASS, LOCAL_RUNTIME_PASS
时间：2026-08-09（Asia/Shanghai）
目标：先冻结低耦合的 Agent Registry、结构化消息/结果和唯一 Orchestrator，再用确定性规则 Agent 验证论文所需动态路径。
新增文件：backend/app/recommendation/agents/base.py；backend/app/recommendation/agents/registry.py；backend/app/recommendation/agents/rule_agents.py；backend/app/recommendation/agents/orchestrator.py；backend/app/recommendation/agents/__init__.py；backend/app/recommendation/application/orchestration.py；tests/g4/；scripts/verify_g4_orchestrator.py。
修改文件及原版本保存位置：Makefile 增加 G4 测试/证据命令；实施状态记录更新 G4 交接；原版本由 Git 提交历史保留。
新增数据库对象和行数：0；本切片仅进程内确定性编排，不连接数据库、不写 MySQL/Chroma/Neo4j。
受控UPDATE对象和审计ID：0；Agent 不能直接访问 SQL、文件系统、Shell 或其他 Agent 实现；Orchestrator 是唯一状态推进者。
文件删除数量：0。
数据库物理删除数量：0。
执行命令：`python -m unittest discover -s tests/g4 -t tests -p 'test_*.py'`；`python -m scripts.verify_g4_orchestrator --run-id g4-orchestrator-20260809-001`；`python scripts/architecture_guard.py --root .`；`python scripts/safety_scan.py --root .`。
测试结果：5 项 G4 测试 PASS；DIRECT 路径可复现；GUIDED 在策略阶段早停且不调用 Recall/Ranking；DEGRADED 保留结果与警告；REPLANNING 恰好一次并记录第二轮 Recall/Ranking；安全扫描 168 文件 PASS；架构扫描 70 文件 PASS；`destructive_actions=0`。
验证证据目录：`artifacts/verification/g4/g4-orchestrator-20260809-001/orchestrator.json`。
配置/数据/索引版本：orchestrator=g4-orchestrator-v1；Agents=intent-rule-v1/profile-rule-v1/semantic-rule-v1/policy-rule-v1/recall-rule-v1/ranking-rule-v1/explanation-rule-v1/feedback-rule-v1；外部能力写入 0。
未解决风险：Agent message/result/artifact 尚未持久化到 MySQL；真实 Catalog/Profile 端口尚未由 Orchestrator 调用；deadline 超时、失败重试和正式 API 接入待下一小步；G3 正式 Token 验证器部署参数仍待审查。
下一步唯一动作：增加 append-only Agent 执行日志端口和 MySQL 适配，在隔离环境验证日志与主任务结果同事务提交，再扩展真实 Catalog/Recall Agent。
```

## G4 Agent 执行日志与同事务提交记录

```text
交接ID：G4-AGENT-LOG-20260809-002
Gate：G4 动态多智能体闭环（执行事实持久化小步）
状态：CONTRACT_PASS, LOCAL_RUNTIME_PASS, MYSQL_RUNTIME_PASS / IN_PROGRESS
时间：2026-08-09（Asia/Shanghai）
目标：把 Orchestrator 的 message、result、artifact 和最终编排结果置于调用方事务内追加，证明幂等重放不增行且回滚不留行。
新增文件：backend/app/recommendation/ports/agent_logging.py；backend/app/recommendation/adapters/agent_logging_mysql.py；infra/mysql/migrations/005_g4_agent_execution.sql；scripts/migrate_g4_agent_logs.py；scripts/verify_g4_agent_logs_runtime.py；tests/g4/test_agent_logging_contract.py。
修改文件及原版本保存位置：shared_kernel AgentDispatch 契约、Orchestrator dispatches、application persist_orchestration、Makefile、data_dictionary.md、实施状态记录；原版本由 Git 提交历史保留。
新增数据库对象和行数：新增 4 张前向表；成功隔离运行新增 7 条 Agent message、7 条 Agent result、1 条 artifact、1 条 orchestration result；重放增量 0，回滚残留 0。
受控UPDATE对象和审计ID：0；日志适配器仅使用 INSERT IGNORE + 内容一致性读取，事务提交/回滚由调用方拥有。
文件删除数量：0。
数据库物理删除数量：0。
执行命令：`make PYTHON=.venv-g1-release-py311/bin/python G4_AGENT_RUN_ID=g4-agent-migration-20260809-001 migrate-g4-agent-logs`；`make PYTHON=.venv-g1-release-py311/bin/python G4_AGENT_RUN_ID=g4-agent-runtime-20260809-002 verify-g4-agent-logs`；`make PYTHON=.venv-g1-release-py311/bin/python test-g4`；`python scripts/architecture_guard.py --root .`；`python scripts/safety_scan.py --root .`。
测试结果：G4 测试 11 项 PASS；MySQL migration statement_count=5；commit delta=7/7/1/1；replay delta=0；rollback delta=0；SQL inserts=16、updates=0、deletes=0；安全扫描 174 文件 PASS；架构扫描 72 文件 PASS；`destructive_actions=0`。
验证证据目录：`artifacts/verification/g4/g4-agent-migration-20260809-001/agent-migration.json`；`artifacts/verification/g4/g4-agent-runtime-20260809-002/agent-runtime.json`。
配置/数据/索引版本：migration=g4-agent-execution-v1；orchestrator=g4-orchestrator-v1；Agent log schema=message/result/artifact/final-v1；外部通道写入 0。
异常与处置：首次 runtime 尝试在 DATETIME(3) 身份比较处发现微秒精度不一致，修正为毫秒规范化后使用新 run-id 重跑通过；首次尝试只追加隔离 G3 任务事实，未删除文件、表、卷或任何数据。
未解决风险：真实 Catalog/Profile 端口尚未由 Orchestrator 调用；deadline 超时、失败重试和正式 API 组合根待下一小步；Docker CLI 默认 PATH 链接需由环境维护，当前使用 `/Applications/编程/Docker.app/Contents/Resources/bin/docker` 验证。
下一步唯一动作：补齐 Orchestrator 到真实只读 Catalog/Profile 端口的显式组合根，并验证超时/失败重试的追加事实与恢复边界。
```

## G4 真实 Catalog/Profile 只读组合根与韧性记录

```text
交接ID：G4-REAL-PORTS-20260809-001
Gate：G4 动态多智能体闭环（真实只读端口/韧性小步）
状态：CONTRACT_PASS, LOCAL_RUNTIME_PASS, MYSQL_RUNTIME_PASS / IN_PROGRESS
时间：2026-08-09（Asia/Shanghai）
目标：通过显式组合根替换 Profile/Semantic/Recall 的规则 Agent，使用 Catalog/Profile 只读端口，固定 evaluation_at，并验证 deadline、最多两次重试和降级边界。
新增文件：backend/app/profile/ports/；backend/app/profile/adapters/；backend/app/recommendation/agents/real_agents.py；scripts/verify_g4_real_ports_runtime.py；tests/g4/test_port_orchestrator.py；tests/g4/test_real_port_contract.py。
修改文件及原版本保存位置：Catalog MySQL 时间参数规范化；Agent base 增加 RetryPolicy/DependencyCallFailed/call_with_retry；OrchestrationRequest 增加 evaluation_at；application 增加 build_port_orchestrator；Makefile 增加 verify-g4-real-ports；原版本由 Git 提交历史保留。
新增数据库对象和行数：0；运行态只读端口验证不新增对象和事实行，seed/replay 仅使用既有幂等脚本；真实端口验证前后资源/画像相关表行数不变。
受控UPDATE对象和审计ID：0；Profile/Catalog 适配器均无 INSERT/UPDATE/DELETE；Agent 只持有端口。
文件删除数量：0。
数据库物理删除数量：0。
执行命令：`python -m unittest discover -s tests/g4 -t tests -p 'test_*.py'`；`make PYTHON=.venv-g1-release-py311/bin/python G4_PORT_RUN_ID=g4-real-ports-20260809-001 verify-g4-real-ports`；`python scripts/architecture_guard.py --root .`；`python scripts/safety_scan.py --root .`。
测试结果：G4 21 项 PASS；真实 MySQL 端口运行 status=PASS、7 dispatches、Profile event_count=4、Catalog resource_count=5、candidate_count=5；运行前后只读表计数一致；RetryPolicy 最多 2 次；expired deadline fail-closed；安全扫描 182 文件 PASS；架构扫描 77 文件 PASS；`destructive_actions=0`。
验证证据目录：`artifacts/verification/g4/g4-real-ports-20260809-001/real-ports-runtime.json`。
配置/数据/索引版本：profile=profile-mysql-v1；semantic=semantic-mysql-v1；recall=recall-mysql-v1；retry=max_attempts-2；evaluation_at=explicit。
未解决风险：真实 Orchestrator/API 组合根尚未接入正式 HTTP；Catalog/Profile 仍是当前投影读取而非历史重算；超时后的跨 Agent 持久化恢复和 Worker 重试待下一小步；G3 正式 Token 部署参数仍待审查。
下一步唯一动作：将 `build_port_orchestrator` 接入显式 Demo/研究组合根，并把 Agent 日志与任务最终结果接入同一 orchestration service；默认 API 仍保持关闭。
```

## G4 显式 Demo/Research 组合根与持久化编排记录

```text
交接ID：G4-COMPOSITION-20260809-001
Gate：G4 动态多智能体闭环（显式组合根/事务编排小步）
状态：CONTRACT_PASS, LOCAL_RUNTIME_PASS, MYSQL_RUNTIME_PASS / IN_PROGRESS
时间：2026-08-09（Asia/Shanghai）
目标：把真实端口 Orchestrator、Agent 日志和 trace artifact 放入独立 application service，由根级 Demo/Research builder 显式装配；默认 FastAPI 不自动启用。
新增文件：backend/app/composition.py；backend/app/recommendation/application/persistent_orchestration.py；scripts/verify_g4_composition_runtime.py；tests/g4/test_persistent_orchestration.py；tests/g4/test_composition_root_contract.py。
修改文件及原版本保存位置：Makefile 增加 verify-g4-composition；实施状态记录更新；原版本由 Git 提交历史保留。
新增数据库对象和行数：0；复用既有 G4 四张事实表；首次组合运行追加 7 条 Agent message、7 条 Agent result、1 条 ORCHESTRATION_TRACE artifact、1 条 final orchestration result；重复调用 delta=0。
受控UPDATE对象和审计ID：0；service 只执行 Catalog/Profile SELECT、G4 INSERT IGNORE 与身份读取，事务由 service 单点 commit/rollback 管理。
文件删除数量：0。
数据库物理删除数量：0。
执行命令：`python -m unittest discover -s tests/g4 -t tests -p 'test_*.py'`；`make PYTHON=.venv-g1-release-py311/bin/python G4_COMPOSITION_RUN_ID=g4-composition-20260809-001 verify-g4-composition`；`python scripts/architecture_guard.py --root .`；`python scripts/safety_scan.py --root .`。
测试结果：G4 28 项 PASS；持久化成功提交、append 失败回滚、冻结时间边界、内容寻址 artifact 和 Demo/Research 环境门禁均 PASS；隔离 MySQL status=PASS、7 dispatches、首次 delta=7/7/1/1、重放 delta=0；六张资源/画像保护表不变；安全扫描 187 文件 PASS；架构扫描 79 文件 PASS；`destructive_actions=0`。
验证证据目录：`artifacts/verification/g4/g4-composition-20260809-001/composition-runtime.json`。
配置/数据/索引版本：composition=research-v1；orchestrator=g4-orchestrator-v1；artifact=g4-orchestration-trace-v1；retry=max_attempts-2；evaluation_at/deadline=explicit。
未解决风险：正式 HTTP/Worker 尚未接入该 service；数据库重启后的持久化结果恢复读取、跨请求幂等 replay 和历史画像重算待后续 Gate；G3 正式 Token 部署参数仍待审查。
下一步唯一动作：进入 G5，新增 append-only 反馈事件端口和幂等行为事实写入，再以固定 as-of replay 验证画像更新；默认 API 仍保持关闭。
```

## G5 反馈事实与画像 Outbox 第一垂直切片记录

```text
交接ID：G5-FEEDBACK-20260809-001
Gate：G5 曝光反馈画像闭环（第一垂直切片）
状态：CONTRACT_PASS, LOCAL_PASS, MYSQL_RUNTIME_PASS / IN_PROGRESS
时间：2026-08-09（Asia/Shanghai）
目标：在默认 API 关闭的前提下，把推荐曝光、反馈、行为和资源状态作为幂等事实追加，并以受控 Profile outbox worker 完成固定 as-of 画像重放。
新增文件：infra/mysql/migrations/006_g5_feedback_state.sql；backend/app/feedback/domain、ports、adapters、application；backend/app/profile/adapters/behavior_mysql.py、refresh_mysql.py；backend/app/profile/application/refresh.py；scripts/migrate_g5_feedback.py；scripts/verify_g5_feedback_runtime.py；tests/g5/。
修改文件及原版本保存位置：backend/app/composition.py 增加 opt-in feedback service 与受控凭据 worker builder；Profile 端口/适配器导出；Makefile 增加 G5 migration、local test 和 runtime gate；原版本由 Git 提交历史保留。
新增数据库对象和行数：新增 3 张前向表（recommendation_impression、recommendation_feedback、user_resource_state）；隔离 Compose MySQL 本次追加 1 条曝光、1 条反馈、2 条行为、1 条资源状态、1 条 outbox；worker 消费既有 8 条 seed outbox 与新增 1 条，共 9 条 DONE；新增 9 条 replay run、6 条 profile change log（具体前后计数保存在 runtime evidence）。
受控UPDATE对象和审计ID：profile_update_outbox claim/status、user_profile、user_interest_tag、user_negative_preference、user_resource_state；均为受控键条件更新，无物理删除；worker 使用显式 migration 凭据，feedback runtime 使用 SELECT/INSERT runtime 凭据。
文件删除数量：0。
数据库物理删除数量：0。
执行命令：`PYTHONDONTWRITEBYTECODE=1 .venv-g1-release-py311/bin/python -m unittest discover -s tests/g5 -t tests -p 'test_*.py'`；`python -m scripts.migrate_g5_feedback --run-id g5-migration-check-20260809 --env-file .env.compose`；`python -m scripts.verify_g5_feedback_runtime --run-id g5-feedback-20260809-001 --env-file .env.compose`；验证后仅 `docker compose stop mysql`。
测试结果：G5 9 项测试 PASS；迁移 4 条语句 dry-run PASS；MySQL 运行态验证曝光/反馈双 UUID 幂等（事实 delta=1/1/2）、反馈 outbox=1、worker 首轮 9 receipts、二次消费 delta=0、全部 outbox=DONE、固定 as-of replay 生成负向主题画像；安全扫描 208 文件 PASS；架构扫描 93 文件 PASS；`destructive_actions=0`。
验证证据目录：`artifacts/verification/g5/g5-migration-check-20260809/migration.json`；`artifacts/verification/g5/g5-feedback-20260809-001/g5-runtime.json`。
配置/数据/索引版本：migration=g5-feedback-state-v1；formula=profile-g2-v1；event facts=append-only；outbox worker=claim/apply/mark-done-v1；默认 API=disabled。
未解决风险：HTTP feedback DTO/opt-in router、worker retry/DEAD 故障注入与重复 claim 测试、正式部署的 worker controlled-write credential scope、历史画像重算和数据库重启恢复读取待后续小步；合成数据仍不得用于正式论文评价。
下一步唯一动作：补齐 worker retry/DEAD 故障注入和 opt-in feedback HTTP 契约，再评审 G5 Gate；不自动开启默认推荐 API。
```

## G5 opt-in Interaction HTTP 与权限收口记录

```text
交接ID：G5-HTTP-20260810-004
Gate：G5 曝光反馈画像闭环（HTTP/权限第二小步）
状态：CONTRACT_PASS, LOCAL_PASS, MYSQL_RUNTIME_PASS / IN_PROGRESS
时间：2026-08-10（Asia/Shanghai）
目标：把曝光、反馈和直接行为以显式 opt-in HTTP DTO 暴露，在用户身份和推荐项所有权边界内追加事实，并验证 Worker 对 HTTP 产生的 Outbox 进行确定性画像刷新。
新增文件：backend/app/api/feedback.py；backend/app/feedback/application/public.py；scripts/g5_runtime_permissions.py；scripts/verify_g5_http_runtime.py；tests/g5/test_feedback_api.py。
修改文件及原版本保存位置：backend/app/main.py、backend/app/composition.py、backend/app/feedback/application/service.py、backend/app/feedback/adapters/mysql.py、backend/app/feedback/ports/public.py、backend/app/profile/adapters/behavior_mysql.py、backend/app/profile/application/refresh.py、backend/app/observability/adapters/mysql_readiness.py、infra/mysql/init/10-create-runtime-user.sh、Makefile、G5 测试与验证脚本；原版本由 Git 提交历史保留。
新增数据库对象和行数：0（复用 G5 前向表）；真实 run `g5-http-20260810-004` 追加 1 条曝光、1 条反馈、3 条行为、2 条 Outbox；`user_resource_state` 因同一状态已存在而执行一次四列白名单 UPDATE，state_version 2→3，source_event_id 更新为 28；Worker 后全部 15 条 Outbox 为 DONE。
受控UPDATE对象和审计ID：`user_resource_state.suppress_until/source_event_id/last_feedback_at/state_version`；`profile_update_outbox` claim/status、`user_profile`、`user_interest_tag`、`user_negative_preference`；运行账号不授予全库 UPDATE，权限由迁移后 root-only 操作脚本按列授予，应用连接不持有 root/migration 凭据。
文件删除数量：0。
数据库物理删除数量：0。
执行命令：`PYTHONDONTWRITEBYTECODE=1 .venv-g1-release-py311/bin/python -m unittest discover -s tests/g5 -t tests -p 'test_*.py'`；`python scripts/architecture_guard.py --root .`；`python scripts/safety_scan.py --root .`；`python -m scripts.verify_g5_http_runtime --run-id g5-http-20260810-004 --env-file .env.compose`；验证后仅 `docker compose stop mysql`。
测试结果：G5 17 项 PASS；编译、架构 95 文件 PASS、安全 213 文件 PASS；HTTP 首写返回 200/202、同 UUID 重放返回 200/REPLAYED；派生行为返回 `DERIVED_EVENT_NOT_ALLOWED`；默认 app 仍不暴露交互路由；HTTP 前后受保护资源/标签/声明画像事实表计数不变；Worker 首轮消费 6 条、二次消费 0 条、全部 Outbox=DONE；destructive_actions=0。
验证证据目录：`artifacts/verification/g5/g5-http-20260810-004/http-runtime.json`；之前失败的 `g5-http-20260810-001/002/003` 未执行清理，已写入的事实继续保留。
配置/数据/索引版本：http=interaction-v1；migration=g5-feedback-state-v1；formula=profile-g2-v1；runtime-grant=user_resource_state 四列；default API=disabled。
未解决风险：正式 Bearer Token 验证器和 production deployment 尚未配置；真实 MySQL Worker 故障注入/DEAD 运行态与重启恢复读取待下一小步；G5 仍未进入默认 HTTP。
下一步唯一动作：补做真实 MySQL Worker retry/DEAD 故障注入和数据库重启恢复读取，继续保持默认 API 关闭。
```

## G5 Worker 故障注入与 MySQL 重启恢复记录

```text
交接ID：G5-WORKER-RECOVERY-20260810-001
Gate：G5 曝光反馈画像闭环（Worker 故障/恢复第三小步）
状态：CONTRACT_PASS, LOCAL_PASS, MYSQL_RUNTIME_PASS / IN_PROGRESS
时间：2026-08-10（Asia/Shanghai）
目标：在真实 MySQL 上验证 Outbox 失败不丢事实、达到最大尝试次数进入 DEAD、数据库重启后 DEAD/PENDING 状态可读取，并由真实 Profile Worker 完成恢复消费。
新增文件：scripts/verify_g5_worker_recovery_runtime.py。
修改文件及原版本保存位置：Makefile 增加 `verify-g5-worker-prepare`/`verify-g5-worker-resume`；实施状态记录更新；原版本由 Git 提交历史保留。
新增数据库对象和行数：0；run `g5-worker-recovery-20260810-001` 追加 2 条行为事实和 2 条 Outbox 行。Outbox 20 注入三次 `RuntimeError` 后保留为 `DEAD/attempts=3`；Outbox 21 在重启前保持 `PENDING/attempts=0`，重启后被健康 Worker 消费为 `DONE/attempts=1`；Outbox 总行数 17→17。
受控UPDATE对象和审计ID：`profile_update_outbox` claim/status、两次仅用于加速测试重试的 `next_retry_at=NULL`、健康 Worker 的 claim/apply/mark-done，以及既有画像投影更新；无事实 UPDATE、无物理删除。
文件删除数量：0。
数据库物理删除数量：0。
执行命令：`python -m scripts.verify_g5_worker_recovery_runtime --run-id g5-worker-recovery-20260810-001 --phase prepare --env-file .env.compose`；`docker compose --env-file .env.compose restart mysql`；等待 healthy；`python -m scripts.verify_g5_worker_recovery_runtime --run-id g5-worker-recovery-20260810-001 --phase resume --env-file .env.compose`；验证后仅 `docker compose stop mysql`。
测试结果：prepare/resume 均 PASS；三次注入失败的 attempts 轨迹为 1→2→3，最终错误码为 `RuntimeError`；重启前后 15 张事实/投影/保护表计数完全一致；重启后状态为 `DEAD=1,DONE=15,PENDING=1`，健康 Worker 后为 `DEAD=1,DONE=16`；画像 replay run 19→20、profile change log 20→22；健康 Worker 二次消费返回 0；destructive_actions=0。
验证证据目录：`artifacts/verification/g5/g5-worker-recovery-20260810-001/prepare.json`；`artifacts/verification/g5/g5-worker-recovery-20260810-001/runtime.json`。
配置/数据/索引版本：worker=claim/apply/mark-done-v1；max_attempts=3；formula=profile-g2-v1；recovery=MySQL-container-restart；default API=disabled。
未解决风险：正式 Bearer Token 验证器和 production deployment 尚未配置；`domain_state_transition` 迁移/同事务审计及历史画像重算仍未实现；G5 仍未进入默认 HTTP。
下一步唯一动作：评审并实现状态迁移审计事实与历史画像重算前置设计，继续保持默认 API 关闭。
```

## G5 状态迁移审计与历史时点画像记录

```text
交接ID：G5-AUDIT-REPLAY-20260810-001
Gate：G5 曝光反馈画像闭环（状态审计/历史重算第四小步）
状态：CONTRACT_PASS, LOCAL_PASS, MYSQL_RUNTIME_PASS / IN_PROGRESS
时间：2026-08-10（Asia/Shanghai）
目标：把 G5 当前投影与技术状态更新接入同事务 domain_state_transition，并证明历史 as_of 画像读取不依赖当前投影、不写数据库。
新增文件：infra/mysql/migrations/007_g5_state_transition_audit.sql；backend/app/observability/domain/transition.py；backend/app/observability/domain/public.py；backend/app/observability/ports/audit.py；backend/app/observability/ports/public.py；backend/app/observability/adapters/mysql_transition.py；scripts/migrate_g5_state_transition.py；scripts/verify_g5_audit_replay_runtime.py；tests/g5/test_state_transition.py。
修改文件及原版本保存位置：G5 Behavior/Feedback/Profile MySQL 适配器、composition、ProfileSnapshotReader、Makefile、data_dictionary.md 与实施状态记录；原版本由 Git 提交历史保留。
新增数据库对象和行数：新增 1 张 `domain_state_transition` 表；真实 run `g5-audit-replay-20260810-001` 追加 2 条行为事实、2 条 Outbox 和 8 条审计事实；Outbox 创建/claim/DONE 各 2 条，画像版本迁移 2 条；后续 HTTP 运行验证 `USER_RESOURCE_STATE` 创建审计和同事务反馈链路。
受控UPDATE对象和审计ID：`user_resource_state` 四列白名单、`profile_update_outbox` claim/status、`user_profile`/兴趣/负偏好当前投影；每次状态更新由 `MySQLStateTransitionWriter` 在同一调用方事务追加并做 UUID/载荷一致性校验。
历史重算语义：`MySQLProfileSnapshotReader` 只读取 `user_behavior_event` 与 `resource_tag` 的 `occurred_at <= as_of` 事实并调用 `profile-g2-v1` 确定性公式；早/晚快照事件数 20/21，输入哈希不同，晚快照重复读取哈希一致，读取前后数据库计数不变。
文件删除数量：0。
数据库物理删除数量：0。
执行命令：`python -m scripts.verify_g5_audit_replay_runtime --run-id g5-audit-replay-20260810-001 --env-file .env.compose`；`python -m scripts.verify_g5_http_runtime --run-id g5-http-20260810-005 --env-file .env.compose`；`python -m scripts.verify_g5_worker_recovery_runtime --run-id g5-worker-recovery-20260810-002 --phase prepare/resume --env-file .env.compose`；验证后仅停止 MySQL 容器。
测试结果：后端 318 项 PASS；G5 21 项 PASS；状态迁移/历史重放真实 MySQL PASS；安全、架构、文档和契约门禁 PASS；`destructive_actions=0`。
验证证据目录：`artifacts/verification/g5/g5-audit-migration-20260810-001/audit-migration.json`；`artifacts/verification/g5/g5-audit-replay-20260810-001/runtime.json`；`artifacts/verification/g5/g5-http-20260810-005/http-runtime.json`；`artifacts/verification/g5/g5-worker-recovery-20260810-002/runtime.json`。
配置/数据/索引版本：audit=g5-state-transition-audit-v1；worker=claim/apply/mark-done-v1；formula=profile-g2-v1；reader=historical-select-replay-v1；default API=disabled。
未解决风险：正式 Bearer Token 验证器、默认 Compose API、production deployment 和论文实验数据冻结尚未配置；G5 仍未进入默认 HTTP。
下一步唯一动作：评审 G5 Gate 的正式认证/默认 HTTP 与实验冻结清单，继续保持默认 API 关闭。
```

## G5 正式 Bearer 身份与默认业务路由门禁记录

```text
交接ID：G5-FORMAL-AUTH-20260810-001
Gate：G5 曝光反馈画像闭环（正式认证最小安全切片）
状态：CONTRACT_PASS, LOCAL_PASS, RUNTIME_PASS / IN_PROGRESS
时间：2026-08-10（Asia/Shanghai）
目标：在不打开默认业务 API 的前提下，提供可替换的正式 Bearer Token 验证器，并验证普通用户、research_admin、非法 Token 和 Demo Header 的门禁行为。
新增文件：backend/app/platform/__init__.py；backend/app/platform/auth.py；scripts/verify_formal_auth_runtime.py；tests/g3/test_formal_auth.py。
修改文件及原版本保存位置：backend/app/config.py、backend/app/composition.py、backend/app/main.py、compose.yaml、.env.compose.example、.env.host.example、Makefile、docs/api.md 与本交接记录；原版本由 Git 提交历史保留。
实现边界：Platform 适配器仅支持严格 HS256 JWT；校验 typ/alg、iss、aud、sub、已知角色、exp 以及可选 nbf/iat/jti；仅传递 AuthenticatedPrincipal，不记录原始 Token。外部 OIDC/JWKS 需要在组合根替换适配器，不改变 API/领域端口。
配置门禁：RECPRO_AUTH_ENABLED 默认 false；启用时必须提供不小于 32 字符的 RECPRO_AUTH_JWT_SECRET，issuer/audience/clock skew 由 RECPRO_ 配置显式控制；认证开关与 recommendation/feedback service、API enable flag 相互独立。
新增数据库对象和行数：0；运行态未启动、连接或修改 MySQL/Neo4j/Chroma。
受控UPDATE对象和审计ID：0；不适用。
文件删除数量：0。
数据库物理删除数量：0。
执行命令：`python -m unittest tests.g3.test_formal_auth -v`；`python -m scripts.verify_formal_auth_runtime --run-id 20260810-001`；验证脚本创建新的证据目录并使用 TestClient，不执行删除、清空、迁移或数据库连接。
测试结果：认证 5 项 PASS；默认业务路由 404，合法用户 Bearer 201，非法 Token 401，Bearer 与 Demo Header 混用 403，research-admin Debug 200，普通用户/混用身份 Debug 403；数据库读写 0，destructive_actions=0。
验证证据目录：`artifacts/verification/g5/g5-formal-auth-20260810-001/runtime.json`。
配置/数据/索引版本：auth=hs256-bearer-v1；claims=iss/aud/sub/roles/exp/nbf/iat/jti；default business API=disabled。
未解决风险：当前只完成受控 Secret 的 HS256 适配器；外部 OIDC/JWKS、production service composition、默认 Compose API 和论文实验数据冻结仍需 Gate 评审。
下一步唯一动作：评审外部身份提供方/默认 HTTP 的启用条件，继续保持默认 API 关闭。
```

## 生产 HTTP 组合根与论文实验冻结前置记录

```text
交接ID：PLATFORM-FREEZE-PREFLIGHT-20260810-001
Gate：生产 HTTP 显式组合与论文实验冻结前置
状态：CONTRACT_PASS, LOCAL_PASS, PREFLIGHT_PASS_WITH_BLOCKERS / IN_PROGRESS
时间：2026-08-10（Asia/Shanghai）
目标：为正式部署建立 production HTTP 的显式 fail-closed 组合根，并在任何论文确认性实验前验证协议、Manifest、seed 哈希、Git clean 状态和 F1-F3 产物边界。
新增文件：scripts/verify_experiment_freeze.py；tests/g4/test_production_composition.py；tests/g9/__init__.py；tests/g9/test_experiment_freeze.py。
修改文件及原版本保存位置：backend/app/config.py、backend/app/composition.py、compose.yaml、.env.compose.example、.env.host.example、Makefile、docs/api.md、docs/experiment_protocol.md 与本交接记录；原版本由 Git 提交历史保留。
生产组合门禁：仅当 RECPRO_APP_ENV=production、RECPRO_PRODUCTION_HTTP_ENABLED=true、正式 Bearer Secret、Recommendation/Feedback/Behavior 三个服务和完整业务 API 开关同时满足时，build_production_http_app() 才构造路由；默认 backend.app.main:app 和 Compose 仍为 health-only，构造阶段不打开数据库连接。
冻结前置结果：协议版本 1.0.0、协议必需门禁标记、G2 dataset_manifest 与 seed SHA-256 一致，Git 工作区 clean；当前 synthetic-demo-2026-08 被标记 DEMO_FIXTURE，缺少 F2 split_manifest、盲标注 annotation_manifest 和 F3 config_manifest，因此 paper_confirmation_ready=false。
新增数据库对象和行数：0；冻结检查和生产组合根测试未连接或修改任何数据库。
受控UPDATE对象和审计ID：0；不适用。
文件删除数量：0。
数据库物理删除数量：0。
执行命令：`python -m unittest discover -s tests/g4 -t tests -p 'test_*.py'`；`python -m unittest discover -s tests/g9 -t tests -p 'test_*.py'`；`python -m scripts.verify_experiment_freeze --run-id freeze-20260810-001`；`docker compose --env-file .env.compose config --quiet`。
测试结果：G4 33 项、G9 3 项 PASS；freeze preflight=`PASS_WITH_BLOCKERS`；database_reads=0、database_writes=0、expected_delete_count=0、actual_delete_count=0、overwritten_runs=0。
验证证据目录：`artifacts/verification/experiment/freeze-20260810-001/freeze-preflight.json`。
配置/数据/索引版本：production-gate=explicit-production-http-v1；protocol=1.0.0；dataset=synthetic-demo-2026-08；default business API=disabled。
未解决风险：真实评价数据来源/许可、匿名化、F2 Split、盲标注、F3 配置 Manifest、正式 Worker 接线和外部 OIDC/JWKS 仍未完成；不得把当前合成 Fixture 用于论文确认性结论。
下一步唯一动作：先补齐真实评价数据和冻结产物，再评审 Worker/外部 IdP；默认 API 继续关闭。
```

## 正式评价输入契约与只读冻结门禁记录

```text
交接ID：EVAL-INPUT-CONTRACT-20260810-001
Gate：G9 正式评价输入契约与冻结前置（第一小步）
状态：CONTRACT_PASS, LOCAL_PASS, PREFLIGHT_PASS_WITH_BLOCKERS / IN_PROGRESS
时间：2026-08-10（Asia/Shanghai）
目标：把真实数据来源/许可、盲标注、F2 Split 和 F3 配置拆成低耦合、高内聚的五类 Manifest，并在不连接数据库、不覆盖输入的前提下提供可复现的只读校验。
新增文件：contracts/experiment/dataset-manifest.schema.json；contracts/experiment/license-manifest.schema.json；contracts/experiment/annotation-manifest.schema.json；contracts/experiment/split-manifest.schema.json；contracts/experiment/config-manifest.schema.json；scripts/verify_evaluation_freeze_inputs.py；tests/g9/test_evaluation_freeze_inputs.py。
修改文件及原版本保存位置：Makefile 增加 `verify-evaluation-freeze-inputs` 与 `EVAL_INPUT_RUN_ID`；docs/experiment_protocol.md 增加五类 Manifest 契约和输入冻结命令；本交接记录更新；原版本由 Git 提交历史保留。
新增数据库对象和行数：0；校验器只读取本地文件和 Git 元数据，数据库读写均为 0。
受控UPDATE对象和审计ID：0；不适用。
输入边界：当前默认 G2 `synthetic-demo-2026-08` 仅用于证明阻断逻辑，未创建任何虚假真实数据、许可、标注、Split 或配置 Manifest；真实 `data/evaluation/` 目录仍由用户授权后的数据准备阶段填充。
文件删除数量：0。
数据库物理删除数量：0。
执行命令：`python -m unittest discover -s tests/g9 -t tests -p 'test_*.py'`；`python -m scripts.verify_evaluation_freeze_inputs --run-id eval-inputs-20260810-002`；后续将执行完整 G0-G5/G9 回归、文档/契约/架构/安全门禁和 Compose config 校验。
测试结果：评价输入门禁 7 项 PASS；当前输入冻结报告 `PASS_WITH_BLOCKERS`，阻断码包含 `DATASET_MANIFEST_INVALID`、`SYNTHETIC_DATASET`、`LICENSE_MANIFEST_MISSING`、`ANNOTATION_MANIFEST_MISSING`、`SPLIT_MANIFEST_MISSING`、`CONFIG_MANIFEST_MISSING`；safety.database_reads=0、database_writes=0、actual_delete_count=0、overwritten_runs=0。
验证证据目录：`artifacts/verification/experiment-inputs/eval-inputs-20260810-002/input-freeze-report.json`（被 `.gitignore` 保护，不覆盖已有 evidence；此前的 `eval-inputs-dryrun-20260810-001` 和 `eval-inputs-20260810-001` 均保留）。
配置/数据/索引版本：manifest-schemas=evaluation-*-manifest-v1；freeze-report=evaluation-input-freeze-report-v1；dataset=synthetic-demo-2026-08（development-only）；default business API=disabled。
未解决风险：真实评价数据来源、许可审批证据、匿名化、Track-I/Track-J 选择、盲标注及一致性、F2 Split、F3 配置、G8 发布候选和外部 IdP/JWKS/Worker 评审仍未完成；不能运行论文确认性测试。
下一步唯一动作：在不提交身份映射和受限原始数据的前提下，依据五类 Schema 接收真实数据及许可/标注/Split 证据，逐项通过只读输入门禁后再进入 F3 配置冻结。
```

## G6 数据平面与图书接入前置记录

```text
交接ID：G6-DATA-INTAKE-20260810-001
Gate：G6 可选检索与解释（数据平面、书目接入前置）
状态：CONTRACT_PASS, LOCAL_PASS, RUNTIME_PASS / IN_PROGRESS
时间：2026-08-10（Asia/Shanghai）
目标：在不改动现有事实的前提下确认 MySQL/Neo4j 可用，并建立用户爬取书目进入 MySQL 事实层和 Neo4j 版本化图之前的规范化、许可、隐私、哈希和重复检查。
新增文件：contracts/data/intake/book-record.schema.json；contracts/data/intake/book-intake-manifest.schema.json；scripts/inspect_book_intake.py；scripts/verify_data_plane_runtime.py；tests/g6/test_book_intake.py；tests/g6/test_data_plane_runtime.py。
修改文件及原版本保存位置：Makefile 增加 `verify-book-intake`、`verify-data-plane-runtime` 和对应 Run ID；.gitignore 忽略本地 `data/incoming/books/`；README.md、docs/experiment_protocol.md 与本交接记录增加数据入口和当前依赖事实；原版本由 Git 提交历史保留。
数据平面结果：Compose 项目 `recpro-g2-tianyuhang-20260809a` 的 MySQL/Neo4j 均 healthy；MySQL 表数量 40；Neo4j 节点/关系 0/0；干净工作区报告绑定提交 `a49b7a86b7b037c629e172202de49e393b26bce7`。
新增数据库对象和行数：0；只读检查执行 MySQL SELECT 1 次、Neo4j count 查询 2 次；没有迁移、导入或业务写入。
受控UPDATE对象和审计ID：0；数据库物理删除数量：0；文件删除数量：0；覆盖数量：0；只读验证器服务启停动作：0（前置 `up -d` 仅启动/复用隔离服务，未执行 stop/down/rm 或卷删除）。
输入边界：用户尚未提供书目 JSONL/原始抓取文件、来源许可或字段说明；未创建、伪造或导入任何书目数据。干净工作区 intake 报告按设计为 `PASS_WITH_BLOCKERS`，唯一阻断码为 `INTAKE_MANIFEST_MISSING`。
执行命令：`python -m unittest discover -s tests/g6 -t tests -p 'test_*.py'`；`make DATA_PLANE_RUN_ID=data-plane-20260810-003 verify-data-plane-runtime`；`make BOOK_INTAKE_RUN_ID=books-intake-preflight-20260810-002 verify-book-intake`；`docker compose --env-file .env.compose up -d mysql neo4j`（仅启动/复用服务，未执行 down、rm、volume 删除或迁移）。
测试结果：G6 8 项单元测试 PASS；数据平面只读报告 PASS；MySQL/Neo4j 查询与安全计数符合预期；intake 无输入时安全阻断。
验证证据目录：`artifacts/verification/data-plane/data-plane-20260810-003/runtime.json`；`artifacts/verification/data-intake/books-intake-preflight-20260810-002/book-intake-report.json`（均为本地 `.gitignore` 保护的追加式证据）。
配置/数据/索引版本：book-record=library-book-record-v1；intake-manifest=library-book-intake-manifest-v1；data-plane-report=data-plane-runtime-report-v1；Neo4j graph_version 尚未创建；外部 LLM=未配置，Mock/模板保持默认。
未解决风险：Neo4j 图构建/图召回、向量索引、外部 LLM Provider、默认 HTTP/Worker 接线和真实书目导入均未完成；未经用户确认来源/许可和 intake 门禁通过，不得写入数据库。
下一步唯一动作：接收用户授权的书目文件、来源/许可证据、字段说明和是否包含用户数据的确认；通过 intake 后再提交独立的 MySQL append-only 导入与 Neo4j 新 graph_version ChangePlan。
```

## G6 外部 Neo4j 只读盘点与凭据隔离记录

```text
交接ID：G6-DB-BOUNDARY-20260810-002
Gate：G6 数据库边界与凭据隔离
状态：READ_ONLY_AUDIT_PASS / IN_PROGRESS
时间：2026-08-10（Asia/Shanghai）
目标：保存用户提供的本地管理凭据，识别本机已有 Neo4j 数据库，并确保 RecPro 不复用或修改该数据库。
凭据保存：实际凭据仅写入本机 `.env.user-secrets`，权限 0600，Git 忽略；仅提交无值模板 `.env.user-secrets.example`，密码未进入代码、日志、证据或提交。
外部实例识别：Homebrew Neo4j Community 进程，Bolt `127.0.0.1:7687`、HTTP `127.0.0.1:7474`；只读 `SHOW DATABASES` 返回 `neo4j` 与 `system`，默认 `neo4j` 库在线。
外部数据计数：`neo4j` 库节点 59,301、关系 185,238；标签 10 类、关系类型 13 类。查询使用 `--access-mode read`，未执行写 Cypher、DDL、导入、清空或删除。
RecPro 边界：RecPro 使用独立 Compose Neo4j 容器和独立数据卷，当前隔离库节点/关系为 0/0；不得连接本机 `7474/7687`。Neo4j Community 不能在同一实例提供额外独立命名库，因此以独立实例/卷作为新数据库边界。
新目标实例：`recpro-library-neo4j-20260810a-neo4j-1`，数据卷 `recpro-library-neo4j-20260810a_neo4j_data`，HTTP/Bolt 主机端口 `62475/62688`；使用用户提供的 Neo4j 凭据认证成功，`SHOW DATABASES` 仅有空的 `neo4j` 与 `system`。
临时容器处理：为核对旧 `agentsystem-neo4j-1` 容器曾安全启动后执行只读计数（0/0），随后恢复为 stopped；未删除容器、卷或数据。Homebrew Neo4j 外部实例始终保持运行，未停止或重启。
新增数据库对象和行数：0；外部 Neo4j 只读查询，不写入 RecPro 或外部数据库。
文件删除数量：0；数据库物理删除数量：0；覆盖数量：0；容器删除动作：0；临时 `agentsystem-neo4j-1` 停止动作：1（恢复其原 stopped 状态）；Homebrew Neo4j 外部实例未停止。
未解决风险：应用组合根尚未切换到新目标实例，当前旧 RecPro 验证实例仍保留；正式图书导入前必须在配置 Bundle 中显式选择新目标实例，并保留旧隔离卷，不原地改密或复用外部大图。
下一步唯一动作：把新目标实例的端口/凭据引用接入独立配置 Bundle，完成只读健康门禁后，再接收书目导入。
```

## G6 书目图计划与 DeepSeek 适配准备记录

```text
交接ID：G6-BOOK-GRAPH-20260810-003
Gate：G6 可选检索与解释（书目图建模、Neo4j 预演、LLM 适配准备）
状态：PLAN_PASS, DRY_RUN_PASS / IMPORT_PENDING_USER_CONFIRMATION
时间：2026-08-10（Asia/Shanghai）
目标：将 Lib CSV 固化为可审计的实体/关系/三元组计划，并在 RecPro 独立 Neo4j 目标上完成只读预演；同时准备 DeepSeek 端口而不泄露或猜测密钥。
新增文件：`contracts/data/intake/book-graph-plan.schema.json`；`scripts/build_book_graph_plan.py`；`scripts/import_book_graph.py`；`docs/book_graph_model.md`；`backend/app/llm/adapters/deepseek.py`；`tests/g6/test_book_graph_plan.py`；`tests/g1/backend/test_deepseek_llm.py`。
修改文件及原版本保存位置：`Makefile` 增加图计划/预演/显式导入命令；`backend/app/config.py` 增加 DeepSeek opt-in 配置和 fail-closed 校验；LLM 导出、`.env.user-secrets.example`、README、本记录更新；原版本由 Git 提交历史保留。
输入审查：`Lib` 共 76 个 CSV、15,538 条有效来源记录；图计划包含 63,388 个节点和 191,865 条关系；状态 `PASS_WITH_WARNINGS`，371 条警告均为 ISBN 规范化问题；187 个 ISBN 冲突组按内容指纹拆分，不强行合并。
图模型：GraphVersion、SourceFile、SourceRecord、Book、Category、Topic、Author、Publisher、SubjectCode、Keyword 十类实体；SourceRecord/DESCRIBES、Book/CLASSIFIED_AS、AUTHORED_BY、PUBLISHED_BY、HAS_SUBJECT_CODE、HAS_KEYWORD 等 11 类关系；所有节点/边带 `graph_version` 和稳定键。
目标边界：仅访问 `recpro-library-neo4j-20260810a`（HTTP 62475、Bolt 62688）的独立容器；已读取目标计数 0/0；本机 Homebrew `7474/7687` 大图和旧 RecPro 空实例均未连接或修改。
预演结果：`lib-graph-dry-run-20260810-002` PASS；节点/关系写入 0；删除、覆盖和 schema/data 写入均为 0；输入 URL query/fragment 未写入图，仅保留安全 URL和哈希。
DeepSeek：新增 HTTPS origin、API key、model、timeout、max tokens 配置；`MockLLM` 仍为默认，DeepSeek 构造缺少 key 时 fail-closed；本阶段未保存 key、未发起外部网络请求。
用户授权门禁：当前计划 `license_status=PENDING_USER_CONFIRMATION`，因此 `--apply` 被拒绝；只有用户明确确认数据可用于本地研究原型（或提供许可证据）后，才能以 `CONFIRMED_LOCAL_RESEARCH` 重建同一输入哈希的计划并执行追加导入。
新增数据库对象和行数：0；只读预演 Neo4j 查询 6 次，无业务写入；约束/节点/关系尚未创建。
文件删除数量：0；数据库物理删除数量：0；覆盖数量：0；输入 `Lib` 未修改；旧容器、卷和 59,301 节点外部图均保留。
验证命令：`python -m scripts.build_book_graph_plan --run-id lib-graph-plan-20260810-002 --graph-version lib-books-v1-20260810 --input-root Lib`；`python -m scripts.import_book_graph --run-id lib-graph-dry-run-20260810-002 --plan-dir artifacts/verification/book-graph/lib-graph-plan-20260810-002 --env-file .env.user-secrets`；定向单元测试 19 项；Neo4j 目标只读计数。
验证证据：`artifacts/verification/book-graph/lib-graph-plan-20260810-002/graph-plan.json`；`artifacts/verification/book-graph-import/lib-graph-dry-run-20260810-002/import-report.json`；`docs/book_graph_model.md`。
配置/数据/索引版本：graph-plan=book-graph-plan-v1；graph_version=lib-books-v1-20260810；LLM default=mock；DeepSeek prompt=deepseek-json-v1（未启用）。
未解决风险：用户许可确认、Neo4j 实际追加导入、MySQL 书目事实层、图召回/向量索引、DeepSeek key 连通性测试和默认 HTTP/Worker 接线仍未完成。
下一步唯一动作：收到用户明确本地研究授权后，重建 `CONFIRMED_LOCAL_RESEARCH` 计划并在同一独立目标执行显式 `import-book-graph`，完成计数和幂等复验。
```

## G6 Neo4j 书目图实际导入记录

```text
交接ID：G6-BOOK-GRAPH-20260810-004
Gate：G6 可选检索与解释（Neo4j 版本化图实际导入）
状态：IMPORT_PASS, IDEMPOTENCY_PASS / G6_CONTINUES
时间：2026-08-10（Asia/Shanghai）
目标：在用户明确确认本地研究授权后，将 Lib 图计划追加导入独立 RecPro Neo4j，并证明重复执行不增加节点/关系。
授权：用户在本轮明确确认 Lib 数据已获授权用于本地研究原型；计划 `license_status=CONFIRMED_LOCAL_RESEARCH`。
输入绑定：计划 `lib-graph-plan-20260810-003`；graph_version=`lib-books-v1-20260810`；输入 SHA-256=`8a2212a6d6508524243fae3afa36cadaa4efb928cd17db5bd63e108c0cc02e53`；与此前只读计划的节点/三元组文件哈希一致。
目标边界：仅使用 `recpro-library-neo4j-20260810a`（HTTP 62475、Bolt 62688）的独立容器和独立卷；没有连接本机 Homebrew `7474/7687` 大图、旧 RecPro 实例或 MySQL。
首轮结果：`lib-graph-import-20260810-001` PASS；导入前节点/关系 0/0，导入后 63,388/191,865；创建 10 个 Label `graph_key` 唯一约束；计划计数与按 graph_version 计数完全一致。
幂等结果：`lib-graph-import-idempotency-20260810-001` PASS；重复执行前后均为 63,388/191,865；未增加重复节点或关系；第二次仅执行受约束的 MERGE/ON CREATE 批处理和 IF NOT EXISTS 约束检查。
安全计数：两次导入均 `expected_delete_count=0`、`actual_delete_count=0`、`overwritten_inputs=0`；首轮/复验均未删除文件、节点、关系、约束、卷或容器。首轮新增数据库对象为 10 个唯一约束、63,388 个节点、191,865 条关系。
验证命令：`python -m scripts.build_book_graph_plan --run-id lib-graph-plan-20260810-003 --graph-version lib-books-v1-20260810 --input-root Lib --license-status CONFIRMED_LOCAL_RESEARCH`；显式 `import_book_graph.py --apply` 首轮和幂等复验；独立 HTTP 只读核验 labels、relationship types、constraints 和 graph_version counts。
验证证据：`artifacts/verification/book-graph/lib-graph-plan-20260810-003/graph-plan.json`；`artifacts/verification/book-graph-import/lib-graph-import-20260810-001/import-report.json`；`artifacts/verification/book-graph-import/lib-graph-import-idempotency-20260810-001/import-report.json`。
配置/数据/索引版本：graph-plan=book-graph-plan-v1；Neo4j graph_version=lib-books-v1-20260810；LLM default=mock；DeepSeek prompt=deepseek-json-v1（未启用）。
未解决风险：MySQL 书目事实层尚未导入；图召回/向量索引尚未接入推荐 Agent；DeepSeek key 尚未提供；默认 HTTP/Worker 仍保持关闭。
下一步唯一动作：设计 MySQL 书目事实层的 append-only ChangePlan，并实现 Neo4j 只读图召回端口；禁止对已导入 graph_version 做原地清空或覆盖。
```

## G6 MySQL 书目计划与图召回端口记录

```text
交接ID：G6-MYSQL-GRAPH-20260810-005
Gate：G6 书目事实层计划、只读图召回和导入安全边界
状态：PLAN_PASS_WITH_WARNINGS / GRAPH_RECALL_READ_ONLY_PASS / MYSQL_IMPORT_PENDING_AUTHORIZATION
时间：2026-08-10（Asia/Shanghai）
目标：把已导入的 Neo4j graph_version 映射到现有 G2 MySQL 事实表，并提供低耦合、只读、可降级的图召回端口；在未获得 MySQL 单独写入授权前不改变 MySQL。
新增文件：`contracts/data/intake/mysql-book-plan.schema.json`；`scripts/build_mysql_book_plan.py`；`scripts/import_mysql_book_catalog.py`；`backend/app/catalog/adapters/neo4j.py`；`tests/g6/test_mysql_book_plan.py`；`tests/g6/test_graph_recall.py`。
修改文件：`backend/app/catalog/domain/models.py` 增加 `GraphRecallEvidence`；`backend/app/catalog/ports/public.py` 增加 `GraphRecallPort`；`backend/app/recommendation/agents/real_agents.py` 与组合根增加可选 Graph 通道；`Makefile` 增加计划、干跑和显式导入目标；README、图模型和本记录同步状态。
MySQL 计划输入：复核 `lib-graph-plan-20260810-003`，source graph plan SHA-256=`e4b1f382c2ec988f3ea94cee0b256515bb7318bb4843a027cfaa87701a6928c`，graph_version=`lib-books-v1-20260810`，license_status=`CONFIRMED_LOCAL_RESEARCH`。
MySQL 计划结果：`mysql-book-plan-20260810-001` 状态 `PASS_WITH_WARNINGS`；`resource_catalog=14,983`、`resource_book_detail=14,983`、`tag_dictionary=8,516`、`resource_tag=70,750`、`resource_index_state=14,983`；书籍均标记 `REFERENCE_ONLY`，图状态 `READY`，向量状态 `PENDING`；计划生成阶段 database_reads=0、database_writes=0、actual_delete_count=0、overwritten_inputs=0。
导入器安全边界：`scripts/import_mysql_book_catalog.py` 默认只校验计划和 JSONL SHA-256，不连接数据库；实际写入必须同时提供 `--apply --confirm-mysql-write`，目标非空还必须显式 `--allow-nonempty-target`。导入只使用 `INSERT IGNORE`，先检查现有资源/标签/索引状态冲突，冲突时在事务前阻断；无删除、清空、更新或覆盖路径。
MySQL 干跑结果：`mysql-book-import-dryrun-20260810-001` PASS；`database_reads=0`、`database_writes=0`、`expected_delete_count=0`、`actual_delete_count=0`、`overwritten_inputs=0`。随后只读目标预检 `mysql-book-preflight-20260810-001` PASS：目标项目 `recpro-g2-tianyuhang-20260809a`、数据库 `recpro` 的五张目标表均存在，当前行数为 `resource_catalog=6`、`resource_book_detail=3`、`tag_dictionary=6`、`resource_tag=12`、`resource_index_state=6`；计划外部 ID/标签/索引状态冲突均为 0，执行 70 次 SELECT、0 次写入。本记录没有对 MySQL 执行 `--apply`，因为用户目前只明确授权 Lib 数据导入独立 Neo4j，MySQL 写入授权和目标实例仍需单独确认。
图召回端口：`Neo4jGraphReader` 只发送参数化 MATCH 查询，限定 `Book.graph_version`，返回外部稳定 ID、匹配词、分数和 graph_version；通过可选 `GraphRecallPort` 接入 CandidateRecallAgent，不改变默认 Mock/规则路径。对独立 Neo4j 目标的只读查询（`terms=多智能体/智慧图书馆`、`graph_version=lib-books-v1-20260810`、limit=5）返回 1 个命中，未执行任何图写操作。
验证结果：Python 全量测试 362 项 PASS；contracts 20 documents PASS；docs 17 Markdown/42 blocks PASS；安全扫描 249 files PASS；架构扫描 105 files PASS；MySQL 计划与导入器干跑 PASS；图召回适配器独立查询 PASS。
数据库与文件安全：本阶段未删除文件、未删除数据库数据、未清空卷、未修改 `Lib`；Neo4j 只发生前序已授权版本导入，本阶段图召回为只读；MySQL 读写均为 0。旧 Homebrew Neo4j、旧 RecPro Neo4j 和已有 MySQL 历史事实均未被覆盖。
未解决风险：MySQL 实际追加导入、向量索引、DeepSeek key 连通性和默认 HTTP/Worker 接线仍未完成；当前 `.env.user-secrets` 中的 MySQL 管理凭据不代表已授权写入现有 Compose MySQL，且本次预检使用的是现有 Compose 的隔离迁移账号只读路径。
下一步唯一动作：由用户明确确认 MySQL 目标项目/端口及本次 append-only 写入授权；确认后先执行只读目标快照和冲突报告，用户再次确认后才可执行 `--apply`。在此之前不得写入 MySQL。
```

## G6 MySQL 书目事实层实际导入与幂等复验记录

```text
交接ID：G6-MYSQL-BOOK-20260810-006
Gate：G6 可选检索与解释（MySQL 书目事实层追加导入）
状态：PREFLIGHT_PASS / IMPORT_PASS / IDEMPOTENCY_PASS / INTEGRITY_PASS
时间：2026-08-10（Asia/Shanghai）
目标：在用户确认本地研究用途和 MySQL 写入范围后，把已审查的 Lib 书目 ChangePlan 追加到 RecPro 隔离 Compose MySQL，并证明重复执行不增加行、不覆盖既有事实。
授权：用户在本轮明确确认继续完成任务并授权本次 MySQL append-only 写入；授权仅覆盖隔离 Compose 项目 `recpro-g2-tianyuhang-20260809a` 的 `recpro` 数据库，不覆盖其他 MySQL 实例或任何 Neo4j 实例。
目标边界：只连接本机端口 `127.0.0.1:62306` 的 RecPro 隔离 MySQL，使用现有 migration 账号；未使用用户既有 Homebrew Neo4j、旧 RecPro Neo4j 或其他业务数据库。root 凭据仍只保存在本机受保护环境文件，不出现在日志、证据或提交中。
输入绑定：MySQL 计划 `mysql-book-plan-20260810-002`；graph_version=`lib-books-v1-20260810`；source graph plan SHA-256=`e4b1f382c2ec988f3ea94cee0b256515bb7318bb4843a027cfaa87701a6928c`；license_status=`CONFIRMED_LOCAL_RESEARCH`。
只读预检：`mysql-book-preflight-20260810-002` 为 `PREFLIGHT_PASS`；五张目标表存在，导入前行数为 `resource_catalog=6`、`resource_book_detail=3`、`tag_dictionary=6`、`resource_tag=12`、`resource_index_state=6`；资源、标签和索引状态冲突均为 0；`database_reads=70`、`database_writes=0`、`actual_delete_count=0`。
首轮追加：`mysql-book-import-20260810-002` 为 `APPLIED`；计划新增 `resource_catalog=14,983`、`resource_book_detail=14,983`、`tag_dictionary=8,516`、`resource_tag=70,750`、`resource_index_state=14,983`；写入尝试 124,215 次；提交后目标总数为 `14,989/14,986/8,522/70,762/14,989`；`actual_delete_count=0`、`overwritten_inputs=0`。所有 SQL 写入均为 `INSERT IGNORE`，没有 DELETE、TRUNCATE、DROP、ALTER 或覆盖路径。
幂等复跑：`mysql-book-import-idempotency-20260810-001`、`-002`、`-003` 和最新 `mysql-book-import-idempotency-20260810-004` 均为 `APPLIED`；复跑前后五张表总数完全一致，未增加重复行；安全计数仍为 `actual_delete_count=0`、`overwritten_inputs=0`。早期复跑曾因 asyncmy 默认行为输出大量已存在键提示，事务结果和计数均正确；导入器现已在执行窗口内仅过滤 `Duplicate entry ...` 这一预期的 `INSERT IGNORE` 日志，最新 `-004` 复跑输出干净，其他异常仍会正常失败。
独立只读完整性：`mysql-book-import-integrity-20260810-001/readonly.json` 为 `PASS`；graph_version=`lib-books-v1-20260810` 的书籍数/REFERENCE_ONLY 数为 14,983/14,983，`resource_tag` 关系 70,750、可解析关系 70,750，`graph_status=READY` 且 `embedding_status=PENDING` 索引 14,983，重复外部 ID=0；只读事务回滚，`database_writes=0`、`actual_delete_count=0`。抽样标题为《二十世纪中国文学与世界》。
新增数据库对象和行数：未新增表、索引或约束；仅向既有五张表追加计划行。首轮新增行总计 124,215，复跑新增 0。
受控UPDATE对象和审计ID：0；本阶段未执行 UPDATE，不产生状态迁移审计行。
文件删除数量：0；数据库物理删除数量：0；未删除或修改 `Lib`、旧 Neo4j 数据、旧 MySQL 历史事实、容器或卷。
执行命令：`python -m scripts.import_mysql_book_catalog --run-id mysql-book-preflight-20260810-002 --plan-dir artifacts/verification/mysql-book-plan/mysql-book-plan-20260810-002 --env-file .env.compose --preflight-db`；用户授权后 `python -m scripts.import_mysql_book_catalog --run-id mysql-book-import-20260810-002 --plan-dir artifacts/verification/mysql-book-plan/mysql-book-plan-20260810-002 --env-file .env.compose --apply --confirm-mysql-write --allow-nonempty-target`；幂等复跑使用同一 `--apply` 参数；独立只读 SQL 完整性检查使用 migration 账号并回滚事务。
测试结果：导入计划 Schema/行级校验 PASS；首轮导入 PASS；幂等复跑 PASS；独立只读完整性 PASS；代码修改后的 Python 全量 `unittest` 363 项 PASS，contracts 20 documents PASS，docs 17 Markdown/42 blocks PASS，安全扫描 249 files PASS，架构扫描 105 files PASS，`git diff --check` PASS。
验证证据目录：`artifacts/verification/mysql-book-plan/mysql-book-plan-20260810-002/`；`artifacts/verification/mysql-book-import/mysql-book-import-20260810-002/import.json`；`artifacts/verification/mysql-book-import/mysql-book-import-idempotency-20260810-004/import.json`；`artifacts/verification/mysql-book-import/mysql-book-import-integrity-20260810-001/readonly.json`；追加后只读预检 `mysql-book-preflight-20260810-003`。
配置/数据/索引版本：graph_version=`lib-books-v1-20260810`；MySQL plan=`mysql-book-plan-v1`；书籍初始 `REFERENCE_ONLY`；图索引 `READY`；向量索引 `PENDING`；LLM default=`mock`；DeepSeek 未联网。
未解决风险：向量索引尚未构建；图召回尚未接入默认 HTTP/Worker；DeepSeek key、模型、Base URL 和外部请求授权尚未提供；默认推荐仍保持关闭。
下一步唯一动作：冻结双库书目版本并生成向量索引 ChangePlan，先完成离线质量校验；在用户另行提供 DeepSeek 配置和外部调用授权后，仅做一次受控 HTTPS 连通性测试，再评审 opt-in Agent 接线。
```

## G6 确定性向量索引 ChangePlan 与离线构建记录

```text
交接ID：G6-VECTOR-20260811-007
Gate：G6 可选检索与解释（向量索引数据库无关构建）
状态：PLAN_PASS_WITH_WARNINGS / OFFLINE_BUILD_PASS / IDEMPOTENCY_PASS / VERIFY_PASS
时间：2026-08-11（Asia/Shanghai）
目标：从已审核的 MySQL 书目 ChangePlan 生成可审计、可重复、可供后续 Chroma adapter 消费的向量构建计划和离线向量文件；本阶段不连接数据库、不写 Chroma、不切换 MySQL 索引状态。
输入绑定：`mysql-book-plan-20260810-002/mysql-book-plan.json`；source SHA-256=`423142ce43a8a16e6d85c6a1a767e7f0c054e5c545622193c93778d3a4f72c9b`；graph_version=`lib-books-v1-20260810`；license_status=`CONFIRMED_LOCAL_RESEARCH`。
新增文件：`contracts/data/intake/vector-index-plan.schema.json`；`scripts/build_vector_index_plan.py`；`scripts/verify_vector_index_plan.py`；`tests/g6/test_vector_index_plan.py`；README、图模型和本记录同步更新。HashingEmbeddingProvider 使用纯 Python 实现，不新增未锁定依赖。
嵌入契约：embedding_version=`hash-char-ngram-v1`；index_version=`lib-books-vector-v1-20260811`；namespace=`library_resources__hash_char_ngram_v1`；analyzer=`char`；ngram 2—4；dimension=384；alternate_sign=false；L2；float32 little-endian base64；文档格式=`title\nkeywords\nabstract`。
首次构建：`vector-index-plan-20260811-001` 状态 `PASS_WITH_WARNINGS`、`can_build=true`；resource_count/vector_count/skipped_count=`14,983/14,983/0`；vectors.jsonl 52,019,638 bytes，SHA-256=`7714919f8e57902002d42fb39dc0ba8b2f6106c4f8c1594a691e5ea180c944ae`。缺少摘要 2,602 条、缺少关键词 2,032 条；空文档、重复 external_id、重复 vector_id、非法 content_hash 均为 0。
幂等构建：`vector-index-plan-20260811-002` 使用同一输入和版本独立生成；向量文件 SHA-256 与首次完全一致，resource/vector 计数和质量报告一致，未覆盖首次产物。
完整性校验：`vector-index-verify-20260811-002` 通过 Schema、源计划哈希、产物哈希/字节数/行数、每行 base64 解码、384 维、document/vector SHA-256、稳定 vector_id 和重复检查。
新增数据库对象和行数：0；MySQL、Neo4j、Chroma 均未连接或写入；`resource_index_state.embedding_status` 仍保持 `PENDING`，没有执行 UPDATE 或活动版本切换。
安全计数：database_reads=0、database_writes=0、external_store_writes=0、expected_delete_count=0、actual_delete_count=0、overwritten_inputs=0、files_deleted=0。两次构建只创建新的、唯一命名的本地 artifacts 目录，未删除或覆盖既有证据。
执行命令：`python -m scripts.build_vector_index_plan --run-id vector-index-plan-20260811-001 --mysql-plan-dir artifacts/verification/mysql-book-plan/mysql-book-plan-20260810-002`；相同命令使用 run-id `vector-index-plan-20260811-002` 做独立复算；`python -m scripts.verify_vector_index_plan --run-id vector-index-verify-20260811-002 --plan artifacts/verification/vector-index-plan/vector-index-plan-20260811-001/vector-index-plan.json`。
测试结果：向量定向测试 3 项 PASS；完整性验证 PASS；代码修改后全量 Python `unittest` 366 项 PASS，contracts 21 documents PASS，docs 17 Markdown/42 blocks PASS，安全扫描 252 files PASS，架构扫描 105 files PASS。
验证证据目录：`artifacts/verification/vector-index-plan/vector-index-plan-20260811-001/`；`artifacts/verification/vector-index-plan/vector-index-plan-20260811-002/`；`artifacts/verification/vector-index-plan/vector-index-verify-20260811-002/verification.json`；独立比较记录 `vector-index-integrity-20260811-001/readonly.json`。
配置/数据/索引版本：graph_version=`lib-books-v1-20260810`；embedding_version=`hash-char-ngram-v1`；index_version=`lib-books-vector-v1-20260811`；MySQL embedding status=`PENDING`；Chroma=`NOT_BUILT`；LLM default=`mock`；DeepSeek 未联网。
未解决风险：Chroma Python client/版本尚未锁定和安装；VectorRecallPort、Chroma 故障降级和 MySQL embedding READY 的受控投影尚未实现；DeepSeek key、模型、Base URL 和外部请求授权仍未提供；默认推荐保持关闭。
下一步唯一动作：先实现 Chroma 版本化 adapter 与只读 VectorRecallPort/故障测试，形成新的 collection ChangePlan；向用户汇报 collection 名称、版本、预计记录数和安全计数，获得单独授权后才执行 Chroma 追加构建。
```

## G6 版本化向量只读召回边界记录

```text
交接ID：G6-VECTOR-RECALL-20260811-008
Gate：G6 可选检索与解释（VectorRecallPort、Chroma 只读 adapter）
状态：PORT_PASS / ADAPTER_PASS / FAULT_TEST_PASS / NO_WRITE
时间：2026-08-11（Asia/Shanghai）
目标：在不安装可选 Chroma 客户端、不创建 collection、不写入向量和不更新 MySQL 状态的前提下，完成低耦合的版本化向量召回端口与只读 adapter，确保跨版本数据、异常和超时 fail-closed。
新增文件：`backend/app/catalog/adapters/chroma.py`；`tests/g6/test_vector_recall.py`。
修改文件：`backend/app/catalog/domain/models.py` 新增 `VectorRecallEvidence`；`backend/app/catalog/domain/public.py` 和 `backend/app/catalog/ports/public.py`/`ports/__init__.py` 暴露公共领域值与 `VectorRecallPort`；README、图模型和本记录同步更新。领域层未导入 Chroma/数据库/SDK。
只读契约：adapter 仅依赖注入 collection 的 `query` 方法，使用 `$and` 过滤 `embedding_version=hash-char-ngram-v1` 与 `index_version=lib-books-vector-v1-20260811`；固定 namespace=`library_resources__hash_char_ngram_v1`，默认维度=384，limit=1—50；校验 `external_id`、`vector_id`、元数据版本、有限距离和重复命中。cosine distance 使用 `clip((1-distance+1)/2, 0, 1)` 得到 0—1 score。
故障边界：collection 不可用/查询异常转换为 `ConnectionError`；超时转换为 `TimeoutError`；输入维度、版本、limit、零向量和返回数据形状不合约时拒绝；不同版本、重复 ID、缺失外部 ID、非有限距离不返回部分脏结果。
测试结果：VectorRecallPort/Chroma adapter 定向 4 项 PASS；全量 Python `unittest` 370 项 PASS；架构扫描 106 files PASS；安全扫描 254 files PASS；contracts 21 documents PASS；docs 17 Markdown/42 blocks PASS；`git diff --check` PASS。
新增数据库对象和行数：0；MySQL、Neo4j、Chroma 均未连接或写入；`resource_index_state.embedding_status` 仍为 `PENDING`；默认 Agent/HTTP/Worker 未接线。
安全计数：database_reads=0、database_writes=0、external_store_writes=0、expected_delete_count=0、actual_delete_count=0、overwritten_inputs=0、files_deleted=0；未删除或覆盖任何既有文件、artifact、数据库数据、容器或卷。
当前向量构建绑定：collection=`library_resources__hash_char_ngram_v1`；embedding_version=`hash-char-ngram-v1`；index_version=`lib-books-vector-v1-20260811`；预计记录数=14,983；向量产物 SHA-256=`7714919f8e57902002d42fb39dc0ba8b2f6106c4f8c1594a691e5ea180c944ae`。
未解决风险：Chroma 客户端及具体版本尚未锁定/安装；尚未生成 collection ChangePlan；向量构建后 MySQL `embedding_status=READY` 的受控投影、向量通道 Agent 融合、默认 HTTP/Worker 接线和 DeepSeek key/外部请求授权仍未完成。
下一步唯一动作：生成只读 Chroma collection ChangePlan（客户端/版本、collection、记录数、metadata 字段、追加范围和回滚边界），向用户汇报并等待单独授权；授权前不得安装或写入 Chroma，不得更新 MySQL，不得删除任何数据。
```

## G6 Chroma collection ChangePlan 记录

```text
交接ID：G6-CHROMA-PLAN-20260811-009
Gate：G6 可选检索与解释（Chroma collection 数据库无关计划）
状态：PLAN_PASS_WITH_WARNINGS / VERIFY_PASS / WRITE_NOT_AUTHORIZED
时间：2026-08-11（Asia/Shanghai）
目标：依据已验证的确定性向量计划冻结一个新的、版本隔离的 Chroma collection ChangePlan；本阶段只创建本地计划和验证证据，不安装客户端、不连接 Chroma、不创建 collection、不写入向量、不切换活动版本。
新增文件：`contracts/data/intake/chroma-collection-plan.schema.json`；`scripts/build_chroma_collection_plan.py`；`scripts/verify_chroma_collection_plan.py`；`tests/g6/test_chroma_collection_plan.py`；README、图模型和本记录同步更新。
输入绑定：向量计划 `vector-index-plan-20260811-001/vector-index-plan.json`，source vector plan SHA-256=`8672ef594d6ecce7c5c026b197d4f0212ef6bd9bf880535af392ec5c54c249ba`；向量 artifact SHA-256=`7714919f8e57902002d42fb39dc0ba8b2f6106c4f8c1594a691e5ea180c944ae`。
冻结配置：collection=`library_resources__hash_char_ngram_v1`；distance_metric=`cosine`；dimension=384；embedding_version=`hash-char-ngram-v1`；index_version=`lib-books-vector-v1-20260811`；namespace=`library_resources__hash_char_ngram_v1`；预计记录数=14,983；质量状态=`PASS_WITH_WARNINGS`，缺少摘要=2,602、缺少关键词=2,032、source blockers=0。
客户端边界：package=`chromadb`；version_status=`NOT_INSTALLED`；具体版本必须在用户授权后锁定；`write_authorization_required=true`。本 ChangePlan 不等同于写入授权。
metadata 契约：必须含 `external_id`、`vector_id`、`resource_type`、`content_hash`、`metadata_version`、`embedding_version`、`index_version`、`namespace_name`、`graph_version`、`category_code`、`publication_year`、`difficulty_level`、`available_from_epoch`；查询必须同时过滤 embedding/index 版本。
写策略：`ADD_NEW_COLLECTION_ONLY`；append_only=true；overwrite_existing=false；physical_delete=false；activity_switch=false。目标已存在、版本冲突、记录数不一致或回读哈希不一致时 fail-closed，不覆盖既有 collection。
验证结果：ChangePlan Schema 校验 PASS；源向量计划、源 artifact、版本、维度、记录数和质量计数独立核验 PASS；ChangePlan 状态 `PASS_WITH_WARNINGS`，verifier 状态 `PASS`；Chroma collection 仍 `NOT_BUILT`。
新增数据库对象和行数：0；MySQL、Neo4j、Chroma 均未连接或写入；`resource_index_state.embedding_status` 仍为 `PENDING`；默认 Agent/HTTP/Worker 未接线。
安全计数：database_reads=0、database_writes=0、external_store_writes=0、expected_delete_count=0、actual_delete_count=0、overwritten_inputs=0、files_deleted=0；未删除或覆盖任何既有文件、artifact、数据库数据、容器或卷。
执行命令：`python -m scripts.build_chroma_collection_plan --run-id chroma-collection-plan-20260811-001 --vector-plan artifacts/verification/vector-index-plan/vector-index-plan-20260811-001/vector-index-plan.json`；`python -m scripts.verify_chroma_collection_plan --run-id chroma-collection-verify-20260811-001 --plan artifacts/verification/chroma-collection-plan/chroma-collection-plan-20260811-001/chroma-collection-plan.json`。
测试结果：Chroma collection 计划定向 2 项 PASS；全量 Python `unittest` 372 项 PASS；contracts 22 documents PASS；docs 17 Markdown/42 blocks PASS；安全扫描 257 files PASS；架构扫描 106 files PASS；`git diff --check` PASS。
验证证据目录：`artifacts/verification/chroma-collection-plan/chroma-collection-plan-20260811-001/`；`artifacts/verification/chroma-collection-plan/chroma-collection-verify-20260811-001/`。
未解决风险：Chroma 客户端及版本尚未锁定/安装；未执行 collection 冲突只读检查、追加写入、回读计数和幂等复验；MySQL `embedding_status=READY` 投影、向量通道 Agent 融合、默认 HTTP/Worker 接线和 DeepSeek key/外部请求授权仍未完成。
下一步唯一动作：向用户提交本 ChangePlan，等待明确的 Chroma 客户端/版本、目标 collection 追加写入和本阶段写入范围授权；授权前不得安装、连接、创建或写入 Chroma，不得更新 MySQL，不得删除任何数据。
```

## G6 Chroma collection 实际追加与只读复核记录

```text
交接ID：G6-CHROMA-IMPORT-20260811-010
Gate：G6 可选检索与解释（Chroma 版本化 collection 实际追加）
状态：IMPORT_PASS / READONLY_VERIFY_PASS / IDEMPOTENCY_PASS / G6_CONTINUES
时间：2026-08-11（Asia/Shanghai）
目标：在用户明确授权后，将已验证的 14,983 条确定性向量追加到全新、版本隔离的 Chroma collection；完成全量回读、版本/元数据验证、召回冒烟、幂等重跑和独立只读验证，不修改 MySQL 索引状态或默认推荐接线。
输入绑定：`chroma-collection-plan-20260811-002/chroma-collection-plan.json`；plan SHA-256=`a055fb93e64245ec63b8e6048ddcf048eccce5c881eea6bd067dae43139c58c4`；source vector plan SHA-256=`8672ef594d6ecce7c5c026b197d4f0212ef6bd9bf880535af392ec5c54c249ba`；vector artifact SHA-256=`7714919f8e57902002d42fb39dc0ba8b2f6106c4f8c1594a691e5ea180c944ae`。
新增文件：`backend/requirements-g6-chroma.in`；`backend/requirements-g6-chroma.lock`（operator-only，`chromadb==1.5.9`）；`scripts/import_chroma_vectors.py`；`scripts/verify_chroma_import.py`；`tests/g6/test_chroma_import.py`；Makefile 的干跑/导入/幂等/只读校验目标；`.gitignore` 追加 `data/chroma*/` 运行态边界。默认 backend/worker 依赖未改变。
正式目标：本地忽略路径 `data/chroma`；collection=`library_resources__hash_char_ngram_v1`；distance=`cosine`；dimension=384；embedding_version=`hash-char-ngram-v1`；index_version=`lib-books-vector-v1-20260811`；graph_version=`lib-books-v1-20260810`。仅创建 1 个新 collection，首轮追加 14,983 条，最终计数 14,983；未覆盖或修改既有 collection。
执行过程：`chroma-import-dryrun-20260811-001` 仅验证计划并确认目标路径不存在；`chroma-import-20260811-001` 创建新 collection 并成功追加 59 个批次/14,983 条，首次回读因 Chroma 1.5.9 `get(include=["embeddings", ...])` 返回 NumPy 数组而非 list 被安全阻断，现场未清理并生成 `FAILED_NO_CLEANUP` 证据；修正为只读容差校验后，`chroma-import-idempotency-20260811-002` 复核新增 0、跳过既有 14,983、最终 14,983/14,983，完整回读与 query smoke PASS。
独立验证：`chroma-import-integrity-20260811-001/readonly.json` 在独立进程中只执行 list/get/count/query；ID 集合 expected/actual=`14,983/14,983`，unexpected/missing=`0/0`，向量/文档/metadata 验证=`14,983`，client=`chromadb 1.5.9`，query top-1 score=`1.0`。Chroma cosine 持久化归一化的最大绝对误差=`2.9802322387695312e-08`，严格阈值=`2e-6`，源向量 SHA-256 全量验证=`14,983`。
幂等性：二次运行没有调用 `add`，`added_count=0`、`write_batches_attempted=0`、`external_store_writes=0`；collection 元数据、版本过滤和最终计数保持一致。
数据库与默认接线：MySQL、Neo4j 均未在本阶段写入；`resource_index_state.embedding_status` 全部保持 `PENDING`；图/向量端口未接入默认 HTTP/Worker，`can_recommend` 不因 collection 创建而改变；DeepSeek 未联网、未读取或保存 key。
安全计数：本阶段数据库读/写=`0/0`；正式 collection 创建=`1`；Chroma 向量追加=`14,983`（幂等复核追加=`0`）；actual_delete_count=`0`；files_deleted=`0`；overwritten_inputs=`0`；没有 reset、清空、覆盖、删除或活动版本切换。
保留的探查产物：此前为读取 Chroma API 签名而创建的独立路径 `data/chroma-probe-g6-20260811` 中保留空 collection `probe_signature_20260811`，count=`0`；它不属于正式 collection，未删除、未合并、未复用。
测试结果：G6 定向测试 8 项 PASS；G6 其他测试 PASS；operator lock `uv pip check` PASS；安全扫描 260 files PASS；架构扫描 106 files PASS；contracts 22 documents PASS；docs 17 Markdown/42 blocks PASS；`git diff --check` PASS。首次失败证据不被覆盖，修复后的幂等与只读证据另建唯一 run 目录。
验证证据目录：`artifacts/verification/chroma-collection-plan/chroma-collection-plan-20260811-002/`；`artifacts/verification/chroma-collection-plan/chroma-collection-verify-20260811-002/`；`artifacts/verification/chroma-import/chroma-import-dryrun-20260811-001/`；`artifacts/verification/chroma-import/chroma-import-20260811-001/`；`artifacts/verification/chroma-import/chroma-import-idempotency-20260811-002/`；`artifacts/verification/chroma-import/chroma-import-integrity-20260811-001/`。
配置/数据/索引版本：graph_version=`lib-books-v1-20260810`；embedding_version=`hash-char-ngram-v1`；index_version=`lib-books-vector-v1-20260811`；collection=`library_resources__hash_char_ngram_v1`；MySQL embedding status=`PENDING`；LLM default=`mock`；DeepSeek 未联网。
未解决风险：Neo4j/Chroma 端口仍需在可选 Agent 组合根中接线并验证融合/解释证据；默认 HTTP/Worker、MySQL `embedding_status=READY` 受控投影、DeepSeek key/模型/Base URL 和外部请求授权仍待单独评审；operator Chroma 依赖不得进入默认运行镜像。
下一步唯一动作：实施低耦合的只读检索接线 Gate，先验证图/向量版本过滤、超时 fail-closed、候选融合和解释引用，再由用户另行确认 MySQL READY 投影和 DeepSeek 外部调用。
```

## G6 Prompt Bundle 与显式 LLM Intent Agent 记录

```text
交接ID：G6-PROMPT-20260811-011
Gate：G6 可选检索与解释（Prompt/LLM 配置边界）
状态：PROMPT_BUNDLE_PASS / LLM_INTENT_OPT_IN_PASS / G6_CONTINUES
时间：2026-08-11（Asia/Shanghai）
目标：将提示词从 DeepSeek 适配器代码中抽离为可审计、可版本化、可安全降级的本地 Prompt Bundle；为 IntentUnderstandingAgent 提供显式 LLM 端口接线，同时保持默认规则、HTTP、Worker 和外部请求关闭。
新增文件：`contracts/prompts/prompt-bundle.schema.json`；`contracts/prompts/rec-prompts-v1.0.0.json`；`backend/app/llm/prompts.py`；`backend/app/recommendation/agents/llm_agents.py`；`scripts/verify_prompt_bundle.py`；`tests/g1/backend/test_prompt_bundle.py`；`tests/g4/test_llm_intent_agent.py`；`docs/LLM_PROMPT_CONFIGURATION.md`。
修改文件：`backend/app/config.py`、`backend/app/llm/ports/public.py`、`backend/app/llm/adapters/deepseek.py`、`backend/app/llm/adapters/mock.py`、`backend/app/llm/factory.py`、`backend/app/recommendation/application/orchestration.py`、`backend/app/composition.py`、三个环境模板、`Makefile`、`README.md`；原版本均保留在本次 Git 差异和历史提交中。
Prompt/配置版本：Bundle=`prompt-v1`；文件 SHA-256=`bad547702e4c3b42395280ea44781e60992a85f981605afbcd29aa13d33db94a`；任务=`intent.classify/feedback.parse/explanation.render/group_summary.render`；默认 provider=`mock`。
安全边界：Prompt Bundle `allowed_tools=[]`；禁止 filesystem_write/filesystem_delete/database_admin/free_sql/free_cypher/shell/credential_access；变量缺失、多余、超长或输出字段越权均 fail-closed；LLMResult 只保存 prompt_id、模板 SHA、请求 ID 和尝试次数，不保存用户原文或密钥。
Agent接线：仅 `build_rule_orchestrator(..., llm_provider=...)` / `build_port_orchestrator(..., llm_provider=...)` 和显式组合根 `enable_llm_provider=True` 才替换 Intent Agent；空输入、超时、异常、非法枚举均规则降级，Explanation/Feedback 仍待 EvidenceValidator/反馈事务边界评审后再接入真实 LLM。
新增数据库对象和行数：0；MySQL、Neo4j、Chroma 均未连接或写入。
受控UPDATE对象和审计ID：0；不适用。
文件删除数量：0。
数据库物理删除数量：0。
外部请求：0；未读取或保存 DeepSeek 密钥，未联网。
执行命令：`python -m scripts.verify_prompt_bundle`；Prompt/DeepSeek/Agent 定向 unittest；`scripts.architecture_guard.py`；`git diff --check`。
测试结果：Prompt/DeepSeek 定向 16 项 PASS；LLM Intent Agent 4 项 PASS；既有 G4 编排/组合根 18 项 PASS；架构扫描 108 files PASS；Prompt Bundle 只读验证 PASS。
验证证据：命令输出；`docs/LLM_PROMPT_CONFIGURATION.md`；本记录；旧 G6 artifact 未覆盖。
未解决风险：没有真实 DeepSeek key/外部调用授权；Prompt Bundle 尚未接入 Explanation EvidenceValidator 和 Feedback 持久化事务；Neo4j/Chroma 仍待只读融合接线；MySQL `embedding_status` 仍为 `PENDING`。
下一步唯一动作：先完成 Neo4j/Chroma 只读端口与版本过滤/超时降级的 fake/隔离验证；若需要真实 LLM，先由用户确认脱敏、伦理、费用和外部请求范围，不得默认启用。
```

## G6 DeepSeek 本机密钥配置记录

```text
交接ID：G6-DEEPSEEK-CONFIG-20260811-012
Gate：G6 可选检索与解释（DeepSeek 运行配置）
状态：LOCAL_CONFIGURED / OFFLINE_CONSTRUCTION_PASS / EXTERNAL_CALLS_ZERO / G6_CONTINUES
时间：2026-08-11（Asia/Shanghai）
目标：将用户提供的 DeepSeek 凭据安全注入本机 opt-in 运行环境，同时保持默认 HTTP/Worker、数据库和外部请求关闭。
本机配置文件：`.env.host`、`.env.compose`；均被 `.gitignore` 忽略，权限 `0600`，不进入 Git。真实 key 值不在此记录、代码、日志、Prompt、Agent 消息或验证 artifact 中。
运行参数：provider=`deepseek`；model=`deepseek-v4-flash`；base_url=`https://api.deepseek.com`；timeout=`20s`；max_output_tokens=`512`；Prompt Bundle=`prompt-v1`；Prompt SHA-256=`bad547702e4c3b42395280ea44781e60992a85f981605afbcd29aa13d33db94a`。
验证结果：Compose 环境结构校验 PASS；DeepSeek provider 离线构造 PASS（未打印 key）；host 校验仍被既有 MySQL 运行时缺失字段和占位探针阻断，与 DeepSeek 配置无关。
外部请求：0；数据库读取：0；数据库写入：0；数据库物理删除：0；文件删除：0；Docker/容器/卷变更：0。
安全边界：默认 provider 仍为 `mock`，默认 API/Worker 不挂载 LLM；本阶段不做连通性请求。任何真实 DeepSeek 调用仍需单独确认脱敏、论文伦理、费用上限、超时/降级和数据出境范围。
下一步唯一动作：完成 Neo4j/Chroma 只读端口与版本过滤、超时 fail-closed、候选融合和解释引用的 fake/隔离验证，再评审是否需要一次受控外部 LLM 请求。
```

## G6 DeepSeek 默认模型与 Agent 清单校准记录

```text
交接ID：G6-DEEPSEEK-MODEL-20260811-013
Gate：G6 可选检索与解释（模型与 Agent 清单）
状态：MODEL_DEFAULT_UPDATED / AGENT_INVENTORY_VERIFIED / G6_CONTINUES
时间：2026-08-11（Asia/Shanghai）
默认模型：`deepseek-v4-flash`。已同步本机 `.env.host`/`.env.compose`、Compose 默认值、AppSettings、DeepSeek 适配器、三个环境示例、配置测试和 LLM 配置文档；真实 key 仍只在本机忽略文件中。
Agent 数量口径：设计文档定义 9 个逻辑角色（1 个 RecommendationOrchestratorAgent + 8 个业务 Agent）；当前默认 Registry 实际注册 8 个执行 Agent，Orchestrator 作为独立控制器不注册到业务 Agent Registry。
默认执行 Agent：IntentUnderstandingAgent、UserProfileAgent、ResourceSemanticAgent、RecommendationPolicyAgent、CandidateRecallAgent、RankingAgent、ExplanationAgent、FeedbackLearningAgent。
显式端口组合根：Profile、Semantic、CandidateRecall 三个角色可由 MySQL/图端口实现替换；它们是同一角色的适配实现，不是额外并行 Agent。启用 LLM 时，LLMIntentUnderstandingAgent 替换规则 IntentUnderstandingAgent，不增加总角色数。
外部请求：0；数据库读取：0；数据库写入：0；文件删除：0。
```

## G6 图/向量只读融合接线记录

```text
交接ID：G6-RETRIEVAL-FUSION-20260811-014
Gate：G6 可选检索与解释（显式组合根只读融合）
状态：PORT_WIRING_PASS / FAKE_FUSION_PASS / DEFAULT_PATH_UNCHANGED / G6_CONTINUES
时间：2026-08-11（Asia/Shanghai）
新增能力：`QueryEmbeddingPort`、`HashCharNgramQueryEmbedder`、VectorRecall 可选注入、CandidateRecall 图/向量融合、查询向量版本校验、通道状态和 evidence_ref 绑定。
安全边界：只调用 Neo4j/Chroma 的读取端口；不提供写、删除、重置或 collection 生命周期操作；未连接数据库和 Chroma 实例。
故障策略：图/向量超时或连接失败最多两次无退避重试，随后保留 MySQL 候选并标记 `PARTIAL`、`fallback_used=true`；可用通道权重重新归一化；默认没有注入端口时保持原 MySQL-only 分数路径。
测试结果：`tests/g6/test_retrieval_fusion.py` 3 项 PASS；G4 端口回归、Chroma 读取契约和 G6 全套 37 项 PASS；查询向量与已冻结 `hash-char-ngram-v1` 离线向量逐元素一致。
外部请求：0；数据库读取：0；数据库写入：0；文件删除：0；Docker/容器/卷变更：0。
下一步唯一动作：在独立 RecPro Neo4j/Chroma 目标上做一次只读真实融合运行证据，再进入 G7 推荐前端设计；默认 HTTP/Worker 仍关闭。
```

## G7 前端当前状态记录

```text
交接ID：G7-FRONTEND-STATUS-20260811-015
Gate：G7 前端与论文演示
状态：G1_STATUS_SHELL_PASS / G7_RECOMMENDATION_UI_NOT_STARTED
时间：2026-08-11（Asia/Shanghai）
已完成：Vue 3/Vite 状态页、健康客户端、取消与超时处理、StatusBadge/SystemStatus 组件、响应校验、响应式样式、追加式安全构建脚本；当前页面明确提示 G1 不提供推荐结果。
验证：前端 Vitest 33 项 PASS；使用锁定的临时 TypeScript 5.9.3/vue-tsc 3.3.9 运行时类型检查 PASS；追加式构建 `g7-status-20260811-004` PASS。工作区现有 `node_modules` 的 TypeScript 实际版本为 7.0.2，与 `package.json`/lockfile 的 5.9.3 不一致，因此直接 `npm run build` 的 vue-tsc 入口会失败；未执行会清理或重装现有 `node_modules` 的操作。
未完成：推荐请求页、澄清交互、推荐卡片、证据解释、反馈、画像和 research-admin 调试页；真实推荐 API 接线和论文六场景演示流程仍未开始。
外部请求：0；数据库读取：0；数据库写入：0；文件删除：0。
下一步唯一动作：先固定前端依赖复现方式，再实现推荐/澄清/解释/反馈的只读或显式 API 页面，不改变默认 API 关闭策略。
```

## G6 隔离目标真实只读融合验证记录

```text
交接ID：G6-RETRIEVAL-FUSION-READONLY-20260811-016
Gate：G6 可选检索与解释（隔离 MySQL/Neo4j/Chroma 真实只读融合）
状态：REAL_READONLY_FUSION_PASS / COUNTS_UNCHANGED / G6_CONTINUES
时间：2026-08-11（Asia/Shanghai）
目标：在已授权且独立的 RecPro 目标上，只读执行一次 MySQL 目录、Neo4j 图召回和 Chroma 向量召回的融合，验证版本绑定、证据引用和通道状态；不启动默认 API/Worker，不改变索引状态。
固定版本：graph_version=`lib-books-v1-20260810`；embedding_version=`hash-char-ngram-v1`；index_version=`lib-books-vector-v1-20260811`；namespace=`library_resources__hash_char_ngram_v1`；dimension=384。
目标边界：MySQL Compose project=`recpro-g2-tianyuhang-20260809a`、host port=`62306`；Neo4j 独立 project=`recpro-library-neo4j-20260810a`、HTTP port=`62475`；Chroma 仅读取本地 `data/chroma` 正式 collection，未访问 `data/chroma-probe-g6-20260811`。
执行脚本：`scripts/verify_g6_readonly_fusion.py`；唯一证据目录：`artifacts/verification/g6/g6-retrieval-fusion-readonly-20260811-001/readonly.json`。脚本只调用 MySQL SELECT、Neo4j HTTP transaction 查询和 Chroma count/query，并对 MySQL 事务执行 rollback；不存在写、删除、upsert、reset、collection lifecycle 或版本切换代码。
结果：MySQL `resource_catalog/resource_book_detail/tag_dictionary/resource_tag/resource_index_state` 计数分别为 `14,989/14,986/8,522/70,762/14,989`，前后完全一致；Neo4j 图通道 READY 并返回命中；Chroma count 前后均为 `14,983`，向量通道 READY；候选融合返回 8 条，channels=`MYSQL+GRAPH+VECTOR`，fallback=`false`，warnings=`[]`，evidence_ref 带 graph/index version。
安全计数：MySQL SELECT=`12`（计数与目录召回）；Neo4j reads=`1`；Chroma reads=`3`；MySQL/Neo4j/Chroma writes=`0/0/0`；actual_delete_count=`0`；files_deleted=`0`；overwritten_inputs=`0`；外部 LLM requests=`0`。
回归：G6 真实只读 verifier PASS；正式目标容器仅做读取，未启动或触碰本机既有 Neo4j、旧 RecPro 目标、旧 MySQL 容器或任何 Docker volume。
未解决风险：默认 HTTP/Worker 仍未挂载图/向量组合根；MySQL `embedding_status` 仍为 `PENDING`；真实 DeepSeek 仍未联网；生产化前需要独立评审索引 READY 投影、API 闸门和解释证据链。
下一步唯一动作：推进 G7 推荐工作台前端，保持真实 API 显式闸门关闭并先完成本地演示、契约客户端和浏览器冒烟。
```

## G7 推荐工作台首个可运行切片记录

```text
交接ID：G7-FRONTEND-RECOMMENDATION-20260811-017
Gate：G7 前端与论文演示（推荐请求/澄清首个闭环）
状态：UI_WORKBENCH_PASS / API_CLIENT_PASS / DEFAULT_PIPELINE_GATED / G7_CONTINUES
时间：2026-08-11（Asia/Shanghai）
目标：在既有 G1 状态页基础上提供低耦合推荐工作台：研究问题输入、BOOK/PAPER 选择、数量限制、本地演示、类型化推荐 API 客户端、澄清问题渲染、证据置信度与理由展示；默认不调用真实推荐 API。
新增文件：`frontend/src/domain/recommendation.ts`；`frontend/src/api/recommendationClient.ts` 及其测试；`frontend/src/components/RecommendationWorkbench.vue` 及其测试；`scripts/verify_g6_readonly_fusion.py`；`artifacts/verification/g6/g6-retrieval-fusion-readonly-20260811-001/readonly.json`；`artifacts/verification/g7/g7-recommendation-ui-20260811-001/frontend.json`。
修改文件：`frontend/src/App.vue`、`frontend/src/styles.css`；原 G1 状态页与健康客户端接口保持存在，未删除旧实现。
低耦合边界：组件只依赖 `RecommendationClient` 端口；请求/错误/响应在 API adapter 内校验；`pipelineEnabled=false` 时 submit 只显示闸门提示，不触发 fetch；本地演示是静态、明确标注的 UI fixture，不访问 MySQL、Neo4j、Chroma 或 DeepSeek。
真实 API 契约：POST `/api/v1/recommendation-tasks` 携带 `Idempotency-Key=request_id` 和 `X-Demo-User-Id`；澄清走 `/api/v1/recommendation-tasks/{task_id}/clarifications`；响应必须包含 task/trace/status/context/decision/warnings，items/questions 通过运行时校验后才渲染；稳定错误码转为用户文案，不直接展示服务端本地化文本。
验证：前端 Vitest=`38` 项 PASS（6 files）；临时锁定 TypeScript=`5.9.3`、vue-tsc=`3.3.9` 类型检查 PASS；追加式安全构建 `frontend/dist/g7-recommendation-ui-20260811-003/` PASS；架构扫描确认组件到 API adapter 的直接依赖为 `0`，由 `App.vue` 组合根注入 `RecommendationClient`，组件卸载时会中止未完成请求；浏览器本地冒烟 PASS，点击“查看本地演示”显示三张推荐卡片并明确“不访问 API，不写入 MySQL、Neo4j 或 Chroma”；后端未启动时健康错误只显示连接状态。
安全计数：本切片 database_reads=`0`、database_writes=`0`、external_requests=`0`、actual_delete_count=`0`、files_deleted=`0`、overwritten_inputs=`0`；未清理或重装现有 `frontend/node_modules`，未覆盖旧 build artifact。
当前限制：后端健康契约仍以 `can_recommend=false` 为默认安全事实；真实推荐 API、反馈/画像/解释详情、research-admin 调试页和六场景论文演示仍需后续 Gate；现有 node_modules 的 TypeScript 实际版本漂移，直接 `npm run build` 仍需在干净依赖环境执行。
下一步唯一动作：在用户确认后端推荐组合根/API Gate 后，使用同一 RecommendationClient 连接真实结果，并为反馈/解释增加独立端口与只读/显式写边界测试；不得默认打开或绕过健康闸门。
```

## G7 后端显式 HTTP/API 闸门记录

```text
交接ID：G7-OPTIN-HTTP-GATE-20260811-018
Gate：G7 前端与论文演示（显式推荐 HTTP 组合根与健康闸门）
状态：OPTIN_COMPOSITION_PASS / DEFAULT_HEALTH_ONLY / FRONTEND_CONTRACT_PASS / G7_CONTINUES
时间：2026-08-11（Asia/Shanghai）
目标：将真实推荐请求从前端本地演示接入一个可审计的显式 HTTP 组合根；默认模块级 FastAPI 应用继续只提供健康接口，只有调用方同时提供推荐服务、启用 API 和推荐 readiness 闸门时，健康响应才允许声明 can_recommend=true。
新增文件：`tests/g7/__init__.py`、`tests/g7/test_optin_http_composition.py`、`scripts/verify_g7_optin_http.py`。
修改文件：`backend/app/composition.py` 新增 `build_demo_http_app` 并让 production 组合根显式开启 readiness；`backend/app/main.py` 增加 `recommendation_readiness_enabled` 保护和中性 OpenAPI 描述；`backend/app/observability/application/public.py` 让 readiness 组件版本/状态随显式组合根输出；`frontend/src/domain/health.ts`、`frontend/src/api/healthClient.ts`、`frontend/src/App.vue`、`frontend/src/presentation/healthPresentation.ts` 和相关测试支持严格的 opt-in readiness 响应。
低耦合边界：组合根负责装配服务与端口；ReadinessService 只聚合配置/MySQL 探针及显式能力状态；前端 App 只把经过契约校验的 `can_recommend` 注入 RecommendationWorkbench，组件仍只依赖 `RecommendationClient` 端口；默认应用不会构造业务服务、连接数据库或注册推荐路由。
行为验证：Demo 组合根在构造阶段不打开数据库连接，GET `/api/v1/health/ready` 在两个 UP 探针下返回 `DEGRADED/can_recommend=true`、推荐管线 `UP/required=true/active_version=recommendation-g3-mysql-v1`；默认 `create_app` 无推荐服务、无推荐路由并返回 `can_recommend=false`；缺少服务、API 闸门或错误环境时 fail-closed。
新增数据库对象和行数：0；本阶段未连接 MySQL、Neo4j 或 Chroma，也未改变任何索引状态。
受控UPDATE对象和审计ID：0。
文件删除数量：0。
数据库物理删除数量：0。
执行命令：`PYTHONDONTWRITEBYTECODE=1 .venv-g1-final-py311/bin/python -m unittest tests.g7.test_optin_http_composition`；`PYTHONDONTWRITEBYTECODE=1 .venv-g1-final-py311/bin/python -m scripts.verify_g7_optin_http --run-id g7-optin-http-20260811-001`；`PATH=... npm --prefix frontend run test`；临时锁定 TypeScript 5.9.3/vue-tsc 3.3.9 执行 `vue-tsc --project frontend/tsconfig.json --noEmit`。
测试结果：G7 后端 opt-in 定向 4 项 PASS；全量 Python unittest 398 项 PASS；前端 6 个文件/40 项 Vitest PASS；临时锁定 TypeScript 5.9.3/vue-tsc 3.3.9 类型检查 PASS；安全扫描 276 files PASS；架构扫描 109 files PASS；contracts 24 documents PASS；docs 18 Markdown/42 blocks PASS；`git diff --check` PASS。
验证证据目录：`artifacts/verification/g7/g7-optin-http-20260811-001/evidence.json`；本阶段使用定向 unittest、前端测试和类型检查输出；未覆盖既有 artifact。
配置/数据/索引版本：recommendation_version=`recommendation-g3-mysql-v1`；现有 graph/index/vector 版本不变；MySQL `embedding_status=PENDING` 不变；LLM/DeepSeek 外部请求数=0。
未解决风险：默认 HTTP/Worker 仍未挂载真实 MySQL 编排服务；生产/演示 API 真实请求仍需独立运行态验收、反馈/画像事务与解释证据链；DeepSeek 外部调用和 MySQL READY 投影仍未授权；前端真实 API 只有健康闸门通过才会发送。
下一步唯一动作：在不触碰既有数据库数据的前提下，为显式 Demo 组合根增加隔离 MySQL 真实请求冒烟和只读计数前后核验，再评审是否开放论文演示流量；默认应用继续保持关闭。
```

## G7 隔离 MySQL 真实 HTTP 只读冒烟记录

```text
交接ID：G7-MYSQL-HTTP-READONLY-20260811-019
Gate：G7 前端与论文演示（真实 MySQL 健康闸门与 HTTP 组合根）
状态：REAL_MYSQL_READONLY_PASS / COUNTS_UNCHANGED / BUSINESS_POSTS_ZERO / G7_CONTINUES
时间：2026-08-11（Asia/Shanghai）
目标：在已存在的 RecPro 隔离 Compose MySQL 上验证显式 Demo HTTP 组合根和真实 readiness；只执行健康 GET、SELECT 与 SHOW GRANTS，不执行推荐 POST、迁移、seed、反馈、画像或任何业务写入。
新增文件：`scripts/verify_g7_mysql_http_readonly.py`、`scripts/build_g7_recommendation_post_plan.py`。
修改文件：`backend/app/composition.py` 新增 `build_demo_mysql_http_app`，将契约完整的 G3 `MySQLRecommendationTaskService`、HTTP API 和健康闸门保持在一个显式组合根；G4 `PersistentOrchestrationService` 继续通过独立 `build_demo_orchestration_service` 暴露，不伪装成 HTTP task service；`tests/g7/test_optin_http_composition.py` 增加服务连接惰性测试；Makefile 增加 `verify-g7-mysql-http-readonly` 和 `build-g7-recommendation-post-plan`。
目标边界：Compose project=`recpro-g2-tianyuhang-20260809a`；MySQL 本地端口=`62306`；本阶段未连接或查询本机既有 Neo4j，未启动/停止任何容器。
真实结果：`GET /api/v1/health/live=200`；`GET /api/v1/health/ready=200`；状态=`DEGRADED`；`can_recommend=true`；recommendation_pipeline=`UP/required=true/active_version=recommendation-g3-mysql-v1`；OpenAPI 包含推荐任务路由，但业务 POST 数=`0`。
只读计数：`resource_catalog=14,989`、`resource_book_detail=14,986`、`tag_dictionary=8,522`、`resource_tag=70,762`、`resource_index_state=14,989`、`recommendation_task=18`、`recommendation_task_transition=156`、`recommendation_candidate=270`、`recommendation_record=18`、`recommendation_item=90`、`recommendation_item_explanation=90`、`recommendation_policy_decision=18`、`recommendation_trace=18`；前后完全一致。
验证证据：修正组合根后的最新证据为 `artifacts/verification/g7/g7-mysql-http-readonly-20260811-004/readonly.json`；此前 `...-001`、`...-002`、`...-003` 证据均保留、未覆盖；命令为 `make verify-g7-mysql-http-readonly PYTHON=.venv-g1-final-py311/bin/python G7_MYSQL_READONLY_RUN_ID=g7-mysql-http-readonly-20260811-004`。
安全计数：database_read_queries=`30`（两次完整计数快照各执行 1 条 information_schema 查询与 13 条 COUNT，健康探针另执行 persistence identity 与 SHOW GRANTS）；database_writes=`0`；external_requests=`0`；actual_delete_count=`0`；files_deleted=`0`；overwritten_inputs=`0`；business HTTP POST=`0`。
新增数据库对象和行数：0；未执行 DDL、INSERT、UPDATE、DELETE、迁移、seed、索引状态切换或向量/图写入。
未解决风险：尚未执行真实推荐 POST，因此没有证明任务、候选、Trace 与 Agent 日志在 MySQL 中的事务闭环；反馈/画像、真实图向量请求和 DeepSeek 外部调用仍需单独的范围与写入审查。
ChangePlan 证据：`artifacts/verification/g7/g7-recommendation-post-plan-20260811-003/recommendation-post-change-plan.json`；生成时 git_commit=`3c35ce62002eeaeaf07ce35fb5b1c8019d06c7e3`，plan_hash=`48f64cbfbb13ed5f1f31408011bf95c6edf88c1f899834a91afecc6337c0cff3`，idempotency_key 与 request_id=`49cd9d61-1f24-524d-b15b-db2e183668b5`，`max_changes=37`；Schema 校验 PASS，mode=`DRY_RUN`，不包含 apply 操作。
下一步唯一动作：审阅上述 `S1_APPEND/DRY_RUN` ChangePlan（基于上述 `...-004` 基线，含用户、输入、幂等键、预计新增表行、前置条件和安全断言）；只有用户明确批准未变更的 plan hash 和写入范围后，才可执行一次隔离 Demo 请求及只读复核；默认应用继续保持关闭。
```

## G7 真实推荐执行前性能阻断与新计划记录

```text
交接ID：G7-RECOMMENDATION-PERF-20260811-020
Gate：G7 真实 MySQL 推荐 POST（性能与事务边界）
状态：APPLY_ABORTED_BEFORE_COMMIT / COUNTS_UNCHANGED / NEW_PLAN_PENDING_APPROVAL
时间：2026-08-11（Asia/Shanghai）
触发：按已批准的旧 plan hash 启动一次唯一 POST 前置执行；健康、目标身份、权限、基线计数和请求唯一性均通过，但 G3 计算在 14,989 本书规模上进入每资源/每通道重复全量排序，形成不可接受的长事务风险。
安全动作：在事务写入阶段前终止进程；随后 `g7-mysql-http-readonly-20260811-005` 只读复核 PASS，13 张表计数仍为 `recommendation_task=18`、`recommendation_record=18`、`recommendation_item=90`、`recommendation_trace=18` 及原书目计数；未生成 apply evidence，未提交任何业务行。
修复：提交 `4915351 perf(g3): precompute recommendation channel ranks`；三个通道各只生成一次排名映射，保留负向偏好惩罚与确定性排序；15,000 条离线资源基准约 `0.137s`，G3 服务测试 4 项 PASS。
新计划：基于只读基线 `artifacts/verification/g7/g7-mysql-http-readonly-20260811-005/readonly.json` 生成 `artifacts/verification/g7/g7-recommendation-post-plan-20260811-004/recommendation-post-change-plan.json`；git_commit=`4915351ea61a6194d77fc319d346c378211aa06b`；plan_hash=`2b115b3790a6281f4725be7fe29a5448e674c92570cdaac766cc0f40eb961d53`；仍为 `S1_APPEND/DRY_RUN`、`max_changes=37`，不包含 apply 授权。
下一步唯一动作：确认上述新 plan hash 后，才重新执行一次受控 POST；若成功，再核验 13 张推荐/资源表及三个上下文表的前后计数、响应 GET 回读、幂等重放和事务闭环。
```

## G7 新哈希真实推荐追加与只读回读记录

```text
交接ID：G7-RECOMMENDATION-APPLY-20260811-021
Gate：G7 真实 MySQL 推荐 POST（一次受控追加与事务回读）
状态：REAL_MYSQL_APPEND_PASS / TRANSACTION_COMMIT_PASS / READBACK_PASS / G7_CONTINUES
时间：2026-08-11（Asia/Shanghai）
授权边界：用户确认使用 plan hash=`2b115b3790a6281f4725be7fe29a5448e674c92570cdaac766cc0f40eb961d53`；仅允许对隔离 Compose MySQL 的一个新 `request_id` 执行一次 `S1_APPEND` 推荐请求，不允许重放，不触碰既有 Neo4j、Chroma 或其他数据库。
执行目标：Compose project=`recpro-g2-tianyuhang-20260809a`；MySQL 本地端口=`62306`；ChangePlan=`artifacts/verification/g7/g7-recommendation-post-plan-20260811-004/recommendation-post-change-plan.json`；只读基线=`artifacts/verification/g7/g7-mysql-http-readonly-20260811-005/readonly.json`。
真实结果：HTTP POST=`201`，`Idempotency-Replayed=false`；任务 `task_id=70c56792-b8ab-5244-a267-bac7020b704b`，回读状态=`COMPLETED`，record=`19`，trace 已关联。数据库追加 `37` 行：`recommendation_task +1`、`recommendation_task_transition +8`、`recommendation_candidate +15`、`recommendation_record +1`、`recommendation_item +5`、`recommendation_item_explanation +5`、`recommendation_policy_decision +1`、`recommendation_trace +1`；三个上下文表对该 task 均为 `0`。
计数核验：资源事实表 `resource_catalog/resource_book_detail/tag_dictionary/resource_tag/resource_index_state` 前后分别为 `14,989/14,986/8,522/70,762/14,989`，全部 `delta=0`；推荐表与基线的 delta 与 ChangePlan 完全一致；健康 live/ready 和任务 GET 均为 `200`，`can_recommend=true`。
执行器说明：POST 已提交后，原执行器因 GET 状态契约不返回顶层 `items` 而在证据组装阶段退出；该退出不影响已提交事务。已补充“items 可选、record_id 必须回读”的执行器兼容修复，并使用独立只读脚本完成事实回读，避免再次发送业务 POST。
验证证据：`artifacts/verification/g7/g7-recommendation-post-reconcile-20260811-001/reconciliation.json`；新增 Make 目标 `verify-g7-recommendation-post-result` 可复核同一计划/基线。回读 SQL 只读，`reconciliation_database_writes=0`、`reconciliation_http_business_posts=0`、`external_requests=0`、`actual_delete_count=0`、`files_deleted=0`、`overwritten_inputs=0`。
新增数据库对象和行数：0 个对象；仅按已批准 ChangePlan 追加上述 37 行，未执行 DDL、UPDATE、DELETE、迁移、seed、索引/向量/图写入。
文件删除数量：0。
数据库物理删除数量：0。
下一步唯一动作：进入真实前端 API/浏览器闭环，将同一 `RecommendationClient` 接到显式 HTTP 组合根；继续保持默认 API/Worker 关闭，不在此阶段重复推荐请求或开放 DeepSeek 外部调用。
```

## G7 显式 Demo HTTP 入口与浏览器接线记录

```text
交接ID：G7-FRONTEND-API-BROWSER-20260811-022
Gate：G7 前端与论文演示（显式 MySQL HTTP 入口、Vite 代理和浏览器冒烟）
状态：EXPLICIT_DEMO_ENTRYPOINT_PASS / BROWSER_HEALTH_PASS / LOCAL_DEMO_SAFE / G7_CONTINUES
时间：2026-08-11（Asia/Shanghai）
新增文件：`backend/app/demo_main.py`；`tests/g7/test_demo_http_entrypoint.py`；证据 `artifacts/verification/g7/g7-frontend-api-browser-20260811-001/frontend.json`。
修改文件：`Makefile` 增加 `demo-backend` 显式目标；`.env.host.example` 增加 `RECPRO_DEMO_HTTP_ENABLED=false` 默认关闭开关；`frontend/README.md` 固化默认 health-only 与 demo 入口边界。
安全设计：默认 `backend.app.main:app` 不变，仍只提供 health 路由；`demo_main` 只有同时满足 `RECPRO_APP_ENV=demo` 和 `RECPRO_DEMO_HTTP_ENABLED=true` 才构造 `build_demo_mysql_http_app`。Make 目标先校验环境，再启动可替换的本地入口，不修改 Compose 默认命令，不连接既有 Neo4j。
真实浏览器结果：临时启动显式 Demo HTTP（MySQL host port=`62306`）与 Vite（`127.0.0.1:5173`）；live/ready 均 `200`，ready=`DEGRADED`、`can_recommend=true`、MySQL=`UP`、推荐管线=`UP`；前端工作台显示“真实接口已就绪”；点击“查看本地演示”渲染 3 张明确标注的本地 fixture，浏览器控制台错误=`0`。
请求边界：浏览器冒烟只通过 Vite 代理执行健康 GET；未点击“请求真实推荐”，业务 HTTP POST=`0`，未重放已完成的 request；真实推荐 POST 的 MySQL 事务闭环由 `G7-RECOMMENDATION-APPLY-20260811-021` 和只读回读证据覆盖。
安全计数：browser smoke database_writes=`0`、external_requests=`0`、actual_delete_count=`0`、files_deleted=`0`、overwritten_inputs=`0`；临时 backend/Vite 进程已停止；未删除文件、容器、卷或数据库数据。
测试结果：Demo 入口定向测试 `2` 项 PASS；全量 Python `401` 项 PASS；浏览器 DOM 冒烟和控制台错误检查 PASS；Make 目标展开检查 PASS。
未解决风险：前端还未执行新的真实推荐 POST（避免重复业务写入）；G4 多智能体持久化编排、图/向量接线、反馈/画像 API 和 DeepSeek 外部调用仍未接入该 Demo HTTP 入口。
下一步唯一动作：为 `RecommendationClient` 增加一次经过单独 ChangePlan 授权的浏览器真实请求验收，或先进入 G4 MAS 编排 HTTP 适配；两者均不得默认开启、不得复用已完成 request_id。
```

## G4 真实多智能体图/向量只读融合记录

```text
交接ID：G4-READONLY-FUSION-20260811-023
Gate：G4 多智能体系统（真实隔离端口融合与确定性验收）
状态：REAL_G4_READONLY_FUSION_PASS / SEVEN_AGENTS_PASS / COUNTS_UNCHANGED / G4_CONTINUES
时间：2026-08-11（Asia/Shanghai）
目标：在已导入且已授权的隔离数据平面上，使用真实 MySQL Catalog/Profile 只读端口、独立 Neo4j 图读端口和版本化 Chroma 向量读端口，运行完整 G4 `build_port_orchestrator`；不构造 HTTP 业务写服务，不执行迁移、seed、INSERT、UPDATE、DELETE 或索引切换。
执行脚本：`scripts/verify_g4_readonly_fusion_runtime.py`；Make 目标：`verify-g4-readonly-fusion`；唯一证据：`artifacts/verification/g4/g4-readonly-fusion-20260811-001/readonly.json`。
真实结果：Orchestrator 状态=`COMPLETED`；dispatch=`7`，依次覆盖 IntentUnderstanding、UserProfile、ResourceSemantic、RecommendationPolicy、CandidateRecall、Ranking、Explanation；同一固定请求重复运行的 payload/trace 一致；返回 `8` 条候选，CandidateRecall 通道=`MYSQL+GRAPH+VECTOR`，无 fallback/warnings。
固定版本：graph_version=`lib-books-v1-20260810`；embedding_version=`hash-char-ngram-v1`；index_version=`lib-books-vector-v1-20260811`；namespace=`library_resources__hash_char_ngram_v1`；dimension=`384`。
计数核验：MySQL `resource_catalog=14,989`、`resource_book_detail=14,986`、`tag_dictionary=8,522`、`resource_tag=70,762`、`resource_index_state=14,989` 前后完全一致；G4 `recommendation_agent_message/result/artifact/orchestration_result` 分别为 `14/14/2/2` 前后完全一致；Chroma 前后均=`14,983`。
安全计数：MySQL writes=`0`（连接最终 rollback）、Neo4j writes=`0`、Chroma writes=`0`、external_requests=`0`、actual_delete_count=`0`、files_deleted=`0`、overwritten_inputs=`0`；未删除或覆盖任何文件、artifact、容器、卷或数据库数据。
当前边界：本阶段证明的是 G4 真实 Agent/图/向量只读融合和确定性，不等同于 G4 HTTP 持久化投影已完成；现有 Demo HTTP 仍使用 G3 `MySQLRecommendationTaskService`，避免在没有新的 ChangePlan 时增加业务行。
下一步唯一动作：设计并测试 G4→RecommendationTaskService 的单事务投影适配器（任务、候选、record、解释、Agent 日志同一事务）；完成前不把 G4 编排挂到默认 HTTP/Worker，也不发送新的业务 POST。
```

## G4→HTTP 投影契约与 fail-closed 设计记录

```text
交接ID：G4-PROJECTION-CONTRACT-20260811-024
Gate：G4 多智能体系统（HTTP 投影边界设计，不写库）
状态：PURE_CONTRACT_PASS / SCENE_PRESERVED / CHANNEL_SPLIT_PASS / FAIL_CLOSED_PASS / G4_CONTINUES
时间：2026-08-11（Asia/Shanghai）
目标：在实现单事务 MySQL 适配器前，先冻结 G4 Agent 事实到 RecommendationTaskService 的纯函数边界，避免 HTTP 层直接依赖 Agent 实现或把不完整候选伪装成可用响应。
新增文件：`backend/app/recommendation/application/g4_projection.py`；`tests/g4/test_g4_projection.py`。
修改文件：`backend/app/recommendation/agents/orchestrator.py` 新增显式 `scene` 字段并在 Intent 消息中透传；旧版本由 Git 提交历史保留。
契约结果：命令映射要求显式、带时区的 `evaluation_at/deadline_at`，使用与 G3 一致的 UUID5 task/trace 身份；`MYSQL+GRAPH+VECTOR` 会拆分为独立、长度受控的候选通道；HTTP 完成态要求目录资源摘要、`evidence_confidence`、解释证据和已持久化 `item_id` 全部存在。
安全边界：本阶段只执行纯函数单元测试和静态检查；未连接 MySQL/Neo4j/Chroma，未执行迁移、seed、INSERT、UPDATE、DELETE、索引切换或外部 LLM 请求。
执行命令：`python -m unittest tests.g4.test_g4_projection tests.g4.test_orchestrator tests.g4.test_persistent_orchestration`；`python -m unittest tests.architecture.test_dependency_rules`；`python -m py_compile backend/app/recommendation/application/g4_projection.py backend/app/recommendation/agents/orchestrator.py tests/g4/test_g4_projection.py`。
测试结果：G4 定向回归 `14` 项 PASS；既有编排/持久化回归 `28` 项 PASS；架构依赖检查 PASS；`database_reads=0`、`database_writes=0`、`external_requests=0`、`actual_delete_count=0`、`files_deleted=0`。
新增数据库对象和行数：0。
受控UPDATE对象和审计ID：0。
文件删除数量：0。
数据库物理删除数量：0。
未解决风险：当前真实 G4 Agent 候选仍缺少 HTTP 所需的资源摘要、证据置信度和持久化 item identity；投影契约因此不会接入默认 HTTP。单事务适配器还需要先定义任务创建、Agent 日志、候选/record/item/trace 写入的顺序及并发幂等回读。
下一步唯一动作：实现显式、未接入默认路由的 MySQL G4 投影适配器，并先以独立 ChangePlan 预演 SQL 与回滚/幂等测试；在用户批准前不执行新的业务 POST。
```

## G4 MySQL 单事务投影 writer 与显式服务记录

```text
交接ID：G4-MYSQL-PROJECTION-WRITER-20260811-025
Gate：G4 多智能体系统（单事务投影 writer / 显式服务，未接入默认 HTTP）
状态：WRITE_PLAN_PASS / APPEND_REPLAY_READBACK_PASS / TRANSACTION_OWNER_PASS / DEFAULT_HTTP_OFF
时间：2026-08-11（Asia/Shanghai）
目标：把已经冻结的 G4→HTTP 契约落到可审查的 MySQL append-only writer；Agent message/result/artifact/orchestration_result 与 G3 task/transition/candidate/record/item/explanation/policy/trace 在同一个调用方事务内追加，writer 本身不 commit/rollback。
新增文件：`backend/app/recommendation/application/g4_persistence.py`；`backend/app/recommendation/adapters/g4_mysql.py`；`tests/g4/test_g4_persistence.py`；`tests/g4/test_g4_mysql_writer.py`。
修改文件：`backend/app/recommendation/agents/orchestrator.py` 将 intent 纳入可追溯 payload；`backend/app/recommendation/agents/real_agents.py` 为真实候选补齐 channel_scores/channel_ranks/primary_channel/evidence_confidence；`backend/app/composition.py` 新增显式 `build_research_g4_recommendation_service`；`tests/g4/test_composition_root_contract.py` 增加组合根门禁；旧版本由 Git 提交历史保留。
事务设计：`MySQLG4ProjectionWriter` 先追加 task 与 transitions，再追加 G4 Agent 事实和 trace artifact，随后追加候选通道行、record、item、explanation、policy、trace；每个关键 INSERT IGNORE 后读取并核对身份/JSON/分数，冲突直接抛错交由上层 rollback。writer 不执行 UPDATE、DELETE、DROP、TRUNCATE、迁移或索引切换。
显式服务边界：`MySQLG4RecommendationTaskService` 复用 G3 的只读 GET/debug/replay 查询，但 create 只在显式组合根调用时运行 G4；澄清 continuation 暂时 fail-closed，避免把 G4 WAITING 状态错误地交给 G3 规则路径。默认 `backend.app.main:app`、Demo HTTP 和 Worker 均未改变。
测试结果：G4 全量 `49` 项 PASS；架构扫描 `113` 文件 PASS；安全扫描 `289` 文件 PASS；所有 fake-connection writer 测试确认 `commit=0`、`rollback=0`，事务由调用方拥有；无外部 LLM 请求。真实隔离只读融合复核也通过，新增证据 `artifacts/verification/g4/g4-readonly-fusion-20260811-003/readonly.json`，7 dispatches、8 candidates、MYSQL+GRAPH+VECTOR，且新增四类 writer 所需候选字段均存在。
真实运行边界：只读复核连接了隔离 MySQL/Neo4j/Chroma 并最终 rollback；MySQL/Neo4j/Chroma writes 均为 `0`，Chroma 前后均 `14,983`，资源/G4 事实表计数不变。没有执行新的 ChangePlan、迁移、seed 或业务 POST；未改变既有 G7 task/record 与 G4 事实计数。
新增数据库对象和行数：0。
受控UPDATE对象和审计ID：0。
文件删除数量：0。
数据库物理删除数量：0。
未解决风险：尚未在隔离 MySQL 上执行新的 G4 writer 真实 ChangePlan；G4 澄清续跑、跨 Agent 超时恢复和正式认证部署仍未完成。
已生成但未批准的 DRY_RUN：`artifacts/verification/g4/g4-projection-plan-20260811-001/g4-recommendation-projection-change-plan.json`；plan_hash=`37e5d950daabd05ca9ea3127550bd4ffee1f9aecf7f534d31f53ee62b3267ca4`，git_commit=`9267e7b9231d84337f15b0cf52242494402f600c`，max_changes=`68`。计划只合并两份既有 PASS 只读基线，未连接数据库；任何 apply 都必须重新读基线并得到用户对该 hash 的明确批准。
下一步唯一动作：由用户审阅该 DRY_RUN ChangePlan；在明确批准前继续保持默认 HTTP/Worker 关闭，不执行 `--apply` 或新的业务 POST。
```

## G4 澄清续跑纯函数契约

```text
交接ID：G4-CLARIFICATION-CONTRACT-20260811-026
Gate：G4 动态多智能体闭环（澄清续跑输入契约，不写库）
状态：PURE_CLARIFICATION_PASS / CONTEXT_INCREMENT_PASS / IDENTITY_PRESERVED / DEFAULT_HTTP_OFF
时间：2026-08-11（Asia/Shanghai）
目标：在实现 G4 continuation 事务适配器前，先把等待态问题、答案、上下文版本和下一轮 RecommendationTaskCommand 的关系冻结为独立纯函数，避免 G4 适配器复用 G3 私有答案解释逻辑或在事务中临时推断。
新增文件：`backend/app/recommendation/application/g4_clarification.py`；`tests/g4/test_g4_clarification.py`。
契约结果：仅接受声明过的槽位和非空答案；required 槽位必须全部回答；声明 options 时答案必须命中 options；`BOOK`/`PAPER`/`BOOK_AND_PAPER` 映射为显式资源类型元组；topic/output_type 只能覆盖对应字段；request/session/user/scene、evaluation_at、来源引用、constraints 和 limit 原样保留；下一 context_version 必须是 previous+1。
事务边界：该模块不连接数据库、不读取上下文、不调用 Agent、不生成 task/trace ID、不提交或回滚；数据库适配器必须先完成幂等键与最新 WAITING context 的只读校验，再调用此纯函数，最后由同一调用方事务追加下一轮事实。
测试结果：新增澄清定向测试 `4` 项 PASS；G4 目录回归 `53` 项 PASS；`py_compile` 和 `git diff --check` PASS。
安全边界：本阶段未连接 MySQL/Neo4j/Chroma，未执行迁移、seed、INSERT、UPDATE、DELETE、索引切换或外部 LLM 请求；文件删除数量=`0`；数据库物理删除数量=`0`。
新增数据库对象和行数：0。
受控UPDATE对象和审计ID：0。
验证证据目录：无运行时 artifact（纯函数阶段）；测试输出由 CI/提交记录保留。
未解决风险：G4 opt-in service 的 `submit_clarification` 仍保持 fail-closed；尚未将下一轮 Agent message/result、task transition、context/clarification、record/item 和 trace revision 组合到同一事务，也未生成该 continuation 的独立 ChangePlan。
下一步唯一动作：实现未接入默认 HTTP 的 G4 continuation writer/service 适配器，先完成 fake 事务的提交、回滚、幂等和 stale-context 测试，再单独生成 DRY_RUN 计划；用户批准前不执行任何新的业务 POST。
```

## G4 首轮投影计划偏差隔离记录

```text
交接ID：G4-PROJECTION-QUARANTINE-20260811-027
Gate：G4 多智能体闭环（首轮受控追加后的计划偏差隔离）
状态：APPLY_QUARANTINED / NO_COMPENSATION_WRITE / DATA_PRESERVED / SUCCESSOR_REQUIRED
时间：2026-08-11（Asia/Shanghai）
触发：已批准的旧 ChangePlan `g4-projection-plan-20260811-002` 使用了与执行请求不同的只读基线文本；基线文本为“多智能体 智慧图书馆”，执行请求为“多智能体系统与智慧图书馆”。
安全动作：执行器在提交事务后发现 `recommendation_candidate` 实际增量为 `13`，而旧计划要求 `24`，立即停止后续动作；未重试、未删除、未 UPDATE、未补偿、未回滚其他事实，也未连接写入 Neo4j/Chroma 或外部 LLM。
实际结果：该次事务本身完整提交并返回 `COMPLETED`，task=`3ab10789-56ae-5fd5-904a-12d0ac28d4b3`，8 个 item，实际追加 `57` 行；`MYSQL=8`、`VECTOR=5`、`GRAPH=0` 是该精确请求的真实候选通道结果。该批次被标记为审计隔离，不对既有事实做任何破坏性处理。
验证证据：`artifacts/verification/g4/g4-projection-apply-20260811-001/g4-recommendation-projection-quarantine.json`；证据状态=`QUARANTINED`，明确记录预期/实际增量、前后计数、通道拆分、Chroma 前后=`14,983` 及零删除/零补偿断言。
根因修复：`scripts/verify_g4_readonly_fusion_runtime.py` 现在记录完整 `query_spec`、候选通道组件和候选持久化行数；计划构建器与执行器按该只读事实动态计算 candidate delta/max_changes，并要求精确请求一致；只读校验允许合法的候选通道子集，但拒绝未知、重复或非规范顺序。
未解决风险：旧隔离批次保留为有效追加事实但不作为新计划的补偿对象；后续任何新追加必须使用新的幂等键和独立批准的 successor plan。
```

## G4 successor ChangePlan 真实追加与回读记录

```text
交接ID：G4-PROJECTION-APPLY-20260811-028
Gate：G4 多智能体闭环（精确请求、单事务投影与隔离目标回读）
状态：REAL_G4_APPEND_PASS / PLAN_DELTA_EXACT / READONLY_RECHECK_PASS / DEFAULT_HTTP_OFF
时间：2026-08-11（Asia/Shanghai）
授权边界：用户明确批准 plan_id=`784de60f-3db5-504b-a222-4a3d979a2dac`、plan_hash=`ea73755d0d51819693612dea45097e87f89e52e904fda29209eaf17e8ac90a53`；仅允许对 Compose project=`recpro-g2-tianyuhang-20260809a`、MySQL `recpro`（本地端口=`62306`）执行一个新的 `S1_APPEND` 请求；不触碰既有 Neo4j、Chroma 或其他数据库。
计划与基线：ChangePlan=`artifacts/verification/g4/g4-projection-plan-20260811-003/g4-recommendation-projection-change-plan.json`；git_commit=`0bafbfb84f1edc6fb6361a00f18a39a0d99e3bc4`；MySQL 基线=`artifacts/verification/g7/g7-mysql-http-readonly-20260811-008/readonly.json`；G4 精确请求基线=`artifacts/verification/g4/g4-readonly-fusion-20260811-007/readonly.json`；请求文本=`多智能体系统与智慧图书馆`，resource_types=`BOOK`，output_type=`TOPIC_RESOURCES`，limit=`8`。
真实结果：HTTP/服务返回 `201`、`replayed=false`、状态=`COMPLETED`；task=`b9e9bfc0-6e3f-5d43-9205-9e5103af97d2`，record=`21`，trace=`5fa5028a-726c-57c7-8b31-c9fdadb754a4`，8 个条目。数据库追加精确 `57` 行：task=`+1`、transition=`+8`、candidate=`+13`、record=`+1`、item=`+8`、explanation=`+8`、policy=`+1`、trace=`+1`、agent_message=`+7`、agent_result=`+7`、artifact=`+1`、orchestration_result=`+1`。
计数回读：目标表均达到计划下界，追加后 task=`21`、transition=`180`、candidate=`311`、record=`21`、item=`111`、explanation=`111`、policy=`21`、trace=`21`、agent_message/result=`28/28`、artifact/orchestration_result=`4/4`；资源事实表、上下文表和其他非目标表未变化。执行前后 Chroma count 均=`14,983`，Neo4j writes=`0`，Chroma writes=`0`，external_llm_requests=`0`，actual_delete_count=`0`，files_deleted=`0`，overwritten_inputs=`0`。
执行证据：`artifacts/verification/g4/g4-projection-apply-20260811-002/g4-recommendation-projection-apply.json`；后置只读证据：`artifacts/verification/g4/g4-readonly-fusion-20260811-008/readonly.json`、`artifacts/verification/g7/g7-mysql-http-readonly-20260811-009/readonly.json`。后置 G4 仍为 7 dispatches、8 candidates、`MYSQL+VECTOR`，MySQL/Chroma 计数不变；后置 G7 live/ready=`200`，`can_recommend=true`，业务 POST=`0`。
配置边界：执行环境中配置的 LLM provider=`deepseek`，本次安全执行器强制 `enable_llm_provider=false`，因此没有发送 DeepSeek 请求或暴露密钥；默认 HTTP/API/Worker 继续关闭，G4 仍为显式组合根能力。
告警处理：首次执行输出 MySQL `Data truncated for column 'confidence' at row 1`；只读回查确认该 task 的 7 条 Agent confidence 均在 `0.800000—1.000000`、无 NULL，列类型为 `DECIMAL(7,6)`，未观察到已提交值丢失。随后提交 `d70118b`，将 Agent confidence 固定为六位小数文本后再写入，并新增回归测试；该修复不修改既有数据库行，后续追加需重新生成并批准新的计划。
测试与版本：本阶段执行前后完整 Python unittest=`423` 项 PASS；修复后的 G4 回归=`60` 项 PASS；安全扫描=`295` files PASS；架构扫描=`114` files PASS；未删除文件、artifact、容器、卷或数据库对象。
下一步唯一动作：进入 G4 continuation（澄清续跑）和真实 HTTP 接线设计；先完成 fake 事务/幂等/stale-context 测试与新的 DRY_RUN 计划，默认 HTTP/Worker 不变，用户批准前不得追加新的业务行。
```

## G4 澄清续跑适配器代码完成记录

```text
交接ID：G4-CLARIFICATION-CONTINUATION-20260811-029
Gate：G4 动态多智能体闭环（澄清续跑适配器与追加式事务边界）
状态：CONTINUATION_ADAPTER_PASS / FAKE_TX_PASS / MULTI_ROUND_GUARD_PASS / REAL_PLAN_PENDING
时间：2026-08-11（Asia/Shanghai）
目标：实现 G4 等待态的真实续跑路径，但在生成并批准专用 ChangePlan 前不触碰隔离 MySQL、Neo4j、Chroma 或外部 LLM。
新增文件：`tests/g4/test_g4_continuation.py`。
修改文件：`backend/app/recommendation/adapters/g4_mysql.py`、`backend/app/recommendation/agents/orchestrator.py`、`backend/app/recommendation/application/g4_projection.py`、`tests/g4/test_g4_mysql_writer.py`、`tests/g4/test_g4_orchestrator.py`。
代码结果：`OrchestrationRequest.initial_status` 允许从 `WAITING_CLARIFICATION` 进入同一 Agent 编排；G4 service 先读取任务身份、幂等键和最新等待上下文，再调用纯 `build_g4_clarification_continuation`，使用原 task/trace identity 和递增 context_version 执行 Agent；writer 追加 context 2 及后续轮次的 transition、Agent message/result、artifact、orchestration result、policy、trace revision、候选/record/item/explanation 和回答上下文。根任务请求事实不更新，writer 以最新上下文而不是根行的旧版本作为多轮续跑边界。
幂等与失败边界：同一幂等键同答案直接回放；同键不同答案拒绝；context_version 陈旧、任务非 WAITING 或数据库唯一性冲突均回滚；所有续跑事实由调用方一次 commit，writer 不 commit/rollback，SQL 不包含 UPDATE、DELETE、DROP、TRUNCATE 或覆盖式写入。
测试结果：全量 Python unittest=`431` 项 PASS；架构扫描=`114` files PASS；安全扫描=`296` files PASS；文档校验=`18` Markdown/42 blocks PASS；相关 `py_compile`、`git diff --check` PASS。
版本提交：`5e6d63a feat(g4): implement append-only clarification continuation`，已推送 `origin/codex/g1-runnable-skeleton`。
数据库与外部副作用：database_reads=`0`、database_writes=`0`、Neo4j writes=`0`、Chroma writes=`0`、external_requests=`0`；新增数据库对象和行数=`0`；文件删除数量=`0`；数据库物理删除数量=`0`。
配置/部署边界：默认 `backend.app.main:app`、Demo HTTP、Worker 和 DeepSeek 外部调用均保持关闭；仅代码与 fake connection 测试验证，不宣称真实续跑已经可用。
未解决风险：当前隔离 MySQL 没有可直接复用的 G4 WAITING 任务；真实续跑必须先用新的 request_id 创建一个等待任务，并为“创建等待任务”和“提交澄清答案”分别生成、核对和批准 append-only ChangePlan；真实运行还需验证响应 GET、debug context/trace、幂等重放和前后计数。
下一步唯一动作：基于新的只读基线生成 G4 WAITING 任务创建 DRY_RUN 计划；未得到该计划的精确 hash 和用户批准前，不执行任何续跑业务 POST。
```

## G4 等待态只读验证与计划门禁记录

```text
交接ID：G4-CLARIFICATION-PLAN-GATE-20260811-030
Gate：G4 动态多智能体闭环（初始 WAITING 任务的只读基线与 ChangePlan）
状态：READONLY_GATE_CODE_PASS / HOME_EMPTY_FIX_PASS / RUNTIME_BASELINE_PENDING
时间：2026-08-11（Asia/Shanghai）
目标：为真实澄清续跑准备第一步“创建一个 G4 WAITING_CLARIFICATION 任务”的只读验证器和 DRY_RUN 计划构建器；不在本阶段创建任务、不提交业务 POST。
新增文件：`scripts/verify_g4_clarification_readonly.py`、`scripts/build_g4_clarification_plan.py`、`tests/g4/test_g4_clarification_plan.py`。
修改文件：`backend/app/recommendation/application/g4_projection.py` 保留 HOME 空请求的显式空 resource_types；`Makefile` 增加 `verify-g4-clarification-readonly` 与 `build-g4-clarification-plan`。
门禁设计：只读验证器通过真实 MySQL Catalog/Profile 端口运行 HOME 空请求，要求 4 次 Agent dispatch、4 条 transition、问题列表、确定性重复结果和全表计数前后不变；MySQL 连接最终 rollback，不接入 writer，不连接 Neo4j/Chroma，不启用 DeepSeek。计划构建器只接受上述 PASS evidence，冻结新的 request/session/idempotency identity、基线计数和版本 commit，目标集仅允许 19 行 append：task=`+1`、transition=`+4`、policy=`+1`、trace=`+1`、task_context=`+1`、clarification=`+1`、Agent message/result=`+4/+4`、artifact=`+1`、orchestration_result=`+1`。
代码验证：全量 Python unittest=`435` 项 PASS；架构扫描=`114` files PASS；安全扫描=`299` files PASS；文档校验=`18` Markdown/42 blocks PASS；`py_compile` 与 `git diff --check` PASS。提交=`ad02c16 feat(g4): add clarification read-only plan gates`，已推送 `origin/codex/g1-runnable-skeleton`。
运行态阻断：本机 `/usr/local/bin/docker` 是指向不存在 `/Applications/Docker.app/Contents/Resources/bin/docker` 的断链，当前 shell 无可用 Docker CLI；因此没有执行 MySQL 只读验证、没有生成新的 clarification-readonly evidence 或 ChangePlan artifact，也没有连接/写入任何数据库。
数据库与文件安全：本阶段 database_reads=`0`、database_writes=`0`、Neo4j/Chroma writes=`0`、external_requests=`0`；新增数据库对象和行数=`0`；文件删除数量=`0`；数据库物理删除数量=`0`。已有 artifact、容器、卷和数据库数据均未修改。
未解决风险：恢复 Docker Desktop/CLI 后需重新读取完整表计数（包含上下文与 Agent 表），确认 Docker Compose 项目和 least-privilege 账号，再运行只读 verifier；若基线漂移，旧计划不得复用。等待任务创建计划获批并成功回读后，才能为具体 task/context_version 生成第二份澄清答案 DRY_RUN 计划。
下一步唯一动作：恢复可用 Docker CLI，执行 `make verify-g4-clarification-readonly G4_CLARIFICATION_READONLY_RUN_ID=<new-run-id>`；只读证据 PASS 后再执行 `make build-g4-clarification-plan ...`，向用户报告精确 plan hash，等待批准。
```

## G4 等待态只读验证通过记录

```text
交接ID：G4-CLARIFICATION-READONLY-20260811-031
Gate：G4 动态多智能体闭环（HOME 空请求等待态只读验证）
状态：REAL_MYSQL_READONLY_PASS / FOUR_AGENTS_PASS / COUNTS_UNCHANGED / PLAN_PENDING_APPROVAL
时间：2026-08-11（Asia/Shanghai）
执行：`make verify-g4-clarification-readonly PYTHON=.venv-g1-release-py311/bin/python G4_CLARIFICATION_READONLY_RUN_ID=g4-clarification-readonly-20260811-001`；虽然 Docker CLI 断链，隔离 MySQL 62306、Neo4j 62688 和 62475 端口仍可访问，本次仅连接 MySQL 读取。
真实结果：HOME 空请求（scene=`HOME`、input_text=`null`、resource_types=`[]`、output_type=`null`、limit=`5`）稳定返回 `WAITING_CLARIFICATION`；4 个 Agent 依次为 IntentUnderstanding、UserProfile、ResourceSemantic、RecommendationPolicy，4 条 transition，问题为 resource_types/topic 两个 required slots；同一请求重复编排 payload/trace 一致。
只读计数：resource_catalog=`14,989`、resource_book_detail=`14,986`、tag_dictionary=`8,522`、resource_tag=`70,762`、resource_index_state=`14,989`；recommendation_task/transition/candidate/record/item/explanation/policy/trace=`21/180/311/21/111/111/21/21`；trace_revision/context/clarification=`3/6/6`；Agent message/result/artifact/orchestration=`28/28/4/4`。19 张表 before/after 完全相同。
验证证据：`artifacts/verification/g4/g4-clarification-readonly-20260811-001/clarification-readonly.json`；任务/Trace 只读演练 ID=`d6f81ae1-27a5-5776-8e7e-62159d02e175`/`390a17bb-0979-50fd-81a6-c5004c546d9b`，不写入数据库。
安全计数：`mysql_mode=SELECT_ONLY_ROLLBACK`、MySQL writes=`0`、Neo4j/Chroma writes=`0`、external_requests=`0`、actual_delete_count=`0`、files_deleted=`0`、overwritten_inputs=`0`。
计划预演：构建器已生成 `artifacts/verification/g4/g4-clarification-plan-20260811-001/g4-clarification-waiting-change-plan.json`，当时 `plan_id=e90c1714-c409-57a0-847a-ccd527468cb3`、`plan_hash=2c16ff9de7a4e69f011a0a05ca99a4652848afa9feae4e19833ee42870724209`、`max_changes=19`；由于本交接记录提交会改变 reviewed git commit，该 hash 仅作为预演记录，提交后会重新生成最终 hash，旧 hash 不得批准或执行。
下一步唯一动作：完成本交接提交后重新生成最终等待任务 DRY_RUN ChangePlan，向用户报告新的精确 `plan_id/plan_hash`；在批准前不执行 `--apply`、不创建等待任务、不提交澄清答案。
```

## G4 等待任务批准执行器完成记录

```text
交接ID：G4-CLARIFICATION-EXECUTOR-20260811-032
Gate：G4 动态多智能体闭环（等待任务 ChangePlan 的 fail-closed 执行器）
状态：APPROVED_EXECUTOR_CODE_PASS / PREPOST_COUNT_GUARD_PASS / NO_APPLY_YET
时间：2026-08-11（Asia/Shanghai）
新增文件：`scripts/execute_g4_clarification_plan.py`、`tests/g4/test_g4_clarification_executor.py`。
修改文件：`Makefile` 增加 `execute-g4-clarification-plan`，要求显式 `--apply`、plan_id、plan_hash、只读 evidence、request run id 和新的 apply run id。
执行器边界：只接受 S1_APPEND/DRY_RUN 且目标集严格等于 19 行等待事实；执行前核对 canonical plan hash、reviewed Git commit、只读 evidence/config hash、Compose/MySQL 身份、runtime probe、最小权限 grants、幂等 request_id 不存在和全部目标 before counts。服务只使用 MySQL Catalog/Profile 读端口，`enable_llm_provider=false`；成功后要求 WAITING response、问题列表、任务 GET 回读和每张表精确 delta。任何漂移、重放、非 append 目标、非 WAITING 返回或未计划表变化都会失败，不重试、不补偿、不删除。
测试结果：全量 Python unittest=`438` 项 PASS；架构扫描=`114` files PASS；安全扫描=`301` files PASS；文档校验=`18` Markdown/42 blocks PASS；`py_compile`、`git diff --check` PASS。
版本提交：`f89bdae feat(g4): add approved clarification append executor`，已推送 `origin/codex/g1-runnable-skeleton`。
数据库与外部副作用：本阶段没有调用执行器 `--apply`；database_writes=`0`、Neo4j/Chroma writes=`0`、external_requests=`0`、actual_delete_count=`0`、files_deleted=`0`；既有只读 evidence 和计划 artifact 未覆盖。
计划边界：此前计划 `...-002` 因本提交改变 reviewed Git commit，不能批准或执行；需在本提交后重新生成最终等待任务计划，再报告新的精确 plan_id/hash。
下一步唯一动作：重新生成最终 DRY_RUN ChangePlan；用户明确批准未变更的 plan_id/hash 后，才可执行一次等待任务追加并做只读回读。
```

## G4 等待任务首次执行失败隔离与修复记录

```text
交接ID：G4-CLARIFICATION-APPLY-FAILURE-20260811-034
Gate：G4 动态多智能体闭环（已批准等待任务追加的失败隔离）
状态：APPLY_STOPPED_BEFORE_COMMIT / ZERO_DELTA_CONFIRMED / SUCCESSOR_PLAN_REQUIRED
时间：2026-08-11（Asia/Shanghai）
授权边界：用户批准了 plan_id=`8bcd9c3a-67aa-5cc5-a901-9854741dadfe`、plan_hash=`ffa6764a14cf1445c955d91750033e430f5bb4adcc2ff67f20d64d16e49ebc00`；执行器仅尝试一次，未复用或重试该旧计划。
执行命令：`make execute-g4-clarification-plan PYTHON=.venv-g1-release-py311/bin/python G4_CLARIFICATION_APPLY_RUN_ID=g4-clarification-apply-20260811-001 ...`；运行前已核对 plan/evidence/config/Git hash、MySQL 62306 身份、Neo4j 62688 与 HTTP 62475 端口。
失败原因：真实等待态响应在 G4 writer 的 JSON 持久化边界携带 `datetime`，触发 `TypeError: Object of type datetime is not JSON serializable`；异常恢复分支又引用了当前 asyncmy 版本不存在的 `asyncmy.IntegrityError`，导致原始异常未能进入受控回滚分支。
安全处置：停止新写请求，不重试、不补偿、不 UPDATE、不 DELETE；关闭连接后立即执行独立 SELECT-only 核对。MySQL 19 张表计数仍为 `task/transition/candidate/record/item/explanation/policy/trace=21/180/311/21/111/111/21/21`、`context/clarification=6/6`、`Agent message/result/artifact/orchestration=28/28/4/4`，资源事实表仍为 `14,989/14,986/8,522/70,762/14,989`；目标 request_id 不存在，确认数据库增量为 `0`。
根因修复：提交 `d81efe6 fix(g4): harden waiting-task transaction serialization`，在 G4 persistence boundary 将带时区 datetime 规范化为 UTC `Z` JSON 字符串，并改用 `asyncmy.errors.IntegrityError`；新增时区回归测试。该修复不修改任何既有数据库行或文件。
验证结果：完整 Python unittest=`439` 项 PASS；架构扫描=`114` files PASS；安全扫描=`301` files PASS；文档校验=`18` Markdown/42 blocks PASS；`compileall` 与 `git diff --check` PASS；分支已推送 `origin/codex/g1-runnable-skeleton`。
副作用计数：database_writes=`0`、Neo4j writes=`0`、Chroma writes=`0`、external_requests=`0`、actual_delete_count=`0`、files_deleted=`0`、overwritten_inputs=`0`。
证据：原执行器在提交前失败，故没有生成 apply PASS artifact；失败堆栈与独立只读计数保留在本次任务日志，成功后的新执行必须写入新的 apply run 目录，不覆盖旧目录。
未解决风险：修复改变了 reviewed Git boundary，旧 plan_id/hash 不再可执行；不能在未获新批准前提交任何新的业务 POST。
下一步唯一动作：基于同一 PASS 只读 evidence 和新 Git commit 生成新的 G4 WAITING `S1_APPEND/DRY_RUN` ChangePlan，报告新的精确 plan_id/plan_hash，等待用户重新批准后再执行一次。
```

## G4 successor 等待任务计划预演记录

```text
交接ID：G4-CLARIFICATION-PLAN-PREVIEW-20260811-035
Gate：G4 动态多智能体闭环（失败修复后的 successor DRY_RUN）
状态：DRY_RUN_PASS / NO_DATABASE_WRITE / FINAL_PLAN_AFTER_DOC_COMMIT_REQUIRED
时间：2026-08-11（Asia/Shanghai）
计划预演：已基于 PASS 只读 evidence `artifacts/verification/g4/g4-clarification-readonly-20260811-001/clarification-readonly.json` 和 Git `343a2b094d4d463f71cf8434605226e56d0aa993` 生成 `artifacts/verification/g4/g4-clarification-plan-20260811-004/g4-clarification-waiting-change-plan.json`；预演 plan_id=`83470675-8956-5bd4-aedb-1cb84a76182f`、plan_hash=`5caeb6cb787db7f3b0cc08c583f15fba3a8be51a2e06aa0f5e90ffda1732d071`、max_changes=`19`。
边界：该文件仅为 DRY_RUN，未连接 MySQL、Neo4j、Chroma 或外部 LLM，不产生业务 POST；目标仍严格为 19 行 MySQL APPEND，预期 task/transition/policy/trace/context/clarification=`+1/+4/+1/+1/+1/+1`，Agent message/result=`+4/+4`，artifact/orchestration=`+1/+1`，不追加 candidate/record/item/explanation/trace revision。
失效规则：本交接记录的追加提交会改变 reviewed Git commit，因此 plan 004 仅作审计预演，不得批准或执行；提交完成后必须重新生成最终 successor plan，并只报告最终 plan_id/plan_hash。
安全计数：database_writes=`0`、Neo4j/Chroma writes=`0`、external_requests=`0`、actual_delete_count=`0`、files_deleted=`0`、overwritten_inputs=`0`。
下一步唯一动作：提交本交接记录后生成 final `g4-clarification-plan-20260811-005` DRY_RUN，用户重新批准其精确 hash 后才可执行一次等待任务追加。
```

## G4 等待任务真实追加与独立回读记录

```text
交接ID：G4-CLARIFICATION-APPLY-20260811-036
Gate：G4 动态多智能体闭环（初始 WAITING_CLARIFICATION 任务真实追加）
状态：REAL_MYSQL_WAITING_APPEND_PASS / PLAN_DELTA_EXACT / READONLY_READBACK_PASS
时间：2026-08-11（Asia/Shanghai）
授权：用户批准 plan_id=`0357dbfe-9e7c-5833-8bf5-70dd24620106`、plan_hash=`e286f9d4a7681829da5f74d0824507a0a495294a8834cbf47b611e7f977c9153`；执行器仅运行一次，apply run=`g4-clarification-apply-20260811-002`。
计划与环境：ChangePlan=`artifacts/verification/g4/g4-clarification-plan-20260811-005/g4-clarification-waiting-change-plan.json`，reviewed Git=`8c60885feae37178237fbbd9965b05ffafb62eae`，Compose project=`recpro-g2-tianyuhang-20260809a`，MySQL=`recpro`、本地端口=`62306`；runtime probe 与 grants guard 均通过。
真实结果：返回 HTTP/service `201`、`replayed=false`、状态=`WAITING_CLARIFICATION`、context_version=`1`、问题=`2`、record_id=`null`；task=`b6dc4ed8-4c3d-500b-8026-7b5f7779f7cf`，trace=`76a31b9b-c613-5dbc-af53-4e2d398ea5fe`，request_id=`f580118a-e459-5ccc-86fe-d636ab6270ed`。
精确追加：MySQL 共 `19` 行：task=`+1`、transition=`+4`、policy=`+1`、trace=`+1`、task_context=`+1`、clarification=`+1`、Agent message/result=`+4/+4`、artifact=`+1`、orchestration_result=`+1`；candidate、record、item、explanation、trace_revision 及资源事实表均 `+0`。
计数回读：task/transition/candidate/record/item/explanation/policy/trace=`22/184/311/21/111/111/22/22`；context/clarification/trace_revision=`7/7/3`；Agent message/result/artifact/orchestration=`32/32/5/5`；resource_catalog/book_detail/tag_dictionary/resource_tag/index_state=`14,989/14,986/8,522/70,762/14,989`，与计划精确一致。
独立只读回读：目标 task 根状态=`WAITING_CLARIFICATION`、根 context_version=`1`、trace identity 一致；context 1 包含 2 个问题、空答案、response status=`WAITING_CLARIFICATION`、evaluation_at 已规范化为字符串；clarification 1 的 answered_at=`NULL`；trace `g4-trace-v1` complete=`true`、4 steps；transition/Agent message/result/artifact/orchestration 行数=`4/4/4/1/1`。独立回读 writes=`0`、deletes=`0`。
副作用计数：本次数据库写入=`19`；Neo4j writes=`0`、Chroma writes=`0`、external_requests=`0`、external_llm_requests=`0`、files_deleted=`0`、actual_delete_count=`0`、overwritten_inputs=`0`。
证据：`artifacts/verification/g4/g4-clarification-apply-20260811-002/g4-clarification-apply.json`；只读基线=`artifacts/verification/g4/g4-clarification-readonly-20260811-001/clarification-readonly.json`。两份 artifact 均追加保存，未覆盖旧证据。
未解决风险：尚未提交任何澄清答案；默认 HTTP/Worker/DeepSeek 仍关闭。下一轮必须针对 task=`b6dc4ed8-4c3d-500b-8026-7b5f7779f7cf`、context_version=`1` 先生成独立答案 DRY_RUN ChangePlan，核对问题槽位与答案，再经用户单独批准；不得直接 POST。
下一步唯一动作：实现/生成澄清答案 continuation 的只读计划门禁，目标为 context_version=`2`；在新 plan_id/hash 获批前不追加答案。
```

## G4 澄清答案真实续跑与独立回读记录

```text
交接ID：G4-CLARIFICATION-CONTINUATION-APPLY-20260811-037
Gate：G4 动态多智能体闭环（context 1→2 真实澄清续跑）
状态：REAL_MYSQL_CONTINUATION_PASS / PLAN_DELTA_EXACT / READONLY_READBACK_PASS
时间：2026-08-11（Asia/Shanghai）
授权：用户批准 plan_id=`e79afba2-7d68-56e3-909c-9d56a522adb4`、plan_hash=`f37437d853ee9b660e2fe1eced4a1ba4ba477b31025b352d9874b80e7d9ac7f6`；执行器仅运行一次，apply run=`g4-clarification-continuation-apply-20260811-001`。
计划与环境：ChangePlan=`artifacts/verification/g4/g4-clarification-continuation-plan-20260811-002/g4-clarification-continuation-change-plan.json`，reviewed Git=`a7b76cb3aa1e3fb346504e541e0ca4309e3f9a70`，Compose project=`recpro-g2-tianyuhang-20260809a`，MySQL=`recpro`、本地端口=`62306`；runtime probe 与 grants guard 均通过。
答案：resource_types=`BOOK`；topic=`多智能体+推荐系统+知识图谱`。该组合主题在 500 字符边界内保留为答案事实，资源类型仍使用封闭枚举。
真实结果：同一 task=`b6dc4ed8-4c3d-500b-8026-7b5f7779f7cf`、trace=`76a31b9b-c613-5dbc-af53-4e2d398ea5fe` 从最新 WAITING context 1 进入 context 2，返回 `200`、`replayed=false`、状态=`COMPLETED`、record=`22`、5 个图书条目。
精确追加：MySQL 共 `44` 行：transition=`+8`、candidate=`+5`、record=`+1`、item/explanation=`+5/+5`、policy=`+1`、trace_revision=`+1`、task_context/clarification=`+1/+1`、Agent message/result=`+7/+7`、artifact=`+1`、orchestration_result=`+1`；根 task 与原始 trace 不更新，资源事实表不变。
计数回读：task/transition/candidate/record/item/explanation/policy/trace=`22/192/316/22/116/116/23/22`；trace_revision/context/clarification=`4/8/8`；Agent message/result/artifact/orchestration=`39/39/6/6`；resource_catalog/book_detail/tag_dictionary/resource_tag/index_state=`14,989/14,986/8,522/70,762/14,989`，与计划精确一致。
独立只读回读：根 task 保留不可变快照 `WAITING_CLARIFICATION/context_version=1`；最新 context 2=`COMPLETED`，答案键为 resource_types/topic，response 包含 5 items；clarification 2 的 answered_at 非空；context 1 问题与空答案事实保留；context 2 trace revision `g4-trace-v1` complete=`true`、7 steps；context 2 有 8 transitions、7 Agent message/result，record 22 下 rank 1—5 的 5 个 item。独立回读 writes=`0`、deletes=`0`。
副作用计数：本次数据库写入=`44`；Neo4j writes=`0`、Chroma writes=`0`、external_requests=`0`、external_llm_requests=`0`、files_deleted=`0`、actual_delete_count=`0`、overwritten_inputs=`0`。
证据：`artifacts/verification/g4/g4-clarification-continuation-apply-20260811-001/g4-clarification-continuation-apply.json`、只读证据=`artifacts/verification/g4/g4-clarification-continuation-readonly-20260811-002/clarification-continuation-readonly.json`；均为新目录追加保存，未覆盖历史 artifact。
未解决风险：本轮使用安全执行器关闭外部 LLM、Neo4j/Chroma 写入；默认 HTTP/Worker 仍不自动启用。下一阶段可在独立计划下接入真实 HTTP 工作台回读、幂等重放和 feedback/outbox，不得把本轮事实当作可覆盖状态。
下一步唯一动作：整理 G4 真实闭环验收报告，随后生成下一项独立 DRY_RUN 计划；不对已提交事实做删除或 UPDATE。
```

## 当前运行态、前端与参数审计记录

```text
交接ID：STATUS-AUDIT-20260811-001
Gate：G4/G6/G7 当前实现可运行性与前端配置审计
状态：COMPOSE_RUNTIME_PASS / FRONTEND_LOCKED_RUNTIME_PASS / CONFIG_BOUNDARY_REPORTED
时间：2026-08-11（Asia/Shanghai）
安全边界：本轮只构建/启动本项目 backend/frontend 容器、执行 HTTP GET 与 SELECT-only 验证；未执行业务 POST、迁移、UPDATE、DELETE、文件删除或外部 DeepSeek 请求。
基础设施：Docker Desktop 实际引擎 client/server=`29.3.1`；Compose project=`recpro-g2-tianyuhang-20260809a`。MySQL=`healthy`（62306→3306）、Neo4j=`healthy`（62474/62687）；独立图书 Neo4j project=`recpro-library-neo4j-20260810a`（62475/62688）保持隔离。backend=`healthy`（62000→8000）、frontend=`healthy`（62173→8080）。
默认 HTTP：backend.app.main:app 真实 live=`200`、ready=`200`，MySQL=`UP`、配置包=`UP`，但 `can_recommend=false`、推荐链路=`DISABLED`；这是默认 health-only 闸门，不是故障。前端 Nginx `/healthz`、前端代理 `/api/v1/health/live` 均真实返回 `200`。
显式 Demo HTTP：临时以 `RECPRO_APP_ENV=demo` 与 `RECPRO_DEMO_HTTP_ENABLED=true` 启动 demo_main，仅执行 live/ready 和既有 task GET 回读；ready=`200`、`can_recommend=true`、G3 MySQL 推荐管线=`UP`，既有 task=`b6dc4ed8-4c3d-500b-8026-7b5f7779f7cf` 回读为 `COMPLETED/context_version=2/record=22`。本次没有新增业务行。
G7/G6 当前回读：`g7-mysql-http-readonly-20260811-010` PASS，推荐路由存在、业务 POST=`0`、13 张资源/推荐事实表前后计数一致；`g6-retrieval-fusion-readonly-20260811-002` PASS，MYSQL+GRAPH+VECTOR 三通道、8 候选、三依赖 READY，MySQL/Neo4j/Chroma 写入均=`0`，Chroma collection=`14983`。
前端页面：Vue 页面已完成状态核验卡片、组件状态、推荐工作台、资源类型/结果数选择、澄清面板、证据卡片和明确标注的本地演示；浏览器真实点击“查看本地演示”显示 3 张 fixture 卡片，并提示不访问 API/不写入三类存储。页面视觉与交互验收通过。
前端验证：锁文件隔离环境中 Vitest=`6 files/40 tests PASS`、vue-tsc=`PASS`、追加式生产构建=`PASS`；Compose Node 24 镜像按 package-lock 重新构建成功。当前工作区既有 `frontend/node_modules` 实际 TypeScript=`7.0.2`，而锁文件要求=`5.9.3`，因此本机直接 `npm test`/`make frontend-build` 会失败；未使用 `npm ci`，未删除现有依赖目录。该问题属于本地依赖漂移，源码与锁文件未发现缺陷。
参数：`.env.compose` 结构校验=`PASS`，MySQL/Neo4j/Prompt Bundle、DeepSeek provider=`deepseek`、model=`deepseek-v4-flash`、HTTPS base URL、20 秒、512 token、key 存在且仅在 0600 Git-ignored 文件中；离线 provider 构造为 `DeepSeekLLMProvider`。但默认 Compose/Worker/health-only 不会自动调用 DeepSeek，G3 demo 仍使用 MockLLM，G4 LLM/Graph/Vector HTTP 接线尚未开启。
参数缺口：当前 `.env.host` 仍是旧 host-mode 文件，端口=`3306`（本隔离 Compose 映射为=`62306`），且缺少 migration user/password，`validate_runtime_env --mode host` 失败；因此不能宣称 host demo 参数已完全就绪。正式生产认证、production HTTP、Worker、G4 HTTP 入口也仍按 fail-closed 关闭。
证据：`artifacts/verification/g6/g6-retrieval-fusion-readonly-20260811-002/readonly.json`、`artifacts/verification/g7/g7-mysql-http-readonly-20260811-010/readonly.json`；源码/配置未覆盖历史 artifact。
副作用计数：database_writes=`0`、Neo4j writes=`0`、Chroma writes=`0`、external_requests=`0`、external_llm_requests=`0`、actual_delete_count=`0`、files_deleted=`0`、overwritten_inputs=`0`。
下一步唯一动作：在不清理现有 `frontend/node_modules` 的前提下提供锁定依赖的可复现启动入口；随后单独设计/审查 G4 HTTP（真实多智能体、图/向量读取、澄清续跑、幂等）DRY_RUN 计划，获批前不发送新的业务 POST。
```

## 配置修复与健康检查稳定化记录

```text
交接ID：CONFIG-FIX-20260811-001
Gate：本机配置同步、前端锁定依赖恢复与 Compose 健康检查稳定化
状态：HOST_ENV_SYNC_PASS / FRONTEND_LOCKED_RUNTIME_PASS / COMPOSE_HEALTHCHECK_TUNED / NEO4J_RESOURCE_CONTENTION_REPORTED
时间：2026-08-11（Asia/Shanghai）
安全边界：本阶段未执行业务 POST、迁移、UPDATE、DELETE、DROP、TRUNCATE 或外部 DeepSeek 请求；没有删除文件、容器、卷、数据库对象或数据库数据。
主机环境：新增 `scripts/sync_host_env_from_compose.py`，默认只做 DRY_RUN，显式 `--apply` 才同步；仅复制已审查的运行时/迁移/LLM/Prompt 键，强制 host MySQL 使用 `127.0.0.1` 与隔离 Compose 映射端口 `62306`，并保持 Demo/Auth/Production HTTP/Debug/G4 HTTP 闸门为 `false`。`HOST_ENV_SYNC_RUN_ID=host-env-sync-20260811-001` 的首次 DRY_RUN 与 APPLY 均通过；随后 `host-env-sync-20260811-004` 将新增 G4 闸门同步到 `.env.host`，主机预检仍 PASS。两次原文件均先备份到权限 `0600` 的 `/tmp/recpro-env-host-before-host-env-sync-*` 路径，未进入 Git。
前端依赖：发现旧 `frontend/node_modules` 的 TypeScript=`7.0.2` 与 `package-lock.json` 的 TypeScript=`5.9.3` 漂移；旧目录仅移动到 `/tmp/recpro-frontend-node_modules-drift-backup-20260811-001` 保留，未删除。按锁文件重新安装后，Vitest=`6 files/40 tests PASS`，vue-tsc=`PASS`，生产构建=`PASS`，构建产物写入新的 `frontend/dist/config-fix-20260811-002/`。
Docker CLI：Makefile 增加只读探测并自动回退到实际 Docker Desktop 二进制 `/Applications/编程/Docker.app/Contents/Resources/bin/docker`；没有修改或替换系统 `docker` 符号链接。`make status` 与 `make compose-config` 均可执行。
健康检查：MySQL timeout 调整为 `5s`；backend/worker timeout 调整为 `10s`、start_period=`20s`；Neo4j 使用轻量 HTTP(`7474`)+Bolt(`7687`) 探测，timeout=`10s`、start_period=`60s`，避免启动期反复拉起 `cypher-shell` JVM。配置已通过 Compose 语法门禁；MySQL、backend、frontend 与本项目隔离 Neo4j 当前均为 `healthy`，live/ready 与前端 `/healthz` GET 均通过。
Neo4j 运行态：本项目隔离 `neo4j_data` 卷在容器重建前后保持同一命名卷，未执行卷删除或数据清理。短暂初始化期间的资源竞争已自行缓解，当前隔离 Neo4j 已恢复 `healthy`。为使图书只读验证使用新的轻量健康检查，本阶段仅重建了项目自有的 `recpro-library-neo4j-20260810a` 容器并复用原卷，未执行 Cypher 写入；用户原有 Homebrew/外部 Neo4j 大图始终未停止、未重启、未访问。
自动化验证：新增 host-env-sync 单元测试 `2` 项 PASS；全量 Python unittest、safety/architecture/docs/contracts/prompt 门禁与 `git diff --check` 均通过；同步脚本报告 `database_writes=0`、`external_requests=0`、`files_deleted=0`、`overwritten_inputs=0`。
G4 HTTP 组合边界：新增 `RECPRO_G4_HTTP_ENABLED=false` 配置与 `build_research_g4_http_app()`；构造期要求非 production、显式开关和调用方注入 G4 service，默认 API/Compose/Worker 不变。该组合根尚未接入真实 Graph/Vector 客户端或 DeepSeek，也未启动或发送任何 HTTP 业务请求；新增构造契约测试覆盖“关闭即拒绝”和“仅挂载注入 service”。
下一阶段：在默认 HTTP/Worker/LLM 继续 fail-closed 的前提下，进入 G4 HTTP 真实投影入口的纯只读/DRY_RUN 设计，先冻结 graph/vector 读取、澄清续跑、幂等与认证边界，再生成独立 ChangePlan；未获新的精确批准前不提交新的业务写入。
```

## G4 Graph/Vector 只读接线与融合证据

```text
交接ID：G4-READONLY-FUSION-20260811-010/011
Gate：G4 动态多智能体闭环（版本锁定的 Graph/Vector 只读运行时）
状态：READONLY_FUSION_PASS / VERSION_PINNED / NO_BUSINESS_WRITE / HTTP_STILL_OFF
时间：2026-08-11（Asia/Shanghai）
运行时接线：新增 `backend/app/catalog/runtime/g4_ports.py`，通过显式注入的 Chroma collection 构造 `Neo4jGraphReader`、`ChromaVectorReader` 和 `HashCharNgramQueryEmbedder`；构造阶段不连接数据库、不查询存储、不导入 Chroma 客户端、不暴露写操作。`build_research_g4_http_app_from_runtime()` 只在 `RECPRO_G4_HTTP_ENABLED=true` 且调用方提供 runtime 时组装 G4 HTTP，默认应用/Compose/Worker 不调用。
固定版本：graph=`lib-books-v1-20260810`；embedding=`hash-char-ngram-v1`；index=`lib-books-vector-v1-20260811`；namespace=`library_resources__hash_char_ngram_v1`；dimension=`384`。版本漂移、embedder 维度不一致或不安全命名空间在构造期拒绝。
只读证据一：`artifacts/verification/g4/g4-readonly-fusion-20260811-010/readonly.json`，请求 `BOOK` + `多智能体+推荐系统+知识图谱`，240 秒有界 deadline，7 个 Agent、8 个候选，通道=`MYSQL+VECTOR`；该主题未命中图谱术语，但 Vector 真实 READY。
只读证据二：`artifacts/verification/g4/g4-readonly-fusion-20260811-011/readonly.json`，请求 `BOOK` + `多智能体 智慧图书馆`，7 个 Agent、8 个候选，通道=`MYSQL+GRAPH+VECTOR`，三依赖均真实 READY。
安全回读：两轮均使用 MySQL `SELECT_ONLY_ROLLBACK`；资源表与 Agent 事实表前后计数一致，Chroma 前后均为 `14,983`，Neo4j/Chroma writes=`0`，external_requests=`0`，files_deleted=`0`，overwritten_inputs=`0`。第一次 90 秒默认验证因资源冷启动触发 deadline 并安全失败，没有生成证据或写入；随后只增加有界只读 deadline，没有放宽写入权限。
测试与门禁：新增 G4 runtime 构造/版本/无连接测试；只读 verifier 默认 deadline=`180s`，Makefile 可通过 `G4_READONLY_FUSION_DEADLINE_SECONDS` 显式调整（30—300s）；架构、安全、文档、契约门禁必须继续通过。
下一步：为上述 runtime 提供独立的 operator-only Chroma collection loader 与 host 入口预演，再单独生成 G4 HTTP/幂等 DRY_RUN ChangePlan；未获得新的精确 plan_id/hash 批准前不提交业务行、不启用 DeepSeek。
```

## G4 operator-only Chroma loader 与 HTTP host 只读预演

```text
交接ID：G4-HTTP-HOST-READONLY-20260811-003
Gate：G4 版本锁定 runtime 的 operator-only collection loader 与 HTTP 组合根预演
状态：HOST_PREFLIGHT_PASS / GET_SELECT_ONLY / COUNTS_UNCHANGED / HTTP_DEFAULT_OFF
时间：2026-08-11（Asia/Shanghai）
新增文件：scripts/g4_operator_runtime.py；scripts/verify_g4_http_host_readonly.py；tests/g4/test_g4_operator_runtime.py。
接线：loader 只打开已有 `library_resources__hash_char_ngram_v1`，校验 graph=`lib-books-v1-20260810`、embedding=`hash-char-ngram-v1`、index=`lib-books-vector-v1-20260811`、namespace、cosine metadata 和 14,983 条记录；不调用 `get_or_create_collection`，不创建目录，不暴露集合写操作。host 预演在内存启用 G4 开关，注入版本锁定 Graph/Vector runtime，调用 `/api/v1/health/live` 与 `/api/v1/health/ready`，未调用业务 POST。
运行结果：live=`200`、ready=`200`、`can_recommend=true`；MySQL 12 张资源/推荐/G4 表前后计数一致；Chroma 前后均=`14,983`；Neo4j recall=`0`（本阶段只验证组合入口，真实 Graph recall 已由 G4-READONLY-FUSION-010/011 覆盖）。
安全边界：MySQL 仅 SELECT/SHOW GRANTS，`mysql_writes=0`；Neo4j writes=`0`；Chroma writes=`0`；external_requests=`0`；external_llm_requests=`0`；business_post_count=`0`；files_deleted=`0`。未删除或覆盖任何文件、数据库、容器、卷或数据。
证据：`artifacts/verification/g4/g4-http-host-readonly-20260811-003/readonly.json`。
测试：新增 operator loader 4 项测试通过；随后需继续通过完整 Python、G0 安全/架构/合同/文档/提示词和 Compose 门禁。
剩余核心工作量：按“真实可用而非模拟”口径仍有 4 个实现/授权 Gate：
1. G4 HTTP 真实业务 POST 的新 ChangePlan、一次隔离追加、GET/幂等/计数回读；
2. 前端使用同一 RecommendationClient 完成一次真实 G4 推荐/澄清浏览器闭环，并接入 feedback/behavior API 的独立受控验证；
3. Worker/Outbox、正式认证和 production 组合根的部署验收，保持默认 fail-closed；
4. DeepSeek 外部调用的脱敏、费用/超时/审计与单次 opt-in 验证，或明确论文演示继续使用 MockLLM。
若只要求本地隔离论文演示，完成第 1、2 Gate 后即可视为核心演示闭环；若要求生产级全部能力，还需第 3、4 Gate，预计还需 4 个阶段（每阶段至少一份独立证据和一次提交）。
下一步唯一动作：基于本次 host 预演证据生成新的 G4 HTTP/幂等 `S1_APPEND/DRY_RUN` ChangePlan；在用户批准精确 plan_id/hash 前不执行业务 POST、不启用 DeepSeek。
```

## G4 HTTP 推荐投影批准追加与独立只读回读

```text
交接ID：G4-HTTP-PROJECTION-RECONCILE-20260811-004
Gate：G4 版本锁定 runtime 的真实推荐投影、HTTP GET 回读与追加边界
状态：APPROVED_APPEND_PASS / READONLY_HTTP_GET_PASS / EXACT_DELTA_PASS / DEFAULT_HTTP_OFF
时间：2026-08-11（Asia/Shanghai）
授权边界：用户明确批准 plan_id=`3591f2e9-33c8-5f77-842b-d6c02cba413b`、plan_hash=`8b26a12776796b5884bbf44efb28743eb7a04b2883fabf262da7a24c140642ce`；执行器只允许对 Compose project=`recpro-g2-tianyuhang-20260809a`、隔离 MySQL `recpro`（本地端口=`62306`）执行一个 `S1_APPEND`，不触碰既有 Neo4j 数据库或其他数据库。
请求与结果：请求 run=`g4-http-projection-plan-20260811-002`，`scene=SEARCH_AFTER`、`resource_types=BOOK`、`output_type=TOPIC_RESOURCES`、`limit=8`；服务返回 `201`、`replayed=false`、状态=`COMPLETED`、context_version=`1`，task=`7f71efa9-1557-5e9d-8d5c-633d1b85bb4f`，record=`23`，trace=`aeecebd3-4758-569f-afda-3059998c5fac`，8 个 item。
精确追加：数据库只追加 `57` 行：task=`+1`、transition=`+8`、candidate=`+13`、record=`+1`、item=`+8`、explanation=`+8`、policy=`+1`、trace=`+1`、Agent message/result=`+7/+7`、artifact=`+1`、orchestration_result=`+1`。资源事实表、用户/画像/反馈/上下文等非目标表均未变化；所有目标表均达到计划下界且没有计数下降。
独立回读：新增脚本 `scripts/verify_g4_recommendation_projection_result.py` 与 Make 目标 `verify-g4-recommendation-projection-result` 不重放业务 POST，仅 SELECT 当前全表计数、读取 request/task/record/各目标行族、在显式 G4 组合根调用 health live/ready 与 `GET /api/v1/recommendation-tasks/{task_id}`，并校验 task/status/trace/record identity。live=`200`、ready=`200`（`can_recommend=true`）、task GET=`200`、状态=`COMPLETED`、context_version=`1`。
数据平面回读：MySQL 当前计数与批准追加证据逐表完全一致；Chroma 前后均=`14,983`，版本 metadata 与 namespace 一致。Neo4j writes=`0`、Chroma writes=`0`、business POST=`0`、external_requests=`0`、external_llm_requests=`0`。
证据：执行证据=`artifacts/verification/g4/g4-http-projection-apply-20260811-002/g4-recommendation-projection-apply.json`；独立回读证据=`artifacts/verification/g4/g4-http-projection-reconcile-20260811-002/reconciliation.json`。
配置边界：执行环境虽配置 `RECPRO_LLM_PROVIDER=deepseek`，本次执行器和回读器均显式 `enable_llm_provider=false`，没有发送 DeepSeek 请求，也没有读取或输出密钥；默认 `backend.app.main:app`、Compose HTTP、Worker 仍保持关闭。
安全边界：本阶段未删除文件、artifact、容器、卷或数据库对象；文件删除数量=`0`、数据库物理删除数量=`0`、UPDATE=`0`、补偿写入=`0`、覆盖输入=`0`。追加是用户批准范围内的一次性事实写入，之后只读回读。
测试与版本：新增回读器后需重新执行全量 Python、G4、架构、安全、文档、契约和前端门禁；本条记录提交后不复用已执行 ChangePlan，任何下一次业务追加必须重新生成并批准新的 plan_id/hash。
剩余核心工作量：按“真实可用而非模拟”口径，G4 初始推荐投影已完成；仍需 3 个 Gate：前端真实推荐/澄清浏览器闭环与 feedback/behavior 受控验证；Worker/Outbox、正式认证和 production 组合根部署验收；DeepSeek 外部调用的脱敏、费用/超时/审计与单次 opt-in 验证（或论文演示明确继续 MockLLM）。本地隔离论文演示还需前端 Gate；生产级验收还需后两 Gate。
下一步唯一动作：先复核并通过代码/文档/安全门禁，再进入前端真实 GET/POST 受控闭环设计；未生成并批准新的前端或续跑 ChangePlan 前不追加新的业务行、不启用 DeepSeek。
```

## G4 前端真实运行入口与浏览器请求冻结记录

```text
交接ID：G4-FRONTEND-RUNTIME-20260812-001
Gate：G4 版本锁定 Graph/Vector HTTP 入口与前端请求身份冻结
状态：CODE_PASS / READONLY_BASELINES_PASS / PLAN_PENDING_APPROVAL / DEFAULT_HTTP_OFF
时间：2026-08-12（Asia/Shanghai）
目标：为真实前端推荐/澄清浏览器闭环提供独立、显式、可审查的 G4 入口；默认 backend.app.main:app、Compose backend、Worker 和 DeepSeek provider 继续 fail-closed。
入口：新增 `backend.app.g4_demo_main:app`。只有 `RECPRO_APP_ENV=demo`、`RECPRO_G4_HTTP_ENABLED=true`、有效隔离 Neo4j 凭据、固定版本 Graph/Vector runtime 和已有 operator-only Chroma collection 全部满足时才构造；始终以 `enable_llm_provider=false` 运行。默认入口与 Compose 配置未切换。
前端：`RecommendationWorkbench.vue` 标识为 G4，默认请求文本=`多智能体系统与智慧图书馆`、limit=`8`；澄清续跑复用同一 session/context/answers，并支持 AbortSignal；可选 `VITE_G4_DEMO_REQUEST_ID`/`VITE_G4_DEMO_SESSION_ID` 将浏览器请求与 ChangePlan 固定身份对齐，未设置时仍使用随机 UUID。RecommendationClient 超时上限提升为 150 秒以覆盖真实只读融合冷启动。
只读证据：G4=`artifacts/verification/g4/g4-frontend-browser-readonly-20260812-001/readonly.json`，状态=`PASS`，7 dispatches、8 candidates、通道=`MYSQL+VECTOR`，候选持久化预期=`13`，MySQL/Chroma 前后计数一致；MySQL=`artifacts/verification/g7/g7-frontend-browser-mysql-readonly-20260812-001/readonly.json`，状态=`PASS`，推荐与资源事实表计数不变，业务 POST=`0`。
计划边界：本 Gate 仅生成新的 `S1_APPEND/DRY_RUN` ChangePlan，固定 `request_run_id`、`request_payload`、idempotency key 与浏览器请求身份；计划生成后向用户报告精确 `plan_id`/`plan_hash`，未获批准前不得点击真实推荐按钮、不得提交任何业务 POST、不得启用 DeepSeek。
安全边界：本 Gate 未执行 INSERT/UPDATE/DELETE/DROP/TRUNCATE、迁移、Neo4j/Chroma 写入或外部请求；未删除文件、artifact、容器、卷、数据库对象或数据库数据。
下一步唯一动作：完成代码/前端/文档/契约/安全门禁并推送后，提交该 DRY_RUN 计划的精确 hash；仅在用户明确批准同一 hash 后，执行一次隔离追加，再做浏览器 POST、GET、幂等和计数回读。
```

## G4 前端真实推荐与幂等浏览器闭环验收记录

```text
交接ID：G4-FRONTEND-BROWSER-CLOSURE-20260812-002
Gate：G4 版本锁定 Graph/Vector 推荐入口、批准追加、HTTP 回读与浏览器幂等重放
状态：APPROVED_APPEND_PASS / READONLY_RECONCILIATION_PASS / BROWSER_REPLAY_PASS / NO_DESTRUCTIVE_ACTION
时间：2026-08-12（Asia/Shanghai）
批准范围：用户批准 plan_id=`419b030a-d0ed-531f-812c-d45843d560e5`、plan_hash=`8a7f4c326500dddb8da30943792baed71f886dbd649aa4c9b3348de287bdf06e`；计划绑定 Git=`215a436125f0da9c318e4831ba8b74f71bc17726`、request_id=`6d558332-5cca-41c1-b1e2-8a707e75a372`、session_id=`ec16eb21-2da6-4047-8138-d4dbbae0e09f`。
真实追加：`g4-frontend-browser-apply-20260812-001` 执行一次 `APPLY_ONE_BOUNDED_APPEND`，隔离 Compose=`recpro-g2-tianyuhang-20260809a`、MySQL=`recpro`、端口=`62306`；服务返回 `201/COMPLETED`，task=`b476b901-b78e-5c3e-afd9-6fc880f20623`、record=`24`、trace=`e9f97880-eb96-5693-b630-0ff5fc0cec42`、8 个 item/context v1。严格追加 57 行：task=`+1`、transition=`+8`、candidate=`+13`、record=`+1`、item=`+8`、explanation=`+8`、policy=`+1`、trace=`+1`、Agent message/result=`+7/+7`、artifact=`+1`、orchestration result=`+1`。
独立回读：`g4-frontend-browser-reconcile-20260812-001` 与浏览器重放后的 `g4-frontend-browser-reconcile-20260812-002` 均为 `PASS`；MySQL 计数与 apply 证据一致，HTTP live/ready/task GET=`200`，task=`COMPLETED/context_version=1`，Chroma=`14,983 -> 14,983`，回读写入=`0`、业务 POST=`0`。资源事实表与非目标表均无变化。
浏览器闭环：首次固定身份重放暴露前端漏传 `requested_output_type`，后端按契约返回 `409 IDEMPOTENCY_KEY_REUSED`，未产生写入；提交 `18d92a4 fix(frontend): preserve G4 request identity on replay` 后，前端发送与批准 payload 完全一致的 `TOPIC_RESOURCES` 请求，服务返回 `200` 幂等重放，页面渲染 8 条真实结果，控制台 error/warning=`0`。该修复只影响浏览器请求契约，不得复用旧计划执行新的追加。
安全边界：批准执行未发生 UPDATE/DELETE/DROP/TRUNCATE/迁移；Neo4j writes=`0`、Chroma writes=`0`、external LLM requests=`0`、files_deleted=`0`、database physical deletions=`0`。配置虽保留 `RECPRO_LLM_PROVIDER=deepseek`，本次入口和执行器均显式禁用外部 LLM。
验证证据：`artifacts/verification/g4/g4-frontend-browser-apply-20260812-001/g4-recommendation-projection-apply.json`；`artifacts/verification/g4/g4-frontend-browser-reconcile-20260812-001/reconciliation.json`；`artifacts/verification/g4/g4-frontend-browser-reconcile-20260812-002/reconciliation.json`。
下一步唯一动作：进入 feedback/behavior 受控 API 验证；Worker/Outbox、正式认证与 production 组合根仍保持独立 Gate，DeepSeek 外部调用仍需单独脱敏、费用、超时、审计和 opt-in 计划。
```

## G5 feedback/behavior opt-in 路由只读审计记录

```text
交接ID：G5-FEEDBACK-HTTP-READONLY-20260812-001
Gate：G5 feedback/behavior HTTP 契约、权限与只读健康边界
状态：READONLY_PASS / ROUTES_PRESENT / COUNTS_UNCHANGED / NO_BUSINESS_POST
时间：2026-08-12（Asia/Shanghai）
目标：在不扩大 G4 批准范围的前提下，核验 feedback/behavior opt-in 组合根可以安全构造，路由存在且默认运行时仍不暴露；不执行迁移、seed、反馈、行为或 Worker 写入。
新增只读验证器：`scripts/verify_g5_feedback_http_readonly.py`；Make 目标=`verify-g5-feedback-http-readonly`。该验证器只构造真实 `build_demo_mysql_http_app(... feedback_api_enabled=True)`，调用 live/ready GET，读取全表计数、runtime probe 和 grants；不会调用 `scripts/verify_g5_http_runtime.py`，因为后者包含迁移、seed、业务 POST 与 Worker 消费。
路由结果：`POST /api/v1/recommendation-impressions/batch`、`POST /api/v1/recommendation-items/{item_id}/feedback`、`POST /api/v1/behavior-events` 均存在且方法集合严格为 POST；健康 live/ready=`200`、`can_recommend=true`。
只读数据证据：G5 表计数为 impression=`6`、feedback=`5`、behavior=`29`、outbox=`23`、user_resource_state=`3`、profile_replay_run=`26`、profile_change_log=`29`、user_profile=`2`、interest=`9`、negative=`6`，全库表计数前后完全一致；runtime user=`recpro_runtime@%`、database=`recpro`、least-privilege grants guard=`PASS`。
验证证据：`artifacts/verification/g5/g5-feedback-http-readonly-20260812-001/readonly.json`；`database_writes=0`、`business_posts=0`、`outbox_claims=0`、`external_requests=0`、`files_deleted=0`、`actual_delete_count=0`。
安全边界：没有执行 INSERT/UPDATE/DELETE/DROP/TRUNCATE、迁移、seed、Neo4j/Chroma 写入或外部 LLM 请求；未删除任何文件、artifact、容器、卷、数据库对象或数据库数据。
下一步唯一动作：为一次受控 impression + feedback + direct behavior + outbox worker 幂等验证单独设计 DRY_RUN/append-only ChangePlan，重新读取基线并等待用户批准；不得把本只读证据当作新的写入授权。
```

## G5 feedback + behavior + Outbox Worker DRY_RUN 计划前置记录

```text
交接ID：G5-FEEDBACK-WORKER-PLAN-PREFLIGHT-20260812-001
Gate：G5 反馈、行为与画像 Outbox Worker 的受控追加计划生成
状态：PLAN_BUILDER_READY / DRY_RUN_PENDING_APPROVAL / NO_DATABASE_WRITE
时间：2026-08-12（Asia/Shanghai）
目标：在既有 G5 只读基线不变的前提下，为一个真实推荐 item 冻结 impression + NOT_INTERESTED/TOPIC_NOT_INTERESTED feedback + CLICK_RECOMMENDATION behavior，并明确两条新 Outbox 由 limit=2 Worker 消费的精确前后计数。
新增文件：`scripts/build_g5_feedback_http_plan.py`；Make 目标=`build-g5-feedback-http-plan`。
修改文件及原版本保存位置：`contracts/safety/change-plan.schema.json` 增加严格 `interaction_payload`（三类事实 UUID、行为 session、固定时间/可见性、Worker 参数）；`Makefile` 增加 G5 计划参数；原版本由 Git 提交历史保留。
只读目标：隔离 MySQL `recpro` 中 task=`b476b901-b78e-5c3e-afd9-6fc880f20623`、record=`24`、item=`128`、resource=`6452`、user=`1001`；图书标题为《智慧图书馆服务模式与阅读推广研究》，resource_type=`BOOK`，资源标签冻结为 `(102,0.8,0.95,IMPORT)` 与 `(8463,0.9,0.9,IMPORT)`，当前无该用户/资源的 HIDDEN 状态。
计划边界：ChangePlan 分类为 `S2_CONTROLLED_UPDATE`、模式为 `DRY_RUN`；预计 `max_changes=26`（impression +1、feedback +1、behavior +3、outbox +2、resource_state +1、replay +2、change_log +3、interest +2、negative +2、state_transition +9；user_profile 行数不变）。计划生成只执行 SELECT/SHOW GRANTS 和本地 artifact 写入，不提交业务 POST、不 claim Worker、不迁移/seed、不写 Neo4j/Chroma、不调用 DeepSeek。
幂等与安全：UUID 按 run_id 的 URL namespace 确定性生成；apply 前必须重读全库计数、任务/记录/item 所有权、资源标签、UUID 空缺、Outbox 无 PENDING/PROCESSING、运行用户 grants；仅允许 G5 明确白名单的状态/画像投影更新，禁止删除、DROP、TRUNCATE、迁移、补偿删除或受保护事实更新。
当前证据：基线 `artifacts/verification/g5/g5-feedback-http-readonly-20260812-001/readonly.json` 为 PASS，G5 计数 impression=`6`、feedback=`5`、behavior=`29`、outbox=`23`、resource_state=`3`、replay=`26`、change_log=`29`、interest=`9`、negative=`6`、profile=`2`，全库 before/after 一致。
下一步唯一动作：代码与门禁提交并推送后生成新的 DRY_RUN 文件，报告精确 `plan_id`/`plan_hash`；只有用户明确批准同一 hash，才可执行一次受控追加和独立只读回读。
```

## G5 feedback + behavior + Outbox Worker 受控追加闭环记录

```text
交接ID：G5-FEEDBACK-WORKER-APPLY-20260812-001
Gate：G5 反馈事实、行为事实、画像 Outbox Worker 与幂等回读
状态：APPROVED_APPEND_PASS / WORKER_PASS / IDEMPOTENCY_PASS / READONLY_RECONCILIATION_PASS
时间：2026-08-12（Asia/Shanghai）
批准范围：用户批准 plan_id=`afec54a6-94e8-580e-b896-0ff02c5a33de`、plan_hash=`77d54f90f913f6723595fae89229e7df25436eeb86aff795cef2370c105da99d`；执行绑定 Git=`f4b241db4b2d05f014f43ceac169dbc81e1ecb50`，隔离 Compose=`recpro-g2-tianyuhang-20260809a`、MySQL=`recpro`。
目标与事实：task=`b476b901-b78e-5c3e-afd9-6fc880f20623`、record=`24`、item=`128`、resource=`6452`、user=`1001`；图书《智慧图书馆服务模式与阅读推广研究》，BOOK；新增 impression UUID=`762b46fa-ccf3-5fe5-96d9-072319e2cb75`、feedback UUID=`11fdc777-a3cd-56cd-b0d3-60072fb3af4c`、behavior UUID=`adedc97f-c97f-59f3-9b46-1c29025c0d0a`。
精确追加：recommendation_impression=`+1`（6→7）、recommendation_feedback=`+1`（5→6）、user_behavior_event=`+3`（29→32）、profile_update_outbox=`+2`（23→25）、user_resource_state=`+1`（3→4）；Worker 后 profile_replay_run=`+2`（26→28）、profile_change_log=`+3`（29→32）、user_interest_tag=`+2`（9→11）、user_negative_preference=`+2`（6→8）、domain_state_transition=`+9`（28→37），user_profile 行数保持 2。
幂等与 Worker：同 UUID 的 impression/feedback/behavior 重放计数不变；Outbox=`29/30` 首轮均 DONE、attempts=`1`，Worker `limit=2` 首轮 receipts=`2`、二次 receipts=`0`，最终状态仅 `DONE=23、DEAD=2`，没有 PENDING/PROCESSING。
受控投影：资源 `6452` 为 user `1001` 创建 HIDDEN，state_version=`1`、source_event_id=`43`；标签 `102/8463` 均写入正向与 TOPIC_NOT_INTERESTED 负向画像投影；当前 user_profile profile_version=`25`。资源、任务、推荐上下文、声明画像、标签字典和其他非目标事实计数均未变化。
执行证据：`artifacts/verification/g5/g5-feedback-worker-apply-20260812-001/g5-feedback-worker-apply.json`；独立只读回读=`artifacts/verification/g5/g5-feedback-worker-reconcile-20260812-001/reconciliation.json`，task/item/资源标签/行为 UUID/Outbox/投影和全库计数均与 apply evidence 一致。
安全边界：数据库写入按计划计数=`26`，Outbox claim=`2`；business_posts=`0`、external_llm_requests=`0`、Neo4j writes=`0`、Chroma writes=`0`、文件删除=`0`、数据库物理删除=`0`。执行期间首次 Worker 连接因本地虚拟环境缺少 `cryptography` 被阻断；首写和幂等重放已完成且未回滚或补偿删除，补齐本地依赖后仅从两条已批准 PENDING Outbox 继续，最终闭环通过。
配置/版本：画像公式=`profile-g2-v1`；Worker=`g5-g5-feedback-worker-plan-20260812-001`；默认业务 API 与 DeepSeek 外部调用仍保持原有 fail-closed 边界。
下一步唯一动作：进入 G5 运行态可复用 executor/部署接线评审；任何新的业务追加必须重新生成并批准新的 plan_id/hash。
```

## G5 Worker 运行态接线与默认安全门禁记录

```text
交接ID：G5-WORKER-WIRING-20260812-001
Gate：G5 Profile Outbox Worker 运行态接线、配置校验与 Compose 默认安全边界
状态：CODE_COMPLETE / STATIC_GATE_PASS / READONLY_RUNTIME_WIRING_PASS
时间：2026-08-12（Asia/Shanghai）
安全边界：本阶段只修改 Worker 入口、配置契约、Compose 环境映射、验证脚本和测试；未连接 MySQL、未 claim Outbox、未执行 INSERT/UPDATE/DELETE/DDL/迁移、未访问 Neo4j/Chroma、未调用 DeepSeek，文件删除数=0、数据库物理删除数=0。
实现内容：`backend.app.worker` 现在先校验配置包，再按 `RECPRO_WORKER_ENABLED` 与 `RECPRO_WORKER_MODE=profile_outbox` 双闸门选择能力；默认 `false/disabled` 仅保持健康等待，不创建连接。显式非 production profile_outbox 模式才构造受控 MySQL 连接和 `ProfileOutboxWorker`，使用可配置 worker_id、batch_limit、lease、max_attempts、poll interval 与 `profile-g2-v1` 公式；连接/轮询失败直接抛出，交由容器重启策略处理，不吞错或降级写入。
配置契约：Compose 与 `.env.*.example` 已加入 Worker 参数；`AppSettings` 与 `validate_runtime_env` 均拒绝“启用但模式不匹配”“禁用但选择 profile_outbox”“production 启用”以及越界/不安全 ID。默认 backend/worker/DeepSeek/业务 HTTP 仍保持原有 fail-closed 边界。
只读证据：`artifacts/verification/g5/g5-worker-wiring-20260812-001/worker-wiring.json`，Compose 标记=5，database_connections=`0`、database_writes=`0`、outbox_claims=`0`、external_requests=`0`、actual_delete_count=`0`、files_deleted=`0`；默认 worker=`enabled:false/mode:disabled`。
测试与版本：新增 Worker 配置/入口测试；本阶段需通过 G1/G5、架构、安全、契约、文档及 Compose 门禁后再提交。任何显式启用 Worker 或新的业务事实追加，仍须另行生成并批准精确 plan_id/hash，不得把本只读接线证据当作写入授权。
下一步唯一动作：完成本提交的全量门禁并推送；随后若要验证运行态消费，先生成新的 Worker 专用 DRY_RUN/ChangePlan，批准后才可在明确范围内运行一次。
```

## G5 Worker 隔离空队列真实运行态只读探针记录

```text
交接ID：G5-WORKER-READONLY-RUNTIME-20260812-002
Gate：G5 Profile Outbox Worker 真实隔离运行态空队列探针
状态：READONLY_RUNTIME_PASS / EMPTY_QUEUE / COUNTS_UNCHANGED
时间：2026-08-12（Asia/Shanghai）
目标：在不追加任何业务事实的前提下，让新 Worker 接线实际走一次 `ProfileOutboxWorker.run_once(limit=1)`，证明空队列时不会产生消费或投影副作用。
安全前置：探针先用运行账号读取完整 40 张表计数和 Outbox 状态，发现 `PENDING/PROCESSING=0` 才继续；第一次尝试使用运行账号执行 `SELECT ... FOR UPDATE` 被 MySQL 最小权限正确拒绝（1142），未产生写入。随后按既有 G5 设计改用单独受控 migration 身份重跑；不修改凭据、不扩大授权、不执行迁移。
真实结果：隔离 Compose=`recpro-g2-tianyuhang-20260809a`、MySQL host port=`62306`；Worker mode=`profile_outbox`、batch_limit=`1`、formula=`profile-g2-v1`；实际 receipts=`0`。前后完整表计数完全一致：`profile_update_outbox=25`、`DONE=23`、`DEAD=2`，无 `PENDING/PROCESSING`；40 张表均未变化。
安全计数：数据库连接=`3`（前置/Worker/后置只读连接）、database_writes=`0`、outbox_claims=`0`、external_requests=`0`、actual_delete_count=`0`、files_deleted=`0`；未访问 Neo4j/Chroma、未调用 DeepSeek。
证据：`artifacts/verification/g5/g5-worker-readonly-runtime-20260812-002/readonly.json`；脚本=`scripts/verify_g5_worker_readonly_runtime.py`，Make=`verify-g5-worker-readonly-runtime`。
下一步唯一动作：若要验证非空 Outbox 的真实受控消费，必须重新生成并批准新的 G5 Worker 专用 ChangePlan；在批准前不得追加行为/反馈事实、不得 claim Outbox、不得启用默认 Worker。
```

## G5 第二个推荐项受控追加与安全失败记录

```text
交接ID：G5-FEEDBACK-WORKER-APPLY-20260812-002
Gate：G5 反馈、行为与画像 Outbox Worker 的第二个真实推荐项受控追加
状态：APPROVED_PLAN_EXECUTED / FINAL_COUNT_GUARD_FAILED / NO_RETRY
时间：2026-08-12（Asia/Shanghai）
批准范围：用户批准 plan_id=`4bb3a297-1f93-58e8-a476-b82b32c50b50`、plan_hash=`fa19aca430597d6b13486ecfd2f5c657d4e3e0348b0c727dd25b5383842611eb`；执行绑定 Git=`df8f072285723f82cbd78093fa29b39e9b8b68e4`，隔离 Compose=`recpro-g2-tianyuhang-20260809a`、MySQL=`recpro`。
目标与事实：task=`b476b901-b78e-5c3e-afd9-6fc880f20623`、record=`24`、item=`129`、resource=`6850`、user=`1001`；图书《智慧图书馆与阅读推广》、BOOK；impression UUID=`be3fba8e-4dfb-59d3-b9ca-3d00b4f883a8`、feedback UUID=`2d7b8dbe-9dda-54e9-b59b-c7743ee8205f`、behavior UUID=`cfb6fb2d-ad62-5e47-b50d-77ad82a2e678`。
执行结果：impression、feedback、direct behavior 均唯一落库；Outbox=`33/34` 首轮均 `DONE`、attempts=`1`；Worker 首轮消费 2 条、二次运行 0 条；资源 `6850` 为 user `1001` 创建 `HIDDEN`，source_event_id=`49`；画像 replay profile_version=`26/27`，change_log=`+3`，state transition=`+9`。
安全失败：执行器最终固定 delta 检查发现 `user_interest_tag` 实际 `+3`、`user_negative_preference` 实际 `+3`，而该旧计划静态预期均为 `+2`，因此返回 `count delta mismatch`；没有重试、没有补偿删除、没有回滚或覆盖，原计划不再可执行。
实际全库 delta：`recommendation_impression/feedback/user_behavior_event/profile_update_outbox/user_resource_state/profile_replay_run/profile_change_log/user_interest_tag/user_negative_preference/domain_state_transition/user_profile`=`+1/+1/+3/+2/+1/+2/+3/+3/+3/+9/0`；所有资源、任务、标签、声明画像、索引和其他非目标表 delta=`0`。
安全计数：本次原执行器没有文件删除、数据库物理删除、Neo4j/Chroma 写入或外部 LLM 请求；后续只允许读取和审计，不得复用本计划。
```

## G5 第二个推荐项只读 reconciliation 与动态预算修复

```text
交接ID：G5-FEEDBACK-WORKER-RECONCILE-20260812-003
Gate：G5 受控追加后独立只读回读与画像 upsert 预算修复
状态：PARTIAL_APPLY_RECONCILED / CODE_GUARD_FIXED / NO_DATABASE_WRITE
时间：2026-08-12（Asia/Shanghai）
只读证据：`artifacts/verification/g5/g5-feedback-worker-reconcile-20260812-003/reconciliation.json`；runtime user=`recpro_runtime@%`、database=`recpro`、grants guard=`PASS`。
回读结果：3 个确定性 interaction UUID 各 1 行；Outbox=`33/34` 均 `DONE`，全局 `DONE=25、DEAD=2` 且无 `PENDING/PROCESSING`；目标 HIDDEN state、2 个 replay、3 个 replay change-log 和 9 个 profile/domain transition 均存在；全库非目标表 delta=`0`。
状态解释：事实链完整，但原计划状态不是 PASS，而是 `PARTIAL_APPLY_RECONCILED`；计划预计画像表各新增 2 行，实际各新增 3 行，原因是资源标签 `(102,6178,6962,7885,8463)` 中 6178/6962/7885 是用户首次出现的正/负画像键，102/8463 已存在，属于确定性 upsert 的真实行数变化。
代码修复：`scripts/build_g5_feedback_http_plan.py` 将用户现有正向 tag_id 与负向 `(tag_id,reason_code)` 集合作为 target snapshot 的一部分，并动态计算画像表新增行数；`scripts/execute_g5_feedback_worker_plan.py` 在任何业务写入前比较 live target snapshot 与计划 delta；新增 `scripts/verify_g5_feedback_worker_reconcile.py` 和 Make 目标 `verify-g5-feedback-worker-reconcile`，只执行 SELECT/SHOW GRANTS。
验证边界：本修复未连接 Neo4j/Chroma、未调用 DeepSeek、未运行迁移/seed、未更新或删除任何数据库数据；测试覆盖画像键差异会改变计划 hash 和 delta。
下一步唯一动作：提交并推送本修复后，进入 G7 feedback/behavior 前端真实只读页面；若需要新的数据库业务追加，必须重新生成并批准新的 plan_id/hash。
```

## G7 feedback/behavior 前端 opt-in 工作台代码切片

```text
交接ID：G7-FRONTEND-INTERACTION-20260812-001
Gate：G7 前端 feedback/behavior 交互端口与默认安全边界
状态：CODE_COMPLETE / CONTRACT_TEST_PASS / BUILD_PASS / NO_NETWORK_WRITE
时间：2026-08-12（Asia/Shanghai）
新增文件：`frontend/src/domain/interaction.ts`、`frontend/src/api/interactionClient.ts`、`frontend/src/api/interactionClient.spec.ts`、`frontend/src/components/InteractionPanel.vue`、`frontend/src/components/InteractionPanel.spec.ts`。
实现内容：交互客户端覆盖 `POST /api/v1/recommendation-impressions/batch`、`POST /api/v1/recommendation-items/{item_id}/feedback`、`POST /api/v1/behavior-events`；严格校验成功/错误响应、超时和幂等键；工作台要求先显式记录 impression，再允许 NOT_INTERESTED feedback 或 CLICK_RECOMMENDATION behavior，并显示资源、事实 UUID 和画像状态。
安全边界：`VITE_G5_INTERACTION_ENABLED` 未设置或不是 `true` 时，按钮不会调用网络；本地演示只改变前端状态，不写 MySQL、Neo4j、Chroma，也不调用 DeepSeek。该环境变量不等价于用户授权或 ChangePlan 批准。
验证结果：前端 8 个测试文件、46 项测试全部 PASS；`RECPRO_BUILD_RUN_ID=g7-interaction-ui-20260812-001 npm --prefix frontend run build` PASS；没有启动真实业务 API、没有发送 POST、没有数据库连接或数据修改。
未解决风险：真实浏览器反馈/行为闭环仍需新的 opt-in 后端运行态、脱敏/伦理/费用审查和独立的业务 ChangePlan；默认 Compose backend 与 Worker 继续关闭。
下一步唯一动作：在不追加数据库事实的前提下补齐浏览器只读/默认关闭验收；如需真实按钮写入，重新生成并批准新的精确 plan_id/hash。
```

## G7 G4+G5 独立后端入口与浏览器默认关闭验收

```text
交接ID：G7-G4-G5-ENTRYPOINT-BROWSER-20260812-002
Gate：G7 前端交互工作台与 G4+G5 opt-in 后端接线
状态：ENTRYPOINT_CODE_COMPLETE / DEFAULT_OFF_BROWSER_PASS / NO_DATABASE_WRITE
时间：2026-08-12（Asia/Shanghai）
新增文件：`backend/app/g4_feedback_demo_main.py`、`tests/g7/test_g4_feedback_demo_entrypoint.py`。
修改文件：`backend/app/config.py` 新增 `g5_interaction_http_enabled`；`compose.yaml`、`.env.compose.example`、`.env.host.example` 与 `scripts/sync_host_env_from_compose.py` 新增默认关闭的 G4/G5 后端开关传递；`backend/Dockerfile` 补齐 `contracts/prompts`；`frontend/README.md`、`docs/api.md` 和本交接记录补充独立入口说明。
运行边界：默认 `backend.app.main:app`、Compose backend、Worker 和 DeepSeek 不变；只有 `RECPRO_APP_ENV=demo`、`RECPRO_G4_HTTP_ENABLED=true`、`RECPRO_G5_INTERACTION_HTTP_ENABLED=true`、`AppSettings` 校验后的同名设置和已核验 Graph/Vector 运行时全部满足时，才会挂载 Recommendation/Feedback/Behavior 三类服务。构造阶段不连接 MySQL、Neo4j 或 Chroma。
浏览器证据：使用追加式构建 `g7-interaction-ui-20260812-001` 的本地预览；页面显示“交互 API 默认关闭”。点击“记录曝光”“不感兴趣”“记录点击”均只显示关闭提示，点击“查看交互演示”只改变前端状态；预览日志仅出现后端健康探针 `GET /api/v1/health/live`、`GET /api/v1/health/ready` 因 8000 未启动而失败，未出现交互 POST。移动视口 390×844：G4/G5 区域可见，document/body 宽度均为 390，无横向溢出。
数据库与外部服务：database_reads=0、database_writes=0、Neo4j writes=0、Chroma writes=0、DeepSeek requests=0、文件删除=0、数据库物理删除=0。
验证命令：`.venv-g1-final-py311/bin/python -m unittest tests.g7.test_g4_feedback_demo_entrypoint`；`make test-g1-python test-g7 contracts-check docs-check architecture-check safety-check compose-config`（全部 PASS）；`npm --prefix frontend test`；`RECPRO_BUILD_RUN_ID=g7-interaction-ui-20260812-002 npm --prefix frontend run build`；`docker build --tag recpro-backend:g7-g4-g5-entrypoint-check-20260812 --file backend/Dockerfile .`（PASS，仅构建镜像，不启动容器）；浏览器本地默认关闭/移动端验收。
未解决风险：真实浏览器写入仍需用户/伦理范围、正式身份和新的精确 `plan_id`/`plan_hash`；G5 Outbox 非空消费仍需单独 ChangePlan；生产 OIDC/JWKS、发布候选和外部 DeepSeek 网络审查未完成。
下一步唯一动作：完成本阶段测试与门禁后，进入 G8 发布候选清单，或在用户批准新的 G5 业务 ChangePlan 后进行一次最小真实浏览器闭环。
```

## G8 发布候选只读/构建前置

```text
交接ID：G8-RELEASE-PREFLIGHT-20260812-001
Gate：G8 可靠性、安全与发布候选前置
状态：PREFLIGHT_PASS / PASS_WITH_BLOCKERS
时间：2026-08-12（Asia/Shanghai）
新增文件：`scripts/verify_g8_release_preflight.py`、`tests/g8/__init__.py`、`tests/g8/test_release_preflight.py`。
修改文件：`Makefile` 增加 `test-g8` 与 `verify-g8-release-preflight`；README、Gate 状态和 Working Set 补充 G8 前置边界。
安全范围：工具只检查源码/模板/镜像元数据，运行静态门禁、G1/G4/G5/G7/G8 测试和新的前端追加式构建；不会启动 API/Worker，不连接 MySQL/Neo4j/Chroma，不 claim Outbox，不调用 DeepSeek，不覆盖已有 artifact 目录。
实际命令：`make PYTHON=.venv-g1-final-py311/bin/python G8_RELEASE_RUN_ID=g8-release-preflight-20260812-001 G8_FRONTEND_RUN_ID=g8-release-ui-20260812-001 G8_BACKEND_IMAGE=recpro-backend:g7-g4-g5-entrypoint-check-20260812 verify-g8-release-preflight`。
实际结果：契约、文档、架构、安全、G1/G4/G5/G7/G8 测试、前端测试/构建、默认安全配置和后端镜像检查共 12 项技术检查全部 PASS；前端产物为 `g8-release-ui-20260812-001`；源码清单 402 个文件，root_sha256=`3733f3963e2a18985517e65b566d40537e71300d4cc5cb1c7e5340edc8c88e2c`。报告必须保留 `PASS_WITH_BLOCKERS`，因为 A01—A25 最终复验、六场景浏览器 E2E、正式 OIDC/JWKS、真实 G5 ChangePlan 和 G9 输入冻结仍未完成。
证据：`artifacts/verification/g8/g8-release-preflight-20260812-001/release-preflight.json`。
删除与数据库边界：文件删除=0，数据库物理删除=0，数据库读取/写入=0，Neo4j/Chroma 写入=0，外部 LLM 请求=0。
下一步唯一动作：执行新 run_id 的前置报告；若命令失败只修复代码并使用新的 run_id 重跑，不覆盖旧证据。
```

## G8 发布候选离线门禁扩展复验

```text
交接ID：G8-RELEASE-PREFLIGHT-20260812-002
Gate：G8 可靠性、安全与发布候选离线门禁扩展
状态：PREFLIGHT_PASS / PASS_WITH_BLOCKERS
时间：2026-08-12（Asia/Shanghai）
实际命令：`make PYTHON=.venv-g1-final-py311/bin/python G8_RELEASE_RUN_ID=g8-release-preflight-20260812-002 G8_FRONTEND_RUN_ID=g8-release-ui-20260812-002 G8_BACKEND_IMAGE=recpro-backend:g7-g4-g5-entrypoint-check-20260812 verify-g8-release-preflight`。
检查结果：20 项全部 PASS：契约、文档、架构、安全脚本；G0 合约/架构/安全测试；G1、G2、G3、G4、G5、G6、G7、G8、G9 测试；Compose config；前端测试与追加式构建；默认 fail-closed 配置；后端镜像用户/命令检查。
产物：`artifacts/verification/g8/g8-release-preflight-20260812-002/release-preflight.json`；前端 `dist/g8-release-ui-20260812-002`；源码清单 402 个文件，root_sha256=`1c4ed1df042989fbacae81c09e1f7949155e7e72320fe516e5c7fa312815b0b5`。
状态解释：报告保持 `PASS_WITH_BLOCKERS`，阻塞项为 A01—A25 最终复验、六场景浏览器 E2E、G5 真实浏览器写入/非空 Worker 的新 ChangePlan、生产 OIDC/JWKS、DeepSeek 外部调用审查和 G9 输入冻结。
安全计数：database_reads=0、database_writes=0、Outbox claim=0、Neo4j reads/writes=0、Chroma reads/writes=0、DeepSeek requests=0、文件删除=0、数据库物理删除=0、旧证据覆盖=0。
下一步唯一动作：在不触碰数据库的前提下补齐 A01—A25/故障矩阵覆盖审计；真实 G5 业务追加仍须新的精确 plan_id/hash 和单独批准。
```

## A01—A25 离线覆盖审计

```text
交接ID：G8-A01-A25-COVERAGE-20260812-003
Gate：G8 可靠性与发布候选 / A01—A25 覆盖盘点
状态：PASS_WITH_BLOCKERS
时间：2026-08-12（Asia/Shanghai）
新增文件：`scripts/verify_g8_acceptance_coverage.py`、`tests/g8/test_acceptance_coverage.py`。
修改文件：`Makefile` 增加 `G8_ACCEPTANCE_COVERAGE_RUN_ID` 与 `verify-g8-acceptance-coverage`；`docs/acceptance_matrix.md`、README 和本交接记录补充审计边界。
实际命令：`make PYTHON=.venv-g1-final-py311/bin/python G8_ACCEPTANCE_COVERAGE_RUN_ID=g8-acceptance-coverage-20260812-003 verify-g8-acceptance-coverage`。
实际结果：A01—A25 共 25 项，测试/源码/工具映射 25/25 有效；离线覆盖评估为直接 9 项、相关 14 项、缺少直接测试 2 项（A12、A24）；25 项最终 G8/G9 复验均保持 `PENDING`，不能把离线盘点当作验收通过。
安全范围：只读 acceptance matrix、测试源码、业务源码和已有 verification artifact；不启动服务、不连接 MySQL/Neo4j/Chroma、不调用 DeepSeek、不 claim Outbox、不执行任何业务写入。
安全计数：database_reads=0、database_writes=0、Neo4j reads/writes=0、Chroma reads/writes=0、external_llm_requests=0、文件删除=0、数据库物理删除=0、旧 artifact 覆盖=0。
证据：`artifacts/verification/g8/g8-acceptance-coverage-20260812-003/acceptance-coverage.json`；运行基线 commit=`f9554e682b5037faa3d316f2c30fdd5b9d828090`，报告生成前工作区 clean；`docs/acceptance_matrix.md` SHA-256=`a1e461ae69c273c8aecc0420965b0448505a5bd696672fad66367ff866abeb5f`。
未解决风险：缺少 A12/A24 直接测试/运行契约；A01—A25 最终运行态复验、浏览器六场景、故障矩阵、生产认证、真实 G5 写入和 G9 正式输入仍未完成。
下一步唯一动作：先补齐四个缺失直接测试并新增独立 run_id；任何真实数据库/Worker/浏览器写入仍须新的精确 ChangePlan、hash 和用户批准。
```

## A12/A24 直接离线契约补齐

```text
交接ID：G8-A12-A24-DIRECT-OFFLINE-20260812-004
Gate：G8 A12 Neo4j 超时降级与 A24 输出类型稳定性
状态：CODE_COMPLETE / TARGETED_TEST_PASS / NO_DATABASE_ACCESS
时间：2026-08-12（Asia/Shanghai）
目标：补齐 A01—A25 离线审计中最后两个缺失直接测试，同时保持端口边界、证据可追溯和零删除约束。
新增文件：`backend/app/recommendation/domain/output_type_stability.py`、`tests/g4/test_output_type_stability.py`。
修改文件：`backend/app/recommendation/agents/real_agents.py`、`backend/app/recommendation/agents/rule_agents.py`、`tests/g6/test_retrieval_fusion.py`、`scripts/verify_g8_acceptance_coverage.py`、README 与本交接记录。
A12 结果：Neo4j 依赖使用最多两次有界重试；超时后依赖状态为 `UNAVAILABLE`，候选 `kg_score=null`，不追加 `:graph:` 证据引用；解释 Agent 仅复用真实证据引用，故障 tool-call 保留 `TIMEOUT/attempts`。
A24 结果：自动输出类型通过纯领域状态机执行最小两轮保持与 `0.05` 滞回区间；连续近阈值序列保持原类型，信号明显离开区间后才切换；`output_type` 显式值返回 `EXPLICIT_OUTPUT_TYPE_OVERRIDE` 并立即覆盖。
测试结果：A12/A24 新增定向测试 4 项 PASS；G4 全套 97 项 PASS；G6 全套 38 项 PASS；不连接 MySQL、Neo4j、Chroma，不调用 DeepSeek。
安全计数：database_reads=0、database_writes=0、neo4j_reads=0、neo4j_writes=0、chroma_reads=0、chroma_writes=0、external_llm_requests=0、files_deleted=0、database_physical_deletes=0、artifacts_overwritten=0。
覆盖审计：映射已更新为 A12/A24 `DIRECT`；`artifacts/verification/g8/g8-acceptance-coverage-20260812-004/acceptance-coverage.json` 已生成，11 项直接、14 项相关、0 项缺失、mapping_stale=0，绑定 commit=`e066b990c3d2baed777b5e98fd18759c428d40af` 且生成前工作区 clean；最终 A01—A25 G8/G9 复验仍为 `PENDING`。
未解决风险：六场景浏览器 E2E、故障矩阵、生产 OIDC/JWKS、真实 G5 非空 Worker/浏览器写入和 G9 正式输入仍未完成；任何数据库写入仍需新的精确 ChangePlan、plan_id/hash 与用户批准。
下一步唯一动作：运行全量 G0—G9 离线门禁、静态门禁和新的 `g8-acceptance-coverage` 报告，然后提交并推送本阶段变更。
```

## A11/A13 可选检索故障矩阵补齐

```text
交接ID：G8-A11-A13-OPTIONAL-OUTAGE-20260812-005
Gate：G8 A11 向量降级与 A13 图谱/向量同时故障
状态：CODE_COMPLETE / FULL_OFFLINE_GATE_PASS / NO_DATABASE_ACCESS
时间：2026-08-12（Asia/Shanghai）
目标：把可选检索通道的单通道与双通道故障行为固化为直接离线验收证据。
修改文件：`tests/g6/test_retrieval_fusion.py`、`scripts/verify_g8_acceptance_coverage.py`、README 与本交接记录。
A11 结果：向量查询超时后最多两次重试，状态为 `UNAVAILABLE`，MySQL 候选保留，所有候选 `semantic_score=null`，不生成 `:vector:` 证据引用。
A13 结果：Neo4j 与 Chroma 同时超时后仍保留 2 个 MySQL 候选；Graph/Vector 独立为 `UNAVAILABLE`，候选仅有 `MYSQL` 通道，`kg_score`/`semantic_score` 均为 `null`，两次故障均记录独立 `TIMEOUT` tool-call。
测试结果：G0 合约 67、架构 28、安全 36、G1 128、G2 14、G3 29、G4 97、G5 27、G6 39、G7 9、G8 5、G9 7 全部 PASS；文档、契约、架构、安全扫描全部 PASS。
覆盖审计：`artifacts/verification/g8/g8-acceptance-coverage-20260812-005/acceptance-coverage.json`=`PASS_WITH_BLOCKERS`；25 项映射有效，13 项直接、12 项相关、0 项缺失，mapping_stale=0，绑定 commit=`cc861d8e613b8846a40cbb850d782a26c6bcc6c8` 且报告生成前工作区 clean。
安全计数：database_reads=0、database_writes=0、neo4j_reads=0、neo4j_writes=0、chroma_reads=0、chroma_writes=0、external_llm_requests=0、files_deleted=0、database_physical_deletes=0、artifacts_overwritten=0。
未解决风险：A01—A25 最终运行态复验仍有 25 项待完成；A15、A18、A19 等仍是相关覆盖；六场景浏览器 E2E、生产认证、真实 Worker/浏览器写入和 G9 正式输入仍未完成。
下一步唯一动作：设计剩余离线缺口与最终运行复验的只读/隔离 ChangePlan；在新的精确 plan_id/hash 获得批准前不执行任何业务写入。
```

## A15/A18 分数安全与阅读路径降级补齐

```text
交接ID：G8-A15-A18-SCORE-PATH-20260812-006
Gate：G8 A15 缺失特征分数安全与 A18 单难度阅读路径降级
状态：CODE_COMPLETE / FULL_OFFLINE_GATE_PASS / NO_DATABASE_ACCESS
时间：2026-08-12（Asia/Shanghai）
目标：补齐可选特征缺失和单难度阅读路径的直接离线证据，保持推荐输出有界、可解释、低耦合且不伪造用户未提供的学习阶段。
修改文件：`backend/app/recommendation/agents/rule_agents.py`；`tests/g3/test_recommendation_service.py`；`tests/g4/test_orchestrator.py`；`scripts/verify_g8_acceptance_coverage.py`；README 与本交接记录。
A15 结果：新增参数化离线矩阵，分别覆盖空标签、空画像、空行为、负画像值和空目录；每条输出的 `rrf_score`、`final_score`、`negative_penalty`、`evidence_confidence` 及各检索通道分数均断言为有限值且位于 `[0,1]`，并保留证据引用。
A18 结果：显式 `READING_PATH` 且仅覆盖一个难度层时返回 `DEGRADED`，发出 `READING_PATH_SINGLE_DIFFICULTY` 原因码和策略警告；不添加图谱/向量不可用噪声，不伪造其他阅读阶段，仍保留可交付结果。
测试结果：G0 合约 67、架构 28、安全 36、G1 128、G2 14、G3 30、G4 98、G5 27、G6 39、G7 9、G8 5、G9 7 全部 PASS；文档 18 个 Markdown/42 个结构化块、契约 24 个文档、架构扫描 121 个文件、静态安全扫描 342 个文件全部 PASS。
覆盖审计：`artifacts/verification/g8/g8-acceptance-coverage-20260812-006/acceptance-coverage.json`=`PASS_WITH_BLOCKERS`；A01—A25 共 25 项映射有效，15 项直接、10 项相关、0 项缺失、mapping_stale=0，25 项最终运行态复验仍为 `PENDING`；绑定 commit=`5cd6aa48be419fc9602cf00256cdce808013c646` 且报告生成前工作区 clean。
安全计数：database_reads=0、database_writes=0、neo4j_reads=0、neo4j_writes=0、chroma_reads=0、chroma_writes=0、external_llm_requests=0、files_deleted=0、database_physical_deletes=0、artifacts_overwritten=0。
未解决风险：A19/A23/A25 及其余最终运行态证据、六场景浏览器 E2E、生产 OIDC/JWKS、真实非空 Worker/浏览器写入、DeepSeek 外部调用审查和 G9 正式输入仍未完成。
下一步唯一动作：继续补齐剩余直接离线故障/证据映射并设计最终只读运行态复验；任何真实数据库、Worker 或浏览器业务写入仍须新的精确 ChangePlan、plan_id/hash 和用户批准。
```

## A19/A23/A25 证据安全、反馈画像与历史重放补齐

```text
交接ID：G8-A19-A23-A25-EVIDENCE-FEEDBACK-REPLAY-20260812-007
Gate：G8 A19 证据越权回退、A23 反馈画像版本与 change log、A25 evaluation_at 历史重放边界
状态：CODE_COMPLETE / FULL_OFFLINE_GATE_PASS / NO_DATABASE_ACCESS
时间：2026-08-12（Asia/Shanghai）
目标：补齐三项剩余直接离线缺口，形成可复现、低耦合且不依赖真实存储的安全证据。
新增文件：`backend/app/evaluation/__init__.py`；`backend/app/evaluation/domain/__init__.py`；`backend/app/evaluation/domain/historical_replay.py`；`tests/g5/test_feedback_profile_version_change_log.py`；`tests/g6/test_evidence_bounded_explanation.py`；`tests/g9/test_historical_replay_boundary.py`。
修改文件：`backend/app/recommendation/agents/llm_agents.py`；`backend/app/recommendation/application/orchestration.py`；`scripts/verify_g8_acceptance_coverage.py`。
A19 结果：新增可选 `LLMExplanationAgent`；仅接受输入 Evidence Bundle 中的引用，文本、引用标记和引用集合逐项校验。越权引用、空输出、超长输出或 Provider 异常均返回有界模板解释，并记录 `LLM_EXPLANATION_FALLBACK` 与 `EVIDENCE_VALIDATION_FAILED`，不把模型事实写入业务结果。
A23 结果：离线内存夹具串联曝光、反馈、行为 Outbox、Worker claim/apply/mark-done，断言画像版本由 0 增长到 1、Outbox 进入 `DONE`，并追加一条 `profile_change_log`；服务事务边界和 Worker 事务边界均保持显式。
A25 结果：新增 storage-independent historical replay selector，按 `evaluation_at` 同时过滤资源 `available_from`、行为 `occurred_at`、资源状态 `effective_at` 与热度 `cutoff_at`，对冻结集合生成稳定 content hash；添加未来四类事实不会改变快照或哈希，输入重排也不改变哈希。
测试结果：G0 合约 67、架构 28、安全 36、G1 128、G2 14、G3 30、G4 98、G5 28、G6 40、G7 9、G8 5、G9 9 全部 PASS；文档 18 个 Markdown/42 个结构化块、契约 24 个文档、架构扫描 124 个文件、静态安全扫描 348 个文件全部 PASS。
覆盖审计：`artifacts/verification/g8/g8-acceptance-coverage-20260812-007/acceptance-coverage.json`=`PASS_WITH_BLOCKERS`；A01—A25 共 25 项映射有效，18 项直接、7 项相关、0 项缺失、mapping_stale=0，25 项最终运行态复验仍为 `PENDING`；绑定 commit=`eea67d88beb8eff58b47e5696e33aa72e2ea8e5c` 且报告生成前工作区 clean。
安全计数：database_reads=0、database_writes=0、neo4j_reads=0、neo4j_writes=0、chroma_reads=0、chroma_writes=0、external_llm_requests=0、files_deleted=0、database_physical_deletes=0、artifacts_overwritten=0。
未解决风险：离线相关项仍为 A01/A02/A03/A08/A09/A10/A16；A01—A25 最终运行态复验、六场景浏览器 E2E、生产 OIDC/JWKS、真实非空 Worker/浏览器写入、DeepSeek 外部调用审查和 G9 正式输入仍未完成。
下一步唯一动作：继续为上述七项设计直接离线测试和最终只读运行态复验；任何真实数据库、Worker 或浏览器业务写入仍须新的精确 ChangePlan、plan_id/hash 和用户批准。
```

## A01/A02/A03/A08/A09/A10/A16 幂等、曝光、反事实与指纹补齐

```text
交接ID：G8-A01-A02-A03-A08-A09-A10-A16-DIRECT-20260812-008
Gate：G8 A01—A25 离线直接覆盖收口
状态：CODE_COMPLETE / FULL_OFFLINE_GATE_PASS / NO_DATABASE_ACCESS
时间：2026-08-12（Asia/Shanghai）
目标：将最后七项相关离线映射提升为可独立复现的 DIRECT 证据，同时保持领域逻辑纯函数化、适配器边界清晰和零删除约束。
新增文件：`backend/app/recommendation/domain/fingerprint.py`、`tests/g5/test_exposure_boundaries.py`。
修改文件：`backend/app/feedback/domain/models.py`、`backend/app/feedback/domain/public.py`、`backend/app/feedback/adapters/mysql.py`、`tests/g2/test_profile_replay.py`、`tests/g3/test_recommendation_api.py`、`tests/g3/test_recommendation_service.py`、`tests/g5/test_feedback_api.py`、`scripts/verify_g8_acceptance_coverage.py`。
A01 结果：画像快照在相同 `as_of` 下对事件输入重排保持 `input_hash`、事件数和快照内容稳定，新增独立测试 `test_profile_snapshot_content_hash_is_replay_stable`。
A02 结果：相同 `request_id` 的推荐任务重放返回同一任务身份、首写 201/重放 200，内存持久化边界的推荐记录数保持为 1。
A03 结果：相同直接行为 `event_uuid` 重放返回 `Idempotency-Replayed=true`，行为事实边界只保留 1 条事实。
A08 结果：固定候选集在加入 `TOPIC_NOT_INTERESTED` 负画像信号后，目标资源得到正惩罚且 `final_score` 严格低于基线。
A09/A10 结果：纯领域 `is_valid_exposure` 固化闭区间 `visible_ms>=1000`、`max_visible_ratio>=0.5`，边界 `999/0.49` 失败、`1000/0.5` 通过；MySQL 适配器复用该函数，避免阈值漂移。
A16 结果：新增纯领域 `execution_fingerprint`，将 `config_bundle_version`、`dataset_version`、`seed`、`evaluation_at`、意图、排序分数、负反馈、证据和警告纳入规范化 SHA-256；等价输入重排产生相同指纹，拒绝空版本和非有限分数。
实际命令：`make PYTHON=.venv-g1-final-py311/bin/python test-g0 test-g1-python test-g2 test-g3 test-g4 test-g5 test-g6 test-g7 test-g8 test-g9 docs-check contracts-check architecture-check safety-check`；`make PYTHON=.venv-g1-final-py311/bin/python G8_ACCEPTANCE_COVERAGE_RUN_ID=g8-acceptance-coverage-20260812-008 verify-g8-acceptance-coverage`。
测试结果：G0 合约 67、架构 28、安全 36、G1 128、G2 15、G3 33、G4 98、G5 30、G6 40、G7 9、G8 5、G9 9 全部 PASS；文档 18 个 Markdown/42 个结构化块、契约 24 个文档、架构扫描 125 个文件、静态安全扫描 350 个文件全部 PASS；`git diff --check` PASS。
覆盖审计：`artifacts/verification/g8/g8-acceptance-coverage-20260812-008/acceptance-coverage.json`=`PASS_WITH_BLOCKERS`；A01—A25 共 25 项映射有效，25 项 DIRECT、0 项 RELATED、0 项缺失、mapping_stale=0；25 项 `final_revalidation` 仍为 `PENDING`；报告绑定 commit=`78bfc451300a3e24347323d3d1fb296826ef16ff`，报告生成前工作区 clean。
安全计数：`database_reads=0`、`database_writes=0`、`neo4j_reads=0`、`neo4j_writes=0`、`chroma_reads=0`、`chroma_writes=0`、`external_llm_requests=0`、`files_deleted=0`、`database_physical_deletes=0`、`artifacts_overwritten=0`、`Outbox claim=0`。
未解决风险：A01—A25 最终运行态复验仍未执行；六场景浏览器 E2E、生产 OIDC/JWKS、故障矩阵、真实非空 Worker/浏览器写入、DeepSeek 外部调用审查、G9 正式输入与发布凭据仍未完成。上述新增 A02/A03 直接证据使用内存 fake 持久化边界，不等同于真实 MySQL 运行态验收。
下一步唯一动作：在新的独立 ChangePlan/plan_id/hash 获得批准后，先执行只读运行态基线，再逐项完成 A01—A25 final runtime revalidation；未获批准前不执行真实业务 POST、非空 Outbox claim、Neo4j/Chroma 写入或 DeepSeek 外部请求。
```

## G8 最终复验只读计划冻结

```text
交接ID：G8-FINAL-REVALIDATION-PLAN-20260812-002
Gate：G8 A01—A25 最终运行态复验范围冻结
状态：PLAN_READY_WITH_BLOCKERS / NO_DATABASE_ACCESS
时间：2026-08-12（Asia/Shanghai）
目标：把离线覆盖与最终运行态验收明确分离，冻结 25 项 A01—A25 的运行证据要求和六个浏览器演示边界，为后续逐项复验提供不可覆盖的版本基线。
新增文件：`contracts/verification/g8-final-revalidation-plan.schema.json`、`scripts/build_g8_final_revalidation_plan.py`、`tests/g8/test_final_revalidation_plan.py`。
修改文件：`Makefile` 新增 `G8_FINAL_REVALIDATION_PLAN_RUN_ID` 与 `build-g8-final-revalidation-plan`；`scripts/validate_contracts.py` 将新契约列入 G0 必备文档；README、Gate 状态和 Working Set 更新计划边界。
计划产物：`artifacts/verification/g8/g8-final-revalidation-plan-20260812-002/final-revalidation-plan.json`；状态=`PLAN_READY_WITH_BLOCKERS`；绑定 commit=`dc178c15bbc5bcf56745aa1448c469ffff975462`；`plan_hash=c9ba9d61e264accc34605fe7a5dea22a982b8dfaa998040b5ec2565a57666ca2`；acceptance matrix SHA-256=`2098f0cb465ca96605d68a327e12b0ba4142f6eb625816f1e1a35fdc37ffb9a5`。
范围冻结：A01—A25 每项要求运行结果、artifact schema/SHA-256、环境/配置指纹和安全/前后计数；浏览器场景固定为 `demo_cold`、`demo_clear`、`demo_topic`、`demo_path`、`demo_negative`、`demo_degraded`，全部标记 `PENDING`。
安全边界：计划模式为 `READ_ONLY`，`database_writes=0`、`neo4j_writes=0`、`chroma_writes=0`、`outbox_claims=0`、`external_llm_requests=0`、`file_deletions=0`、`database_physical_deletions=0`、`artifact_overwrites=0`、`business_post_authorization=false`。六个浏览器业务场景均标记 `REQUIRES_SEPARATE_CHANGE_PLAN`；本计划不授权任何业务 POST、非空 Worker claim、索引写入或 DeepSeek 调用。
验证命令：`make PYTHON=.venv-g1-final-py311/bin/python test-g0 test-g1-python test-g2 test-g3 test-g4 test-g5 test-g6 test-g7 test-g8 test-g9 docs-check contracts-check architecture-check safety-check`；`make PYTHON=.venv-g1-final-py311/bin/python G8_FINAL_REVALIDATION_PLAN_RUN_ID=g8-final-revalidation-plan-20260812-002 build-g8-final-revalidation-plan`。
测试结果：G0 合约 67、架构 28、安全 36、G1 128、G2 15、G3 33、G4 98、G5 30、G6 40、G7 9、G8 8、G9 9 全部 PASS；文档 18 个 Markdown/42 个结构化块、契约 25 个文档、架构扫描 125 个文件、静态安全扫描 352 个文件全部 PASS；`git diff --check` PASS。
未解决风险：该计划只冻结范围，尚未产生 A01—A25 final runtime PASS；六场景浏览器 E2E、完整故障矩阵、生产 OIDC/JWKS、G9 正式输入、外部 DeepSeek 评审和发布凭据仍未完成。
下一步唯一动作：先依据本计划执行不产生业务写入的运行态健康/故障证据；如需推荐 POST、反馈/行为提交、澄清续跑或非空 Worker，必须另行生成新的精确 ChangePlan、plan_id/hash 并等待用户批准。
```

## G8 最终复验就绪审计

```text
交接ID：G8-FINAL-REVALIDATION-AUDIT-20260812-001
Gate：G8 A01—A25 最终运行态复验就绪审计
状态：READY_FOR_RUNTIME / NO_DATABASE_ACCESS
时间：2026-08-12（Asia/Shanghai）
目标：验证最终复验计划的结构、哈希、引用和证据边界，识别可先执行的只读项与必须单独授权的追加项；不把历史 artifact 当作 final 通过。
新增文件：`scripts/verify_g8_final_revalidation_plan.py`、`contracts/verification/g8-final-revalidation-audit.schema.json`、`contracts/verification/g8-final-runtime-evidence.schema.json`、`tests/g8/test_final_revalidation_audit.py`。
修改文件：`Makefile` 新增 `verify-g8-final-revalidation-plan`；计划 Schema/生成器新增每个案例的 `execution_mode`、`authorization`、`blocking_reason`；`scripts/validate_contracts.py` 将两份证据契约列入 G0 必备文档；README、Gate 状态和 Working Set 更新。
实际命令：`make PYTHON=.venv-g1-final-py311/bin/python test-g0 test-g1-python test-g2 test-g3 test-g4 test-g5 test-g6 test-g7 test-g8 test-g9 docs-check contracts-check architecture-check safety-check`；`make PYTHON=.venv-g1-final-py311/bin/python G8_FINAL_REVALIDATION_PLAN_RUN_ID=g8-final-revalidation-plan-20260812-003 build-g8-final-revalidation-plan`；`make PYTHON=.venv-g1-final-py311/bin/python G8_FINAL_REVALIDATION_AUDIT_RUN_ID=g8-final-revalidation-audit-20260812-001 G8_FINAL_REVALIDATION_PLAN=artifacts/verification/g8/g8-final-revalidation-plan-20260812-003/final-revalidation-plan.json verify-g8-final-revalidation-plan`。
计划绑定：plan=`g8-final-revalidation-plan-20260812-003`，commit=`ccdf71f981a223db26cc54ca561480cf1f3ecf01`，plan_hash=`00a21f9f9c58737186fa4949e1a13c2318a37d9a82ed17b77d5ce9ff6fedba87`；acceptance matrix SHA-256=`2098f0cb465ca96605d68a327e12b0ba4142f6eb625816f1e1a35fdc37ffb9a5`。
实际结果：`artifacts/verification/g8/g8-final-revalidation-audit-20260812-001/final-revalidation-audit.json`=`READY_FOR_RUNTIME`；计划有效 25/25，`read_only_ready=17`，`requires_change_plan=8`（A02/A03/A04/A07/A08/A09/A10/A23），`historical_artifact_cases=25` 但 `final_pass=0`、`final_pending=25`；当前计划 Git 与审计 checkout 匹配。
安全计数：`database_reads=0`、`database_writes=0`、`neo4j_reads=0`、`neo4j_writes=0`、`chroma_reads=0`、`chroma_writes=0`、`outbox_claims=0`、`external_llm_requests=0`、`files_deleted=0`、`database_physical_deletions=0`、`artifact_overwrites=0`。
未解决风险：该审计只证明“可以开始准备运行态证据”，不证明任何 A01—A25 final 通过；真实数据库读证据、故障运行证据、六场景浏览器 E2E、生产 OIDC/JWKS、G9 正式输入及外部 DeepSeek 审查仍未完成。
下一步唯一动作：先按 17 项 `READ_ONLY_RUNTIME` 逐项设计/执行只读或故障验证；A02/A03/A04/A07/A08/A09/A10/A23 与任何浏览器业务 POST、非空 Worker claim、索引写入或 DeepSeek 请求必须另行生成精确 ChangePlan 并等待用户批准。
```

## G8 首批只读运行态复验

```text
交接ID：G8-READONLY-RUNTIME-20260812-001
Gate：G8 A01—A25 最终复验的首批只读运行态证据
状态：PASS_WITH_BLOCKERS / NO_BUSINESS_WRITES
时间：2026-08-12（Asia/Shanghai）
目标：在当前提交上验证隔离服务健康、G4 编排/融合/澄清、G6 三通道检索和 G7 health-only HTTP；不执行业务 POST、非空 Worker claim、索引写入或外部 LLM 请求。
新增数据库对象和行数：0；受控UPDATE对象和审计ID：0；文件删除数量：0；数据库物理删除数量：0。
执行命令：
  `PYTHONDONTWRITEBYTECODE=1 .venv-g1-final-py311/bin/python -m scripts.verify_data_plane_runtime --run-id data-plane-20260812-004 --env-file .env.compose --docker-bin /Applications/编程/Docker.app/Contents/Resources/bin/docker`
  `make PYTHON=.venv-g1-final-py311/bin/python G4_RUN_ID=g4-orchestrator-20260812-006 verify-g4-orchestrator`
  `make PYTHON=.venv-g1-final-py311/bin/python G4_READONLY_FUSION_RUN_ID=g4-readonly-fusion-20260812-012 G4_READONLY_FUSION_DEADLINE_SECONDS=180 verify-g4-readonly-fusion`
  `make PYTHON=.venv-g1-final-py311/bin/python G4_CLARIFICATION_READONLY_RUN_ID=g4-clarification-readonly-20260812-004 verify-g4-clarification-readonly`
  `make PYTHON=.venv-g1-final-py311/bin/python G6_READONLY_RUN_ID=g6-retrieval-fusion-readonly-20260812-012 verify-g6-readonly-fusion`
  `make PYTHON=.venv-g1-final-py311/bin/python G7_MYSQL_READONLY_RUN_ID=g7-mysql-http-readonly-20260812-006 verify-g7-mysql-http-readonly`
测试结果：数据平面 backend/frontend/mysql/neo4j 均 healthy，MySQL=40 张表、隔离 Compose Neo4j=0/0；G4 纯编排四分支 PASS；真实 G4 7 个 Agent 返回 8 条 `MYSQL+GRAPH+VECTOR` 候选且 MySQL/Chroma 计数不变；HOME 空请求为 `WAITING_CLARIFICATION`，4 个 Agent 和 19 张相关表前后计数一致；G6 返回 8 条三通道候选，Chroma=14,983 且 MySQL/Neo4j/Chroma 均只读；G7 live/ready health-only PASS、13 张相关表计数不变、业务 POST=0、数据库写入=0，但 readiness=`DEGRADED`，不视为生产就绪。
验证证据目录：`artifacts/verification/data-plane/data-plane-20260812-004/runtime.json`；`artifacts/verification/g4/g4-orchestrator-20260812-006/orchestrator.json`；`artifacts/verification/g4/g4-readonly-fusion-20260812-012/readonly.json`；`artifacts/verification/g4/g4-clarification-readonly-20260812-004/clarification-readonly.json`；`artifacts/verification/g6/g6-retrieval-fusion-readonly-20260812-012/readonly.json`；`artifacts/verification/g7/g7-mysql-http-readonly-20260812-006/readonly.json`。
安全计数：所有报告的 database/Neo4j/Chroma writes=0、Outbox claim=0、external requests=0、files_deleted=0、database physical deletions=0、artifact overwrite=0；MySQL 读取仅 SELECT/rollback，容器未启动或停止。
未解决风险：这些证据尚未组成 `g8-final-runtime-evidence-v1`，不会把历史或部分运行证据提升为 A01—A25 final PASS；A02/A03/A04/A07/A08/A09/A10/A23、六个浏览器业务场景、非空 Worker 和 DeepSeek 仍需独立 ChangePlan/审批。
下一步唯一动作：继续补齐剩余只读/故障案例，并生成新的追加式 G8 审计；任何写入前先报告精确目标、影响和回读方案，未经批准不写入。
```

## G8 最终复验审计（当前提交绑定）

```text
交接ID：G8-FINAL-REVALIDATION-AUDIT-20260812-002
Gate：G8 A01—A25 最终复验计划的当前提交一致性审计
状态：READY_FOR_RUNTIME / NO_DATABASE_ACCESS
时间：2026-08-12（Asia/Shanghai）
目标：将最终复验计划重新绑定到文档交接提交 `a490652664306d4fe89bcbc9a16a608e02f6ff5b`，复核计划引用、Git 一致性、历史 artifact 清单和授权边界；不连接数据库或服务，不把首批部分运行证据提升为 final PASS。
计划：`artifacts/verification/g8/g8-final-revalidation-plan-20260812-004/final-revalidation-plan.json`，`plan_hash=0cac04a818e9ff61ae2df7c3a6e4f90a414462ff7f755aa9d7171cfd528d9dfb`。
实际命令：`make PYTHON=.venv-g1-final-py311/bin/python G8_FINAL_REVALIDATION_PLAN_RUN_ID=g8-final-revalidation-plan-20260812-004 build-g8-final-revalidation-plan`；`make PYTHON=.venv-g1-final-py311/bin/python G8_FINAL_REVALIDATION_AUDIT_RUN_ID=g8-final-revalidation-audit-20260812-002 G8_FINAL_REVALIDATION_PLAN=artifacts/verification/g8/g8-final-revalidation-plan-20260812-004/final-revalidation-plan.json verify-g8-final-revalidation-plan`。
实际结果：`artifacts/verification/g8/g8-final-revalidation-audit-20260812-002/final-revalidation-audit.json`=`READY_FOR_RUNTIME`；计划有效 25/25，Git 匹配当前提交，17 项只读路径、8 项需独立 ChangePlan，历史 artifact cases=25，final_pass=0、final_pending=25；六个浏览器业务场景均为 `BLOCKED_NO_CHANGE_PLAN`。
安全计数：database_reads=0、database_writes=0、neo4j_reads=0、neo4j_writes=0、chroma_reads=0、chroma_writes=0、outbox_claims=0、external_llm_requests=0、files_deleted=0、database_physical_deletions=0、artifact_overwrites=0。
未解决风险：A01—A25 尚未形成完整 `g8-final-runtime-evidence-v1`；A02/A03/A04/A07/A08/A09/A10/A23、浏览器业务流、非空 Worker、索引写入、生产 OIDC/JWKS、G9 输入冻结和 DeepSeek 外部调用评审仍未完成。
下一步唯一动作：继续补齐只读/故障案例；任何追加写入前先提交精确 ChangePlan、影响范围、回读和回滚边界，等待用户明确批准。
```

## 阶段交接模板

每个Gate结束时追加一条记录，不覆盖旧记录：

```text
交接ID：
Gate：
状态：
时间：
目标：
新增文件：
修改文件及原版本保存位置：
新增数据库对象和行数：
受控UPDATE对象和审计ID：
文件删除数量：0，或删除批准编号
数据库物理删除数量：0，或删除批准编号
执行命令：
测试结果：
验证证据目录：
配置/数据/索引版本：
未解决风险：
下一步唯一动作：
```

---

## 状态刷新规则

在以下时点更新Task Spine和Working Set：

1. 用户改变范围、技术路线或安全约束。
2. 一个Gate开始、完成或被阻断。
3. 测试失败揭示新的系统性风险。
4. 数据源、配置、API或Agent契约被冻结。
5. 准备暂停工作或交接给下一执行者。

只在事实发生变化时更新Task Spine。原始命令输出、冗长日志和已解决的探索过程保存在验证artifact中，不复制到长期主干。

---

## Dropped Context

- 已被最新版实施文档替代的早期方案细节不进入活动上下文。
- 已完成的审查过程和长日志不进入活动上下文，可从文件与验证证据恢复。
- 尚未形成决定的技术选型只保留为open issue，不记录为既定事实。
