# WorkBuddy Hub 架构决策记录

| ADR | 状态 | 决策 |
|---|---|---|
| ADR-001 | Accepted | Hub 是统一入口和稳定契约，SkillHub/AgentTeams 独立部署 |
| ADR-002 | Accepted | Case 归 Hub，Skill 归 SkillHub，统一目录只做投影 |
| ADR-003 | Accepted | 组织内部范围使用认证 Namespace，不映射匿名 global |
| ADR-004 | Accepted | Skill 发布使用 Trusted Publication Grant，不共享超级管理员代发凭据 |
| ADR-005 | Accepted | AgentTeams 内部使用 Matrix；A2A 只作为后续外部边界 |
| ADR-006 | Accepted | 当前采用主动 Connector；出现受支持 headless/API 证据后再评审完整 Worker |
| ADR-007 | Accepted | PoC 与静态生产主机隔离；后端容器化、可迁移和可回滚 |
| ADR-008 | Accepted | Controller 只管资源，任务走 Matrix；一期自动投递仅支持 Team Admin 的 Leader DM |
| ADR-009 | Accepted | OIDC Bearer JWT 提供稳定 Subject，Claim 驱动个人/部门/组织可见性 |
| ADR-010 | Accepted | 版本不可变、报告隐藏、Owner 回滚，评分/报告使用幂等审计事件 |
| ADR-011 | Accepted | 仓库和工作区执行不输出凭据值的 Secret 扫描，历史凭据仍须轮换和审计 |
| ADR-012 | Accepted | 前端统一认证引导；远程只使用 Bearer，本地才允许 actor header |
| ADR-013 | Accepted | 请求 ID、低基数指标和脱敏 JSON 日志构成 Hub 可观测性基线 |
| ADR-014 | Accepted | Kubernetes 发布先迁移后滚动，镜像 digest 一致且占位符必须被生产预检拒绝 |
| ADR-015 | Accepted | `uv.lock` 导出哈希锁；固定基础镜像，依赖审计、镜像漏洞和 CycloneDX SBOM 作为 CI 门禁 |

ADR-006 已按当前证据冻结为主动 Connector，不将桌面 UI 自动化作为完整 Worker 的替代品。
