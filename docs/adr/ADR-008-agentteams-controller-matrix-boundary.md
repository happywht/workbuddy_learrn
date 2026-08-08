# ADR-008：AgentTeams Controller 与 Matrix 任务边界

- 状态：Accepted
- 日期：2026-08-08
- 上游基线：`agentscope-ai/AgentTeams@90f861c05040559ecafe6dbba6cb3f466f2e4ac5`

## 证据

固定版本 Controller 只有 Team、Worker、Human、Manager、生命周期、Gateway、凭据和 AppService 资源接口，
没有 `/api/v1/tasks`、`/events`、`/messages` 或 `/cancel`。Team 响应提供 `teamRoomID` 和
`leaderDMRoomID`，但不提供 coordinator 在 Team Room 中可靠提及 Leader 所需的 Leader Matrix ID。

## 决策

1. Hub 拆分 `AgentTeamsControllerClient` 与 `MatrixClient`；Controller 只读取 Team 资源，Matrix 只使用已配置房间。
2. Hub 不创建 AgentTeams 房间，不复制完整聊天记录，不把 Matrix 消息伪装成 Controller Task。
3. 自动任务投递一期仅允许 token 身份与 `team.admin.matrixUserId` 一致、且已加入 `leaderDMRoomID` 的 Team Admin。
4. Hub ID 同时作为 Matrix transaction ID 和 `[WBH:<task_id>]` 关联标记；重试保持幂等。
5. `queued/running/...` 是 Hub 状态。只有带 `com.workbuddy.hub` 结构化扩展的状态事件才推进状态机。
6. `cancel` 是写入 Matrix 的可审计停止请求，不代表 Controller 已强制终止 Worker。
7. 固定版本 Matrix channel 使用带 Bearer token 的 `/_matrix/media/v3/download/{server}/{mediaId}` 获取 MXC 媒体。Hub 只允许显式 allowlist 内的 MXC server，限制读取字节数且拒绝重定向。
8. Hub 只保存文件校验元数据和审计事件，不保存 Matrix 文件正文；只有大小、检测 MIME 和 SHA-256 全部通过时才标记 `content_verified`。
9. 当前 Hub thin client 只处理明文结构化 `m.file`。AgentTeams channel 的 E2EE 是可选能力；加密房间必须另行实现设备密钥持久化、Megolm 解密和密钥恢复测试，不能沿用明文事件路径宣称支持。

## 后续条件

若上游增加正式任务 API、Leader Matrix ID、AppService Bridge 或可校验的 taskflow 事件，应新增契约测试并重新评审。启用 E2EE 前也必须新增加密消息、加密媒体和密钥丢失恢复的专项 ADR。
