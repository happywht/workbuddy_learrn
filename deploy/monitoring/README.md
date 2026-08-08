# Hub PoC monitoring

本目录提供 Hub API 的内部 Prometheus 采集和首批告警规则。它验证指标可采集、规则可加载，不包含生产 Alertmanager、通知渠道、长期存储或 Trace 后端。

先配置 `deploy/compose-poc/.env`，再从仓库根目录启动：

```powershell
docker compose -p workbuddy-hub-poc `
  -f deploy/compose-poc/compose.yaml `
  -f deploy/compose-poc/compose.monitoring.yaml `
  up -d --build --wait
python deploy/compose-poc/smoke.py http://127.0.0.1:8100
python deploy/compose-poc/monitoring_smoke.py http://127.0.0.1:19090
```

Prometheus 镜像固定为 `v3.5.0` 的多架构 digest。PoC 在宿主机映射 `19090` 便于验收；生产不应通过公网 Ingress/Nginx 暴露 Prometheus 或 Hub `/metrics`，应使用集群内部网络策略和采集身份。

当前规则：

- Hub 指标目标持续 2 分钟不可用；
- 在请求速率超过 0.1 次/秒时，5xx 比例持续 10 分钟高于 5%；
- 在目录请求速率超过 0.1 次/秒时，统一目录 p95 持续 10 分钟高于 1 秒。

流量门槛避免极低流量下单次失败触发比例告警。这些是试点初值，不是已验收 SLO。生产上线前必须用真实流量和压测校准，并配置 Alertmanager 去重、抑制、升级路径和值班负责人，再执行一次真实告警触达演练。

## Trace Collector PoC

`compose.tracing.yaml` 使用固定 digest 的 OpenTelemetry Collector `0.130.1`，只在 Compose 内部接收 OTLP/HTTP Trace。PoC 将 Span 输出到 Collector debug exporter，不提供长期存储：

```powershell
docker compose -p workbuddy-hub-poc `
  -f deploy/compose-poc/compose.yaml `
  -f deploy/compose-poc/compose.tracing.yaml `
  up -d --build --wait
python deploy/compose-poc/tracing_smoke.py `
  http://127.0.0.1:8100 http://127.0.0.1:18889 http://127.0.0.1:13134
```

smoke 通过标准是 Hub 返回与输入一致的 W3C trace ID，且 Collector 自身指标至少记录 1 个通过 OTLP/HTTP 接收的 Span。PoC 不映射 4318 到宿主机；生产需改用集群 Service、NetworkPolicy、TLS/mTLS、持久 Trace 后端和 RBAC 检索权限。
