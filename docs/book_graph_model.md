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

当前首轮计划：76 个 CSV、15,538 条来源记录、63,388 个节点、191,865 条关系；状态 `PASS_WITH_WARNINGS`，警告为 371 条 ISBN 规范化问题，目标库仍为 0/0。由于数据来源许可尚未由项目负责人明确确认，当前只执行了只读预演，未写入书目数据。
