# Changelog

本文档记录 Epistree 的所有重要变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added

- 新增 Signal Garden 前端视觉方案：沉浸式知识演化画布、信号扫描层、状态微动效、画布操作提示和移动端重排。

### Changed

- 将三栏卡片式界面重构为“紧凑语义轨道 + 中央知识场 + 情报抽屉”，强化图谱主视觉和时间探索路径。
- 收敛颜色、圆角和阴影，采用单一薄荷绿主强调色；补充减弱动态偏好、键盘焦点和控件按压反馈。
- 将树节点聚焦从矩形光晕改为轮廓高亮，避免圆形节点出现方形底板。

## [0.2.0] - 2026-09-10

### Added

- 补齐 Demo 的过期缓存降级、每次运行配额刷新、后台进度与取消落库、来源时间筛选和离线回归验收。
- 新增《Epistree Demo 修改实施方案》，根据当前实现审查结果明确安装启动、配额缓存、来源闭环、运行事务、预热交互和发布验收六个修复阶段。
- 新增《Epistree 初步工程设计》，完成模块边界、统一契约、数据模型、存储、工作流与可视化的分阶段方案。
- 增加知乎 API 日配额治理与 L0–L3 多层缓存设计，支持查询去重、跨日积累、单航班和派生结果复用。
- 记录 GraphRAG、Graphiti、Prefect、Dagster、PostgreSQL/pgvector、Neo4j、Valkey、Cytoscape.js 等参考实现的比较与取舍。
- 新增《Epistree 可行 Demo 完整设计》，将完整蓝图收敛为 Dash、Dash Cytoscape、requests-cache、SQLite 和 Instructor 组成的单实例实施方案。
- 补充 Demo 的数据契约、持久化表、配额硬上限、错误降级、测试矩阵、六步实施顺序与完成定义。
- 新增深色三栏知识世界树界面、确定性时间布局和 Topic / Question / Claim / Event / Source 的内联 SVG 节点语义。
- 新增年轮时间带、年份筛选、分步生长回放、节点聚焦、Esc 退出与 JSON 导出交互。
- 新增《Epistree 前端设计方案》，记录参考产品、技术约束、视觉语义和迭代边界。
- 新增预热按钮与实际主题一一对应的回归测试。

### Changed

- 限定 stale 回退只接受过期不超过 7 天的响应，官方额度查询不再写入 HTTP 缓存。
- 来源快照改为保存对应知乎原始 Item，而非为每条来源重复整份搜索响应。
- 明确 MVP 以知乎开放数据为默认数据边界，不默认接入外部新闻、论文或其他社区。
- 将图谱展示调整为纵向时间、横向观点分叉的预设布局，并对粒子背景和键盘增强提供静默降级。

### Fixed

- 修复“时间不详”筛选为空、候选关系详情缺少可点击来源、缓存仍保留敏感请求头名称及过长查询未被拒绝的问题。
- 修复 Dash 后台子进程复用父进程 SQLite 连接和 Docker 运行时尝试重新同步环境的问题。
- 修复循环注册预热回调导致按钮、输入框与已加载图谱主题不一致的问题。

## [0.1.0] - 2026-09-08

### Added

- 确立 Epistree 的产品定位和一句话定义。
- 定义 Topic、Event、Question、Claim、Evidence 和 Source 核心对象。
- 设计知识分叉、合并、修正、反驳、替代与消亡的演化关系。
- 完成时间主轴、世界树视觉语义和七层系统架构构想。
- 界定知乎数据驱动的 MVP 范围与三阶段演进路线。
- 建立项目级知乎 Skill 和本地认证隔离约定。
- 补充仓库入口、贡献规范、路线图与版本管理文档。

[Unreleased]: https://github.com/MaQiangQAQ/Epistree/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/MaQiangQAQ/Epistree/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/MaQiangQAQ/Epistree/releases/tag/v0.1.0
