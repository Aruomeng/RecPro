# Lib 书目图谱模型与导入契约

本模型面向 `Lib/**/*.csv` 的本地爬取数据，先生成版本化节点和三元组，再由显式授权的追加式导入器写入 RecPro 独立 Neo4j 实例。导入器不连接本机 `7474/7687` 的既有图，也不删除、清空或覆盖输入和数据库事实。

## 输入边界

固定 CSV 表头为：

`题名,外文题名,作者,出版社,发行时间,ISBN号,页数,原书定价,开本,主题词,中图法分类号,内容提要,详情页Url`

每次构建绑定 `input.sha256`、每个源文件 SHA-256、Git 提交和 `graph_version`。详情页 URL 只保存 scheme、域名和 path；query/fragment 不进入图，原始 URL 只保留 SHA-256 作为溯源指纹。

## 实体

| Label | 业务含义 | 稳定键 | 关键属性 |
|---|---|---|---|
| `GraphVersion` | 一次完整图构建的版本边界 | `graph_version` | `source_id`、输入摘要、记录数 |
| `SourceFile` | 一个分类目录下的 CSV | 相对路径 | 文件 SHA-256、字节数、记录数 |
| `SourceRecord` | 一个文件中的一行书目事实 | 文件路径 + 行号 + 行哈希 | 原始行哈希、来源文件、行号 |
| `Book` | 去重后的书籍实体 | 正常 ISBN；冲突 ISBN 加内容指纹；无 ISBN 用内容指纹 | 题名、ISBN、出版信息、摘要、安全来源 URL |
| `Category` | 中图法大类目录 | `category:<code>` | 大类代码和名称 |
| `Topic` | CSV 文件名对应的主题 | `topic:<category>:<name>` | 主题名、所属大类 |
| `Author` | 作者/译者等人员 | 规范化姓名 SHA-256 | 姓名 |
| `Publisher` | 出版社 | 规范化名称 SHA-256 | 名称 |
| `SubjectCode` | 中图法分类号 | `clc:<code>` | 分类号 |
| `Keyword` | 主题词 | 规范化词 SHA-256 | 词名 |

所有实体带 `graph_key`、`entity_id` 和 `graph_version`。`graph_key = graph_version + label + SHA-256(entity_id)`，因此不同版本不会碰撞；Neo4j 对每个 Label 的 `graph_key` 建唯一约束。

ISBN 冲突不强行合并：相同 ISBN 出现多个核心书目指纹时，Book 键使用 `ISBN_VARIANT_CONTENT_FINGERPRINT`；缺少或非法 ISBN 时使用 `CONTENT_FINGERPRINT`。`SourceRecord` 始终保留每次出现，重复分类不会丢失来源事实。

## 三元组关系

| 主体 | 谓词 | 客体 | 关系属性 |
|---|---|---|---|
| `SourceFile` | `FROM_BATCH` | `GraphVersion` | — |
| `SourceRecord` | `FROM_BATCH` | `GraphVersion` | — |
| `SourceRecord` | `READ_FROM` | `SourceFile` | — |
| `SourceRecord` | `DESCRIBES` | `Book` | — |
| `Book` | `IN_GRAPH_VERSION` | `GraphVersion` | — |
| `Book` | `CLASSIFIED_AS` | `Category` | — |
| `Book` | `IN_TOPIC` | `Topic` | — |
| `Category` | `HAS_TOPIC` | `Topic` | — |
| `Book` | `AUTHORED_BY` | `Author` | `role`（著/译/主编等） |
| `Book` | `PUBLISHED_BY` | `Publisher` | — |
| `Book` | `HAS_SUBJECT_CODE` | `SubjectCode` | — |
| `Book` | `HAS_KEYWORD` | `Keyword` | — |

每条边都有由主体、谓词、客体和属性计算的 `edge_key`。导入使用 `MERGE` + `ON CREATE SET`，同一计划重复执行不会产生重复节点/边，也不会更新已有节点属性。

## 可执行流程

