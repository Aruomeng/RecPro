# LibraMAS 全局 Agent 工作区一致性阶段交接

```text
交接 ID：AGENT-WORKSPACE-CONSISTENCY-20260830-001
范围：前端全局 Agent Workspace 的身份切换、重连和并发观察
状态：CODE_COMPLETE / FRONTEND_VALIDATION_PASS
```

## 本阶段产出

- 为每次 Workspace 初始化分配独立 generation 和 AbortController；旧 SSE 流的事件、失败回调不会覆盖新 Workspace。
- `observe` 与 Directive action 捕获 Workspace generation 和 ID，身份切换或重连后返回结果自动丢弃，过期异常不会把当前工作区标记为降级。
- 同一 Workspace 的快照按 `context_version` 单调接收；相同上下文版本再按公开事件序号防止旧响应覆盖新状态。
- 停止 Workspace 时取消事件流、清理 Agent/事件/Directive/数据源快照和错误状态，避免页面生命周期结束后残留敏感会话状态。
- 事件回调增加 generation 边界，即使底层流实现延迟交付已解析事件，也不会写入新工作区。

## 验证证据

- 新增 `frontend/src/stores/agentWorkspace.spec.ts`：旧流失败隔离、工作区替换后的 observation 隔离、并发 observation 乱序收敛，共 3 项测试。
- `vue-tsc --noEmit`：通过。
- Vitest：19 个测试文件、81 项测试全部通过。
- `git diff --check`：通过。

## 安全与兼容边界

- 仅修改浏览器内存运行时和事件消费顺序；不改变后端 Workspace API、SSE 契约或 8 个 Agent 身份。
- 没有连接 MySQL、Neo4j、Chroma，没有执行迁移、业务写入、审计追加或 DeepSeek 请求。
- 没有删除文件、数据库记录、数据库、容器或数据卷；删除数量均为 0。

## 后续边界

后续可在同一一致性边界上补充浏览器视觉/交互验收；任何真实业务 POST、审计事实、图谱导入、账号数据或新增模型请求仍须先生成独立精确 ChangePlan 并取得批准。
