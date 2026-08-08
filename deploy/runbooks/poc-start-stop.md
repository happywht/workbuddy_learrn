# Hub PoC 启停与回滚

## 前置检查

1. 使用隔离测试主机，不复用当前静态生产主机。
2. 从 `.env.example` 生成本机 `.env`，替换数据库密码；Token 只放 Secret/环境变量。
3. `AUTH_MODE=local_header` 只允许用于本地 PoC。连接组织环境时切换到 `oidc`，配置固定 HTTPS issuer、audience、组和部门 Claim；用伪造 `X-Actor-Id`、错误 issuer/audience、过期 Token 和跨部门账号执行拒绝烟测。
4. SkillHub、AgentTeams 分别部署并固定 release/digest；本 Compose 不共享它们的数据库或 Bucket。

## 启动与验收

```powershell
docker compose config
docker compose up -d --build
docker compose ps
.\smoke.ps1 -BaseUrl http://127.0.0.1:8100
```

验收还需检查：

- `GET /api/v1/artifacts?kind=case` 返回 4 个案例；
- `case-capacity` 标题仍为 `项目资料交付检查`；
- 未配置 SkillHub/AgentTeams 时返回明确 `503`，不返回模拟成功；
- 每个响应返回 `X-Request-Id`，`GET /metrics` 包含请求计数、耗时和处理中请求指标，动态工件/任务 ID 不进入标签；
- 配置真实上游后，执行固定版本 Skill 安装计划和协作任务创建/状态/取消契约测试。
- OIDC 模式下匿名仍只能看到公共案例；个人、部门和组织范围分别按 `sub`、部门 Claim 和已验证组织身份授权。

`/metrics` 仅供容器或集群内部 Prometheus 采集。示例 Nginx 不代理该路径；生产需用 NetworkPolicy、采集身份和 TLS/mTLS 限制访问。访问日志不得采集 Authorization、Cookie、请求体、原始 URL 或查询值。告警接收人、阈值、保留期和容量需在生产同构环境压测后冻结。

需要验证内部采集时，叠加 `deploy/compose-poc/compose.monitoring.yaml` 启动固定 digest 的 Prometheus，再执行 `monitoring_smoke.py`。验收必须同时看到 Hub target 为 `up` 和 3 条规则加载；PoC 页面可打开不等同通知触达成功。

Trace 默认关闭导出。接入 Collector 时只允许配置无内嵌凭据的完整 OTLP/HTTP `/v1/traces` 地址，先用低采样率验证 `X-Trace-Id -> JSON access log -> Collector span -> provider traceparent` 的同一 trace ID，再逐步放量。验收记录不得包含 Token、请求体、查询值或异常消息。

隔离 PoC 可叠加 `compose.tracing.yaml` 并执行 `tracing_smoke.py`。脚本必须确认输入 trace ID 与 Hub `X-Trace-Id` 一致，且 Collector 的 `otelcol_receiver_accepted_spans` 指标大于 0；仅看到 Collector 容器运行不算通过。

## 回滚

1. 保留上一版镜像 digest，不覆盖同一标签。
2. 数据库迁移先执行 `python -m hub_api.migrate`（当前 head 为 `0005_publication_scan_rules`）；任何失败都必须阻止 API 启动。
3. 回滚应用镜像前确认数据库迁移是否向后兼容；当前 `0001_initial` 不允许在含业务数据的环境直接执行 downgrade。
4. 回滚后重新执行健康检查、4 案例兼容烟测和只读 Skill 查询。

## 备份与隔离恢复演练

创建备份时使用 PostgreSQL custom format，并同时保存 SHA-256、Alembic 版本和 7 张 Hub 表的行数清单：

```powershell
python ..\compose-poc\backup.py `
  --project workbuddy-hub-poc `
  --env-file ..\compose-poc\.env `
  --output-dir D:\workbuddy-backups
```

恢复演练只能写入脚本生成的 `workbuddy_hub_restore_<8位随机值>` 临时数据库，并使用独立端口启动临时 Hub：

```powershell
python ..\compose-poc\restore_drill.py D:\workbuddy-backups\workbuddy-hub-<timestamp>.dump `
  --project workbuddy-hub-poc `
  --env-file ..\compose-poc\.env `
  --restore-port 18101
```

通过标准为：Manifest 哈希和大小一致、迁移版本一致、7 张表行数一致、`case-capacity` 标题正确、恢复实例 `/ready` 通过，并完成包含 MCP 工具列表的 smoke。脚本结束后删除临时 API 容器和临时数据库，不删除源 volume、源数据库或备份文件。

## 停止

```powershell
docker compose down
```

默认保留 PostgreSQL volume。只有确认数据可丢弃并完成备份后，才允许人工删除 volume。
