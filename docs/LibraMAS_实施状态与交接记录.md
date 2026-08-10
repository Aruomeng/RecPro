# LibraMAS 实施状态与交接记录

> 状态版本：3.2
> 更新时间：2026-08-10
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
  - G1 最终验证环境：Python 3.11.14、Node 25.6.0、npm 11.8.0、MySQL 客户端 9.3.0、Docker 29.3.1、Docker Compose 5.1.1、GitHub CLI 2.97.0。Docker Desktop 位于 `/Applications/编程/Docker.app`，当前需显式加入其资源目录到 PATH；`gh` 已安装但尚未认证。
  - macOS 元数据文件已保留并由 `.gitignore` 忽略，未删除、未提交；Finder 可自动更新或新建这类文件，本项目不对其执行清理或哈希回写。
  - 当前未连接或修改任何既有业务数据库；G1 只在全新隔离 Compose 卷中创建平台探针表和唯一标记行，用于验证安全复启。
- `decisions`：
  - 用户最新零删除要求优先于旧实施文档中的reset、destroy和clear语义。
  - `demo-reset`替换为新 `fixture_generation/test_run_id`。
  - 数据纠错、撤销和停用使用版本或补偿事件。
  - Chroma和Neo4j重建使用新版本构建与活动指针，不删除旧版本。
  - 代码按Catalog、Profile、Recommendation、Feedback、Observability、Platform等业务域组织。
  - 正式论文实验只能在G8发布候选通过后开始。
- `completed_work`：
  - 已完成最新版可运行实施文档。
  - 已完成安全、低耦合、高内聚的系统实施计划。
  - 已建立本交接记录。
  - 已验证计划文档代码围栏成对、JSON示例合法、相对链接目标存在，且需求基线哈希未变化。
  - 已完成零删除政策、删除前汇报模板、G0 基线清单和两份架构 ADR。
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
- `next_step`：依据五类 Manifest 契约接收并审查真实评价数据、许可证据、盲标注和 F2 Split，再生成 F3 配置 Manifest；同时评审外部 IdP/JWKS 与 Worker 运行接线；默认 API 继续关闭。

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
| G6 可选检索与解释 | NOT_STARTED | — | 依赖G3/G4 |
| G7 前端与论文演示 | NOT_STARTED | — | 依赖G4—G6 |
| G8 可靠性与发布候选 | NOT_STARTED | — | 依赖G5—G7 |
| G9 冻结实验 | NOT_STARTED | `artifacts/verification/experiment-inputs/eval-inputs-20260810-002/input-freeze-report.json`（当前为 PASS_WITH_BLOCKERS） | 契约和输入门禁已建立；真实数据、许可、标注、Split、F3 配置和 G8 仍未完成 |
| G10 最终发布 | NOT_STARTED | — | 依赖G9 |

允许的状态：`NOT_STARTED / IN_PROGRESS / BLOCKED / COMPLETED`。状态只能在证据存在后更新为COMPLETED。

---

## Working Set

- `current_subtask`：已建立五类正式评价输入 Manifest Schema 与只读校验器；当前 G2 合成 Fixture 和 F2/F3/许可/标注输入缺失仍被阻断，真实数据准备完成前不得开始确认性实验。
- `current_evidence`：G0 131 项、G1 Python 103 项、G2 13 项、G3 22 项、G4 33 项、G5 21 项、认证 5 项、G9 冻结前置 3 项、评价输入门禁 7 项和前端 33 项测试通过（累计 368 项）；安全扫描、架构扫描、文档/契约校验待本阶段最终回归；评价输入报告 `PASS_WITH_BLOCKERS`，全程 database_reads=0、database_writes=0、actual_delete_count=0、overwritten_runs=0。
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
- `immediate_risk`：G3/G4/G5 HTTP 仍未进入默认生产配置；production HTTP 仅能通过显式组合根构造，正式 Worker 接线和外部 IdP/JWKS 仍待补；五类输入门禁已证明当前数据只能用于合成演示，不得用于正式论文评价。
- `next_action`：按五类 Schema 准备真实数据/许可/盲标注/F2 Split/F3 配置，并完成 Worker/外部 IdP 评审；任何默认环境仍不得自动开启推荐。

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
