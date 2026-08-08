# WorkBuddy Hub PoC

此 Compose 只启动 Hub API 和它自己的 PostgreSQL。SkillHub、AgentTeams 各自拥有数据库、对象存储和网络边界，不能把它们的生产容器直接合并到这个文件中。

## 启动

```powershell
Copy-Item .env.example .env
# 修改 .env 中的 POSTGRES_PASSWORD
docker compose up -d --build
Invoke-WebRequest http://127.0.0.1:8100/health
Invoke-WebRequest http://127.0.0.1:8100/metrics
```

`/metrics` 和 `X-Request-Id` 用于 PoC 内部诊断。生产入口不应公开 `/metrics`；应由受限的内部 Prometheus 采集，并在生产同构环境另行验证告警触达、保留期和容量。

## Backup and restore drill

Create a PostgreSQL custom-format backup plus a SHA-256, migration and table-count manifest:

```powershell
python backup.py --project workbuddy-hub-poc --env-file .env --output-dir .\backups
```

Restore one backup into a generated `workbuddy_hub_restore_<suffix>` database, launch a temporary Hub container on a separate port, run the complete smoke check, and remove the temporary container/database:

```powershell
python restore_drill.py .\backups\workbuddy-hub-<timestamp>.dump `
  --project workbuddy-hub-poc --env-file .env --restore-port 18101
```

The drill never restores over `POSTGRES_DB`. A successful backup file alone is not recovery evidence; retain the manifest and the successful drill output together.

## 内部监控

使用 `compose.monitoring.yaml` overlay 可启动固定 digest 的 Prometheus，并执行 `monitoring_smoke.py` 验证 Hub target 和 3 条规则。完整命令、规则语义和生产边界见 `../monitoring/README.md`。

## 停止

```powershell
docker compose down
```

## 上游平台

- SkillHub：使用固定 release 镜像或上游 Compose，配置公开 URL、OIDC、PostgreSQL、Redis、S3/MinIO 后再把 `SKILLHUB_BASE_URL` 指向其后端。
- AgentTeams：使用固定 release/Helm，配置 HTTPS、Matrix、Higress、MinIO 和 Worker；`AGENTTEAMS_BASE_URL` 指向 Controller，`AGENTTEAMS_MATRIX_URL` 指向 Matrix homeserver。Matrix token 必须属于隔离 PoC 的 Team Admin，并用 `AGENTTEAMS_MATRIX_USER_ID` 固定校验身份。

当前 Hub API 在上游地址未配置时仍可提供案例目录；对 Skill/协作写操作必须返回“适配器未配置”，不能模拟成功。

Trace 默认不导出。需要接入受控的 OTLP/HTTP Collector 时设置 `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`
为完整 `/v1/traces` 地址，并按需调整 `OTEL_TRACE_SAMPLE_RATIO`；不得在 URL 中放凭据或查询 Token。
代码与本机 OTLP 测试只证明协议和数据最小化边界，生产 Collector、存储和检索权限需单独验收。
需要验证真实接收时叠加 `compose.tracing.yaml`，并执行 `tracing_smoke.py`；固定 digest、端口和通过标准见 `../monitoring/README.md`。

组织身份接入时将 `AUTH_MODE` 改为 `oidc`，并填写 `.env.example` 中的 issuer、audience、组 Claim、
部门 Claim 和 group 前缀。issuer 必须是 HTTPS。上线前必须用真实账号验证个人、同部门、跨部门、
组织和匿名五组访问矩阵；本地 RSA/JWKS 测试通过不等于真实 SSO 已验收。

Hub API 容器启动前自动执行 Alembic migration。它可以收编本项目早期由 `create_all`
创建的已知 PoC 数据库；未知或部分数据库结构不会被自动 stamp。生产变更和回滚按
`../runbooks/poc-start-stop.md` 执行。

门户新增：

- `/skills/`：SkillHub 搜索与固定版本安装计划；
- `/collaboration/`：Team 查询、任务创建、状态刷新和取消；
- `/community/?api=1`：案例页切换到 Hub API，并保留静态 JSON 回退。
