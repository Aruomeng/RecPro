# LibraMAS / RecPro

LibraMAS 是一个面向智慧图书馆知识资源推荐的研究生论文原型，核心研究方向为多智能体协同、动态交互策略、可解释推荐与反馈学习。

## 当前状态

G0—G5 的核心代码切片、MySQL 隔离运行态和安全门禁已经建立；G6 已完成真实图书数据、可选检索能力和一次隔离目标只读融合验证。`Lib` 已完成 76 个 CSV 的只读规范化，并将版本化图 `lib-books-v1-20260810` 追加导入独立 Neo4j（15,538 条来源记录、63,388 个节点、191,865 条关系）；在用户明确授权后，同一书目已按 append-only ChangePlan 写入隔离 Compose MySQL（14,983 本书、8,516 个标签、70,750 条标签关系），并完成幂等复跑与只读计数核验。当前已基于同一 MySQL ChangePlan 离线构建 14,983 条确定性向量记录（`hash-char-ngram-v1`、384 维），两次独立构建哈希一致；用户授权后已在独立本地 Chroma 路径创建新 collection `library_resources__hash_char_ngram_v1`，追加 14,983 条向量，并完成全量回读、版本/元数据核验、召回冒烟和幂等复核（`chromadb==1.5.9`）。MySQL 的 `embedding_status=PENDING` 未修改。Neo4j/Chroma 只读召回端口已通过真实隔离运行态融合验证：固定三组版本，MySQL 计数和 Chroma 14,983 条向量前后不变，8 条候选同时带 MYSQL/GRAPH/VECTOR 通道且无 fallback；详细证据见 `artifacts/verification/g6/g6-retrieval-fusion-readonly-20260811-001/readonly.json`。G7 已有推荐工作台、契约化 RecommendationClient、澄清交互占位和明确标注的本地演示；默认页面会根据健康响应决定是否允许真实请求，默认 `can_recommend=false` 时仍只显示闸门提示，不会绕过健康闸门或自动写入数据库。新增的显式 Demo/Production HTTP 组合根只有在调用方提供服务、启用 API 与健康闸门后才会声明 `can_recommend=true`；默认 HTTP/API/Worker 仍保持关闭，`can_recommend` 不因容器启动而自动变为 `true`。

G5 Worker 运行态接线已完成：Compose worker 继续启动为健康但无副作用的 `false/disabled` 模式；只有显式设置 `RECPRO_WORKER_ENABLED=true` 与 `RECPRO_WORKER_MODE=profile_outbox`，并满足非 production 配置，才会连接 MySQL 消费画像 Outbox。默认安全门禁的只读证据见 `artifacts/verification/g5/g5-worker-wiring-20260812-001/worker-wiring.json`，本阶段数据库连接、写入和 Outbox claim 均为 0。
随后已在隔离 MySQL 空队列上真实调用一次 `run_once(limit=1)`：receipts=`0`，40 张表计数与 Outbox `DONE=23/DEAD=2` 前后完全一致；证据见 `artifacts/verification/g5/g5-worker-readonly-runtime-20260812-002/readonly.json`。非空队列消费仍需新的 ChangePlan 与用户批准。

