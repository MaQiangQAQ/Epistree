# Epistree 可行 Demo 完整设计

> 文档状态：Draft 0.1<br>
> 面向目标：一个可公网演示、可回溯知乎来源的最小知识世界树<br>
> 最后更新：2026-09-08<br>
> 上位文档：[《Epistree 初步工程设计》](ENGINEERING_DESIGN.md)

## 0. 结论先行

这个 Demo 只实现一条能被评委完整操作的主链路：

```text
输入一个主题
  → 预览 4 条固定规则生成的知乎查询
  → 在本地预算内检索，优先命中持久缓存
  → 按 ContentID 去重，最多选 12 条来源
  → 用一次结构化模型调用生成 Question / Claim / Event / Relation
  → 显示可交互知识世界树
  → 点击节点查看原文摘要、作者、时间和知乎链接
```

为了保证可实现性，Demo 使用单个 Python 应用、单个持久化目录和一个可配置的模型端点。不使用微服务、PostgreSQL、Valkey、Neo4j、向量数据库、Prefect、Celery 或消息队列。

Demo 的技术组合：

| 职责 | 直接使用的成熟项目 | 用法 |
| --- | --- | --- |
| Web 界面 | [Plotly Dash](https://github.com/plotly/dash) | 表单、状态、回调和页面布局 |
| 交互图谱 | [Dash Cytoscape](https://github.com/plotly/dash-cytoscape) | 节点、边、布局、点击与导出 |
| 后台回调 | Dash 官方 DiskCache manager | 执行搜索与模型调用，支持进度和取消 |
| HTTP 缓存 | [requests-cache](https://github.com/requests-cache/requests-cache) | SQLite 后端、TTL、`stale_if_error`、`from_cache` |
| 数据验证 | [Pydantic](https://github.com/pydantic/pydantic) | 知乎响应和世界树对象校验 |
| 模型结构化输出 | [Instructor](https://github.com/567-labs/instructor) | 让模型直接返回 Pydantic 对象并限制重试 |
| 上游瞬时错误重试 | [Tenacity](https://github.com/jd/tenacity) | 仅重试超时、429 和 5xx，指数退避 |
| 业务数据 | Python `sqlite3` + SQLite | 原始快照、去重结果、模型结果和运行记录 |
| 测试 | [pytest](https://github.com/pytest-dev/pytest) + [responses](https://github.com/getsentry/responses) | 单元测试和知乎 HTTP 模拟 |

---

## 1. Demo 要证明什么

Demo 不需要证明 Epistree 已经是完整知识图谱平台。它只需要证明三件事：

1. 从一组有限的知乎内容中，可以组织出比搜索列表更易理解的问题、观点和关系。
2. 每个模型产生的节点都能回到具体知乎来源，而不是无来源的结论。
3. 在知乎每日配额下，缓存能将已支付过的调用转化为可重复演示的主题资产。

### 1.1 核心用户故事

> 作为一个对某个话题感兴趣的知乎用户，我输入话题后，能看到这个话题下的主要问题、不同观点及其支持、冲突和演变关系，并且可以点回知乎原文自行判断。

### 1.2 成功画面

一次成功演示应在 2–3 分钟内完成：

1. 输入主题或选择一个已缓存的演示主题。
2. 页面显示将要执行的 4 条查询和“预计最多消耗 4 次知乎搜索调用”。
3. 点击“生成世界树”，看到搜索、去重、抽取和绘图进度。
4. 世界树显示 Topic、Question、Claim、Event 和 Source 节点。
5. 点击 Claim 看到来源摘要；点击 Source 能打开知乎原链接。
6. 页面明确显示缓存命中数、真实调用数、数据时间和模型候选标识。

---

## 2. 固定范围

### 2.1 Demo 包含

- 一个主题输入框。
- 3 个可预热的演示主题。
- 最多 6 条可编辑知乎查询，默认 4 条。
- 知乎搜索响应的持久缓存。
- 最多 12 条来源的去重与入选。
- 一次结构化知识抽取。
- 一张交互图、一个节点详情栏、一个来源列表。
- JSON 结果导出。
- 配额、缓存、错误和过期数据提示。

### 2.2 Demo 不包含

- 多用户账号和知乎 OAuth。
- 知乎以外的数据。
- 自动事实判定。
- 自主 Research Agent 和无限查询扩展。
- 向量搜索、知识库问答和对话。
- 人工审核后台。
- 图数据库、分布式任务和横向扩容。
- 实时监控知乎内容变化。
- 对知乎整体覆盖率的声明。

### 2.3 数据原则

- 只向模型提供知乎 API 返回的文本与元数据。
- 提示词要求模型不得使用自身知识补充事实。
- `ContentText` 在产品中始终标记为“知乎接口返回文本”，不声称是全文。
- 所有 Claim、Event 和推断关系都标记为 `model_candidate`。
- 每个候选节点至少引用一个 `source_id`；无合法引用时整个输出拒绝入库。

---

## 3. 为什么选这些现成项目

### 3.1 UI 方案比较

| 方案 | 优点 | Demo 中的代价 | 结论 |
| --- | --- | --- | --- |
| Dash + Dash Cytoscape | 全 Python；官方图组件；回调直接支持节点点击、样式和进度 | 复杂前端定制能力不如 React | **采用** |
| Streamlit | 上手快，生态大 | 交互图需另选社区组件或自己包装 Cytoscape | 不采用 |
| Gradio | 非常适合模型输入输出 | 知识图不是核心组件 | 不采用 |
| FastAPI + React | 扩展性最强 | 需要两套工程、API client 和前端状态管理 | 完整产品阶段再考虑 |

Dash Cytoscape 本身就接受 `elements=[nodes, edges]`，并提供 `tapNodeData`、stylesheet 和布局参数。Demo 不再自建 Canvas、SVG 引擎或图互动层。

### 3.2 存储与缓存方案比较

| 方案 | 是否需要外部服务 | 是否适合单实例 Demo | 结论 |
| --- | ---: | ---: | --- |
| SQLite + requests-cache | 否 | 是 | **采用** |
| PostgreSQL + Valkey | 是 | 能用，但部署和故障面增加 | 不采用 |
| Neo4j | 是 | 数据量过小，查询价值不明显 | 不采用 |
| 只使用内存 | 否 | 不能跨重启复用配额 | 不采用 |

`requests-cache` 已经实现 SQLite 后端、过期时间、按请求匹配、过期回退和缓存命中标识。因此 Demo 不自己写 HTTP 缓存协议。SQLite 业务表只保存 Epistree 必需的可回溯数据。

### 3.3 模型输出方案比较

| 方案 | 优点 | 问题 | 结论 |
| --- | --- | --- | --- |
| Instructor + Pydantic | 结构化输出、校验、有限重试已封装 | 需要支持的模型 Provider | **采用** |
| 手写 JSON 解析/修复 | 表面上依赖少 | 容易形成无尽的容错代码 | 不采用 |
| LangGraph Agent | 适合多步长流程 | Demo 只有一次有界抽取，引入状态图过重 | 不采用 |
| GraphRAG 完整管线 | 能力强 | 对 12 条来源过度；当前上游 Python 版本边界也不适作 Demo 直接依赖 | 只借鉴来源回链思路 |

---

## 4. 运行架构

```text
Browser
  │
  │ Dash callbacks / progress
  ▼
Dash application
  ├── DemoService                  # 串行组合主链路
  │    ├── QueryBuilder             # 4 条固定规则
  │    ├── ZhihuSearchClient        # requests-cache + Tenacity
  │    ├── SourceSelector           # ContentID 去重 + 轮询入选
  │    ├── KnowledgeExtractor       # Instructor + Pydantic
  │    └── CytoscapePresenter       # 领域对象→elements
  │
  ├── DiskCache background manager # Dash 官方 Demo 后台方案
  ├── http_cache.sqlite             # requests-cache 管理
  └── epistree.sqlite               # 应用持久化
       ├── runs / queries / query_observations
       ├── sources / source_snapshots
       └── graph_bundles

External calls
  ├── Zhihu official zhihu_search API
  └── Configured structured-output model endpoint
```

### 4.1 部署单元

只有一个容器：

- 一个 Dash/Gunicorn Web 进程。
- Dash DiskCache 后台任务使用官方 manager 创建子进程。
- 一个挂载到 `/data` 的持久化目录。
- 只运行一个容器副本。

DiskCache 后台回调在 Dash 文档中定位为本地或轻量场景方案，不适合通用生产系统。这个限制与单实例黑客松 Demo 相符。不为了未发生的横向扩容提前引入 Celery/Redis。

### 4.2 代码目录

```text
.
├── pyproject.toml
├── Dockerfile
├── .env.example
├── src/epistree_demo/
│   ├── app.py                  # Dash 布局与回调注册
│   ├── config.py               # Pydantic Settings
│   ├── models.py               # 全部 Pydantic 契约
│   ├── db.py                   # SQLite 建表与明确 SQL
│   ├── query_builder.py        # 固定查询模板
│   ├── zhihu_client.py         # 官方 HTTP API adapter
│   ├── selector.py             # 去重和轮询入选
│   ├── extractor.py            # Instructor 单次抽取
│   ├── presenter.py            # Dash Cytoscape 元素转换
│   ├── service.py              # 主链路编排
│   └── assets/style.css        # 少量页面样式
├── tests/
│   ├── fixtures/zhihu_search.json
│   ├── test_models.py
│   ├── test_zhihu_client.py
│   ├── test_selector.py
│   ├── test_extractor_contract.py
│   └── test_demo_flow.py
└── docs/
    ├── ENGINEERING_DESIGN.md
    └── DEMO_DESIGN.md
```

不增加 `domain/ports/adapters/infrastructure` 等多层目录。对 Demo 而言，九个职责明确的文件已足够。

---

## 5. 端到端流程

### 5.1 步骤 1：构造查询

`QueryBuilder` 不使用模型，也不做递归扩展。它只根据主题构造四条可见、可编辑查询：

```text
{topic}
{topic} 起源
{topic} 争议
{topic} 变化
```

规则：

- 对主题执行 Unicode NFKC、首尾空格清理和连续空格折叠。
- 主题长度限制为 2–50 个字符。
- 查询去重，总数不得超过 6。
- 用户在执行前可删除或修改查询。
- 页面根据当前缓存状态显示“最多真实调用数”，不只显示查询条数。

这一阶段的意图是让评委理解系统如何使用配额，也避免 Query Agent 把一个 Demo 变成不可控的多步任务。

### 5.2 步骤 2：执行知乎搜索

`ZhihuSearchClient` 只包装已文档化的官方接口：

```text
GET https://developer.zhihu.com/api/v1/content/zhihu_search
Query=<query>
Count=10
Authorization: Bearer <ZHIHU_ACCESS_SECRET>
X-Request-Timestamp: <unix-seconds>
```

同一 client 还提供官方额度读取：

```text
GET https://developer.zhihu.com/api/v1/quota?APIIDs=zhihu_search
```

额度查询不消耗业务额度。只在本次运行存在未命中缓存的搜索时读取一次；所有查询都命中缓存时不读取。

它输出统一的 `SearchResponse`，但不改写上游业务语义。

处理规则：

- `Code != 0` 一律按上游失败处理，不伪装成空结果。
- `Count` 固定为 10，不构造不存在的分页。
- 仅对连接超时、429 和 5xx 重试，最多 2 次。
- 401/403 立即停止并显示凭据错误，不重试。
- 每次真实请求前先检查 Demo 本地预算。
- 缓存响应同样经过 Pydantic 验证，不默认旧格式永远可用。

### 5.3 步骤 3：持久化与去重

上游响应校验通过后，在一个 SQLite 事务中：

1. 保存 run 与 query observation。
2. 将每个 Item 按 `(content_type, content_id)` upsert 到 `sources`。
3. 根据返回文本和元数据计算 `payload_sha256`。
4. 新哈希写入 `source_snapshots`，相同哈希只记录新 observation。
5. 保留查询内的原始排名和 `RankingScore`。

用户不会因同一内容命中多个查询而看到重复 Source，但查询观测不会被删除。

### 5.4 步骤 4：选择模型输入

Demo 不自建复杂质量评分器。`SourceSelector` 使用可解释的轮询方法：

1. 按查询在页面中的顺序建立 4 个结果队列。
2. 每轮从每个查询取一条尚未出现的 ContentID。
3. 直到选满 12 条或无新结果。
4. 队列内保持知乎 API 返回顺序，不自己重算排名。

这样能避免“主题本身”查询占据所有位置，同时不引入向量模型、权重学习或人工阈值系统。

持久化时保留完整 `ContentText`；发给模型时每条最多使用前 1,500 个字符，并在输入中标记 `truncated_for_model=true/false`。

### 5.5 步骤 5：一次结构化抽取

`KnowledgeExtractor` 将主题和最多 12 条 Source 一次性发给模型。模型必须返回 `GraphBundle`，不允许返回 Markdown 或自由文本。

输出上限：

| 对象 | 最多数量 |
| --- | ---: |
| Question | 5 |
| Event | 5 |
| Claim | 12 |
| Claim 间候选关系 | 15 |

抽取不拆成“摘要→实体→聚类→关系判断”四个模型任务。对 12 条来源的 Demo，一次有上限、有 Schema 的抽取更容易调试和控制成本。

Instructor 重试最多 2 次。只有以下情况可重试：

- 不符合 Pydantic Schema。
- 引用了不存在的 `source_id`。
- 节点或关系数量超过上限。

超过重试上限后，运行标记失败并保留搜索结果，不进入手写 JSON 修复分支。

### 5.6 步骤 6：构造图元素

`CytoscapePresenter` 是一个纯函数：

```text
GraphBundle + Sources -> list[CytoscapeElement]
```

节点类型与样式：

| 节点 | 形状 | 主色 | 展示文字 |
| --- | --- | --- | --- |
| Topic | 大圆 | 深绿 | 主题 |
| Question | 圆角矩形 | 蓝色 | 问题简写 |
| Claim | 椭圆 | 紫色 | 命题简写 |
| Event | 菱形 | 橙色 | 事件 + 时间 |
| Source | 小矩形 | 灰色 | 作者 / 标题 |

边分两类：

- 确定结构边：`contains`、`answers`、`mentioned_in`。
- 模型候选边：`supports`、`contradicts`、`evolves_into`。

模型候选边使用虚线，详情栏始终显示“AI 提取，请查看来源”。

---

## 6. 最小数据契约

### 6.1 知乎搜索对象

```python
class SearchItem(BaseModel):
    source_id: str                    # "zhihu:{type}:{ContentID}"
    content_id: str
    content_type: str
    title: str
    content_text: str
    url: HttpUrl
    author_name: str
    edit_time: datetime | None
    vote_up_count: int = 0
    comment_count: int = 0
    authority_level: str | None = None
    ranking_score: float | None = None
```

`source_id` 由系统确定性生成，不使用模型产生的 ID。

### 6.2 知识对象

```python
class SourceRef(BaseModel):
    source_id: str
    quote: str | None = None

class QuestionNode(BaseModel):
    id: str
    text: str
    source_refs: list[SourceRef]

class ClaimNode(BaseModel):
    id: str
    text: str
    question_id: str
    source_refs: list[SourceRef]
    confidence: float = Field(ge=0, le=1)

class EventNode(BaseModel):
    id: str
    text: str
    occurred_at: str | None
    source_refs: list[SourceRef]
    confidence: float = Field(ge=0, le=1)

class CandidateRelation(BaseModel):
    id: str
    source_node_id: str
    target_node_id: str
    relation_type: Literal["supports", "contradicts", "evolves_into"]
    source_refs: list[SourceRef]
    confidence: float = Field(ge=0, le=1)

class GraphBundle(BaseModel):
    topic: str
    questions: list[QuestionNode] = Field(max_length=5)
    claims: list[ClaimNode] = Field(max_length=12)
    events: list[EventNode] = Field(max_length=5)
    relations: list[CandidateRelation] = Field(max_length=15)
```

### 6.3 跨对象校验

Pydantic model validator 负责：

- 所有 ID 在各自集合内唯一。
- Claim 的 `question_id` 必须存在。
- Relation 两端必须是存在的 Claim。
- 所有 `source_refs` 必须指向本次输入来源。
- Question、Claim、Event 和 Relation 的 `source_refs` 不得为空。
- `quote` 若非空，必须能在对应 `content_text` 中找到；否则将引用降级为无 quote 的 SourceRef，不伪造字符位置。

---

## 7. SQLite 设计

Demo 业务库只保留 7 张表。

### 7.1 `runs`

| 字段 | 用途 |
| --- | --- |
| `id` | UUID |
| `topic` | 规范化主题 |
| `status` | queued/running/completed/failed/cancelled |
| `started_at`, `finished_at` | 运行时间 |
| `real_api_calls`, `cache_hits` | 配额与缓存观测 |
| `error_code`, `error_message` | 失败信息 |
| `graph_bundle_id` | 成功结果 |

### 7.2 `queries`

| 字段 | 用途 |
| --- | --- |
| `id` | UUID |
| `normalized_query` | 去重后查询 |
| `query_sha256` | 唯一键 |
| `created_at` | 首次出现时间 |

### 7.3 `query_observations`

| 字段 | 用途 |
| --- | --- |
| `id` | UUID |
| `run_id`, `query_id` | 关联运行和查询 |
| `observed_at` | 本次观测时间 |
| `from_cache`, `is_expired` | 缓存状态 |
| `search_hash_id` | 知乎返回的请求标识 |
| `item_count` | 返回条数 |

### 7.4 `sources`

| 字段 | 用途 |
| --- | --- |
| `id` | `zhihu:{type}:{ContentID}` |
| `content_id`, `content_type` | 上游身份 |
| `canonical_url` | 移除 UTM 后的知乎链接 |
| `first_seen_at`, `last_seen_at` | 观测边界 |

### 7.5 `source_snapshots`

| 字段 | 用途 |
| --- | --- |
| `id`, `source_id` | 快照身份 |
| `observed_at` | 获取时间 |
| `payload_sha256` | 内容去重 |
| `title`, `content_text`, `author_name` | 展示与抽取 |
| `edit_time`, `metrics_json` | 时间和社区指标 |
| `raw_json` | 可离线重放的原始 Item |

唯一约束：`(source_id, payload_sha256)`。

### 7.6 `query_source_observations`

保存 `query_observation_id`、`source_snapshot_id`、`rank`、`ranking_score`。同一 Source 出现在不同查询时保留多条观测。

### 7.7 `graph_bundles`

| 字段 | 用途 |
| --- | --- |
| `id` | UUID |
| `input_sha256` | 排序后 Source payload hash + Prompt/Model 版本 |
| `prompt_version`, `model_name` | 可复现信息 |
| `bundle_json` | Pydantic 验证通过的 GraphBundle |
| `created_at` | 生成时间 |

`input_sha256` 唯一。完全相同的输入、Prompt 和模型配置直接复用旧结果，不再调用模型。

---

## 8. 缓存与配额

### 8.1 两类“缓存”

Demo 只区分两类：

1. **HTTP 缓存**：由 `requests-cache` 管理，目的是避免相同搜索重复调用知乎。
2. **研究资产**：由 `epistree.sqlite` 保存 SourceSnapshot 和 GraphBundle，它们不是可随意清空的性能缓存。

这个区分很重要：HTTP 缓存可以过期，已经用配额获得的来源快照应持续保留，使 Demo 能跨天积累而不是每天归零。

### 8.2 requests-cache 配置

建议配置等价于：

```python
CachedSession(
    cache_name="/data/http_cache",
    backend="sqlite",
    expire_after=timedelta(hours=24),
    stale_if_error=timedelta(days=7),
    ignored_parameters=[
        *DEFAULT_IGNORED_PARAMS,
        "X-Request-Timestamp",
    ],
    wal=True,
)
```

关键原因：

- 知乎搜索请求使用每请求 `expire_after=24h`；额度请求使用 `expire_after=5min`，不另写 TTL 引擎。
- `Authorization` 在 requests-cache 默认忽略和脱敏参数中，应显式保留该默认列表。
- `X-Request-Timestamp` 每次不同，必须从缓存键与持久化内容中忽略，否则同一查询永远不会命中。
- 只缓存公共的 `zhihu_search` GET 响应。未来的 OAuth 用户数据不得共享该缓存。
- 数据过期且上游错误时，允许返回 7 天内的 stale 响应，页面必须显示“过期缓存”和原观测时间。
- 不使用 `pickle` 作为可被外部修改的交换格式。缓存目录只对应用运行用户可写。

### 8.3 本地硬预算

即使官方每日配额较高，公网 Demo 也不直接开放整个配额池。

| 限制 | 默认值 |
| --- | ---: |
| 每次运行查询数 | 4，最多 6 |
| 每条查询结果 | 10 |
| 每次运行真实知乎调用 | 最多 6 |
| Demo 每日真实知乎调用 | 默认 20，环境变量可调 |
| 同一会话发起新运行的冷却 | 60 秒 |
| 入选模型来源 | 最多 12 |

真实请求前，在 SQLite `BEGIN IMMEDIATE` 事务中更新当日计数。因为 Demo 只有一个后台 Worker，无需再建分布式限流器。

计数原则：

- 本次运行存在未缓存查询时，先读取一次官方 `zhihu_search` 剩余额度；官方剩余为 0 时不发送搜索请求。
- 官方额度接口暂时失败时，仍受更严格的本地每日上限保护；页面显示“官方额度暂不可用”，不把未知值显示为 0。
- HTTP 缓存命中不占用本地预算。
- 一旦真实请求发出，无论是否返回结果都保守地计为 1 次。
- 重试每次都计数，且重试前再次检查预算。
- 达到本地上限后，仅允许已缓存查询和已保存 GraphBundle。
- “强制刷新”只在管理员演示模式可见，不面向公共用户。

### 8.4 预热主题

部署前人工选定 3 个效果可验证的主题，在同一版本下完成一次搜索和抽取，保存到持久化卷。

公网首页默认展示这 3 个主题。即使当日本地预算用完或知乎上游暂时失败，评委仍然可以完成世界树交互。

预热数据必须保留真实知乎 URL 和观测时间，不手工编造“更漂亮”的内容。

---

## 9. 模型调用设计

### 9.1 配置而非抽象层

Demo 不定义通用 `ModelGateway`。直接通过 Instructor 创建一个客户端，用环境变量选择具体 OpenAI-compatible 端点：

```text
LLM_BASE_URL
LLM_API_KEY
LLM_MODEL
```

更换模型时只改配置和 `model_name`，不为每个 Provider 写 Adapter。如果选定的 Provider 不支持 Instructor 所需的结构化输出，应更换 Provider，不在 Demo 中增加一套 JSON 抢救器。

### 9.2 Prompt 契约

System 约束必须包含：

```text
你只能根据输入中的知乎来源文本提取信息。
不得用你的先验知识补充人物、时间、事件或因果关系。
每个节点和关系必须引用至少一个输入 source_id。
证据不足时少输出，不要猜测。
```

User 输入使用序列化数组，每条来源只包含：

- `source_id`
- `title`
- `author_name`
- `edit_time`
- `content_text`
- `truncated_for_model`

不把赞同数、权威等级放入抽取 Prompt，避免模型把热度错当成真实性。这些字段仅在 Source 详情中展示。

### 9.3 抽取缓存键

```text
sha256(
  sorted(source_id + payload_sha256)
  + topic
  + prompt_version
  + graph_schema_version
  + model_name
)
```

模型温度固定为 0 或 Provider 支持的最低值。不将模型返回当作完全可重现；真正的可重现输出是已保存的 GraphBundle。

---

## 10. 页面设计

Demo 只有一个页面，不引入路由、菜单系统或登录页。

```text
┌─ Epistree ──────────────────────────────────────────────────────┐
│ 主题 [__________________]  [生成查询] [生成世界树]  │
│ 预热主题：[主题 A] [主题 B] [主题 C]                    │
├─ 查询与配额 ───────────────────────────────────────────┤
│ ☑ topic  ☑ topic 起源  ☑ topic 争议  ☑ topic 变化          │
│ 预计真实调用 1/4 · 已缓存 3/4 · 今日 Demo 余额 16/20 │
├─ 进度 ─────────────────────────────────────────────────┤
│ [搜索 4/4] [去重 27] [入选 12] [抽取完成]                 │
├─ 世界树 ────────────────────────────────┬─ 节点详情 ───────┤
│                                              │ 类型 / 文本        │
│           Dash Cytoscape                    │ AI 候选标识       │
│                                              │ 来源摘要          │
│                                              │ [打开知乎原文]    │
├─ 来源列表 / 运行信息 / 导出 JSON ─────────────────────────┤
└───────────────────────────────────────────────────────┘
```

### 10.1 交互规则

- 图默认使用 Cytoscape `breadthfirst` 布局，Topic 为根。
- 若关系边交叉过多，用户可切换 `cose` 布局；不开发自定义布局算法。
- 点击节点通过 Dash Cytoscape `tapNodeData` 更新右侧详情。
- 点击关系边显示关系类型、置信度和支持来源。
- 时间筛选仅基于知乎 `EditTime` 和明确抽取的 `occurred_at`，缺失时归入“时间不详”。
- 来源链接以新标签打开，界面不代理或重新发布知乎原文。
- 过期缓存、截断模型输入和抽取失败都用文字明确显示，不只使用颜色。

### 10.2 空状态与降级

| 情况 | 页面行为 |
| --- | --- |
| 无 Access Secret | 可查看预热主题；自定义搜索按钮禁用 |
| 本地预算用完 | 仅允许命中缓存的查询 |
| 知乎超时/5xx | 若有 7 天内 stale 响应则展示并标记；否则保留其他查询结果 |
| 一条查询无结果 | 显示 EmptyReason，其他查询继续 |
| 实际唯一来源 < 3 | 只显示来源列表，不调用模型 |
| 模型失败 | 保留来源列表和运行日志，允许稍后重试抽取 |
| GraphBundle 无 Claim | 显示“当前来源不足以组成世界树” |

---

## 11. 错误、重试与取消

### 11.1 错误码

Demo 只定义一组稳定内部错误码：

| 错误码 | 含义 | 是否重试 |
| --- | --- | --- |
| `INVALID_TOPIC` | 主题或查询非法 | 否 |
| `AUTH_REQUIRED` | 缺少 Access Secret | 否 |
| `UPSTREAM_AUTH_FAILED` | 知乎认证失败 | 否 |
| `LOCAL_BUDGET_EXHAUSTED` | Demo 当日真实调用上限已到 | 否 |
| `UPSTREAM_RATE_LIMITED` | 知乎频率或配额限制 | 按明确的 retry-after，当次运行不循环 |
| `UPSTREAM_TEMPORARY_ERROR` | 超时或 5xx | 最多 2 次 |
| `UPSTREAM_SCHEMA_CHANGED` | 响应不符合 Pydantic 契约 | 否，需要人工检查 |
| `INSUFFICIENT_SOURCES` | 唯一来源少于 3 | 否 |
| `MODEL_VALIDATION_FAILED` | 结构化输出校验失败 | Instructor 最多 2 次 |
| `RUN_CANCELLED` | 用户取消 | 否 |

### 11.2 取消语义

Dash 后台回调使用官方 `cancel` 机制。取消后：

- 已发出的上游请求无法撤回，仍记入预算。
- 已成功持久化的 SourceSnapshot 保留。
- 未通过验证的模型输出不入库。
- run 标记 `cancelled`，不删除运行记录。

---

## 12. 配置与安全

### 12.1 环境变量

```text
ZHIHU_ACCESS_SECRET          # 仅注入服务进程
LLM_BASE_URL
LLM_API_KEY
LLM_MODEL
DATA_DIR=/data
DEMO_DAILY_CALL_LIMIT=20
DEMO_MAX_QUERIES=6
DEMO_MAX_SOURCES=12
DEMO_ADMIN_TOKEN             # 只控制预热/强制刷新
```

`.env.example` 只包含变量名和占位值。真实凭据不写入代码、SQLite、HTTP 缓存、前端响应和日志。

### 12.2 项目内工具隔离

本地开发和验证时继续遵守项目现有约定：

```text
ZHIHU_CLI_HOME=/Users/lvpeiye/Study/Project/20260901-知乎黑客松/.zhihu-cli
/Users/lvpeiye/Study/Project/20260901-知乎黑客松/.zhihu-cli/current/zhihu-cli
```

CLI 仅用于人工调试和对照 HTTP 响应。Demo 服务自身按官方 HTTP 文档调用接口，不从 Web 进程 shell out 到 CLI。

### 12.3 日志脱敏

日志允许记录：

- run ID、query hash、ContentID、HTTP 状态、耗时、缓存状态。
- 模型名、Prompt 版本、输入条数、验证错误类型。

日志禁止记录：

- Authorization、Access Secret、LLM API Key。
- 完整模型请求头。
- 未脱敏的异常 request 对象。

---

## 13. 依赖和运行方式

### 13.1 直接依赖

`pyproject.toml` 只应包含以下直接运行依赖：

```text
dash[diskcache] >=4.4,<5
dash-cytoscape >=1.0,<2
requests-cache >=1.3,<2
pydantic >=2.13,<3
pydantic-settings >=2,<3
instructor[openai] >=1.16,<2
tenacity >=9.1,<10
gunicorn >=26.2,<27
```

开发依赖：

```text
pytest
responses
ruff
```

不直接列出 Dash、Instructor 等项目的转传依赖。使用 `uv.lock` 锁定实际解析版本。

### 13.2 Python 与命令

本地使用 Python 3.14：

```text
uv sync --python 3.14
uv run --python 3.14 python -m epistree_demo.app
uv run --python 3.14 pytest
uv run --python 3.14 ruff check .
```

公网容器启动：

```text
gunicorn epistree_demo.app:server --workers 1 --threads 4 --timeout 120
```

单 worker 是 Demo 约束，用于避免 DiskCache、SQLite 本地预算和多副本一致性问题。

---

## 14. 测试设计

### 14.1 测试 fixture

`tests/fixtures/zhihu_search.json` 必须来自一次真实官方响应，但需要：

- 删除 Access Secret 和所有请求头。
- 保留响应字段结构。
- 将内容文本缩短为测试所需的最小片段，保留原链接或替换为明确的 example fixture URL。
- 在 fixture 头部记录获取日期和 Schema 用途。

公开仓库中是否保留真实内容片段，应在实现时再根据当时的平台规则确认。

### 14.2 必须自动测试

| 模块 | 测试 |
| --- | --- |
| QueryBuilder | NFKC、空格、长度、去重、最大数量 |
| ZhihuSearchClient | 200、空结果、401、429、500、超时、额度为 0、Schema 变化 |
| requests-cache | 第二次相同查询不发 HTTP；时间戳不影响命中；缓存中无 Authorization |
| SourceSelector | 跨查询 ContentID 去重、轮询公平、12 条上限 |
| GraphBundle | 悬空 source/question/relation 拒绝、数量上限、quote 检查 |
| 抽取缓存 | 同输入命中；Prompt/Model/Source 改变时未命中 |
| 本地预算 | 缓存命中不计数；真实重试计数；上限后拒绝 |
| Presenter | 节点 ID 唯一、边两端存在、Source URL 可达 |
| Demo flow | fixture 离线运行不访问网络也能产生 Cytoscape elements |

### 14.3 手工演示检查

1. 新环境下从零创建数据库。
2. 首次运行预热主题，核对真实调用数。
3. 立即重复运行，确认知乎真实调用为 0。
4. 暂时移除 Access Secret，确认预热主题仍可完整浏览。
5. 点击每类节点和边，核对详情与来源。
6. 打开所有 Source 链接，确认指向知乎。
7. 在任务中途取消，确认按钮恢复、run 状态正确。
8. 在移动端宽度下确认来源详情可读。

---

## 15. 实施顺序

实现严格分为六个可独立验收的步骤。每个步骤通过后再进入下一个。

### Step 1：离线骨架

**实现**

- `pyproject.toml`、配置、SQLite 建表、Pydantic 契约。
- Dash 单页布局和静态示例图。
- fixture 读取器。

**验收**

- 不需要任何凭据即可启动。
- 静态 GraphBundle 能在 Dash Cytoscape 中显示并点击。

### Step 2：知乎 Client 与 HTTP 缓存

**实现**

- 根据官方 HTTP 文档实现 `ZhihuSearchClient`。
- requests-cache SQLite 后端和 Tenacity 有限重试。
- responses 契约测试。

**验收**

- 所有自动测试先通过。
- 获得明确凭据后，仅使用 1 条查询做真实 contract verification。
- 重复请求命中缓存，缓存文件无凭据。

### Step 3：去重、快照和本地预算

**实现**

- 四条查询的串行执行。
- Source/SourceSnapshot/Observation 事务。
- 轮询入选和 12 条上限。
- SQLite 当日硬预算。

**验收**

- 运行统计能准确区分缓存命中和真实调用。
- 同一 ContentID 只展示一次，但查询排名观测完整保留。

### Step 4：一次结构化抽取

**实现**

- Instructor 客户端、GraphBundle Schema 和 Prompt v1。
- 跨对象引用验证。
- GraphBundle 输入哈希缓存。

**验收**

- 三个候选演示主题都能生成有 SourceRef 的 Claim。
- 人工抽查不存在明显脱离输入的事实。
- 相同输入第二次不调用模型。

### Step 5：交互图与详情

**实现**

- Dash Cytoscape 节点和边样式。
- 节点/边点击详情、来源链接、时间过滤和 JSON 导出。
- DiskCache 后台回调、进度、取消和按钮锁定。

**验收**

- 一条 Claim 在两次点击内可达知乎原文。
- 任务运行时无法重复点击发起第二个任务。

### Step 6：预热与部署

**实现**

- Dockerfile、Gunicorn、持久化卷和健康检查。
- 三个预热主题。
- 公共用户与管理员刷新能力隔离。

**验收**

- 重启容器后缓存、来源和 GraphBundle 仍存在。
- 无凭据、配额用完或知乎短时失败时，预热主题仍可演示。
- 从公网地址完整执行提交前检查。

---

## 16. 完成定义

Demo 只有同时满足以下条件才算完成：

### 功能

- [ ] 用户可输入主题并编辑默认查询。
- [ ] 系统能在硬预算内搜索、去重并选取知乎来源。
- [ ] 至少 3 个预热主题可直接展示。
- [ ] GraphBundle 通过 Pydantic 及跨引用验证。
- [ ] 世界树可点击、过滤并导出 JSON。

### 可回溯性

- [ ] 100% Question、Claim、Event 和候选关系至少有一个有效 SourceRef。
- [ ] 100% Source 保留 ContentID、原链接、观测时间和原始 Item JSON。
- [ ] 页面不将 `ContentText` 标注为全文。
- [ ] 模型生成对象均显示 `model_candidate`。

### 配额与可用性

- [ ] 新主题默认最多发起 4 次真实知乎搜索。
- [ ] 相同查询 24 小时内重复执行的真实调用数为 0。
- [ ] 相同抽取输入不重复调用模型。
- [ ] 页面显示真实调用数、缓存命中数、过期状态和数据时间。
- [ ] 达到 Demo 本地每日上限后不再发出新知乎请求。

### 安全与交付

- [ ] Git 历史、前端、日志、HTTP 缓存和 SQLite 中无凭据。
- [ ] 容器以非 root 用户运行，`/data` 可持久化。
- [ ] 公网地址可完成核心流程。
- [ ] README 含最小启动方式，CHANGELOG 记录本版变更。

---

## 17. 从 Demo 过渡到完整工程

Demo 验证成功后，只在出现真实需求时替换组件：

| 真实触发条件 | 才执行的升级 |
| --- | --- |
| 需要多实例或多用户写入 | SQLite → PostgreSQL，DiskCache → Celery/Valkey |
| 已证明 3–5 跳图查询是瓶颈 | 在 PostgreSQL 之外增加可重建图投影 |
| 来源超过单次模型上下文 | 拆分为 TextUnit 抽取、聚类和关系复核 |
| 有跨日自动研究任务 | 引入 Prefect 或其他工作流引擎 |
| 需要更换多种模型 Provider | 将 Instructor client 收口为完整工程的 ModelGateway |
| 需要独立前端产品 | Dash 投影契约稳定后再转 FastAPI + React |

升级时保留 `SearchItem`、`GraphBundle`、Source ID 和 SourceRef 语义，而不保证 Demo 的文件结构或 SQLite SQL 成为长期 API。

---

## 18. 实现前必须确认的两个问题

### 18.1 演示主题

需要人工选定 3 个预热主题。选择标准：

- 知乎上有多个时期的讨论。
- 存在可识别的观点分歧或认知变化。
- 用 4 条查询能获得至少 8 条唯一有效来源。
- 不依赖实时新闻和敏感个人数据。

这个选择会直接影响 Demo 效果，应在 Step 4 前由项目负责人确认。

### 18.2 模型 Provider

需要确认一个实际可用的模型端点，并用 12 条知乎来源验证：

- 上下文足以接收约 18,000 个中文字符及 Schema。
- 能被 Instructor 驱动并返回通过验证的 GraphBundle。
- 单次平均响应时间适合公网 Demo。
- 调用成本有明确上限。

如果不满足，先更换模型或将来源上限从 12 降至 8；不立即把单次抽取改造成复杂 Agent 管线。

---

## 19. 必须停止并上报的情况

1. 为了使世界树“看起来完整”，需要向模型开放知乎之外的数据。
2. 知乎官方搜索的真实样本中，`ContentText` 过短，三个候选主题都无法生成可追溯 Claim。
3. 需要未文档化接口、爬虫、凭据轮换或任何规避配额的方式。
4. 上线环境无法提供持久化卷，导致每次重启丢失缓存和预热主题。
5. 选定模型在最多 2 次验证重试后仍不能稳定产生 GraphBundle。
6. 公网用户可以绕过本地每日硬预算或取得后端凭据。
7. 项目需要在 Demo 期间改为多用户、多实例或长时间自动任务。

上报内容包含：已验证事实、失败样本、影响的完成定义、最小备选方案和增加的交付风险。在项目负责人选择前，不对受影响模块继续扩展。

---

## 20. 参考项目与文档

### Demo 直接依赖

- [Plotly Dash repository](https://github.com/plotly/dash)
- [Dash documentation](https://dash.plotly.com/)
- [Dash background callbacks](https://dash.plotly.com/background-callbacks)
- [Dash Cytoscape documentation](https://dash.plotly.com/cytoscape)
- [Dash Cytoscape callbacks](https://dash.plotly.com/cytoscape/callbacks)
- [Dash Cytoscape user interactions](https://dash.plotly.com/cytoscape/events)
- [requests-cache repository](https://github.com/requests-cache/requests-cache)
- [requests-cache SQLite backend](https://requests-cache.readthedocs.io/en/stable/user_guide/backends/sqlite.html)
- [requests-cache expiration](https://requests-cache.readthedocs.io/en/stable/user_guide/expiration.html)
- [requests-cache security](https://requests-cache.readthedocs.io/en/stable/user_guide/security.html)
- [Pydantic models](https://docs.pydantic.dev/latest/concepts/models/)
- [Instructor repository](https://github.com/567-labs/instructor)
- [Instructor OpenAI integration](https://python.useinstructor.com/integrations/openai/)
- [Instructor retry guidance](https://python.useinstructor.com/concepts/retrying/)
- [Tenacity repository](https://github.com/jd/tenacity)
- [Python sqlite3 documentation](https://docs.python.org/3/library/sqlite3.html)
- [pytest repository](https://github.com/pytest-dev/pytest)
- [responses repository](https://github.com/getsentry/responses)

### 只借鉴设计思路

- [Microsoft GraphRAG architecture](https://microsoft.github.io/graphrag/index/architecture/)
- [Microsoft GraphRAG dataflow](https://microsoft.github.io/graphrag/index/default_dataflow/)
- [Graphiti overview](https://help.getzep.com/graphiti/getting-started/overview)

GraphRAG 和 Graphiti 不进入 Demo 运行依赖。它们在本设计中只用来确认“来源回链、增量快照和候选关系不应丢失”这些边界。
