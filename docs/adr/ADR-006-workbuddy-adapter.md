# ADR-006：WorkBuddy 协作接入档位

- 状态：Accepted（主动 Connector）
- 日期：2026-08-08

## 待验证问题

1. 是否存在受支持的 headless/API 调用；
2. 是否支持事件回调或可恢复轮询；
3. 是否支持取消、文件上传下载和身份委托；
4. 是否能在无桌面会话条件下安全运行。

## 决策

当前仓库只能证明 WorkBuddy Skill/Connector 会话能够主动调用 Registry MCP/HTTP，并要求身份来自 Connector session；没有受支持的 headless 启动、事件回调、无会话唤醒、取消或双向文件交换证据。因此一期采用用户会话内主动调用 Hub MCP/HTTP 的 Connector。

不得使用桌面 UI 自动化模拟自治 Worker，也不得宣传 WorkBuddy 已可自主入群。后续只有在厂商提供受支持接口并完成回调、取消、断线恢复和文件测试后，才重新评审完整 Worker Adapter。
