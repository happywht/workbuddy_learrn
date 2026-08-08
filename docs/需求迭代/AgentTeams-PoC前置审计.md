# AgentTeams PoC 前置审计

## 目的

Phase 4 的退出门要求真实 AgentTeams、Matrix、Worker 和文件权限烟测。由于
AgentTeams 当前没有官方单机 Compose，不能用 Hub 本地 Mock 或 Controller 契约
测试替代真实部署。本轮先把部署前能自动确认的条件固化为脚本，避免安装过程中
才发现版本、工具或密钥缺失。

## 已核对的上游事实

- 审计 checkout：`C:\Users\Hitao\AppData\Local\Temp\workbuddy-upstream-audit\agentteams`。
- 当前只读审计 checkout HEAD：`90f861c05040559ecafe6dbba6cb3f466f2e4ac5`（开发分支，不是部署 pin）。
- 已核实稳定 tag：`v1.2.1` -> `552d0fb54d697b0689dafb6a01740e1a5f507552`；前置脚本默认要求该 commit。
- 官方 Helm chart：`helm/agentteams`，包含 Controller、Tuwunel、MinIO、Higress、Element 和 CRD。
- Helm 默认启用严格 LLM preflight，`credentials.llmApiKey` 是必填项；
  `credentials.adminPassword` 用于 Matrix 管理员初始化。
- Controller 任务、消息、事件和取消仍需通过 Matrix 工作流，不能调用不存在的
  Controller Task API。

## 执行

```powershell
$env:AGENTTEAMS_LLM_API_KEY = '<从 Secret Manager 注入>'
$env:AGENTTEAMS_ADMIN_PASSWORD = '<独立的 Matrix 管理员密码>'
.\deploy\agentteams-poc\agentteams-preflight.ps1 `
  -UpstreamPath "$env:TEMP\workbuddy-upstream-audit\agentteams" `
  -ControllerUrl 'https://teams-poc.example/internal/controller' `
  -MatrixUrl 'https://teams-poc.example' `
  -OutputPath '.\reports\agentteams-preflight.json'
```

脚本不会输出密钥值。退出码为 `0` 才允许继续官方 Helm/installer 部署；退出码为
`2` 表示前置条件不满足。

## 当前证据与剩余退出门

脚本和报告模板已加入工作区，但当前环境缺少可用于真实部署的 LLM API Key、
Matrix 管理员密码、隔离 Kubernetes/installer 目标，以及至少两个可运行的异构
Worker。因此 INFRA-02 仍标记为“部分”，不能报告 AgentTeams 已上线。

真实部署完成后必须补齐：

1. Controller Team Admin token、Team/Leader DM 房间和 joined-room 校验；
2. Matrix 增量同步、Hub dispatch/status/cancel 幂等回归；
3. 两个异构 Worker 的 ready、消息回传、`input_required`、取消和断线恢复；
4. MinIO/Matrix 文件的跨房间隔离、大小/MIME/SHA-256 校验；
5. 一个真实脱敏业务任务，且人类能够观察和中断全过程。
