# RecPro 前端状态页

前端显示 `/api/v1/health/live` 与 `/api/v1/health/ready` 的真实状态，并提供 G4 推荐工作台。工作台的“本地演示”是明确标注的静态 fixture，不代表真实推荐结果；真实推荐只能通过后端健康闸门和显式 G4 API 入口。

本地开发时 Vite 将 `/api` 转发到 `http://127.0.0.1:8000`。容器运行时 Nginx 将 `/api` 转发到 Compose 服务名 `backend:8000`。默认 `backend.app.main:app` 仍是 health-only；需要真实 G4 Graph/Vector 推荐 API 的本地演示时，必须显式启动 `backend.app.g4_demo_main:app`（`RECPRO_APP_ENV=demo` 且 `RECPRO_G4_HTTP_ENABLED=true`，并提供隔离 Neo4j 与已存在的 operator-only Chroma collection）。前端不会自行绕过这个闸门，也不会在未获批准的情况下提交业务请求。

若要在一次经过审查的本地浏览器演示中固定请求身份，可在启动 Vite 前设置两个 UUID v4 形状的变量：

```bash
VITE_G4_DEMO_REQUEST_ID=<reviewed-request-uuid> \
VITE_G4_DEMO_SESSION_ID=<reviewed-session-uuid> \
npm run dev -- --host 127.0.0.1
```

两个变量必须成对设置；未设置时前端为每次请求生成随机 UUID。固定身份只用于让浏览器请求与 DRY_RUN ChangePlan 一一对应，不能替代用户对精确 `plan_id`/`plan_hash` 的批准。

G4 入口示例（默认 Compose backend 不改变）：

```bash
cd ..
set -a; source .env.compose; source .env.user-secrets; set +a
RECPRO_APP_ENV=demo RECPRO_G4_HTTP_ENABLED=true \
  python -m uvicorn backend.app.g4_demo_main:app --host 127.0.0.1 --port 8000
```

```bash
npm run test
RECPRO_BUILD_RUN_ID=local-20260802-001 npm run build
RECPRO_BUILD_RUN_ID=local-20260802-001 npm run preview
```

每次构建必须使用新的小写字母、数字和连字符运行标识，产物写入 `dist/<run-id>`。目标目录已经存在时构建立即失败，不覆盖既有产物。

预览命令必须指向已经成功生成的同一运行标识。它会拒绝不存在的目录、符号链接目录或缺少普通 `index.html` 的产物，因此不会意外展示 `dist` 根目录中的旧版本。

依赖使用 `package-lock.json` 固定。`npm ci` 仅用于全新隔离构建环境；不得把它当作清理已有工作区的手段。