1. `build_book_graph_plan.py` 严格检查表头、编码、字段数和规范化规则，生成 `nodes.jsonl`、`triples.jsonl` 和 `graph-plan.json`。该步骤零数据库读写。
2. `import_book_graph.py` 默认只读预演：校验三个产物的 SHA-256、节点/三元组引用完整性、目标项目名和目标端口，再读取目标节点/关系计数。
3. 只有计划的 `license_status` 已明确为 `CONFIRMED_LOCAL_RESEARCH` 或 `LICENSED_OPEN_DATA`，并显式传入 `--apply`，才会在隔离目标创建唯一约束并按批次追加写入。
4. 写入后按 `graph_version` 和全库分别计数；计划数与实际不一致即失败。报告保存在新建的 `artifacts/verification/book-graph-import/<run_id>/`，不覆盖旧证据。

当前图版本：76 个 CSV、15,538 条来源记录、63,388 个节点、191,865 条关系；计划状态 `PASS_WITH_WARNINGS`，警告为 371 条 ISBN 规范化问题。用户确认本地研究授权后，`lib-books-v1-20260810` 已追加到独立目标并完成幂等复验，最终计数保持 63,388/191,865。

## MySQL 事实层映射与只读召回

`scripts/build_mysql_book_plan.py` 将同一 `graph_version` 的 `Book` 节点和标签关系映射为现有 G2 五张表的 JSONL ChangePlan：`resource_catalog`、`resource_book_detail`、`tag_dictionary`、`resource_tag`、`resource_index_state`。计划只使用稳定 `external_id`，不提前猜测 MySQL 自增 ID；详情见 [MySQL 书目计划 Schema](../contracts/data/intake/mysql-book-plan.schema.json)。

`scripts/import_mysql_book_catalog.py` 默认只做计划完整性校验和干跑。实际追加必须同时提供 `--apply --confirm-mysql-write`，非空目标还要显式 `--allow-nonempty-target`；导入先检查资源、标签和索引状态冲突，再使用 `INSERT IGNORE`，不提供删除、清空、更新或覆盖路径。用户确认目标 `recpro-g2-tianyuhang-20260809a` 的本地研究追加写入后，`mysql-book-import-20260810-002` 已将计划追加到 `recpro` 数据库；前后目标表总数为 `resource_catalog=14,989`、`resource_book_detail=14,986`、`tag_dictionary=8,522`、`resource_tag=70,762`、`resource_index_state=14,989`，其中本次新增 14,983 本书、8,516 个标签和 70,750 条资源标签关系。`mysql-book-import-idempotency-20260810-004` 复跑前后计数完全一致；独立只读核验确认重复外部 ID 为 0、图版本 READY/PENDING 索引为 14,983、标签引用全部可解析。导入器仅过滤 asyncmy 输出的预期 `Duplicate entry ...` 日志，避免污染证据，不改变 append-only 语义。

应用侧的 `Neo4jGraphReader` 实现 `GraphRecallPort`，只发送参数化 `MATCH` 查询，固定 `Book.graph_version`，返回稳定外部 ID 和可解释匹配词。该端口可选接入 `CandidateRecallAgent`，默认组合根仍不自动启用图召回或外部 DeepSeek。

## 确定性向量构建与 Chroma 边界

`scripts/build_vector_index_plan.py` 只读取已经审核的 MySQL 书目 ChangePlan，不连接数据库、不访问网络，也不写入 Chroma。它使用文档约定的 `HashingEmbeddingProvider`：字符 2—4 gram、384 维、非负哈希、L2 归一化、float32 little-endian base64 编码，文档格式固定为 `title\nkeywords\nabstract`。向量 ID 同时绑定 `external_id`、`content_hash`、`metadata_version` 和 `embedding_version`，因此改变模型或内容只能生成新的版本命名空间。

本轮 `vector-index-plan-20260811-001` 状态为 `PASS_WITH_WARNINGS`、`can_build=true`，生成 14,983 条向量记录，产物大小 52,019,638 bytes，SHA-256=`7714919f8e57902002d42fb39dc0ba8b2f6106c4f8c1594a691e5ea180c944ae`。数据质量提示为 2,602 条缺少摘要、2,032 条缺少关键词；空文档、重复外部 ID、重复向量 ID 和非法内容哈希均为 0。第二次独立构建 `vector-index-plan-20260811-002` 的向量文件哈希完全一致，`verify_vector_index_plan.py` 独立校验通过。

证据目录：`artifacts/verification/vector-index-plan/vector-index-plan-20260811-001/`、`artifacts/verification/vector-index-plan/vector-index-plan-20260811-002/`、`artifacts/verification/vector-index-plan/vector-index-verify-20260811-002/`。构建阶段 `database_reads=0`、`database_writes=0`、`external_store_writes=0`、`actual_delete_count=0`、`overwritten_inputs=0`、`files_deleted=0`。向量文件随后被一个新的、版本隔离的 Chroma collection 消费；它仍是可复现的源工件，不能直接推导 MySQL `embedding_status`。