G7 已在隔离 Compose MySQL（本地端口 `62306`）完成真实只读 HTTP 冒烟：live/ready 均通过，`can_recommend=true`，推荐管线版本为 `recommendation-g3-mysql-v1`；资源与推荐相关 13 张表的前后计数完全一致，业务 POST 与数据库写入均为 0。基线证据见 `artifacts/verification/g7/g7-mysql-http-readonly-20260811-005/readonly.json`（实际执行 30 条只读 SQL）；此前 `...-001` 至 `...-004` 证据均保留、未覆盖。此前一次旧计划执行在写入前因 15,000 资源上的重复全量排序被安全中止，计数经只读复核未变化；G3 已提交通道排名预计算修复（`4915351`），15,000 条离线基准约 0.14 秒。用户确认新 plan hash=`2b115b3790a6281f4725be7fe29a5448e674c92570cdaac766cc0f40eb961d53` 后，已按该 `S1_APPEND/DRY_RUN` ChangePlan 在同一隔离 MySQL 执行一次真实 POST：新增 task 1、transition 8、candidate 15、record 1、item 5、explanation 5、policy 1、trace 1，共 37 行；资源事实表计数不变，任务回读为 `COMPLETED`、record=`19`。只读回读证据见 `artifacts/verification/g7/g7-recommendation-post-reconcile-20260811-001/reconciliation.json`；回读本身数据库写入和业务 POST 均为 0，未进行重复提交。
前端现在有独立的显式 Demo HTTP 入口 `backend.app.demo_main:app`：必须同时设置 `RECPRO_APP_ENV=demo` 与 `RECPRO_DEMO_HTTP_ENABLED=true`，默认 `backend.app.main:app` 和 Compose 命令仍保持 health-only。Vite 代理浏览器冒烟已通过真实 health GET，工作台可识别 `can_recommend=true` 并安全展示本地演示；证据见 `artifacts/verification/g7/g7-frontend-api-browser-20260811-001/frontend.json`。浏览器尚未重复发送真实推荐 POST，避免复用已完成幂等键。
G7 现在另有独立的 `backend.app.g4_feedback_demo_main:app` 入口：必须同时通过 G4/G5 后端双开关、经 `AppSettings` 校验的同名设置、隔离 Graph/Vector 运行时和 G5 服务注入，才会挂载真实 feedback/behavior POST。DeepSeek Intent 与 Explanation 分别由 `RECPRO_G4_LLM_INTENT_ENABLED=true` 和 `RECPRO_G4_LLM_EXPLANATION_ENABLED=true` 独立启用；默认 Compose backend 和 Worker 仍关闭。前端交互按钮默认关闭的浏览器验收已通过，390×844 无横向溢出，未产生交互 POST。

最新的获批真实 G4 请求已同时使用 DeepSeek `deepseek-v4-flash` 完成 Intent 与 8 条 evidence-bound Explanation：任务 `228c1064-7267-54f1-a68b-6584c11dae51` 为 `COMPLETED`，Intent 无回退，8 条 Explanation 均通过白名单引用校验且无模板回退；一次 Explanation 语义校验重试使外部请求总数为 10。MySQL 仅按计划追加 56 条推荐审计事实，HTTP 幂等重放新增 0 行，Neo4j、Chroma、文件删除和数据库物理删除均为 0；执行与独立回读证据分别见 `artifacts/verification/g4/g4-deepseek-intent-explanation-http-apply-20260812-002/g4-recommendation-projection-apply.json`、`artifacts/verification/g4/g4-deepseek-intent-explanation-http-reconcile-20260812-002/g4-recommendation-projection-reconciliation.json`。

同一真实推荐已完成获批 G5 闭环：对第 7 名图书候选追加一次有效曝光、一次 `NOT_INTERESTED/TOPIC_NOT_INTERESTED` 反馈和一次直接点击行为，Worker 精确消费两条新 Outbox 并将其置为 `DONE`，画像重放版本由 30 推进到 32。全链路逐表对账为计划内 26 项逻辑变更，其他表均未变化；Neo4j/Chroma/LLM 无调用或写入，文件与数据库删除均为 0。证据见 `artifacts/verification/g5/g5-feedback-worker-apply-20260812-002/g5-feedback-worker-apply.json` 与 `artifacts/verification/g5/g5-feedback-worker-reconcile-20260812-005/reconciliation.json`。在显式 Demo 门禁与忽略的本地环境配置下，`backend.app.g4_feedback_demo_main:app` 的健康响应已为 `READY`、`can_recommend=true`，MySQL/Neo4j/Chroma/推荐链路为 `UP`，LLM 为 `deepseek-v4-flash`；默认 Compose 仍保持 fail-closed。

