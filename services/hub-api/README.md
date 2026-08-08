# WorkBuddy Hub API

Phase 0/2 的最小服务端骨架：把现有 `workbuddy-hub/data/registry.json` 导入版本化的案例目录，并提供统一目录 REST API。SkillHub 与 AgentTeams 适配器在此服务之上逐步加入。

## 本地运行

在仓库根目录执行：

```powershell
cd services/hub-api
uv sync --extra dev --extra postgres
uv run python -m hub_api.migrate
uv run python -m hub_api.seed
uv run uvicorn hub_api.main:app --reload --port 8000
```

接口：

- `GET http://127.0.0.1:8000/health`
- `GET http://127.0.0.1:8000/ready`
- `GET http://127.0.0.1:8000/metrics`（仅内部 Prometheus 采集，不经公网 Nginx 代理）
- `GET http://127.0.0.1:8000/api/v1/artifacts?kind=case`
- `POST http://127.0.0.1:8000/api/v1/mcp` (JSON-RPC 2.0 `initialize`, `tools/list`, `tools/call`)
- `GET http://127.0.0.1:8000/docs`

所有 HTTP 响应带 `X-Request-Id`；合法调用方 ID 会原样返回，缺失或非法时由 Hub 生成 UUID。
访问日志为单行 JSON，只包含请求 ID、方法、路由模板、状态和耗时，不记录 Token、请求体或查询值。
Prometheus 请求计数和耗时以路由模板为标签，不使用工件 ID、任务 ID、用户或查询词；业务审计仍以数据库审计事件为准。

配置 `HUB_OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` 后，Hub 使用 W3C `traceparent` 建立服务端 Span，
将 `trace_id`/`span_id` 写入访问日志并以 `X-Trace-Id` 返回，同时向默认 SkillHub、AgentTeams、Matrix
和 OIDC `httpx` 客户端传播上下文。端点必须是无内嵌凭据、无查询参数的 HTTP(S) `/v1/traces` URL；
未配置时不创建导出器，也不会向外部发送 Trace。配置项：

- `HUB_OTEL_SERVICE_NAME`：服务资源名称，默认 `workbuddy-hub-api`；
- `HUB_OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`：完整 OTLP/HTTP Trace 接收地址；
- `HUB_OTEL_TRACE_SAMPLE_RATIO`：本地根 Span 采样率，默认 `0.1`；
- `HUB_OTEL_EXPORT_TIMEOUT_SECONDS`：单次导出超时，默认 5 秒。

Trace 只记录方法、路由模板、状态码和异常类型，不记录原始 URL、查询串、请求体、认证头或异常消息；
出站只传播 `traceparent`，不传播 baggage。生产仍需在受控 Collector/后端上验证 TLS、租户隔离、保留期、
检索权限和端到端链路，代码级 OTLP 测试不等同生产 Trace 已上线。

当 `HUB_SKILLHUB_BASE_URL` 已配置时，`GET /api/v1/skills?q=...` 和
`GET /api/v1/skills/{slug}` 会通过受控适配器读取 SkillHub；未配置时明确返回
`503 skillhub_adapter_not_configured`。协作入口 `GET /api/v1/collaboration/teams`
读取 AgentTeams Controller 的真实 `/api/v1/teams`；任务、消息和取消请求通过 Matrix Client-Server API
投递，不调用 AgentTeams 中不存在的 `/api/v1/tasks`。协作和发布写接口要求统一身份；上游收到的
`X-Actor-Id` 由 Hub 根据已验证身份的 `sub` 生成，不信任浏览器传入值。

统一目录 `GET /api/v1/artifacts?q=...` 会把本地案例和 SkillHub 搜索结果组合为同一响应；
Skill 详情仍实时读取 SkillHub。`POST /api/v1/artifacts/{artifact_id}/install-plans`
生成固定版本、来源、校验和和安装目录，不执行包内脚本。

协作任务写入 Hub 自有任务 ID、Matrix dispatch event ID、房间、Hub 状态和内部 Matrix sync 游标，并提供状态、事件、
有界等待、任务产物元数据、消息和取消请求接口。客户端使用 Hub 自有事件 ID 作为 `cursor`，不会接触 Matrix
`next_batch`；断线后可从上次 `next_cursor` 继续读取，Matrix 暂不可用时响应会明确标记 `sync.degraded`。
`Idempotency-Key` 同时生成稳定 Hub ID 和 Matrix transaction ID，防止重试重复发消息。
MCP 写工具在 `contracts/mcp/hub-tools.json` 中声明并强制携带 `idempotency_key`；MCP 与 REST
共享同一身份、授权、审计和上游适配器，不另建一套业务状态。
固定的 AgentTeams 版本只向 Hub 暴露 Team Admin 的 `leaderDMRoomID`，没有暴露 coordinator 投递所需的
Leader Matrix ID，因此自动投递当前仅支持 Matrix 身份与 `team.admin.matrixUserId` 一致且已加入 Leader DM 的账号。
取消是可审计的协作请求，不是 Controller 强制终止。

`GET /api/v1/collaboration/tasks/{task_id}/wait` 最多等待 25 秒；
`GET /api/v1/collaboration/tasks/{task_id}/artifacts` 只返回带结构化 `task.artifact` 信封的 Matrix
`m.file` 元数据。未经校验时响应标记 `verification_status=metadata_only` 和 `content_verified=false`。
`POST /api/v1/collaboration/tasks/{task_id}/artifacts/{artifact_id}/verify` 只接受配置 allowlist 中的 MXC server，
通过固定 AgentTeams 版本使用的 `/_matrix/media/v3/download` 路由和 Matrix Bearer token 受限读取内容，校验大小、
MIME 和 SHA-256 并持久化审计结果。Hub 不写入或返回文件正文，也不向浏览器暴露 Matrix token。
通过只代表完整性检查，响应仍固定 `safe_to_execute=false`，不能替代恶意代码或宏安全扫描。当前 thin Matrix
client 只识别明文结构化 `m.file`；E2EE 房间需要持久化设备密钥和 Megolm 解密能力，尚未实现。

