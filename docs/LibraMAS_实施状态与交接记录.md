# LibraMAS 实施状态与交接记录

> 状态版本：4.0
> 更新时间：2026-08-11
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
- `open_issues`：
  - G1 已关闭，但推荐链路仍按设计保持 `can_recommend=false`；必须完成 G2/G3 后才能声称推荐系统可用。
  - 演示数据和论文评价数据来源、许可证仍需在G2前确认并形成版本化清单。
  - 人工标注与伦理流程需要在正式用户实验前完成。
  - `gh` 已安装但尚未登录 GitHub；Git HTTPS 凭据已成功推送 `codex/g1-runnable-skeleton`，Draft PR 仍需 `gh` 认证或在 GitHub 网页创建。
  - G3 前端集成、正式环境 Token 验证器的外部部署配置和默认 Compose API 仍未启用；默认运行配置仍保持 `can_recommend=false`，不能宣称系统已对外提供推荐服务。
  - Docker CLI 的 `/usr/local/bin/docker` 是失效链接；实际 Docker Desktop 位于 `/Applications/编程/Docker.app`，本次已用绝对路径完成隔离 MySQL 验证，未删除容器、卷或数据。
  - G4 真实端口仍读取当前 Profile 投影，尚未提供历史画像重算；超时后的跨 Agent 持久化恢复、正式 HTTP 组合根和正式 Token 部署参数仍待后续 Gate。
  - 持久化 service 的数据库重启恢复读取和 HTTP/API 正式接入仍未实现；Worker 级重试、DEAD 和 MySQL 重启后的 Outbox 恢复已在 G5 隔离运行态验证；当前组合根仅在明确调用时创建连接，默认 API 继续关闭。
  - G5 当前仍未接入默认 HTTP；本轮完成的是带显式门禁的 production HTTP 组合根和可替换 HS256 身份适配器，外部 OIDC/JWKS、默认 Compose API、正式 Worker 运行接线和发布凭据流程仍需 Gate 评审；状态迁移审计与历史画像重算已完成隔离运行态验证。
  - MySQL 已有隔离历史事实；本轮经用户授权后已将书目 ChangePlan 追加写入同一隔离 Compose 项目并完成幂等复验。Neo4j 图构建、实际导入和只读图召回端口均已完成；确定性向量与 Chroma collection 已完成版本化导入和独立只读核验，但图/向量召回尚未接入默认 HTTP/Worker。
  - Neo4j Community 版本只显示 `neo4j` 与 `system` 两个数据库，不能在同一实例中安全提供独立命名库；RecPro 的隔离边界是独立 Compose 实例、容器和数据卷。已有 Homebrew Neo4j 的 `neo4j` 库视为受保护外部数据源，禁止复用。
  - Neo4j Community 版本只显示 `neo4j` 与 `system` 两个数据库，不能在同一实例中安全提供独立命名库；RecPro 的隔离边界是新的 `recpro-library-neo4j-20260810a` Compose 实例、容器和数据卷。已有 Homebrew Neo4j 的 `neo4j` 库视为受保护外部数据源，禁止复用。
  - Chroma 正式运行态位于本地忽略路径 `data/chroma`，仅包含计划 collection `library_resources__hash_char_ngram_v1`；此前 API 签名探查留下的空 collection `probe_signature_20260811` 位于独立路径 `data/chroma-probe-g6-20260811`，0 条向量，未删除、未合并、未纳入正式索引。
  - DeepSeek 密钥已在本机配置，但没有启用默认 HTTP/Worker，也没有发起真实外部 LLM 请求；MockLLM/规则路径仍是安全默认。外部 Provider、密钥、模型和 Base URL 必须在组合根通过被 `.gitignore` 保护的本地环境配置注入，不能写入 Git、Manifest、日志或 Agent 消息。Prompt Bundle 已有本地 SHA-256 绑定，真实请求仍需单独的数据脱敏、伦理、费用和调用范围评审。
