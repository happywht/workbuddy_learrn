# ADR-004：受信任发布授权

- 状态：Accepted
- 日期：2026-08-08

## 决策

保持“自动验证 + 用户确认 + 服务端授权 + 发布后治理”。SkillHub 通过短期、单次、绑定 actor/namespace/visibility/package hash/preview 的 Trusted Publication Grant 接受发布；Hub 不持有通用 SUPER_ADMIN 代发 Token。

## 结果

未配置 Grant 验证端点或请求缺少 Grant 时，Skill 发布必须失败并保留预览草稿。预览 ID 是稳定幂等键；Hub 持久化首次成功结果并将相同键传给 Trusted Publication Grant 上游，重试不会重复创建版本。
