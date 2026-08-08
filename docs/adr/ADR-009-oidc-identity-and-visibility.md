# ADR-009：OIDC 身份与可见范围

- 状态：Accepted
- 日期：2026-08-08

## 决策

1. `local_header` 只用于 `HUB_ENV=local` 的 PoC。生产模式不把客户端 `X-Actor-Id` 当身份凭据。
2. `oidc` 模式只接受 Bearer JWT，通过固定 HTTPS issuer 的 Discovery/JWKS 验证 `RS256`、issuer、audience、expiry、kid 和 `sub`。JWKS 必须与 issuer 同主机并按配置缓存。
3. `sub` 是 Hub、SkillHub 和 AgentTeams 审计链的稳定 actor ID。Hub 调用上游时生成 `X-Actor-Id: <sub>`，不透传浏览器提供的 actor 值。
4. 部门集合由直接部门 Claim 与带配置前缀的 group Claim 合并。`personal` 按 owner subject；`department` 按部门集合；`organization` 只允许组织 IdP 的已验证身份；`public` 允许匿名读取。
5. 发布预览和确认都重新执行相同范围策略。确认不得更改预览范围或目标部门，防止在两阶段之间扩大范围。

## 结果

OIDC 签名和本地授权路径已有自动化测试，但真实 IdP、Claim 名称、Subject 生命周期、组织成员条件、调岗/离职传播时限及目标平台 Namespace 同步尚未确认。因此 IAM-01 保持“部分”，不得宣称组织 SSO 已验收。
