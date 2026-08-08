# ADR-014：Hub Kubernetes 发布门禁

- 状态：Accepted（模板与本地校验完成，目标集群未验收）
- 日期：2026-08-08

## 决策

1. Hub 使用独立 Namespace、ServiceAccount、ConfigMap、外部 Secret、双副本 Deployment、ClusterIP Service、TLS Ingress、PodDisruptionBudget 和默认拒绝 NetworkPolicy。
2. 镜像必须使用可拉取的 `name@sha256:<64 hex>`，迁移 Job 与 Deployment 使用完全相同的 digest。仓库中的零 digest、`.example.invalid` 和 `REPLACE_WITH_` 均是预检会拒绝的占位符。
3. Deployment 只运行 Uvicorn，不在副本启动时执行迁移。发布先运行单独 Alembic Job，只有 Job 完成后才滚动 Deployment；迁移失败不得更新应用。
4. 发布脚本必须核对显式 Kubernetes context、外部 Secret 是否存在、迁移完成和 rollout 状态。旧迁移 Job 的日志需先归档，脚本不自动删除。
5. Pod 使用 UID/GID 10001、restricted Pod Security、只读根文件系统、无 ServiceAccount Token、无 Linux capabilities，并设置探针和资源 requests/limits。
6. Ingress 只暴露 `/api`、`/health`、`/ready`。Prometheus `/metrics` 和 OTLP 只允许集群内部访问。

## 当前边界

Kustomize、Kubernetes 1.30 schema、语义预检和非 root Compose smoke 已通过。当前 requests/limits、443/5432 出口范围、Ingress/监控 Namespace 标签和副本数只是生产起点；必须在目标集群根据 CNI、Ingress、Secret Manager、证书、实际端点和压测结果调整。模板通过不等同 Kubernetes 已上线。
