# WorkBuddy Hub Kubernetes deployment

本目录是 Hub API 的生产部署骨架，不包含 SkillHub、AgentTeams、PostgreSQL、Trace 存储或组织 Secret Manager。当前签入内容含不可部署的镜像、域名和 Trusted Publication 路径占位符；只有生产预检零错误后才能连接集群。

## 资源与边界

- Namespace 强制 Kubernetes restricted Pod Security；
- Hub Deployment 至少 2 副本，滚动更新 `maxUnavailable=0`，包含 startup/readiness/liveness 探针、资源边界、拓扑分散和只读根文件系统；
- Service 只在集群内提供 8000，Prometheus 通过内部注解采集 `/metrics`；
- Ingress 只暴露 `/api`、`/health`、`/ready`，要求 TLS，不暴露 `/metrics`；
- 默认拒绝 ingress/egress，按入口、监控、DNS、HTTPS、PostgreSQL 和 OTLP 端口放行；正式环境应把 `0.0.0.0/0` 的 443/5432 进一步收紧为组织出口代理或固定 CIDR；
- ServiceAccount 不挂载 Kubernetes API Token；Secret 由组织 Secret Manager 创建，契约见 `secret-contract.md`；
- Deployment 只启动 Uvicorn。Alembic 迁移必须使用同一镜像的 `migration-job.yaml` 先执行成功。

资源 requests/limits 是保守起点，不是容量承诺。本地单副本只读基线已形成可重复 Profile，但不覆盖 Ingress/OIDC/上游和峰值资源；HPA、节点规格和最终副本上限必须在生产同构压测后确定，证据见 `../../docs/需求迭代/evidence/2026-08-08-Hub本地容量基线.md`。

## 发布前替换

至少替换以下内容：

1. `deployment.yaml` 与 `migration-job.yaml` 中完全相同的可拉取镜像 digest；
2. `configmap.yaml` 中 OIDC、门户、SkillHub、AgentTeams、Matrix、OTLP 地址和已实现的 Trusted Publication Grant 路径；
3. `ingress.yaml` 中主机名和 TLS Secret；
4. `network-policy.yaml` 中 Ingress/监控 Namespace 标签及生产数据库、IdP、上游和 Collector 的实际出口范围；
5. 由 Secret Manager 在 `workbuddy-hub` Namespace 创建 `hub-api-secrets`。

仓库模板检查允许占位符，用于 CI/schema 验证：

```powershell
python deploy/k8s/preflight.py --allow-placeholders --json
```

生产检查不允许占位符：

```powershell
python deploy/k8s/preflight.py --json
kubectl kustomize deploy/k8s/base
```

预检验证 10 个资源、不可变镜像、迁移/应用镜像一致、双副本与滚动策略、探针、资源、Secret 引用、受限权限、Ingress 路径和 NetworkPolicy。它不验证镜像仓库可拉取、证书签发、Secret 内容、外部地址连通或集群策略准入，这些必须在目标集群另行验收。

## 有序发布

`release.ps1` 要求显式传入当前集群 context，执行顺序为：基础资源 -> 检查外部 Secret -> 迁移 Job -> 等待迁移成功 -> Deployment 滚动更新。迁移失败会停止，不更新 Deployment；如果同名旧 Job 仍存在，脚本要求先归档日志并人工删除，不会自动清理证据：

```powershell
./deploy/k8s/release.ps1 -ExpectedContext '<production-context>'
```

脚本不会创建或输出 Secret。首次生产部署和每次数据库变更还需保留变更单、备份/恢复点、镜像 digest、迁移日志、rollout 状态和 smoke 结果。