G8 发布候选前置检查已加入 `scripts/verify_g8_release_preflight.py` 与 `make verify-g8-release-preflight`：它会在新证据目录中运行契约、文档、架构、安全、G0—G9 离线测试、Compose config、前端测试/追加式构建、后端镜像检查和默认 fail-closed 配置，并写入源码 SHA-256 清单。首次报告 `...-001` 已保留；扩展后的正式报告 `artifacts/verification/g8/g8-release-preflight-20260812-002/release-preflight.json` 为 `PASS_WITH_BLOCKERS`：20 项技术检查全部通过，源码清单 402 个文件；该命令只读检查和构建本地产物，不启动应用、不连接数据库、不 claim Outbox、不调用 DeepSeek。随后新增 `scripts/verify_g8_acceptance_coverage.py` 与 `make verify-g8-acceptance-coverage`，逐项核对 A01—A25 的测试、源码、工具和历史证据；最新报告 `artifacts/verification/g8/g8-acceptance-coverage-20260812-008/acceptance-coverage.json` 为 `PASS_WITH_BLOCKERS`，25 项映射无陈旧引用，25 项直接覆盖、0 项相关覆盖、0 项缺少直接测试；最终 G8/G9 复验仍保持阻塞。
为避免把离线覆盖误当成最终验收，新增 `contracts/verification/g8-final-revalidation-plan.schema.json`、`scripts/build_g8_final_revalidation_plan.py` 和 `make build-g8-final-revalidation-plan`。上一版只读计划 `artifacts/verification/g8/g8-final-revalidation-plan-20260812-003/final-revalidation-plan.json` 绑定提交 `ccdf71f981a223db26cc54ca561480cf1f3ecf01`、`plan_hash=00a21f9f9c58737186fa4949e1a13c2318a37d9a82ed17b77d5ce9ff6fedba87`，冻结 25 项 A01—A25 与六个浏览器场景；其中 17 项可先做只读运行态验证，8 项需要独立 ChangePlan。新增 `scripts/verify_g8_final_revalidation_plan.py` 后，审计 `artifacts/verification/g8/g8-final-revalidation-audit-20260812-001/final-revalidation-audit.json` 为 `READY_FOR_RUNTIME`：计划有效、历史 artifact 仅被计数而未提升 final 状态，25 项 final 仍为 `PENDING`；本次审计数据库/图/向量读取与写入、Outbox claim、DeepSeek、删除和覆盖均为 0。
随后在当前提交上完成追加式只读运行态复验：数据平面五服务均 healthy、MySQL 40 张表、隔离 Compose Neo4j 计数 0/0；G4 纯编排的 direct/guided/degraded/replanning 四分支通过，真实 G4 端口融合 7 个 Agent 返回 8 条 `MYSQL+GRAPH+VECTOR` 候选且 MySQL/Chroma 计数不变；HOME 空请求稳定进入 `WAITING_CLARIFICATION`，4 个 Agent、19 张相关表前后不变；G6 MySQL/Neo4j/Chroma 融合复验返回 8 条候选、三通道和 14,983 条向量不变；G7 health-only HTTP 复验通过且业务 POST/数据库写入均为 0，但 readiness 仍为 `DEGRADED`。证据分别见 `artifacts/verification/data-plane/data-plane-20260812-004/runtime.json`、`artifacts/verification/g4/g4-orchestrator-20260812-006/orchestrator.json`、`artifacts/verification/g4/g4-readonly-fusion-20260812-012/readonly.json`、`artifacts/verification/g4/g4-clarification-readonly-20260812-004/clarification-readonly.json`、`artifacts/verification/g6/g6-retrieval-fusion-readonly-20260812-012/readonly.json`、`artifacts/verification/g7/g7-mysql-http-readonly-20260812-006/readonly.json`。这些只读运行证据本身的外部请求计数为 0；后续 provider-only fixture 另有独立证据，且不改变这些运行态结论或 A01—A25 final 状态。
随后生成与提交 `a490652664306d4fe89bcbc9a16a608e02f6ff5b` 一致的新计划 `artifacts/verification/g8/g8-final-revalidation-plan-20260812-004/final-revalidation-plan.json`（`plan_hash=0cac04a818e9ff61ae2df7c3a6e4f90a414462ff7f755aa9d7171cfd528d9dfb`）和审计 `artifacts/verification/g8/g8-final-revalidation-audit-20260812-002/final-revalidation-audit.json`。审计确认计划 25/25 有效、17 项只读、8 项需独立 ChangePlan、final_pass=0、final_pending=25，且计划 Git 匹配当前提交；它仍只盘点历史 artifact，不将上述部分运行证据自动提升为 final PASS。
G4 已完成一次真实隔离只读多智能体融合：7 个 Agent 全部成功，8 条候选同时带 `MYSQL+GRAPH+VECTOR` 通道，固定 graph/embedding/index 版本，MySQL 资源与 Agent 事实表、Chroma collection 前后计数均不变；证据见 `artifacts/verification/g4/g4-readonly-fusion-20260811-001/readonly.json`。随后新增了无副作用的 G4→HTTP 投影契约和显式 MySQL writer：命令映射保留 scene 与冻结时间，候选通道可拆分为可持久化的独立值，写入前要求资源摘要、证据置信度、channel rank/score、解释证据和 item identity 完整；task/transition/candidate/record 写入均做 INSERT IGNORE 后身份回读。G4 RecommendationTaskService 及研究组合根已具备，但仍未替换 G3 HTTP 持久化服务；默认 HTTP/Worker 不会自动启用 G4。
当前 G4 已进一步落实 Agent 自主性：8 个业务 Agent 均有独立 Role/Goal/Observation/Tools/AllowedActions/AllowedTargets；每次 AgentResult 必须携带经过 Registry 校验的 `AgentDecision`，PolicyAgent 的 `ASK_CLARIFICATION/PLAN_RECALL/DEGRADE` 和 RankingAgent 的 `REQUEST_REPLAN` 会驱动 Orchestrator 的合法状态转换。四路径离线证据见 `artifacts/verification/g4/g4-agent-autonomy-20260812-001/agent-autonomy-runtime.json`，共享契约与二次排序动作校验复验见 `artifacts/verification/g4/g4-agent-autonomy-20260812-003/agent-autonomy-runtime.json`，这证明系统不是把对话模型改名为 Agent；同时仍是受监督式有限自主，默认 HTTP/Worker 保持关闭。
G4 HTTP 投影现在继续校验每一步 trace 的动作与角色边界，并以 `agent_actions` 输出安全快照；G5 feedback/behavior 显式边界由 `FeedbackLearningAgent` 根据 receipt 动态选择 `PROPOSE_PROFILE_DELTA`、幂等 `RETURN_RESULT` 或安全 no-op。该边界验证见 `artifacts/verification/g4/g4-http-feedback-autonomy-20260812-003/http-feedback-autonomy.json`，只运行规则/fake 代码，数据库、Neo4j、Chroma、Outbox 和外部 LLM 均为 0。
G8 现已提供统一的 17 项只读/故障矩阵执行器 `scripts/verify_g8_readonly_fault_matrix.py`：它从当前提交绑定的最终复验计划读取 A01/A05/A06/A11—A22/A24/A25，使用隔离进程、fake adapters 与故障注入生成 `g8-final-runtime-evidence-v1`；A02/A03/A04/A07/A08/A09/A10/A23 继续保持 PENDING。最终审计会逐项核验引用 artifact 的仓库边界、存在性、SHA-256、schema version 和 ChangePlan，不允许无证据提升 PASS。
当前 17 项只读/故障矩阵已在提交 `405ffe61e5bff63859710fb8909b9d587ea20fc4` 上完成：61 项隔离测试全部通过，最终审计为 `17 PASS / 8 PENDING / 0 FAIL`。针对剩余用例，A02 可复用推荐任务幂等执行边界，A03/A04/A08/A23 可复用 feedback/behavior/Outbox 执行边界；A07/A09/A10 新增了专用 `g8-boundary-change-plan-v1` 契约、只读计划生成器和 fail-closed 执行器，精确冻结 `ALREADY_READ -> READ`、`999ms` 与 `0.49` 两个曝光阈值、同 UUID 零增量重放和单条 Outbox 消费，总影响上限为 20 行。执行器只接受当前 clean commit、同一隔离环境、未漂移基线和用户明确批准的精确 `plan_id/plan_hash`；计划生成不授权写入，当前尚未执行这些剩余用例。
G5 与 G8 边界计划现额外拒绝不晚于用户最新行为的交互时间；MySQL 无时区 `DATETIME(3)` 按既有 UTC 存储约定解释。该门禁防止 Worker 用历史 `as_of` 意外回放并覆盖较新的画像投影。发现门禁前生成的预演计划全部保留但标记为提交不匹配、不可批准，未产生数据库写入。
G7 的受控推荐执行器现将 A02 所需的同 request_id 重放纳入同一精确计划：首请求必须为 `201/Idempotency-Replayed=false`，第二次必须为 `200/true` 且返回同一 task，随后才做计数回读；第二次请求的额外行增量必须为 0。
当前已补充 operator-only Chroma loader 与 G4 HTTP host 只读预演：正式 collection 的版本 metadata、cosine 距离度量和 14,983 条记录均核验通过；内存组合根的 live/ready 均为 `200`、`can_recommend=true`，MySQL/Chroma 计数不变且业务 POST 为 `0`。证据见 `artifacts/verification/g4/g4-http-host-readonly-20260811-003/readonly.json`。这证明了 G4 HTTP 入口可安全构造，但不等同于真实 HTTP 业务写入已开放；下一步仍需独立 ChangePlan、一次隔离追加和幂等回读。
随后按用户批准的 successor ChangePlan 完成了一次真实 G4 受控追加：精确请求返回 8 个候选，其中 `MYSQL=8`、`VECTOR=5`，拆分后追加 13 条候选行；连同 task、7 个 Agent 的 message/result、record、8 个 item、解释、policy、trace 等共 57 行。任务状态为 `COMPLETED`，8 个条目，Neo4j/Chroma/外部 LLM 均 0 写入或请求；详细执行与回读证据见 `artifacts/verification/g4/g4-projection-apply-20260811-002/g4-recommendation-projection-apply.json` 和 `artifacts/verification/g4/g4-readonly-fusion-20260811-008/readonly.json`。默认 HTTP/Worker 仍保持关闭。
G4 澄清续跑适配器随后已完成代码级实现：Orchestrator 可从 `WAITING_CLARIFICATION` 继续，G4 writer 对 context 2 及后续轮次只追加 transition、Agent facts、trace revision、policy、结果和回答上下文；服务在最新上下文校验、幂等重放、冲突、陈旧版本和并发唯一性失败时回滚，且不执行 `UPDATE/DELETE`。主题答案支持最多 500 字符的自定义组合文本，资源类型仍是封闭枚举。随后已对具体 task 完成一次获批真实续跑：`BOOK` + `多智能体+推荐系统+知识图谱` 进入 `COMPLETED/context_version=2`，record=`22`、5 个图书条目，精确追加 44 行；证据见 `artifacts/verification/g4/g4-clarification-continuation-apply-20260811-001/g4-clarification-continuation-apply.json`。默认 HTTP/Worker/外部 LLM 仍关闭。
等待态只读验证器和 19 行初始等待任务 DRY_RUN 构建器已加入仓库；它们会冻结 HOME 空请求、4 个 Agent、问题快照、完整表计数和幂等身份。当前 Docker CLI 符号链接指向不存在的 Docker Desktop 路径，尚未生成新的运行态基线或 ChangePlan artifact；恢复 Docker 后先运行只读验证，再生成计划，期间不执行任何业务写入。
隔离端口仍在运行，因此已绕过 Docker CLI 完成真实 MySQL 只读验证：HOME 空请求稳定进入 `WAITING_CLARIFICATION`，19 张相关表前后计数不变，证据见 `artifacts/verification/g4/g4-clarification-readonly-20260811-001/clarification-readonly.json`。初始 19 行等待任务计划已预演生成，但交接文档提交后会重新生成 hash；在最终 hash 获得用户批准前不会创建任务或提交答案。
等待任务专用执行器也已完成：它严格校验 plan/evidence/config/Git hash、权限、幂等身份和 19 张表的精确 delta；continuation 执行器进一步校验 44 行精确目标、最新上下文和 answer payload，显式 `--apply` 之外不会写库。此前失败尝试已按零增量隔离并修复；两次真实追加均完成独立只读回读，所有历史事实保留，不执行删除或覆盖。