配置边界：

- `HUB_AGENTTEAMS_BASE_URL` / `HUB_AGENTTEAMS_TOKEN`：AgentTeams Controller；
- `HUB_AGENTTEAMS_MATRIX_URL` / `HUB_AGENTTEAMS_MATRIX_TOKEN`：Matrix homeserver 与专用 Team Admin token；
- `HUB_AGENTTEAMS_MATRIX_USER_ID`：可选的 token 身份固定值，`whoami` 不一致时拒绝投递。
- `HUB_AGENTTEAMS_MATRIX_MEDIA_SERVER_ALLOWLIST`：允许校验的 MXC server 名称，逗号分隔；为空时拒绝内容校验；
- `HUB_AGENTTEAMS_MATRIX_MEDIA_MAX_BYTES`：单个媒体对象的最大读取字节数，默认 25 MiB。

不要使用全局 Admin token 作为所有用户的共享代理身份。生产环境需把 OIDC subject 映射为独立 Matrix Human，
或增加受控的每用户 token broker；当前固定服务账号只用于隔离 PoC。
静态协作页本地调试可使用 `?apiBase=http://127.0.0.1:8100&actor=local-user`；`actor` 查询参数仅在
API 主机为 `localhost` 或 `127.0.0.1` 时读取，生产页面仍必须注入 `window.WORKBUDDY_ACTOR_ID`。

`HUB_AUTH_MODE=local_header` 只用于 `HUB_ENV=local` 的 PoC，通过 `X-Actor-Id` 模拟身份。
`HUB_AUTH_MODE=oidc` 时只接受 `Authorization: Bearer <JWT>`，使用 OIDC Discovery/JWKS 验证
`RS256` 签名、issuer、audience、expiry、kid 和 `sub`，并忽略客户端伪造的 `X-Actor-Id`。
公共案例允许匿名读取；`personal` 按 owner `sub`、`department` 按部门 Claim、`organization`
按组织 IdP 的已验证身份授权。配置项：

- `HUB_OIDC_ISSUER_URL` / `HUB_OIDC_AUDIENCE`：固定的 HTTPS issuer 与 Hub audience；
- `HUB_OIDC_GROUPS_CLAIM` / `HUB_OIDC_DEPARTMENT_CLAIM`：组与直接部门 Claim 名；
- `HUB_OIDC_DEPARTMENT_GROUP_PREFIX`：从组 Claim 映射部门的前缀，默认 `department:`；
- `HUB_OIDC_JWKS_CACHE_SECONDS` / `HUB_OIDC_CLOCK_SKEW_SECONDS`：JWKS 缓存和时钟偏差。

`sub` 必须是组织内稳定且不会复用的 Subject。真实 IdP、Claim 名称、离职/调岗传播时限和
Namespace 同步仍需组织侧确认；仅填写示例值不构成 SSO 验收。

Skill 发布必须同时配置 `HUB_SKILLHUB_PUBLISH_PATH` 并提供
`X-WorkBuddy-Publication-Grant`。它面向 SkillHub 的 Trusted Publication Grant 扩展点，
不能用通用超级管理员 Token 替代。每个预览 ID 同时作为 Hub 结果记录和上游
`Idempotency-Key`；相同确认重试返回第一次结果，不重复创建案例版本或审计事件。

预览扫描会固化 `rules_version`，检查清单路径/符号链接、声明 MIME 与扩展名、许可证字段、
依赖版本以及脚本/二进制/宏风险。当前服务接收的是结构化 Manifest；真实上传压缩包仍需在
SkillHub/对象存储接入阶段执行内容级 Zip、MIME、许可证和依赖扫描，Manifest 通过不代表包可执行安全。

案例发布后可通过 `/versions` 创建新的不可变版本，通过 `/reports` 进入 `reported` 隐藏状态，
通过 `/rollback` 在明确确认后恢复已有版本；`/ratings` 和 `/reports` 使用幂等键并写入追加审计。

现有案例页默认继续读取静态 `data/registry.json`。验证 Hub API 迁移时，可在 URL 加
`?api=1`，或在浏览器控制台设置 `localStorage.workbuddyHubApi = "1"`，并提供
`window.WORKBUDDY_HUB_API_URL`；API 失败会自动回退静态数据。

默认使用本地 SQLite；生产通过 `HUB_DATABASE_URL` 切换到 PostgreSQL。`HUB_SEED_DEMO_CASES=true` 只适合本地/演示，不得作为生产数据初始化策略。

容器镜像默认使用 UID/GID 10001。Compose 为单实例 PoC，仍在容器启动时迁移；生产 Kubernetes
必须使用 `deploy/k8s/migration-job.yaml` 先完成单独迁移，再滚动只运行 Uvicorn 的双副本 Deployment，
避免多个副本并发执行迁移。

生产镜像从 `uv.lock` 导出 `requirements.lock`，使用固定 Alpine digest、精确版本、哈希和 binary-only
安装，并从最终运行时删除 `pip`。从仓库根目录执行
`python tools/supply_chain_scan.py --output-dir artifacts/supply-chain` 可验证锁漂移、依赖漏洞、镜像漏洞和
CycloneDX SBOM；策略与例外流程见 `deploy/supply-chain/README.md`。

## 测试

```powershell
cd services/hub-api
uv sync --extra dev
uv run pytest
```
