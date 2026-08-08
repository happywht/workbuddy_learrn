# ADR-002：构件所有权与统一索引

- 状态：Accepted
- 日期：2026-08-08

## 决策

案例及其版本由 Hub 管理；Skill 包及版本由 SkillHub 管理。统一目录只保存/生成检索投影，`case+skill` 必须保持两个独立 ID，并通过链接关联。

## 结果

Skill 详情和安装计划实时读取 SkillHub；Hub 不成为第二个 Skill 事实来源。