最近配置修复已完成：`scripts/sync_host_env_from_compose.py` 将经过预检的隔离 Compose 参数安全同步到本机 `.env.host`，修复 host MySQL 端口与迁移凭据缺口，并保留 `0600` 备份；旧前端依赖目录只移动到 `/tmp` 备份后按 `package-lock.json` 恢复，40 个前端测试和生产构建通过。Makefile 现在能自动定位本机实际 Docker Desktop CLI；Compose 健康检查已改为对启动负载更稳健的超时与 Neo4j HTTP+Bolt 端口探测。当前 MySQL、backend、frontend 与本项目隔离 Neo4j 均已健康；图书 Neo4j 只为应用用新的健康检查重建了其容器并复用原卷，未执行 Cypher 写入；用户原有大图始终未停止或访问。G4 的 Graph/Vector 只读融合证据见 `artifacts/verification/g4/g4-readonly-fusion-20260811-010/readonly.json` 与 `...-011/readonly.json`。详细配置记录见 `docs/LibraMAS_实施状态与交接记录.md` 的 `CONFIG-FIX-20260811-001`。

书目数据必须先经过 `contracts/data/intake/` 的规范化记录/Manifest 和图计划只读校验，再由 `scripts/import_book_graph.py` 以显式 `--apply` 追加到带 `graph_version` 的 Neo4j 影子图；实体/关系见 [图书图谱模型与导入契约](docs/book_graph_model.md)。仓库不保存外部大模型密钥，也不需要密钥运行 MockLLM/模板路径；DeepSeek 适配器已准备并保持默认关闭，当前本机的 opt-in 配置只能通过被 Git 忽略的环境文件注入，禁止提交到 Git。详见 [LLM 与 Prompt 配置基线](docs/LLM_PROMPT_CONFIGURATION.md)。
DeepSeek 已通过本地“真实调用就绪预检”：`artifacts/verification/llm/llm-real-call-readiness-20260812-002/real-call-readiness.json`=`READY_FOR_EXPLICIT_OPT_IN`，provider/model/HTTPS/Prompt Bundle/key 存在性均通过。默认 Compose、HTTP、Worker 仍 fail-closed；真实调用只在显式研究组合根、固定非敏感输入、费用/超时/回退/审计边界和用户明确授权同时满足时发生。
用户随后明确批准了固定非敏感能力探针。`intent.classify` 证据 `artifacts/verification/llm/llm-fixture-call-20260812-001/real-call.json`=`PASS`；`explanation.render` 首次运行因旧 Prompt Schema 与运行时引用要求不一致安全失败，失败证据完整保留，修订版不可变 Bundle `rec-prompts-v1.0.1.json` 复验 `llm-explanation-fixture-20260812-002`=`PASS`，1 次请求、约 3.15 秒、白名单引用及文本引用标记均通过。两次成功探针均未读写 MySQL、Neo4j、Chroma，未 claim Outbox，未保存原始模型文本或密钥。
随后新增 Intent-only 的 G4 只读组合与 `make verify-g4-real-llm-readonly`。真实七 Agent 编排证据 `artifacts/verification/g4/g4-real-llm-readonly-20260812-002/real-llm-readonly.json` 为 `PASS`：DeepSeek `deepseek-v4-flash` 实际完成 `intent.classify`，无规则回退，7 个 Agent 全部调度，返回 8 个 `MYSQL+GRAPH+VECTOR` 候选；外部请求 1 次，MySQL/Neo4j/Chroma 写入均为 0。本机 G4 HTTP 入口现已通过独立开关接入真实 Intent Agent，Explanation/Feedback 和 Worker 不随之自动启用。
真实 HTTP 持久化现已纳入同一 G4 ChangePlan 工具：计划可绑定无密钥的 DeepSeek Intent 策略指纹；获批执行必须通过实际 FastAPI POST、同 request_id 的 HTTP 幂等重放、任务 GET 回读和 Intent Agent 持久化回执，并将外部请求限制为首次请求的 1–2 次尝试。计划生成本身仍为零数据库写入、零外部请求。
获批计划 `28d050ce-a922-5480-b326-38fdf8984fdf` 已真实执行并独立对账 PASS：DeepSeek `deepseek-v4-flash` Intent 调用 1 次、无 fallback，HTTP 首写 `201`、幂等重放 `200/zero-delta`，任务 `COMPLETED`、8 个推荐项，MySQL 精确追加 56 行；Neo4j/Chroma 写入和删除均为 0。G4 readiness 现对版本锁定的 Neo4j/Chroma 执行只读探测并报告实际 DeepSeek provider，不再固定显示 Mock；Explanation Agent 的真实能力探针已 PASS，并改为最多 4 路有界并发且保持排序，完整 HTTP 推荐链路仍需下一份限定 8 条解释、最多 16 次尝试和精确数据库增量的 ChangePlan。
G4 ChangePlan 工具现可分别冻结 `deepseek_intent_policy` 与 `deepseek_explanation_policy`：Explanation 计划必须同时启用 Intent，绑定条目上限、每项最多两次尝试、四路并发、证据输入范围、逐项模板回退和重放零调用。计划 `dc1fb053-0218-51d0-97a2-152b662f82d1` 已受用户精确批准并执行：Intent 真实调用成功 1 次，Explanation 记录 8 次调用尝试且发生证据回退，MySQL 精确追加 56 行；首次 HTTP 响应因内部告警未映射到公开枚举而返回 500，但事实未丢失。随后已修复公开告警映射，并用同一请求完成 `GET=200`、`POST replay=200/zero-delta`，未再次调用模型。语义证据校验失败现在也纳入每项最多两次的原始模型重试预算；下一次新业务请求仍需生成并批准新 ChangePlan。

