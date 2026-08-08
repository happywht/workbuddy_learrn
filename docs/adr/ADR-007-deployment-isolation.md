# ADR-007：部署隔离与可恢复性

- 状态：Accepted
- 日期：2026-08-08

## 决策

PoC 不在现有静态生产主机直接试装。Hub、SkillHub、AgentTeams 独立容器/Namespace、数据库、Bucket、ServiceAccount 和网络策略；入口统一 TLS，但管理面不共享。

## 结果

Hub 使用 Alembic migration、健康检查和固定镜像版本；静态 SFTP 同步脚本不承担后端发布。删除 volume 不属于常规回滚步骤。

生产 Kubernetes 模板使用独立 Namespace 和 ServiceAccount、双副本、TLS Ingress、默认拒绝 NetworkPolicy、PodDisruptionBudget 及受限非 root 容器。迁移由单独 Job 在 Deployment 滚动前执行，二者必须使用同一镜像 digest；目标集群的 Secret、证书、CNI 和准入策略仍需环境验收，见 ADR-014。

PoC 备份使用 PostgreSQL custom format，并附带 SHA-256、Alembic 版本和核心表行数清单。恢复演练只能写入脚本生成的临时数据库，使用独立 Hub 容器完成 health、案例兼容和 MCP smoke 后清理；不得覆盖源数据库。生产完成标准仍要求加密异地备份、保留策略、告警及按正式 RPO/RTO 执行的恢复演练。
