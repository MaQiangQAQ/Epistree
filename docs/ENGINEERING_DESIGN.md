# Epistree 初步工程设计

> 文档状态：Draft 0.1<br>
> 面向版本：Epistree v0.2.x 设计阶段<br>
> 最后更新：2026-09-08<br>
> 性质：工程设计文档，不代表功能已实现

## 0. 文档目的

本文档将《知识世界树：系统构想》转换为一套可以分阶段实施、分模块验证、持续替换技术实现的工程蓝图。设计重点是：

1. 先建立可用的最小闭环，同时保留向多主题、多时间尺度和更复杂演化关系扩展的空间。
2. 各模块通过稳定契约协作，不让知乎 API、某个大模型、某个数据库或某个前端库成为不可替换的核心。
3. 任何知识节点、演化关系和生成回答都能回到原始来源、文本片段、采集时间与处理版本。
4. 在知乎每日调用限额和单次结果上限下，通过缓存、去重、增量更新和查询规划有效使用配额。
5. 每个阶段都有可验收产物，遇到足以改变产品边界的问题时停止扩展并上报。

---

## 1. 产品边界与工程假设

### 1.1 必须实现的价值闭环

第一个可实现版本必须让用户完成一次完整体验：

```text
创建研究主题
  → 生成可解释的检索计划
  → 在配额内发现知乎内容
  → 看到采集进度与覆盖边界
  → 生成 Event / Question / Claim / Source
  → 建立支持、反驳和演化关系
  → 查看时序世界树
  → 点击任一节点回溯原始内容
```

### 1.2 知乎优先原则

- MVP 的内容发现、作者信息、社区反馈与内容链接优先来自知乎官方开放能力。
- 默认不接入外部新闻、论文、微博或其他社区。
- 知乎站内搜索返回的 `ContentText` 按“可能不完整的搜索文本”处理，不默认当作完整原文。
- 无法取得完整原文时，可建立低置信度的 Claim 候选，但不能生成“已验证 Evidence”。
- 任何结果页都要显示数据截止时间、实际查询数、唯一内容数、时间覆盖和已知缺口。

### 1.3 当前官方能力约束

根据项目内知乎开放平台文档：

| 能力 | 当前边界 | 工程含义 |
| --- | --- | --- |
| 知乎搜索 | 每次最多 10 条，`HasMore` 当前固定为 `false` | 无法通过普通翻页做全量抓取 |
| 知乎搜索额度 | 当前邀测说明为每日 5,000 次 | 需要日配额预算、查询去重和增量积累 |
| 额度查询 | 返回自然日总额度、已用和剩余，查询本身不消耗业务额度 | 可在调度前读取，但不应高频轮询 |
| 搜索文本 | `ContentText` 为摘要或搜索文本 | 必须保存完整返回并标记文本完整性 |
| 黑客松故事/知识内容 | 列表与详情可返回正文，但属于赛事专用能力 | 做独立 Connector，不将其假设为长期稳定 API |
| Access Secret | 同一账号的多个 Secret 共享额度池 | 不能通过轮换 Secret 扩容，也不应设计此类逻辑 |

工程文档中所有额度数字都是“当前配置值”，运行时以额度接口返回为准，不写死在业务逻辑中。

### 1.4 MVP 非目标

- 不声称完整遍历知乎历史内容。
- 不将大模型的关系判断当作客观事实。
- 不自动认定观点的最终真假。
- 不在 MVP 中同时建设分布式微服务、消息队列集群和独立图数据库。
- 不绕过官方开放能力的额度、认证或内容访问边界。

---

## 2. 调研方法与总体选型

### 2.1 调研方法

本设计没有从空白接口开始，而是先比较与 Epistree 各项能力接近的工程和标准：

- 从 Microsoft GraphRAG 学习文档、TextUnit、Claim、来源回链、Workflow 和 Provider/Factory 边界。
- 从 Graphiti 学习 Episode 增量摄取、双时态事实、失效关系和混合检索。
- 从 Argument Interchange Format（AIF）学习“信息节点”与“推理/冲突节点”分离。
- 从 EventKG 学习事件中心的时序表示。
- 从 W3C PROV-O 和 OWL-Time 学习来源、活动、代理者、时间点和时间区间的通用语义。
- 从 Prefect、Dagster、LangGraph 和 Temporal 比较数据流与长期 Agent 工作流。
- 从 Redis cache-aside、HTTP 缓存标准和 GraphRAG LLM cache 学习缓存键、TTL、失效、单航班与幂等。
- 从 OpenAPI、JSON Schema、RFC 9457 和 CloudEvents 学习对外 API、错误对象和异步事件契约。
- 从 Cytoscape.js 和 Sigma.js 比较交互图谱的数据、样式、布局与规模适配。

### 2.2 候选方案比较

#### 知识抽取与演化建模

