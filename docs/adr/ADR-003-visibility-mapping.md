# ADR-003：发布范围映射

- 状态：Accepted
- 日期：2026-08-08

## 决策

`personal` 映射 SkillHub PRIVATE；`department` 映射部门 Namespace + NAMESPACE_ONLY；`organization` 映射组织 Namespace + NAMESPACE_ONLY。互联网公开是未来单独权限，不与组织内部范围混用。

## 结果

任何 Adapter 都不得把 `organization` 自动映射到匿名 `@global/PUBLIC`。