数据库管理员凭据只保存在本机 `.env.user-secrets`（权限 `0600`，已被 `.gitignore` 忽略），不进入应用日志或提交。MySQL 应用运行账号仍保持最小权限；`root` 仅作为后续受控管理/迁移凭据使用。Neo4j Community 只提供默认 `neo4j` 数据库，因此 RecPro 使用独立 Compose 实例和独立数据卷隔离于本机已有 Neo4j；不会连接本机 `7474/7687` 上的既有图。

当前 RecPro Neo4j 隔离实例为 `recpro-library-neo4j-20260810a`，使用独立数据卷和本地端口 `62475/62688`，图版本 `lib-books-v1-20260810` 当前为 63,388 节点、191,865 关系；原有 RecPro 验证实例和本机已有大图均保留，不迁移、不复用。

## 核心文档

- [可运行版实施文档](docs/LibraMAS_纯推荐模块实施文档_可运行版.md)
- [安全低耦合实施计划](docs/LibraMAS_系统实施计划_安全低耦合版.md)
- [实施状态与交接记录](docs/LibraMAS_实施状态与交接记录.md)
- [G1 可启动工程骨架本地验收清单](docs/G1_RUNNABLE_SKELETON_MANIFEST.md)
- [安全与零删除政策](docs/SAFETY_POLICY.md)
- [模块化单体 ADR](docs/adr/0001-modular-monolith.md)
- [核心数据字典](docs/data_dictionary.md)
- [HTTP API 契约](docs/api.md)
- [论文实验协议](docs/experiment_protocol.md)
- [A01—A25 验收矩阵](docs/acceptance_matrix.md)
- [图书数据接入契约](contracts/data/intake/book-intake-manifest.schema.json)
- [书目图谱模型与导入契约](docs/book_graph_model.md)
- [LLM 与 Prompt 配置基线](docs/LLM_PROMPT_CONFIGURATION.md)
- [书目图计划 Schema](contracts/data/intake/book-graph-plan.schema.json)
- [MySQL 书目计划 Schema](contracts/data/intake/mysql-book-plan.schema.json)
- [向量索引计划 Schema](contracts/data/intake/vector-index-plan.schema.json)
- [Chroma Collection 计划 Schema](contracts/data/intake/chroma-collection-plan.schema.json)