`backend/app/catalog/adapters/chroma.py` 提供版本化的只读 `ChromaVectorReader`，通过依赖注入接收 collection，不导入或锁定 Chroma 客户端；它只调用 `query`，以 `$and` 元数据过滤固定 `embedding_version`/`index_version`，校验 384 维输入、返回行数、稳定 `vector_id`、`external_id` 和元数据版本，异常或超时均 fail-closed。Chroma cosine distance 按 `cosine_similarity = 1 - distance`、`score = clip((cosine_similarity + 1) / 2, 0, 1)` 转换为 `VectorRecallEvidence`；跨 collection/version、重复 ID、缺失元数据和非有限距离拒绝返回。该 adapter 尚未接入默认 Agent/HTTP，也不暴露 collection 写入或生命周期操作。

G4 的 `backend/app/catalog/runtime/g4_ports.py` 是显式研究组合工厂：它把只读 Neo4j/Chroma adapter 和确定性 query embedder 绑定到同一组 graph/embedding/index/namespace 版本，构造期不打开外部连接。`build_research_g4_http_app_from_runtime()` 只有在独立 G4 开关开启且调用方提供该 runtime 时才组装业务 HTTP；默认应用和 Compose 仍不接线。

operator-only 的 `scripts/g4_operator_runtime.py` 只使用 Chroma
`PersistentClient.get_collection()` 打开已存在的正式 collection，并在构造
runtime 前校验路径、collection 名、版本 metadata、距离度量和期望记录数；不会
使用 `get_or_create_collection()`，也不提供写入、覆盖或删除操作。其 host 入口
`scripts/verify_g4_http_host_readonly.py` 只构造内存中的 G4 HTTP 应用并执行
health GET/SELECT 预演，基础 backend 镜像因此继续不携带 Chroma 依赖。

对应端口为 `backend/app/catalog/ports/public.py` 的 `VectorRecallPort`，领域只依赖 `VectorRecallEvidence`，因此可在没有 Chroma 依赖的环境中使用 fake collection 完成契约、异常和零写入测试。当前 MySQL `embedding_status=PENDING`；Chroma collection 已构建但仍未接入默认 Agent/HTTP，避免容器启动自动开启推荐。

本轮生成并独立校验 `chroma-collection-plan-20260811-002`：状态 `PASS_WITH_WARNINGS`、`can_build=true`，collection=`library_resources__hash_char_ngram_v1`，距离度量=`cosine`，记录数=14,983，客户端锁定为 `chromadb==1.5.9`，写入仍要求命令行双确认。metadata 必须包含 `external_id`、`vector_id`、`embedding_version`、`index_version`、`namespace_name`、`metadata_version`、`graph_version`、资源类型/分类/难度/可用时间等字段；写策略固定为 `ADD_NEW_COLLECTION_ONLY`、append-only、禁止覆盖、禁止物理删除、禁止活动版本切换。用户授权后，`data/chroma` 中仅创建该新 collection 并追加 14,983 条记录；导入幂等复核为新增 0、最终 14,983/14,983，独立只读 verifier 为 `PASS`，Chroma 归一化数值误差最大约 `2.98e-8`。本阶段 MySQL 没有写入或状态投影，`actual_delete_count=0`、`files_deleted=0`。

证据目录：`artifacts/verification/chroma-collection-plan/chroma-collection-plan-20260811-002/`、`artifacts/verification/chroma-collection-plan/chroma-collection-verify-20260811-002/`、`artifacts/verification/chroma-import/chroma-import-dryrun-20260811-001/`、`artifacts/verification/chroma-import/chroma-import-20260811-001/`（首次回读兼容性阻断，现场保留）、`artifacts/verification/chroma-import/chroma-import-idempotency-20260811-002/`、`artifacts/verification/chroma-import/chroma-import-integrity-20260811-001/`。另有此前 API 探查建立的空 collection `probe_signature_20260811` 位于 `data/chroma-probe-g6-20260811`，0 条向量，未纳入正式 collection，按零删除政策保留。下一步是只读接线与召回策略评审；MySQL `embedding_status` 仍需另行授权后才能受控投影。
