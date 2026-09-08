# Contributing to Epistree

Epistree 尚处于早期迭代阶段。所有变更都应保持知识演化模型、原始证据和用户可视化结果之间的一致性。

## 开发原则

- **可追溯**：每个关键节点和关系都应能返回原始来源与文本位置。
- **时间分离**：明确区分 Source Time、Event Time 和 Knowledge Time。
- **证据分离**：Claim 与 Evidence 分开存储，不将模型判断写成确定事实。
- **演化优先**：新增能力应服务于知识形成过程，避免退化为搜索结果列表。
- **边界透明**：记录数据缺失、模型不确定性和未被证据支持的推断。

## 提交约定

提交信息建议使用简洁的命令式描述，并可选使用以下前缀：

- `feat`: 新功能
- `fix`: 缺陷修复
- `docs`: 文档变更
- `refactor`: 不改变外部行为的重构
- `test`: 测试变更
- `chore`: 工程与维护工作

一个提交应尽量只解决一类问题，不应包含密钥、个人凭据、本地缓存或无关的生成文件。

## Changelog 要求

每个会影响用户、数据、接口、运行方式或文档理解的变更，必须在同一次提交或 Pull Request 中更新 `CHANGELOG.md` 的 `Unreleased` 区域。

可使用以下分类：

- `Added`：新能力
- `Changed`：行为变化
- `Deprecated`：即将移除的能力
- `Removed`：已移除的能力
- `Fixed`：缺陷修复
- `Security`：安全修复

纯内部格式化、无行为影响的注释修正可标记为“无 Changelog 影响”，但不应滥用该例外。

## 版本发布

1. 确认主分支测试和文档检查通过。
2. 根据变更类型确定 `MAJOR.MINOR.PATCH`。
3. 更新 `VERSION` 中的唯一版本号。
4. 将 `Unreleased` 内容移入带日期的版本标题，并重建空的 `Unreleased` 区域。
5. 检查 README、迁移说明和不兼容变更。
6. 合并发布提交后创建带注释的 `vX.Y.Z` 标签。
7. 以对应 Changelog 内容创建 GitHub Release。

## Pull Request 检查

- 变更目标和边界已说明。
- 新行为有测试或可重现的验证方法。
- 来源追溯和时间语义未被破坏。
- `CHANGELOG.md` 已更新，或已说明为何无需更新。
- 相关 README、架构或接口文档已同步。