| 候选 | 可借鉴能力 | 不直接采用的原因 | 结论 |
| --- | --- | --- | --- |
| [Microsoft GraphRAG](https://github.com/microsoft/graphrag) | 文档切分、Claim/关系抽取、社区检测、来源回链、Provider 注册 | 核心是面向 RAG 的静态语料索引；当前包元数据限制 Python `<3.14` | 借鉴管线和契约，不作核心依赖 |
| [Graphiti](https://github.com/getzep/graphiti) | Episode 增量写入、双时态关系、事实失效、混合检索 | 更偏 Agent memory，缺少 Epistree 的 Question/Claim/Evidence 专门语义 | 借鉴双时态与增量方法 |
| [LightRAG](https://github.com/HKUDS/LightRAG) | 轻量图检索与增量索引 | 主要优化问答检索，不提供所需的论点演化语义 | 作为后期检索对照组 |
| [Neo4j LLM Graph Builder](https://github.com/neo4j-labs/llm-graph-builder) | 非结构化文本到 Neo4j 的工程示例 | 早期绑定 Neo4j，数据模型仍需自定义 | 只借鉴导入和可视化组合 |

**选择：**建设 Epistree 自己的薄领域管线，使用 GraphRAG 式 `Document/TextUnit` 来源回链、Graphiti 式双时态和 AIF 式论据关系分离。不拷贝上述项目的内部数据模型。

#### 工作流编排

| 候选 | 优点 | 代价 | 适用判断 |
| --- | --- | --- | --- |
| [Prefect](https://github.com/PrefectHQ/prefect) | Python 函数即任务，内建缓存、重试、状态和并发；当前允许 Python 3.14 | 需要引入工作流运行时 | **MVP 采用**，用于采集和索引流程 |
| [Dagster](https://github.com/dagster-io/dagster) | 资产中心、血缘和可测试性强 | 概念和部署面对早期 Demo 偏重 | 当数据产物数量大幅增加时复评 |
| [LangGraph](https://github.com/langchain-ai/langgraph) | 有状态 Agent、持久化、人工介入 | 对确定性 ETL 并无明显优势，与 Prefect 并用会出现双编排中心 | MVP 不采用；Research Agent 进入人工介入阶段时复评 |
| [Temporal](https://temporal.io/) | 长期可恢复工作流和强耐久性 | 服务与运维成本最高 | 仅在长达数日、多服务交易式流程成为核心时复评 |

#### 存储与图查询

| 候选 | 优点 | 限制 | 结论 |
| --- | --- | --- | --- |
| PostgreSQL + [pgvector](https://github.com/pgvector/pgvector) | 事务、JSONB、全文、向量和普通关系均可使用；维护面小 | 复杂多跳图遍历需手工优化 | **MVP 唯一事实库** |
| [Neo4j](https://github.com/neo4j/neo4j) | Cypher 成熟，图分析和可视化生态完整 | 引入第二个真实来源会带来同步与版本复杂度 | 当真实多跳查询无法达标时，以投影库引入 |
| [Apache AGE](https://github.com/apache/age) | 在 PostgreSQL 内提供图能力 | 增加扩展运维与迁移约束 | 预留评测，不作 MVP 前置条件 |
| Kùzu | 嵌入式、Cypher、向量与全文 | 上游仓库已归档 | **排除**，不将新项目建在停止维护的核心上 |

#### 结构化模型输出

| 候选 | 特点 | 结论 |
| --- | --- | --- |
| [Instructor](https://github.com/567-labs/instructor) | 基于 Python 类型的结构化输出与重试 | 可作 Provider 实现，不泄漏到领域层 |
| [BAML](https://github.com/BoundaryML/baml) | 专门的模型函数定义和测试方式 | 新增 DSL 和生成链，在 Prompt 数量增长后再评估 |
| [Outlines](https://github.com/dottxt-ai/outlines) | 约束解码与结构化生成 | 适合本地模型 Provider，不作通用域接口 |
| Pydantic + JSON Schema | 数据契约清晰，可生成 JSON Schema，与 FastAPI 一致 | **MVP 核心契约** |

#### 前端图可视化

| 候选 | 适合场景 | 结论 |
| --- | --- | --- |
| [Cytoscape.js](https://js.cytoscape.org/) | 交互图、样式表、多种布局、图算法、序列化 | **MVP 采用**，布局坐标由 Epistree 投影层提供 |
| [Sigma.js](https://www.sigmajs.org/) | WebGL 渲染，更适合数千节点的大图 | 当细节层级规模超过 Cytoscape 实测阈值时替换 Renderer |
| D3 | 高度自定义视觉编码 | 不从零重建图交互；只在年轮、时间轴等局部视觉中使用 |

### 2.3 总体技术基线

| 层 | MVP 选择 | 选择原因 |
| --- | --- | --- |
| 后端语言 | Python 3.14，`uv` 管理 | 匹配项目环境，适合 NLP/LLM 管线 |
| HTTP API | FastAPI + Pydantic | 基于 OpenAPI/JSON Schema，输入输出类型统一 |
| 工作流 | Prefect | 任务缓存、重试、状态与可观测性 |
| 事实存储 | PostgreSQL 16+ | 事务、JSONB、全文和迭代成本均衡 |
| 向量 | pgvector | 与领域数据同事务库，不新增向量数据库 |
| 热缓存 | Valkey（Redis-compatible） | BSD 许可、支持 TTL/原子操作/单航班锁 |
| 原始快照 | PostgreSQL JSONB 起步，预留 BlobStore Port | 前期数量可控；超出阈值时无需改变上层契约 |
| 前端 | React + TypeScript + Cytoscape.js | 互动图组件生态成熟，数据契约可自动生成 |
| 可观测性 | OpenTelemetry；Phoenix 作可选本地 UI | 底层使用通用标准，不绑定某个 LLM 平台 |

---

## 3. 架构形态

### 3.1 先做模块化单体

MVP 采用“模块化单体 + 独立 Worker”，而不是一开始拆成微服务。API 进程和 Worker 进程可分开部署，但共享同一套领域包和事实库。

```text
┌── Web App ────────────────────────────┐
│  Topic / Progress / World Tree / Provenance  │
└────────────────┬────────────────┘
                 │ OpenAPI + SSE
┌────────────────▼────────────────┐
│                  API Application               │
│ Topic / Run / Graph / Node / Review / Export  │
└────────────────┬────────────────┘
                 │ Application Services
┌────────────────▼────────────────┐
│                 Domain Core                    │
│ Source / Knowledge / Time / Evolution / Review│
└────────────────┬────────────────┘
                 │ Ports
┌────────────────▼────────────────┐
│                 Adapters                       │
│ Zhihu / LLM / Postgres / Valkey / Prefect     │
└─────────────────────────────────┘
```

### 3.2 目标目录边界

以下是未来实现时的建议目录，当前不要为了“看起来完整”而建立空包：

```text
apps/
  api/                    # HTTP/SSE 进程
  worker/                 # Prefect flow 与后台任务入口
  web/                    # React 应用
packages/
  contracts/              # Pydantic/JSON Schema/OpenAPI/CloudEvents 契约
  domain/                 # 不依赖外部服务的领域模型
  research/               # 主题扩展、查询计划、覆盖评估
  ingestion/              # Connector 编排、规范化、快照
  extraction/             # 节点与证据片段抽取
  evolution/              # 候选关系与演化判定
  projection/             # 世界树、时间线、争议等读模型
  evaluation/             # 黄金集、指标、回归评测
  infrastructure/         # Postgres/Valkey/LLM/Zhihu 适配器
schemas/
  api/                    # 导出的 OpenAPI
  events/                 # CloudEvents data schema
  domain/                 # JSON Schema 2020-12
docs/
  adr/                    # 架构决策记录
  runbooks/               # 额度耗尽、上游异常、重建投影等手册
tests/
  contract/
  integration/
  golden/
```

### 3.3 依赖规则

```text
contracts ← domain ← application modules → ports ← adapters
```

- `domain` 不导入 FastAPI、Prefect、SQLAlchemy、Valkey 或任何模型 SDK。
- 知乎返回字段只出现在 Zhihu Adapter DTO 和原始快照中，进入领域层前必须转换。
- 所有模型调用都经过 `ModelGateway`，Prompt 和输出 Schema 都有独立版本。
- 图可视化只读取 Projection DTO，不直接暴露数据库表。
- 跨模块通知先通过事务 Outbox 记录为 CloudEvent，前期由本地 Dispatcher 消费，后期可替换消息中间件。

---

## 4. 统一契约设计

### 4.1 契约的外部依据

接口不自定义一套孤立协议，而是组合以下成熟规范：

- HTTP 资源接口：[OpenAPI 3.1](https://spec.openapis.org/oas/v3.1.1.html)。
- 数据校验：[JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12)。
- API 错误：[RFC 9457 Problem Details](https://www.rfc-editor.org/rfc/rfc9457.html)。
- 异步事件信封：[CloudEvents 1.0](https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md)。
- 来源语义：[W3C PROV-O](https://www.w3.org/TR/prov-o/)。
- 时间区间语义：[W3C OWL-Time](https://www.w3.org/TR/owl-time/)。
- 唯一标识：UUIDv7（[RFC 9562](https://www.rfc-editor.org/rfc/rfc9562.html)）用于业务对象，内容哈希用于幂等。

### 4.2 通用字段

所有领域对象的对外表示至少包含：

| 字段 | 语义 |
| --- | --- |
| `id` | UUIDv7，系统内稳定标识 |
| `schema_version` | 该对象的契约版本，例如 `1.0` |
| `created_at` | 对象首次进入系统的 UTC 时间 |
| `updated_at` | 当前表示最后更新的 UTC 时间 |
| `revision` | 乐观并发控制整数 |
| `status` | 领域生命周期状态，不复用 HTTP 状态码 |

对外时间统一 RFC 3339 UTC 字符串；领域层同时保存原始时间字符串、解析方法、精度和时区。

### 4.3 内部 Port 契约

下列 Port 的分类方式来自 Ports and Adapters 与 GraphRAG Provider/Factory 实践。名称可在实现时优化，语义不得随适配器变化。

#### SourceConnector

```text
capabilities() -> ConnectorCapabilities
discover(request: DiscoveryRequest) -> DiscoveryBatch
read(identity: SourceIdentity) -> SourceDocument | NotAvailable
health() -> ConnectorHealth
```

- `DiscoveryRequest` 包含规范化查询、目标内容类型、研究主题、计划查询 ID 和预算类别。
- `DiscoveryBatch` 包含原始响应快照 ID、查询标识、顺序不变的结果、返回时间、上游请求标识和 `has_more`。
- `SourceDocument` 必须显式声明 `content_completeness = full | partial | snippet | metadata_only`。
- 知乎搜索 Adapter 的 `read()` 允许返回 `NotAvailable`，不伪造全文接口。

#### QuotaProvider

```text
snapshot(scope: QuotaScope) -> QuotaSnapshot
reserve(request: QuotaReservationRequest) -> QuotaReservation
commit(reservation_id, actual_units) -> QuotaUsage
release(reservation_id, reason) -> None
```

`reserve` 是应用内的预算预留，不代表知乎上游保证。实际剩余额度仍以官方额度接口为准。

#### CacheStore

```text
get(key) -> CacheEntry | Miss
put(key, value, policy) -> CacheEntry
invalidate(selector) -> InvalidationResult
acquire(key, lease_ttl) -> Lease | Busy
```

契约参考 HTTP cache key/TTL 语义和 Redis cache-aside。`Lease` 用于避免多个 Worker 对同一查询同时打到知乎。

#### ModelGateway

```text
generate(request: ModelRequest[OutputSchema]) -> ModelResult[OutputSchema]
embed(request: EmbeddingRequest) -> EmbeddingResult
capabilities() -> ModelCapabilities
```

`ModelRequest` 必须携带 `prompt_id`、`prompt_version`、`output_schema_id`、`model_profile`、采样参数和幂等键。领域模块不可以直接调用模型 SDK。

#### KnowledgeRepository

```text
put_source_snapshot(snapshot) -> SnapshotRef
upsert_candidate(node, provenance) -> NodeRevision
append_assertion(assertion) -> AssertionRef
append_relation(relation, provenance) -> RelationRevision
get_graph(query: GraphQuery) -> GraphSlice
as_of(timestamp) -> KnowledgeSnapshot
```

`append_assertion` 和 `append_relation` 默认追加新修订，不原地覆盖旧判断。

#### ProjectionBuilder

```text
build_world_tree(query: ProjectionQuery) -> WorldTreeProjection
build_timeline(query: ProjectionQuery) -> TimelineProjection
build_controversy(query: ProjectionQuery) -> ControversyProjection
```

投影层负责裁剪、排序、布局坐标和视觉编码，不改变底层知识事实。

### 4.4 跨模块事件

事件使用 CloudEvents 信封，`source + id` 全局唯一，业务载荷由 JSON Schema 校验。初期事件类型：

```text
io.epistree.research.run.started.v1
io.epistree.query.planned.v1
io.epistree.source.discovered.v1
io.epistree.source.snapshot.created.v1
io.epistree.extraction.completed.v1
io.epistree.relation.proposed.v1
io.epistree.projection.published.v1
io.epistree.research.run.completed.v1
io.epistree.research.run.failed.v1
```

事件使用 Outbox Pattern 与领域写入同事务提交。消费者必须按 `source + id` 幂等。

### 4.5 HTTP API 通用约定

- API 路径使用 `/api/v1` 前缀。
- 创建长任务返回 `202 Accepted`，`Location` 指向 Research Run 资源。
- 客户端创建任务必须可传 `Idempotency-Key`；服务端在限定时间内保留请求哈希与结果引用。
- 列表使用不透明 Cursor，不将数据库 offset 暴露给客户端。
- 错误响应使用 `application/problem+json`，至少包含 `type/title/status/detail/instance`。
- 额度耗尽或上游限流在 Problem Details 扩展字段中附加 `upstream_code`、`quota_scope`、`retry_at`，不要求客户端解析中文 `detail`。
- 进度通知优先使用 SSE，断线后通过 `Last-Event-ID` 恢复；完整状态仍以 Research Run 资源为准。

---

## 5. 核心领域模型

### 5.1 分层对象

Epistree 将“原始内容”、“文本中的陈述”、“系统的知识判断”和“用户看到的投影”分成四层：

```text
Source Layer
  SourceItem → SourceSnapshot → TextUnit → SourceSpan

Semantic Layer
  Topic / Event / Question / Claim / Evidence

Assertion Layer
  Assertion / KnowledgeRelation / ReviewDecision

Projection Layer
  WorldTree / Timeline / Controversy / Consensus / DeadBranch
```

任何 Projection 都可删除后重建；SourceSnapshot 和已发布的 Assertion Revision 不可被投影流程覆盖。

### 5.2 来源对象

#### SourceIdentity

```json
{
  "provider": "zhihu",
  "content_type": "answer",
  "provider_content_id": "1903044959663284716",
  "canonical_url": "https://www.zhihu.com/answer/1903044959663284716"
}
```

唯一键首选 `(provider, content_type, provider_content_id)`；URL 只作补充，必须先移除 UTM 等追踪参数再规范化。

#### SourceSnapshot

每次上游观测产生不可变快照，至少包含：

- `source_identity`
- `observed_at`
- `source_created_at` / `source_edited_at`
- `title`、`author`、`metrics`、`authority_level`
- `content_text`、`content_completeness`
- `raw_payload`或 `blob_ref`
- `content_sha256`、`payload_sha256`
- `connector_name`、`connector_version`
- `query_execution_ids`（可多个）

相同内容在多个查询中出现时，共用 SourceItem/SourceSnapshot，但每个“查询—排名—观测”关系单独保留。

### 5.3 TextUnit 与 SourceSpan

借鉴 GraphRAG 的 TextUnit 来源回链，但根据中文内容调整切分：

- 先按标题、段落、列表、引用等结构边界切分。
- 仅当结构块超过模型上下文策略时再按 Token 切分。
- 每个 TextUnit 保留 `char_start/char_end`、段落索引、原始快照 ID 和前后文哈希。
- 任何抽取结果使用 SourceSpan 引用精确字符区间，而不只保存文档 ID。
- 当原文是 snippet 时，SourceSpan 标记 `span_scope=snippet`，前端显示“搜索摘要中的位置”。

### 5.4 语义节点

| 节点 | 核心字段 | 关键约束 |
| --- | --- | --- |
| Topic | `name`, `aliases`, `scope`, `research_question` | 同名主题可以有不同研究边界 |
| Event | `label`, `occurred_time`, `time_precision`, `participants` | 事件时间与来源发布时间分离 |
| Question | `text`, `question_type`, `first_seen`, `last_active` | 问题相似不等于问题演化 |
| Claim | `proposition`, `modality`, `polarity`, `scope`, `valid_time` | 必须是可单独讨论的命题，不是全文摘要 |
| Evidence | `description`, `evidence_type`, `direction`, `quality_features` | 必须连接到 SourceSpan；无片段时只能是候选 |

### 5.5 Assertion 与关系实体化

不将 `Claim A --supports--> Claim B` 只保存为一条无属性边。每个关系都是可审计对象：

```json
{
  "id": "019...",
  "relation_type": "supports",
  "source_node_id": "019...",
  "target_node_id": "019...",
  "asserted_by": "model",
  "confidence": 0.78,
  "valid_from": null,
  "valid_to": null,
  "observed_at": "2026-09-08T08:00:00Z",
  "status": "proposed",
  "provenance_span_ids": ["019..."],
  "model_run_id": "019...",
  "revision": 1
}
```

这一方法对应 AIF 对信息与推理/冲突的分离，也使关系能够被人工接受、驳回、替代或标记失效。

### 5.6 双时态模型

参考 Graphiti 和图数据库的 temporal versioning 实践，所有可变知识关系至少保留两类时间：

- **Valid Time**：该事件或主张在现实/语义上针对的时间。
- **Transaction/Observation Time**：Epistree 在何时采集、抽取或修改该判断。

另外保留 Source Time（发布/编辑时间）。三者不得共用一个 `timestamp` 字段。

时间值结构：

```text
TimeValue {
  start, end,
  precision: exact | day | month | year | range | unknown,
  timezone,
  original_text,
  normalized_by,
  confidence
}
```

### 5.7 修订和失效

- SourceSnapshot 不可变，内容变化创建新快照。
- Claim 语句修改创建 NodeRevision，保留稳定 Claim ID。
- 新证据推翻旧关系时，设置旧 RelationRevision 的 `invalidated_at` 并新建修订。
- 用户审核永远产生 ReviewDecision，不直接删除模型结果。
- `as_of` 查询可重建某一观测时间点的系统判断。

---

## 6. 持久化模型

### 6.1 主表分组

#### Research

- `research_topic`
- `research_run`
- `query_plan`
- `query_execution`
- `coverage_snapshot`

#### Source

- `source_item`
- `source_snapshot`
- `query_source_observation`
- `text_unit`
- `source_span`

#### Knowledge

- `knowledge_node`（公共字段）
- `event_revision`
- `question_revision`
- `claim_revision`
- `evidence_revision`
- `knowledge_relation_revision`
- `assertion_provenance`
- `review_decision`

#### Model and pipeline

- `prompt_definition`
- `model_run`
- `pipeline_run`
- `pipeline_step_run`
- `extraction_bundle`

#### Delivery and operations

- `projection_snapshot`
- `quota_snapshot`
- `quota_reservation`
- `outbox_event`
- `idempotency_record`

### 6.2 主要索引与约束

- `source_item(provider, content_type, provider_content_id)` 唯一。
- `source_snapshot(source_item_id, payload_sha256)` 唯一。
- `query_execution(cache_key, executed_on)` 用于按自然日查重。
- `text_unit(snapshot_id, char_start, char_end, chunker_version)` 唯一。
- Relation 约束 `source_node_id != target_node_id`，自环需要显式例外类型。
- 当 `status=accepted` 时，Claim/Evidence/Relation 必须存在至少一条 provenance。
- 不确定时间使用 `precision=unknown`，不使用伪造的默认日期。
- 向量表使用 `(model_id, object_type, object_id)` 组合键，允许嵌入模型并存与重建。

### 6.3 JSONB 的使用边界

PostgreSQL 文档建议在需要灵活性时仍保持相对稳定的 JSON 结构。因此：

- 上游 `raw_payload`、未识别字段、可视化扩展样式可用 JSONB。
- ID、状态、时间、置信度、外键、版本等查询核心字段必须为显式列。
- 不使用一个巨大 JSONB 保存整棵世界树作为唯一事实。
- Projection 可以使用 JSONB 快照，因为其可从基础表重建。

### 6.4 何时引入图投影库

只有同时满足以下条件时，才开始 Neo4j/AGE 技术验证：

1. 已有可重现的 3–5 跳关系查询基准。
2. PostgreSQL 递归 CTE 经索引和投影优化后仍无法达到目标 P95。
3. 已明确图投影的重建时间目标和一致性水位。
4. 系统仍将 PostgreSQL 作为唯一事实来源，图库可删除后重建。

---

## 7. 缓存与配额工程

### 7.1 缓存不等于数据库

本项目的缓存分四层，每层解决不同问题：

| 层 | 位置 | 内容 | 丢失后果 |
| --- | --- | --- | --- |
| L0 | 进程内 | 极短时的同请求合并、额度快照 | 性能下降，数据不丢失 |
| L1 | Valkey | 查询响应、进度、单航班锁、负缓存 | 上游调用增加，可恢复 |
| L2 | PostgreSQL | 原始 API 快照、查询观测、内容版本 | **不可丢失**，是研究可复现依据 |
| L3 | PostgreSQL/Blob | 嵌入、抽取、关系候选、投影 | 可按输入哈希和处理版本重建 |

### 7.2 查询缓存键

查询键由规范化后对象的稳定 JSON 生成 SHA-256：

```text
provider
endpoint
normalized_query
normalized_parameters
auth_scope_id       # 不包含 Secret
connector_version
response_schema_version
```

规范化包括 Unicode NFKC、首尾空白清理、参数键排序和明确的大小写策略。原始 query 仍保存于 QueryPlan，不因规范化而丢失。

### 7.3 建议 TTL

TTL 是默认策略，应可配置，并优先尊重上游响应的缓存指令：

| 对象 | 默认 TTL | 说明 |
| --- | ---: | --- |
| 额度快照 | 60–300 秒 | 调度边界或执行失败时主动刷新 |
| 知乎热榜 | 5–10 分钟 | 高时效，但同一时窗不重复调用 |
| 知乎搜索 | 24 小时 | 用户可显式发起 refresh，仍需经配额调度 |
| 静态回填查询 | 7 天 | 例如包含明确历史年份的查询 |
| 无结果/上游 404 | 10–60 分钟 | 防止空结果重复消耗，TTL 短于正常结果 |
| 模型抽取 | 无时间 TTL | 键包含输入哈希、Prompt/Schema/Model 版本，版本变化自然失效 |
| 世界树投影 | 5–60 分钟 | 底层节点修订时通过事件精确失效 |

### 7.4 Cache-aside 与单航班

查询路径参考 Redis cache-aside：

```text
读 L1
  ├─ hit → 返回，记录 cache_hit
  └─ miss
      → 查 L2 持久快照是否仍在新鲜期
      → 尝试获取 single-flight lease
      → 预留配额
      → 调用知乎
      → 先持久化原始快照和配额使用
      → 再填充 L1
      → 释放 lease
```

- 缓存故障时允许降级到 PostgreSQL，但不得绕过配额预算直打上游。
- 获取 lease 的 Worker 崩溃时依赖租约 TTL 自动释放。
- 高热键提前加随机抖动刷新，避免集中过期。
- 不对包含个人用户数据的响应做跨用户共享缓存。

### 7.5 每日配额预算

将知乎搜索可用额度按配置比例分桶，而不是先到先得直至耗尽。建议初始值：

| 预算桶 | 比例 | 用途 |
| --- | ---: | --- |
| 交互查询 | 35% | 用户正在等待的首次研究任务 |
| 新主题发现 | 25% | 扩展词、问题链、争议角度 |
| 历史回填 | 15% | 年份、里程碑、早期同义词 |
| 已有主题刷新 | 15% | 追踪新回答、编辑和演化 |
| 应急保留 | 10% | 用户手动刷新、重要演示和异常恢复 |

比例可配置；当官方剩余额度低于保留线时，只允许交互高优先级和应急任务。

### 7.6 配额调度分数

每个候选查询的执行分数：

```text
score = priority
      × expected_novelty
      × expected_coverage_gain
      × user_waiting_factor
      × source_fit
      ÷ estimated_units
```

- `expected_novelty` 根据过往返回的重复率与查询语义距离计算。
- `expected_coverage_gain` 针对当前时间空洞、问题空洞和观点空洞。
- 查询连续多次的新增唯一内容低于阈值时，对该分支停止扩展。
- 用户可在界面上看到“为什么执行这条查询”和“为什么停止”。

### 7.7 缓存和持久快照可做的“文章”

缓存不能创造上游没有返回的内容，但可以让有限配额随时间转化为越来越稳定的“主题记忆”：

1. **跨用户复用公共查询结果**：同一主题的后来用户直接复用既有发现，只为缺口付费额度。
2. **累积多个查询的并集**：查询 A/B/C 各返回 10 条，通过 ContentID 去重后形成主题语料池。
3. **跨日增量更新**：旧快照保留，第二天只执行信息增益最高的刷新和新分支查询。
4. **查询效果学习**：记录每条查询的唯一结果率、新增率、时间覆盖和观点覆盖，以后优先使用高收益模板。
5. **派生结果幂等**：同一文本、Prompt、Schema 和模型版本不重复抽取，节省模型调用并提高可复现性。
6. **时间快照差分**：内容指标、文本或搜索排名变化可用来发现知识活动度和新问题。

不可做的事包括：轮换 Access Secret 规避限额、伪造翻页、将 snippet 声称为全文、将过期结果不加时间标记地当作当前事实。

---

## 8. 研究规划与查询扩展

### 8.1 输入契约

主题不只是一个关键词。创建 Topic 时建议接受：

```json
{
  "name": "大模型幻觉",
  "research_question": "知乎社区对大模型幻觉的解释如何变化？",
  "scope": {
    "language": ["zh-CN"],
    "time_range": {"from": "2022-01-01", "to": null},
    "content_types": ["question", "answer", "article"],
    "source_policy": "zhihu_only"
  },
  "budget_profile": "interactive_standard"
}
```

用户只输入 `name` 时，系统可生成可编辑的默认 Research Brief；在发起大规模调用前让用户看到范围，避免在错误方向浪费额度。

### 8.2 查询计划结构

QueryPlan 是可审计、可暂停、可追加的资源，不是 Agent 的一段隐形思考。

```text
QueryPlan
  objective
  hypotheses[]
  query_candidates[]
  coverage_dimensions[]
  budget
  stop_conditions
  planner_version
```

每个 QueryCandidate 包含：

- 实际发给知乎的 query。
- 该 query 对应的主题别名、年份、事件、问题类型或争议角度。
- 预期填补的 coverage gap。
- 生成依据（规则、用户、模型或旧结果）。
- 执行分数、预算桶和当前状态。

### 8.3 查询候选生成

查询候选分层生成，每层均可独立关闭：

1. **实体层**：主题名、别名、缩写、旧称、中英文变体。
2. **问题层**：是什么、为什么、如何发生、解决了什么、还有什么问题。
3. **演化层**：起源、转折、争议、反例、修正、替代、共识。
4. **时间层**：年份、里程碑前后、特定事件时窗。
5. **领域层**：理论、产品、教育、职业、政策等主题内部分支。
6. **反馈层**：从已发现的新问题、低覆盖年份和对立观点反向生成。

查询生成结果先经规则校验：长度、空值、重复、已执行记录、与主题的最低语义相似度。

### 8.4 覆盖度与停止条件

无法获得真实全量集合时，不计算伪精确的“召回率”。改用可观测指标：

- 查询累计唯一 ContentID 数。
- 最近 N 条查询的边际新增率。
- 年/月时间桶覆盖。
- Question/Claim 聚类数与新增率。
- 对立观点是否都有来源。
- 来源文本完整性分布。
- 无结果、高重复、额度受限等缺口原因。

任一条件成立可停止当前分支：

- 连续 3 条高相关查询的新增 ContentID 率低于配置阈值。
- 当日该预算桶已用完。
- 上游返回频率或配额限制。
- 查询偏离 Research Brief。
- 新内容只增加数量，不再增加时间、问题或观点覆盖。

---

## 9. 数据采集与规范化

### 9.1 Connector 划分

MVP 内部仍将知乎能力拆成多个 Connector，因为它们的稳定性、认证和缓存策略不同：

| Connector | 责任 | 稳定性 |
| --- | --- | --- |
| `ZhihuSearchConnector` | 知乎问题、回答和文章发现 | 开放平台 API，受额度限制 |
| `ZhihuHotConnector` | 当前社区热点与新事件线索 | 高时效，每日额度更低 |
| `ZhihuHackathonKnowledgeConnector` | 赛事知识列表与详情 | 赛事专用，字段可增减 |
| `ZhihuHackathonStoryConnector` | 赛事故事列表与详情 | 赛事专用，不作通用主题来源 |
| `ZhihuUserContextConnector` | 授权用户的创作/收藏/关注 | 非 MVP 必需，必须隔离用户数据 |

每个 Connector 都有独立 `capabilities()`，上游能力改变时通过能力探测和契约测试暴露，不让业务流程出现隐性行为变化。

### 9.2 采集顺序

```text
Validate query
  → Resolve cache key
  → Check durable observation
  → Reserve quota
  → Call connector
  → Persist raw response
  → Normalize every item
  → Link query observation
  → Commit quota usage
  → Emit source.discovered
```

原始响应必须在规范化之前持久化。如果规范化代码有缺陷，可用旧快照重放，无需再消耗知乎额度。

### 9.3 内容去重层级

1. **强身份去重**：ContentID + ContentType。
2. **URL 规范化**：去除 UTM、fragment 和无语义参数。
3. **精确文本去重**：NFKC + 空白规范化后 SHA-256。
4. **近似重复候选**：SimHash/MinHash 或字符 n-gram。
5. **语义重复**：embedding 相似度 + 标题/时间/作者约束。
6. **灰区判断**：只对阈值区间内的候选使用模型，且保留判断证据。

去重不直接删除 SourceItem，而是建立 `same_as`、`near_duplicate_of` 或 `version_of` 候选关系。

### 9.4 上游变化检测

- 相同 ContentID 的 `payload_sha256` 不同时新建 SourceSnapshot。
- 只有 VoteUpCount/CommentCount 改变时，生成轻量 metrics revision，不重跑文本抽取。
- `content_sha256` 改变时，仅重跑受影响 TextUnit 及其下游。
- 上游内容消失时不删除旧快照，记录 `availability_status` 和检测时间。

---

## 10. 知识抽取管线

### 10.1 设计原则

- 抽取与关系推断分开；先确定文本说了什么，再比较不同内容之间的关系。
- 每个节点先是 `candidate`，通过格式校验、来源验证和去重后才进入 `proposed`。
- 模型必须允许返回“无法判断”。
- 所有抽取结果都要携带 SourceSpan，没有 span 的结果不能进入高置信度图。
- Prompt、Schema、模型和切分器任一版本改变时，新结果与旧结果并存，由评测决定是否提升为当前版本。

### 10.2 分步抽取

#### Step A：文本适用性

判断 TextUnit 是否包含与主题相关的事件、问题、主张或证据。优先使用关键词和 embedding 初筛，只对候选调用模型。

#### Step B：原子主张

将长句或段落拆成可单独讨论的 Claim。每条 Claim 包含：

- 原文中的命题表述。
- 最小语义范围和限定词。
- 肯定/否定/不确定极性。
- 作者表达的模态（事实、推测、建议、假设）。
- 完整 SourceSpan。

不将模型改写后的更强陈述替代原文范围。

#### Step C：Question 与 Event

- Question 优先来自原标题、明示问句和作者提出的开放问题。
- 隐含 Question 必须标记 `inferred=true`，不与原问题混合。
- Event 必须提取事件参与者、动作、时间文本和事件范围。
- 仅有发布时间时，不将其填入 Event Time。

#### Step D：Evidence

证据类型初始包括：`data`、`experiment`、`document`、`case`、`product_behavior`、`official_statement`、`expert_testimony`、`observation`。

每条 Evidence 必须连接 Claim，指定 `supports | contradicts | contextualizes`，并将“证据内容是否可在当前来源独立核对”作为单独字段。

#### Step E：确定性校验

- span 是否越界。
- span 是否真正支持结构化表述。
- Event Time 是否来自正确文本。
- Claim 是否只是文档摘要或同义重复。
- Evidence 是否其实只是另一个未验证 Claim。
- JSON Schema 是否通过。

### 10.3 结构化输出策略

MVP 使用 Pydantic 生成 JSON Schema，ModelGateway 根据 Provider 能力选择：

1. 原生 structured output/tool calling。
2. Instructor 式结构化适配与可控重试。
3. 本地模型使用 Outlines 类约束解码。
4. 仅在上述都不可用时，才使用 JSON 文本解析，失败后不做无限重试。

结构校验成功不代表语义正确，仍必须经过 span 与领域校验。

### 10.4 抽取缓存键

```text
sha256(
  text_unit.content_sha256,
  extraction_task,
  prompt_id,
  prompt_version,
  output_schema_id,
  output_schema_version,
  model_provider,
  model_name,
  decoding_parameters,
  extractor_code_version
)
```

这与 GraphRAG 对相同 Prompt 和参数返回缓存结果的思路一致，但多加了输出 Schema 和代码版本，防止合法但过时的结果被误用。

---

## 11. 聚类、对齐与演化关系

### 11.1 先候选，后判定

不将所有节点两两交给模型。关系管线分为：

```text
确定性约束筛选
  → 语义相似/冲突候选
  → 时间相容性检查
  → 模型分类
  → 反向验证
  → 置信度融合
  → proposed relation
```

### 11.2 Question 聚类

- 强规则：规范化文本完全相同。
- 候选：共享主题、时间重叠、embedding 近邻。
- 判断标签：`same_question`、`rephrases`、`narrows`、`broadens`、`evolves_into`、`unrelated`。
- `evolves_into` 必须同时有时间先后与语义前提，不能仅由相似度推出。

### 11.3 Claim 聚类

先将 Claim 按主题和对应 Question 分区，再使用嵌入近邻和词汇特征生成候选。MVP 数据量小时使用层次聚类或连通分量，不为了算法新颖提前引入复杂图神经网络。

当数据量和密度增长时，再对 HDBSCAN、Leiden 和基于时间的社区发现进行基准比较。

### 11.4 关系集

MVP 对外只开放以下关系：

| 关系 | 有向 | 最低证据 |
| --- | --- | --- |
| `triggers` | Event → Question/Event | 时间先后 + 明示或较强因果文本 |
| `answered_by` | Question → Claim | 同一来源结构或明确问答对齐 |
| `supports` | Evidence/Claim → Claim | 支持 span + 方向判定 |
| `contradicts` | Evidence/Claim → Claim | 冲突 span + 命题范围一致 |
| `evolves_into` | Question/Claim → 同类节点 | 时间先后 + 语义继承/变化 |

`refines`、`supersedes`、`merges_with`、`depends_on` 作为 Phase 2 内部实验标签，在黄金集达到准入阈值前不出现在默认用户视图。

### 11.5 置信度

置信度不直接使用模型自报数字。将其拆为可解释特征：

- `source_completeness`：全文、局部或 snippet。
- `span_entailment`：文本片段与结构化命题的一致度。
- `source_count`：独立来源数。
- `source_quality`：知乎权威等级、明示引用和内容特征，单独显示，不等于真实性。
- `temporal_consistency`：事件和来源时间是否合理。
- `model_agreement`：多次或多模型判定一致性，仅在必要时使用。
- `human_review`：人工审核状态。

对外可提供综合分数，但必须能展开看到上述分量、版本和计算规则。

### 11.6 知识分叉与合并

世界树中的 Branch 是投影对象，不是新的基础事实类型。

- 当一个 Question 对应多个低相似或互相冲突的 Claim 聚类时，产生 Claim Branch。
- 当后续 Question 同时继承前置问题并改变讨论对象时，产生 Question Branch。
- 当两个分支对同一后续 Claim 有高置信支持/修正关系时，投影为 Merge Candidate。
- 合并候选在没有审核或多来源时使用虚线，不直接展示为“共识”。

---

## 12. 世界树投影与前端

### 12.1 视图与事实分离

同一组节点和关系可以生成不同投影：

- `world_tree`：时间纵轴 + 知识分叉。
- `timeline`：突出 Event 与里程碑。
- `question_chain`：只展示 Question 演化。
- `controversy`：围绕指定 Question 展示支持/反驳。
- `consensus`：展示多分支汇聚候选。
- `dead_branch`：展示活跃度下降、被反驳或被替代的分支。

Projection 包含 `projection_version`、`knowledge_as_of`、筛选条件、节点/边 ID、坐标和样式提示。前端可调整外观，但不自行重算知识置信度。

### 12.2 布局契约

```text
WorldTreeNode {
  id, type, label,
  time_anchor,
  x, y,
  branch_id,
  confidence,
  evidence_completeness,
  activity,
  visual_flags[]
}
```

- `y` 由时间映射得到，同一时间精度内保持稳定顺序。
- `x` 由分支层次和冲突减少算法生成。
- 可视化缩放级别分为 overview / branch / evidence，不在首屏渲染所有证据节点。
- 布局在 Web Worker 或服务端生成，避免阻塞前端主线程。

### 12.3 视觉语义映射

| 设计语义 | 工程字段 | 注意 |
| --- | --- | --- |
| 树干高度 | `time_anchor` | 不同时间精度要显示不确定性 |
| 枝条粗细 | `support_weight` | 不只用点赞数，显示计算口径 |
| 枝条长度 | `active_interval` | 缺失后续观测不等于失效 |
| 枝叶密度 | `activity_density` | 需按采样数归一化 |
| 枯枝 | `branch_state=declining|invalidated` | “讨论减少”与“被证伪”分开 |
| 亮度 | `confidence` | 可展开查看分量 |
| 透明度 | `evidence_completeness` | snippet 默认不透明度较低 |

### 12.4 节点详情必须展示

1. 原子命题或事件描述。
2. 节点类型、时间、精度和置信度分量。
3. 支持、反驳和演化关系。
4. 来源标题、作者、发布/编辑时间、知乎链接。
5. 可定位的原文片段和文本完整性警示。
6. 抽取 Prompt/Schema/Model 版本与审核状态。
7. “纠正/确认/标记无法判断”人工审核入口。

---

## 13. 对外 API 草案

### 13.1 资源列表

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/api/v1/topics` | 创建研究主题与边界 |
| `GET` | `/api/v1/topics/{topic_id}` | 查看主题和最新覆盖 |
| `POST` | `/api/v1/topics/{topic_id}/research-runs` | 创建一次可幂等研究任务 |
| `GET` | `/api/v1/research-runs/{run_id}` | 查看阶段、进度、预算与错误 |
| `POST` | `/api/v1/research-runs/{run_id}:cancel` | 请求取消，不删除已持久化快照 |
| `GET` | `/api/v1/research-runs/{run_id}/events` | SSE 进度流 |
| `GET` | `/api/v1/topics/{topic_id}/projections/world-tree` | 世界树投影 |
| `GET` | `/api/v1/topics/{topic_id}/projections/timeline` | 时间线投影 |
| `GET` | `/api/v1/topics/{topic_id}/nodes` | 按类型、时间和状态列出节点 |
| `GET` | `/api/v1/nodes/{node_id}` | 节点当前修订 |
| `GET` | `/api/v1/nodes/{node_id}/provenance` | 来源链与文本片段 |
| `POST` | `/api/v1/assertions/{assertion_id}/reviews` | 提交人工审核决定 |
| `GET` | `/api/v1/topics/{topic_id}/coverage` | 覆盖指标与缺口 |

### 13.2 创建 Research Run

```http
POST /api/v1/topics/{topic_id}/research-runs
Idempotency-Key: 0e5c...
Content-Type: application/json
```

```json
{
  "mode": "initial",
  "budget_profile": "interactive_standard",
  "refresh_policy": "reuse_fresh_cache",
  "requested_views": ["world_tree", "timeline"]
}
```

响应：

```http
HTTP/1.1 202 Accepted
Location: /api/v1/research-runs/019...
Retry-After: 2
```

```json
{
  "id": "019...",
  "status": "queued",
  "stage": "planning",
  "progress": 0,
  "budget": {
    "reserved_units": 30,
    "used_units": 0
  },
  "created_at": "2026-09-08T08:00:00Z"
}
```

### 13.3 Research Run 状态机

```text
queued
  → planning
  → discovering
  → normalizing
  → extracting
  → relating
  → projecting
  → completed
```

任一执行状态可进入 `paused_quota`、`paused_review`、`failed_retryable`、`failed_terminal`或 `cancelled`。恢复时从最后一个已持久化 Step Run 继续。

### 13.4 Problem Details 示例

```json
{
  "type": "https://epistree.dev/problems/upstream-quota-exhausted",
  "title": "Zhihu search quota exhausted",
  "status": 429,
  "detail": "The research run has been paused until quota becomes available.",
  "instance": "/api/v1/research-runs/019...",
  "upstream_code": 30002,
  "quota_scope": "zhihu_search",
  "retry_at": "2026-09-09T00:00:00+08:00",
  "trace_id": "..."
}
```

### 13.5 Projection 分页

大图不一次返回全部证据。请求使用：

```text
focus_node_id
depth
time_from / time_to
node_types[]
min_confidence
review_status
cursor / limit
as_of
```

默认 `depth<=2`、`limit<=500`。超过限制返回明确 Problem Details，不在服务端静默截断却不告知用户。

---

## 14. 工作流与任务幂等

### 14.1 Prefect Flow 划分

```text
research_topic_flow
  plan_queries
  discover_sources[]
  normalize_snapshots[]
  build_text_units[]
  extract_knowledge[]
  deduplicate_nodes
  infer_relations
  build_projections
  evaluate_run
```

数据粒度大的步骤使用 map/并发，但知乎调用必须受全局频率和配额控制器约束。

### 14.2 幂等键

| 任务 | 幂等键组成 |
| --- | --- |
| 发现 | Connector + 规范化查询 + 参数 + 策略时窗 |
| 规范化 | raw payload hash + normalizer version |
| 切分 | content hash + chunker version + policy |
| 抽取 | TextUnit hash + Prompt/Schema/Model/code versions |
| 去重 | candidate set hash + deduper version |
| 关系 | node revision set hash + relation policy version |
| 投影 | graph revision + view config + projection version |

任务重试前先检查持久化结果，不只依赖编排器的短期状态。

### 14.3 重试矩阵

| 错误 | 默认处理 |
| --- | --- |
| 连接超时/5xx | 只对幂等 GET 有限指数退避 + jitter |
| 知乎 `30001` 频率限制 | 停止当前 Connector 并延迟，不紧密重试 |
| 知乎 `30002` 配额耗尽 | Run 进入 `paused_quota`，等待下一自然日或用户决策 |
| 认证失败 | 终止上游任务并报警，不切换凭据 |
| JSON Schema 失败 | 最多按结构化 Provider 策略重试有限次 |
| span 不支持 Claim | 记录为 invalid extraction，不通过改 Prompt 即时循环到成功 |
| 缓存不可用 | 读取降级至持久层，必要时拒绝新上游请求 |
| 数据库写失败 | 不提交配额“成功产物”，但保留实际调用审计记录 |

### 14.4 取消语义

取消是协作式：已经发出的上游请求允许完成持久化，不为了追求“立即停止”而丢弃已消耗的额度成果。新的上游请求不再发出，已完成快照标记所属 Run 被取消，仍可为后续 Run 复用。

---

## 15. 评测与质量门槛

### 15.1 黄金集

在开发演化引擎前，先建立一个小而精的中文知乎黄金集：

- 3–5 个主题，包含技术、社会争议和专业知识类型。
- 每个主题 20–50 条可合法保存的快照或人工标注片段。
- 标注 Event、Question、Claim、Evidence、SourceSpan 和 MVP 五类关系。
- 包含“不应抽取”、“无法判断”、反问、讽刺、引用他人观点等困难样例。
- 黄金集保留标注指南版本和标注者决策。

参考 Phoenix 的 Dataset/Experiment 模型，评测数据集是独立版本化资产，不从某次生产运行中临时挑选几个成功例子。

### 15.2 指标

#### 采集与缓存

- 相同查询新鲜期内的上游重复调用率。
- 查询缓存 hit rate。
- 每个配额单位的新增唯一 ContentID。
- 每个查询的边际新增率。
- 原始响应快照持久化成功率。
- 运行中配额记账与官方快照差异。

#### 抽取

- 节点级 precision / recall / F1。
- SourceSpan exact/overlap F1。
- Claim atomicity 人工评分。
- Evidence 被误当成 Claim 的比例。
- Event Time 语义准确率。
- abstention 在难例上的准确性。

#### 关系

- 每个 relation type 的 precision/recall/F1，不只看总分。
- 关系方向错误率。
- 无来源关系率，目标为 0。
- 时间不可能关系率。
- 人工审核接受、驳回和修改率。

#### 产品投影

- 节点到原文片段的可达率，目标 100%。
- 查询范围内投影稳定性：相同图修订必须生成相同布局键。
- 首屏渲染时间、交互 P95 和内存使用。
- 用户能否回答“这个分支为什么出现”的任务成功率。

### 15.3 初始质量门槛

以下是进入演示环境前的建议起点，需在黄金集完成后根据难度调整：

- 强身份去重正确率 100%。
- 已接受节点的 provenance 完整率 100%。
- Claim 抽取 precision ≥ 0.85。
- `contradicts` precision ≥ 0.85，达不到时不自动显示强冲突线。
- 时间解析准确率 ≥ 0.90；不确定样例允许 abstain。
- 新鲜期内相同查询重复调用上游率 < 1%。
- 缓存故障不导致原始快照丢失。

### 15.4 评测工具选择

- 底层记录使用 OpenTelemetry，保留可迁移性。
- 早期可选自托管 [Arize Phoenix](https://arize.com/docs/phoenix/)，用其 Datasets、Experiments、Tracing 和人工标注界面。
- [Langfuse](https://langfuse.com/docs/) 作为 Prompt 版本管理和生产指标备选；在未确认部署和许可成本前不同时部署两套平台。
- 核心准入指标用项目自身测试实现，不将工具的 LLM-as-a-judge 分数当作唯一质量门槛。

---

## 16. 可观测性与安全

### 16.1 Trace 边界

一次 Research Run 是根 Span，下属包含：

```text
research.run
  planner.plan
  zhihu.quota.snapshot
  zhihu.search
  source.normalize
  text.chunk
  model.extract
  node.deduplicate
  relation.infer
  projection.build
```

字段包含 run ID、topic ID、connector/model 版本、cache hit/miss、耗时、返回数、新增数和 token 使用。不记录 Access Secret、OAuth Token、完整个人数据或无脱敏的模型输入。

### 16.2 Metrics

- `zhihu_requests_total{endpoint,status}`
- `zhihu_quota_remaining{scope}`
- `cache_requests_total{layer,result}`
- `query_unique_items_ratio`
- `pipeline_step_duration_seconds`
- `model_requests_total{task,model,status}`
- `extraction_invalid_total{reason}`
- `relations_proposed_total{type}`
- `provenance_missing_total`
- `projection_build_duration_seconds`

额度预警按剩余百分比和应急保留线触发，而不把当前 5,000 写入监控规则。

### 16.3 凭据

- Access Secret 仅由服务运行时的 Secret Store 注入。
- 依项目 `AGENTS.md` 要求，本地调用使用项目级 `ZHIHU_CLI_HOME`，不执行全局 `auth set`。
- 不将 Secret 写入 `.env`、数据库、缓存、日志、Trace 或原始快照。
- 上游请求日志只记录经过脱敏的 endpoint、参数哈希和 request ID。

### 16.4 内容与用户数据

- 公共知乎搜索缓存与用户授权数据物理/逻辑分区。
- 每个用户授权数据对象携带 owner scope，不进入公共主题缓存。
- 前端不默认展示大段原文，显示必要片段、作者和原链接。
- 删除请求需区分“从当前投影隐藏”和“依合规规则删除持久快照”。

---

## 17. 分阶段实施计划

每个阶段只在前一阶段验收通过后开始。不为了“端到端看起来能跑”跳过原始快照、契约或黄金集。

### Phase 0：契约与固定样例

**目标：**不调用线上 API，定义最小契约和可重放样例。

**产物：**

- Topic、ResearchRun、SourceIdentity、SourceSnapshot、TextUnit 的 JSON Schema。
- 知乎搜索成功、空结果、限流、配额耗尽和字段缺失 fixtures。
- SourceConnector/QuotaProvider/CacheStore contract tests。
- ADR-001 至 ADR-004。

**验收：**

- 同一 fixture 能够稳定生成同一 SourceIdentity 和内容哈希。
- 未识别字段被保留，缺失可选字段不导致整批失败。
- 错误 fixture 转换为稳定的 Problem Details。

### Phase 1：知乎 Connector + 持久快照

**目标：**完成一次受控的真实搜索并可离线重放。

**产物：**

- ZhihuSearchConnector。
- PostgreSQL 原始快照和规范化表。
- 额度快照、预留和实用记录。
- Access Secret 注入、脱敏日志和错误处理。

**验收：**

- 真实请求的 raw response 先于下游产物落库。
- 重放时不调用知乎。
- 额度耗尽和认证失败都不触发无限重试。

### Phase 2：查询规划 + 配额缓存

**目标：**将单次 10 条的限制转换为可计量的跨查询、跨日主题积累。

**产物：**

- QueryPlan、CoverageSnapshot 和停止条件。
- Valkey L1、PostgreSQL L2 与 single-flight。
- 查询收益统计和预算分桶。
- 用户可查看的查询原因与缺口。

**验收：**

- 新鲜期内相同查询几乎不重复调用上游。
- 多查询结果能按 ContentID 正确去重并保留排名观测。
- 任务会因边际收益下降或预算用完而可解释地停止。

### Phase 3：TextUnit + 黄金集

**目标：**在大模型管线前建立可追溯切分和评测基线。

**产物：**

- 中文结构感知切分器。
- TextUnit/SourceSpan 字符级定位。
- 首个主题的标注指南和黄金集。
- 完整性级别和 snippet 警示。

**验收：**

- 任一 TextUnit 可以精确映射回原快照。
- 重放相同切分版本产生相同 TextUnit ID/哈希。
- 标注者可区分 Claim、Evidence 和普通背景陈述。

### Phase 4：节点抽取

**目标：**实现 Event/Question/Claim/Source 的可追溯抽取。

**产物：**

- ModelGateway 与结构化输出 Provider。
- Prompt/Schema 版本化。
- 确定性 span 校验与抽取缓存。
- 黄金集评测报告。

**验收：**

- 所有 proposed 节点均有 SourceSpan。
- 更换模型 Provider 不需修改领域模型。
- 达不到节点类型的准入阈值时不进入下一阶段。

### Phase 5：关系与演化

**目标：**建立 MVP 五类关系和双时态修订。

**产物：**

- Question/Claim 聚类。
- 关系候选生成器和分类器。
- RelationRevision、失效与 ReviewDecision。
- 按 relation type 拆分的评测报告。

**验收：**

- 无来源关系无法进入 accepted。
- `contradicts` 和 `evolves_into` 的方向性检查通过。
- 新快照可以使旧判断失效，但历史 `as_of` 查询仍可重建。

### Phase 6：API + 世界树投影

**目标：**交付可浏览、可追溯、可解释覆盖范围的端到端 Demo。

**产物：**

- OpenAPI 3.1 文档和生成的 TypeScript client。
- Research Run 状态页。
- Cytoscape.js 世界树、节点详情与来源回链。
- Coverage/Gap 面板。
- 模块故障降级与运行手册。

**验收：**

- 从创建主题到查看世界树的核心路径可在真实部署环境完成。
- 节点来源链可达率为 100%。
- 配额耗尽、缓存不可用和模型失败都显示真实状态。

### Phase 7：增量 Research Agent

只有 Phase 6 稳定后才开始。Agent 不是另一套全能流程，只负责：

- 根据 CoverageSnapshot 提议下一批 QueryCandidate。
- 解释当前缺口和预算价值。
- 对超过预算或扩展主题边界的行动请求人工确认。
- 不直接修改 accepted 知识节点。

---

## 18. 发布、Schema 和迁移

### 18.1 版本层级

- 产品版本：仓库 `VERSION` 和 Git tag。
- API 版本：`/api/v1`，只在不兼容资源语义变化时升级。
- Domain Schema 版本：每种对象独立 `schema_version`。
- Prompt 版本：不可变定义 + 可变 label（`candidate`、`production`、`retired`）。
- Model Profile 版本：Provider、模型名、参数和能力快照。
- Projection 版本：布局和视觉语义变化时可重建。

### 18.2 兼容策略

- 字段新增默认为 optional，待所有生产者升级后再改为 required。
- 不重用旧枚举值的语义。
- 事件破坏性变更创建新 type 版本，旧消费者有明确迁移期。
- 原始 SourceSnapshot 永不做破坏性就地迁移，新 Normalizer 从快照重放。
- 数据库迁移使用 expand/migrate/contract 三步，避免一次发布同时修改写入方和删除旧字段。

### 18.3 Changelog

每个发布版本必须同步：

1. 将 `CHANGELOG.md / Unreleased` 按 Added/Changed/Deprecated/Removed/Fixed/Security 归档。
2. 更新 `VERSION`。
3. 更新 Schema/Prompt/Projection 兼容性说明。
4. 生成迁移和重建影响清单。
5. 运行黄金集回归并保存报告引用。
6. 创建对应 Git tag 与 GitHub Release。

---

## 19. 风险、降级与上报条件

### 19.1 风险登记表

| 风险 | 影响 | 缓解 | 上报触发器 |
| --- | --- | --- | --- |
| 搜索无翻页且每次 10 条 | 不能声称全量 | 查询分解、跨日积累、Coverage 透明 | 主题达到收益停止后仍无关键时段 |
| `ContentText` 可能不完整 | Evidence 追溯弱 | 完整性分级，snippet 不进入强证据 | 核心 Demo 主题的全文/部分文本过少 |
| 开放 API 或赛事接口变动 | Connector 失效 | capabilities + contract fixtures + 隔离 Adapter | 字段或认证语义发生破坏变化 |
| 模型幻觉关系 | 错误世界树 | span 强制、abstain、黄金集、人工审核 | 关系 precision 持续低于准入线 |
| 时间歧义 | 错误演化方向 | 三时间分离、精度和原文保留 | 关键分支依赖无法解析的时间 |
| 图过密 | UI 无法理解 | 多级投影、focus/depth、不同视图 | 用户任务测试无法识别主干和分支 |
| 双数据库一致性 | 发生幽灵边/丢边 | MVP 只用 PostgreSQL，图库只是投影 | 决定引入 Neo4j/AGE 前必须审核 |
| 技术框架锁定 | 升级和替换困难 | Ports、JSON Schema、OpenTelemetry | Provider 类型泄漏到领域模型 |

### 19.2 必须停止并向项目负责人汇报的问题

1. 需要使用非知乎数据才能完成核心 Demo，将改变“知乎优先”产品边界。
2. 需要使用未文档化接口、爬虫或绕过额度/认证的方式。
3. 需要将 Access Secret、OAuth Token 或用户数据放入无法保证隔离的环境。
4. 官方 API 的认证、额度、返回字段或内容使用条件发生破坏性改变。
5. 黄金集显示核心关系无法达到准入门槛，需要改变产品展示承诺。
6. 需要引入第二个事实数据库、分布式消息系统或付费基础设施。
7. 需要改变已发布 Domain/API/Event Schema 的兼容性。
8. 需要在无法保留 SourceSpan 的情况下将模型结果展示为事实。

上报内容应包含：已确认事实、受影响模块、可选方案、各方案代价、推荐方案和“暂不决策”的后果。未获得方向后不继续扩展受影响模块。

---

## 20. 架构决策记录（ADR）队列

实现开始前应将以下结论转成独立 ADR，包含 Context / Decision / Alternatives / Consequences：

| ADR | 主题 | 当前建议 |
| --- | --- | --- |
| ADR-001 | 架构形态 | 模块化单体 + 独立 Worker |
| ADR-002 | 事实库 | PostgreSQL + pgvector |
| ADR-003 | 工作流 | Prefect 编排确定性管线 |
| ADR-004 | 来源语义 | SourceSnapshot 不可变 + SourceSpan 强制 |
| ADR-005 | 时间 | Valid/Observation/Source 三时间分离 |
| ADR-006 | 缓存 | L0/L1/L2/L3 分层 + cache-aside + single-flight |
| ADR-007 | 接口 | OpenAPI 3.1 + JSON Schema 2020-12 + RFC 9457 |
| ADR-008 | 事件 | CloudEvents + transactional outbox |
| ADR-009 | 前端图 | Cytoscape.js + Epistree 投影坐标 |
| ADR-010 | 评测 | 版本化黄金集 + 决定性指标优先 |

ADR 只记录具有长期代价的选择，不把每个库的小版本升级都写成 ADR。

---

## 21. 近期工程任务拆分

以下是实现开始后的最小任务顺序，每项应独立评审和验收：

1. 冻结 SourceIdentity/SourceSnapshot JSON Schema。
2. 整理脱敏知乎 API fixtures，覆盖成功与错误。
3. 实现 Connector contract test harness。
4. 确定 PostgreSQL 最小迁移和原始快照表。
5. 实现 ZhihuSearchConnector 的 fixture adapter。
6. 在具备凭据后用一次真实搜索做 contract verification。
7. 实现查询规范化、缓存键和 L2 查重。
8. 实现额度快照和本地预算预留。
9. 实现 Valkey cache-aside 和 single-flight。
10. 建立 QueryPlan 的纯规则版本，先不用 Agent。
11. 实现 ContentID/URL/hash 三层去重。
12. 完成第一个主题语料池与 CoverageSnapshot。
13. 冻结 TextUnit/SourceSpan Schema 并建立切分回链测试。
14. 编写黄金集标注指南并双人复核首批样本。
15. 在没有图可视化之前验证 Claim 和 SourceSpan 抽取质量。

---

## 22. 参考项目与标准

### 知识图谱、论点与时间

- [Microsoft GraphRAG: Architecture](https://microsoft.github.io/graphrag/index/architecture/)
- [Microsoft GraphRAG: Dataflow](https://microsoft.github.io/graphrag/index/default_dataflow/)
- [Microsoft GraphRAG repository](https://github.com/microsoft/graphrag)
- [Graphiti overview](https://help.getzep.com/graphiti/getting-started/overview)
- [Graphiti repository](https://github.com/getzep/graphiti)
- [Argument Interchange Format specification](https://www.arg-tech.org/wp-content/uploads/2011/09/aif-spec.pdf)
- [EventKG paper](https://arxiv.org/abs/1804.04526)
- [W3C PROV-O](https://www.w3.org/TR/prov-o/)
- [W3C OWL-Time](https://www.w3.org/TR/owl-time/)
- [Neo4j graph versioning patterns](https://neo4j.com/docs/getting-started/data-modeling/versioning/)

### 工作流、缓存与存储

- [Prefect task caching](https://docs.prefect.io/v3/concepts/caching)
- [Prefect tasks](https://docs.prefect.io/v3/concepts/tasks)
- [Dagster asset-oriented orchestration](https://docs.dagster.io/)
- [LangGraph overview](https://langchain-ai.github.io/langgraph/index.html)
- [RFC 9111: HTTP Caching](https://www.rfc-editor.org/rfc/rfc9111.html)
- [Redis cache-aside pattern](https://redis.io/docs/latest/develop/use-cases/cache-aside/)
- [Valkey repository](https://github.com/valkey-io/valkey)
- [PostgreSQL JSON types](https://www.postgresql.org/docs/current/datatype-json.html)
- [pgvector](https://github.com/pgvector/pgvector)
- [Apache AGE](https://github.com/apache/age)

### API、事件与观测

- [OpenAPI Specification 3.1](https://spec.openapis.org/oas/v3.1.1.html)
- [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12)
- [RFC 9457: Problem Details for HTTP APIs](https://www.rfc-editor.org/rfc/rfc9457.html)
- [CloudEvents specification](https://github.com/cloudevents/spec)
- [OpenTelemetry Trace specification](https://opentelemetry.io/docs/specs/otel/trace/)
- [FastAPI features and standards](https://fastapi.tiangolo.com/features/)
- [Arize Phoenix](https://arize.com/docs/phoenix/)
- [Langfuse](https://langfuse.com/docs/)

### 前端图可视化

- [Cytoscape.js](https://js.cytoscape.org/)
- [Sigma.js](https://www.sigmajs.org/docs/)

---

## 23. 未决问题

以下问题不阻塞 Phase 0，但必须在对应阶段前决策：

1. 首个黄金集与演示主题是什么？
2. 首版是单用户本地 Demo，还是需要支持公网多用户？
3. 大模型 Provider 的可用性、成本与结构化输出能力如何？
4. 搜索返回的 `ContentText` 在真实样本中完整性分布如何？
5. 世界树的主要评审场景是“一眼理解”还是“进入每个证据详查”？
6. 对知乎内容的本地持久化、片段展示和保留期应采用什么合规策略？

这些问题应通过小样本验证和项目负责人决策逐项关闭，不应由开发者在代码中隐式选择。
