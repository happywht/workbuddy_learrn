# ADR-001：平台边界

- 状态：Accepted
- 日期：2026-08-08

## 决策

WorkBuddy Hub 是唯一门户、REST/MCP 稳定契约和授权编排层。SkillHub 是 Skill 权威注册表；AgentTeams 是协作运行时。三套系统不共享数据库，所有上游变化由 Hub Adapter 吸收。

## 结果

Hub 不复制 SkillHub 包内容或 Matrix 聊天记录；上游不可用时返回明确状态，案例服务继续独立可用。