## 最高优先级安全约束

未经用户查看详细影响报告并明确批准：

- 不得删除任何文件；
- 不得物理删除任何数据库数据或对象；
- 不得清理持久卷、测试运行、实验结果或旧索引；
- 纠错、撤回、停用和恢复必须使用版本、补偿事件或前向修复。

详细规则已经固化在 `docs/SAFETY_POLICY.md`，并由自动化安全扫描强制执行。

## 架构方向

采用模块化单体与端口适配器：Catalog、Profile、Recommendation、Feedback 等业务域保持高内聚；Agent通过结构化消息和Orchestrator协作，不直接访问数据库或互相调用。

## 本地验证

需要 Python 3.11。Python 依赖拆分为 G0 门禁、G1 运行时和 G1 测试三个哈希锁；应在全新的虚拟环境中安装：

```bash
python3.11 -m venv .venv-g1-release-001
.venv-g1-release-001/bin/python -m pip install --require-hashes \
  -r backend/requirements-g0.lock \
  -r backend/requirements-g1.lock \
  -r backend/requirements-g1-test.lock
make verify-g0 PYTHON=.venv-g1-release-001/bin/python
make test-g1-python PYTHON=.venv-g1-release-001/bin/python
```

前端依赖必须在全新克隆或新的隔离目录中执行 `npm ci --ignore-scripts`。测试和构建命令为：