- `next_step`：进入 G6 的只读检索接线评审：把 Neo4j/Chroma 作为可选端口接入 Agent 组合根，保持默认 HTTP/Worker 关闭，并先以 fake/隔离运行态验证版本过滤、超时降级和解释证据；MySQL `embedding_status` 的 READY 投影以及真实 DeepSeek 请求仍需单独评审。

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
| G5 曝光反馈画像闭环 | IN_PROGRESS | `artifacts/verification/g5/g5-feedback-20260809-001/g5-runtime.json`；`artifacts/verification/g5/g5-http-20260810-005/http-runtime.json`；`artifacts/verification/g5/g5-worker-recovery-20260810-002/runtime.json`；`artifacts/verification/g5/g5-audit-replay-20260810-001/runtime.json`；`artifacts/verification/g5/g5-formal-auth-20260810-001/runtime.json`；21 项 G5 测试、5 项认证测试；`g5-audit-migration-20260810-001/audit-migration.json` | 前向迁移、Worker retry/DEAD 契约、opt-in HTTP、HS256 正式身份、身份/幂等/错误映射、资源状态受控 UPDATE 与同事务审计、真实 MySQL HTTP 链路、故障/重启恢复、历史 `as_of` 只读重算 PASS；认证运行态无数据库动作；production HTTP 仅显式组合根可构造，默认 HTTP、外部 IdP/JWKS、正式 Worker 接线和发布凭据流程待补 |
| G6 可选检索与解释 | IN_PROGRESS | 图计划/导入、MySQL 书目导入、向量计划/验证、`chroma-collection-plan-20260811-002`/`chroma-collection-verify-20260811-002`、`chroma-import-idempotency-20260811-002`、独立只读 `chroma-import-integrity-20260811-001`；`backend/app/catalog/adapters/embedding.py`、`backend/app/catalog/adapters/chroma.py`、`backend/app/catalog/adapters/neo4j.py`、`tests/g6/test_retrieval_fusion.py` | Neo4j 63,388/191,865、MySQL 书目追加与幂等、确定性向量 14,983/384 维、Chroma collection 追加 14,983 并最终 14,983/14,983、幂等新增 0、独立只读 verifier PASS；图/向量显式组合根融合与故障降级 fake PASS；MySQL `embedding_status` 仍 PENDING，默认 HTTP/Worker 接线和真实隔离检索运行态待完成；DeepSeek 外部调用仍为 0 |
| G7 前端与论文演示 | NOT_STARTED | G1 Vue 状态页、健康客户端、组件测试和追加式构建证据已存在 | 推荐请求/澄清/解释/反馈/画像/调试交互页面、真实 API 接线和论文演示流程尚未完成；依赖 G6 |
| G8 可靠性与发布候选 | NOT_STARTED | — | 依赖G5—G7 |
| G9 冻结实验 | NOT_STARTED | `artifacts/verification/experiment-inputs/eval-inputs-20260810-002/input-freeze-report.json`（当前为 PASS_WITH_BLOCKERS） | 契约和输入门禁已建立；真实数据、许可、标注、Split、F3 配置和 G8 仍未完成 |
| G10 最终发布 | NOT_STARTED | — | 依赖G9 |

允许的状态：`NOT_STARTED / IN_PROGRESS / BLOCKED / COMPLETED`。状态只能在证据存在后更新为COMPLETED。

---

## Working Set

- `current_subtask`：双库书目事实、确定性向量离线产物和 Chroma collection 已完成版本化导入与独立只读验证；Prompt Bundle、显式 LLM Intent Agent、DeepSeek 本机密钥配置以及图/向量显式组合根融合 fake 验证已完成，下一步是只读真实隔离运行态验证和 G7 推荐前端设计，保持默认 API/Worker 与外部 LLM 请求关闭，不改变 MySQL `embedding_status=PENDING`。
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
- `immediate_risk`：G3/G4/G5 HTTP 仍未进入默认生产配置；G6 图/向量已接入显式组合根但尚未接入默认 Agent/HTTP，MySQL embedding 状态仍 PENDING，DeepSeek 本机密钥虽已配置但尚未联网调用；Prompt Bundle 已冻结但 Explanation/Feedback 的真实 LLM 接线仍待 EvidenceValidator/事务边界评审；G7 推荐前端仍未完成。任何默认环境仍不得自动开启推荐。Chroma operator 依赖只用于显式导入/校验，不进入默认 backend/worker 镜像。
- `database_boundary`：本机 Homebrew Neo4j `neo4j` 库是受保护外部数据（59,301 节点/185,238 关系）；RecPro 只能使用独立 Compose Neo4j 实例/卷，禁止复用 `127.0.0.1:7474/7687`。
- `next_action`：先在独立 RecPro Neo4j/Chroma 目标上执行只读真实融合验证（固定 `graph_version`、`embedding_version`、`index_version`，只读计数和候选证据），再开始 G7 推荐前端的 API DTO、澄清、解释和反馈页面；继续保持默认 HTTP/Worker、MySQL `embedding_status` 和外部 LLM 请求关闭。

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
