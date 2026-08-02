# G1 可启动工程骨架本地验收清单

> 记录时间：2026-08-02（Asia/Shanghai）
> Gate 结论：`IN_PROGRESS / LOCAL_PASS, RUNTIME_PENDING`
> G0 交接基线：`e1c4bae03659ef43ebb81c6a6472e74ce189eef5`
> 分支：`codex/g1-runnable-skeleton`

## 1. 结论边界

G1 的代码、静态契约、隔离安装、前端生产构建和浏览器交互已在本机通过。系统当前只提供健康检查和只读状态页，`can_recommend` 固定为 `false`，推荐链路组件固定为 `DISABLED`，不能对外宣称已经具备推荐能力。

本机没有 Docker，因此五服务 Compose 的真实启动、两次停止/复启和三卷持久性尚未执行。G1 不标记为 `COMPLETED`，也不以既有数据库替代隔离运行态验收。

## 2. 已版本化产出

| 边界 | 产出 | 实现提交 |
|---|---|---|
| 后端健康切片 | FastAPI live/ready、结构化错误、日志中间件、Worker 骨架、MockLLM、配置与 MySQL readiness 端口/适配器、三份哈希依赖锁 | `5c2eb55063ab8f01af2de925993440b27d584c2c` |
| 前端状态切片 | Vue 只读状态页、严格响应校验、超时/取消控制、追加式构建与预览、非 root Nginx 容器 | `c9e780e0a2a76b7c75d9b12108551bb1132769e0` |
| 隔离运行编排 | 五服务 Compose、create-only 配置引导、新卷专用 MySQL 初始化、运行态环境校验、追加式验收证据 | `6be3e27274f752e9e86ba4039aeb4dccd68285d2` |

模块仍遵循端口—适配器方向：API 只依赖 Observability 应用服务，应用服务只依赖 readiness 端口，MySQL 和配置 Bundle 位于适配器层；LLM 通过公开端口接入 Mock 实现。前端的 domain、API、presentation 与 component 分层互不反向依赖。Compose 只负责装配，不承载业务规则。

## 3. 本地验证证据

验证环境为 Python 3.11.14、Node 25.6.0、npm 11.8.0 和 MySQL 客户端 9.3.0。Python 使用从零创建的 `.venv-g1-release-py311`，三份锁以 `--require-hashes` 安装，`pip check` 报告无损坏依赖。

| 检查 | 结果 |
|---|---|
| `make verify-g0 PYTHON=.venv-g1-release-py311/bin/python` | PASS；安全扫描 96 个文件、架构扫描 33 个文件、文档 16 个 Markdown/42 个结构化块、8 个 JSON 契约均无问题；G0 测试 67 + 28 + 36 = 131 项通过 |
| `make test-g1-python PYTHON=.venv-g1-release-py311/bin/python` | PASS；100 项通过 |
| G1 编排与容器定向回归 | PASS；47 项通过 |
| 全新隔离前端安装 | PASS；`npm ci --ignore-scripts` 新增 174 个依赖包并审计 175 个包，0 个已知漏洞 |
| 前端测试与类型检查 | PASS；33 项 Vitest 测试通过，`vue-tsc --noEmit` 通过 |
| 追加式生产构建 | PASS；新目录 `dist/g1-final-20260802-002`，未复用或清空旧目录 |
| 浏览器验收 | PASS；1280×720 与 390×844 均无横向溢出；阶段边界和推荐禁用状态可见；刷新实际重新请求 live/ready |
| `git diff --check` 与删除项审计 | PASS；无空白错误、无已跟踪文件删除项 |

隔离构建目录保留在本机 `/tmp/recpro-g1-frontend-final2.CRsLqJ`。它不是长期证据库，以下摘要用于复核锁文件与产物是否一致：

| 对象 | SHA-256 |
|---|---|
| `backend/requirements-g0.lock` | `09ebbde87be771de54d2bb84a8e4dd5ab8336114a8a25cab9610a242c8e097ac` |
| `backend/requirements-g1.lock` | `98931eea6016e8e55764d35ddc7a78fd99c73e64d1019b1a03f2af621ad62677` |
| `backend/requirements-g1-test.lock` | `f0ceeb18bbb7a14f3ec5c3b6da31ee1493ec2c70867f408e6708ee8536df4d2c` |
| `frontend/package-lock.json` | `6edf388ac2d5ee1f71604178eec0d0a8529d7ca503083d5b0fdcd29c5fcecb5a` |
| 配置 JSON Schema | `2783a75736fe21d39f2ef3101fa9f9849f1ac3757d0a05c50d656b5169ab6bd1` |
| 构建 `index.html` | `cef534b19b3a6415b387a46d9532aa3bd3eabab01da6557058743c1bf3a9e47c` |
| 构建 CSS | `fa4b6d9cf28850ed6f13b1b0af866f7f976fb763bc0a6a9f0f1b2febf086cffe` |
| 构建 JavaScript | `d06bf02d76735a9b026f70a6d5fd9d5b82cfe60a8eb061a450874a49a3f65489` |

## 4. 安全审计

- 既有数据库连接、读取、写入和物理删除次数均为 0。
- Git 受跟踪文件删除数量为 0；从 G0 交接基线到当前分支没有 `D` 或 `R` 差异。
- 所有 `.DS_Store` 和其他用户元数据均保留，未纳入版本管理。
- 首次普通 Vite 构建曾由默认 `emptyOutDir=true` 自动删除 1 个被 Git 忽略的历史 JavaScript 生成物，并重写 2 个被忽略的生成物。该未批准偏差编号为 `G1-INC-20260802-001`，旧 JavaScript 无独立备份，不能声称字节级恢复。
- 偏差发生后，生产构建已改为 `emptyOutDir=false` 且必须使用全新 run id；目标存在、路径越界或符号链接都会 fail-closed。此后没有再次删除或覆盖构建产物。

## 5. 待补运行态验收

Docker 和 `gh` 均不在当前主机 PATH。未执行 Compose、未创建容器/网络/卷、未推送远程，也未创建 Pull Request。

在具备 Docker Compose 且确认是全新隔离项目名的主机上，下一步唯一允许的 Gate 动作是：先运行 create-only bootstrap，再运行 `RUN_ID=<新的唯一值> make verify-g1-runtime`。验收器必须确认项目此前不存在、五个服务健康、MySQL 运行用户只有最小权限、探针行在两次 `stop`/`up` 后保持唯一、三个卷身份不变，并将证据写入新的 `artifacts/verification/g1/<run-id>`。不得使用 `down`、删卷、清库或连接既有数据库来完成验收。