```bash
npm --prefix frontend run test
BUILD_RUN_ID=g1-local-20260802-001 make frontend-build
```

构建只写入新的 `frontend/dist/<run-id>`；若目标已存在则失败，不覆盖旧产物。以上本地门禁不连接数据库，也不修改业务数据。

## 隔离运行时

复制环境模板只能通过 create-only bootstrap 完成；已有目标不会被覆盖：

```bash
make bootstrap
# 编辑被 Git 忽略的 .env.compose，使用新的项目名和三个互不相同的本地密码
RUN_ID=g1-20260802-001 make verify-g1-runtime
# 首次验收通过并保留停止后的容器与卷后，日常使用：
make start
make status
make stop
```

首次运行时验收必须先于该项目名的任何手工 `make start`，因为它只允许此前不存在的 Compose 项目、网络和三个命名卷。它检查五个服务、前后端健康接口、最小权限持久化标记以及两次安全停止/启动的一致性，并把证据追加到新的 `artifacts/verification/g1/<run-id>`。停止只使用 `docker compose stop`；不得执行删容器、删卷或数据库清理命令。

## 当前目录

```text
backend/app/                          领域契约、健康应用切片及基础设施适配器
contracts/                            Agent、配置、安全和 OpenAPI Schema
frontend/                             G1 状态页、G7 推荐工作台及追加式构建脚本
infra/                                新卷专用的最小权限初始化入口
scripts/                              安全、架构、环境与验收门禁
tests/                                G0/G1 自动化测试
contracts/data/intake/                 规范化书目与接入 Manifest Schema
```

## 版本管理

每个Gate使用独立分支和详细提交说明。提交正文至少记录：

1. 变更目的与范围；
2. 关键设计决策；
3. 验证命令和结果；
4. 文件与数据库安全影响；
5. 后续工作或已知限制。

远程仓库固定为 `https://github.com/Aruomeng/RecPro.git`。发布前必须先通过本地门禁；推送和 Pull Request 只在认证工具可用后执行。
