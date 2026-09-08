# Changelog

本文档记录 Epistree 的所有重要变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added

- 新增《Epistree 初步工程设计》，完成模块边界、统一契约、数据模型、存储、工作流与可视化的分阶段方案。
- 增加知乎 API 日配额治理与 L0–L3 多层缓存设计，支持查询去重、跨日积累、单航班和派生结果复用。
- 记录 GraphRAG、Graphiti、Prefect、Dagster、PostgreSQL/pgvector、Neo4j、Valkey、Cytoscape.js 等参考实现的比较与取舍。

### Changed

- 明确 MVP 以知乎开放数据为默认数据边界，不默认接入外部新闻、论文或其他社区。

## [0.1.0] - 2026-09-08

### Added

- 确立 Epistree 的产品定位和一句话定义。
- 定义 Topic、Event、Question、Claim、Evidence 和 Source 核心对象。
- 设计知识分叉、合并、修正、反驳、替代与消亡的演化关系。
- 完成时间主轴、世界树视觉语义和七层系统架构构想。
- 界定知乎数据驱动的 MVP 范围与三阶段演进路线。
- 建立项目级知乎 Skill 和本地认证隔离约定。
- 补充仓库入口、贡献规范、路线图与版本管理文档。

[Unreleased]: https://github.com/MaQiangQAQ/Epistree/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/MaQiangQAQ/Epistree/releases/tag/v0.1.0
