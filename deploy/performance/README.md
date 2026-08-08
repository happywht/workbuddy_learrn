# Hub local capacity probe

`hub_load_probe.py` 对 Hub 的只读端点执行有界并发请求，并输出吞吐、错误率、状态码和 p50/p95/p99。默认只允许 localhost，拒绝认证信息和写接口，最多 100,000 请求、200 并发、单响应读取 2 MiB。

必须在隔离环境运行，不要直接对现有静态生产主机、组织入口或未经授权的外部地址压测：

```powershell
python deploy/performance/hub_load_probe.py `
  'http://127.0.0.1:18170/api/v1/artifacts?kind=case' `
  --requests 1000 --concurrency 20 --warmup 50 `
  --max-error-rate 0 --max-p95-ms 1000
```

远程目标必须显式增加 `--allow-remote`，这只解除工具护栏，不代表获得压测授权。

本机单副本结果只用于证明工具链、发现明显回归和形成后续压测 Profile。正式容量必须在生产同构环境覆盖双副本、真实 Ingress/TLS/OIDC、PostgreSQL、SkillHub、Matrix、OTLP、典型包大小和并发长轮询，并观察 CPU、内存、连接池、数据库锁、5xx、p95/p99 和恢复时间后再确定 requests/limits、HPA 与 SLO。
