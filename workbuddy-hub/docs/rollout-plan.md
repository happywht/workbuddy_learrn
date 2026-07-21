# WorkBuddy Hub 落地计划

## 目标

把一次性培训资料演进为一个 Agent-native 的共建库：同事不必专门写教程，WorkBuddy 在一次任务成功后读取发布指导，自动整理草稿、询问发布范围，用户确认后发布；其他人试用、评分和提出改进建议。

## 分阶段

### Phase 0：可见的产品原型

- 案例搜索、场景标签、详情、版本、评分。
- Skill 入口与 Agent 发布指导。
- 复用 WorkBuddy 官方文档链接，不复制通用产品说明。
- 用静态 `registry.json` 驱动演示。

### Phase 1：最小后端

- `registry.search`、`registry.get`、`registry.publish_preview`、`registry.publish`。
- `registry.rate`、`registry.update`、`registry.report`、`registry.rollback`。
- 以 `actor_context` 作为接口输入，服务端不信任浏览器传入的可见权限。
- 每个发布包保留版本、来源任务摘要、脱敏检查结果和操作审计。

### Phase 2：Agent 端 PoC

- WorkBuddy 安装 `agent-skill/SKILL.md`。
- WorkBuddy 安装自定义 MCP Connector。
- 验证 Agent 能否把身份上下文传给 Connector。
- 完成 `publish_preview -> scope_confirm -> publish` 三步链路。

### Phase 3：共建与治理

- 发布后评分、建议、版本分叉和回滚。
- 个人、部门、组织范围的服务端授权。
- 低评分、敏感字段、失败率等自动风险标记。
- 保留发布，不做事前人工审核；必要时做事后下架和回滚。

## 不变原则

1. Agent 可以代用户执行，但不能代用户扩大发布范围。
2. “用户点击确认”不等于“有权限发布”，服务端必须再次校验。
3. Skill 与案例都必须能说明输入、输出、限制、复核点和版本。
4. 真实项目数据默认不进入公共包，发布前由 Agent 执行脱敏检查。
