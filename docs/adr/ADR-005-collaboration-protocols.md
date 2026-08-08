# ADR-005：协作协议边界

- 状态：Accepted
- 日期：2026-08-08

## 决策

AgentTeams 内部协作继续使用 Matrix/Element 及其 Controller 边界。A2A 仅作为后续跨平台 Agent Card 和任务互操作入口，不取代 Matrix 群聊、人工介入和房间文件能力。

## 结果

Hub 维护自身任务状态、Matrix dispatch event ID、房间 ID 和 sync 游标。Controller 不提供 Task API；
Matrix 普通文本消息不直接改变任务状态，只有 Hub 结构化扩展事件才能推进状态机。具体适配约束见 ADR-008。
