# ARCH-01：WorkBuddy 可编程接入验证

> 日期：2026-08-08
> 结论：一期采用主动协作 Connector（档位 B）

## 当前证据

| 能力 | 仓库证据 | 结论 |
|---|---|---|
| 主动调用 Registry | `workbuddy-hub/agent-skill/SKILL.md`、`references/publish-api.md` 明确要求通过 Connector session 调用 MCP/HTTP | 已有契约基础 |
| 身份传递 | 现有契约规定 actor 来自认证 Connector/session，不能放入包 JSON | Hub 已实现 OIDC JWT 验签与 `sub`/部门映射；真实 IdP 和 Connector Token 注入未验收 |
| Headless/API 唤醒 | 当前项目和已核验资料没有受支持入口 | 未证明 |
| 事件回调/流式回传 | 当前项目没有 WorkBuddy 回调契约或 SDK | 未证明 |
| 取消 | Hub/AgentTeams 侧已有取消契约，WorkBuddy 自身取消能力没有证据 | 未证明 |
| 文件双向交换 | 有 Connector 读取业务材料的培训说明，没有无头 Worker 文件交换证据 | 未证明 |

## 采用方式

WorkBuddy 在用户已登录会话内主动调用 Hub MCP/REST：

1. `registry.search/get/install_plan` 查询和准备 Skill；
2. `registry.publish_preview/publish` 在用户确认后发布；
3. `collab.teams/create_task/status/events/send/cancel` 进入 AgentTeams 协作；
4. Hub 保存任务 ID、状态、事件游标和审计，WorkBuddy 不需要保持页面在线。

WorkBuddy 不能被描述为 AgentTeams 自治 Worker，不能依靠桌面 UI 自动化实现后台唤醒。

## 重新评审门槛

同时满足以下条件才允许把 ADR-006 改为完整 Worker：

- 厂商提供受支持、可版本固定的 headless/API 或 SDK；
- 能接收任务并提供事件回调或可恢复游标；
- 取消、超时、文件上传下载和身份委托可测试；
- 无桌面会话运行、安全隔离和审计演练通过。
