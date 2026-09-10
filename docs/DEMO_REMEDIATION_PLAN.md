# Epistree Demo 修改实施方案

> 状态：Implemented (v0.2.0)<br>
> 日期：2026-09-10<br>
> 目标版本：v0.2.0<br>
> 适用范围：`src/epistree_demo` 当前实现

> 注：本轮已完成 R0–R5 的代码基线与离线验收；真实知乎接口验证仍需在用户明确授权后执行。

### 实施结果摘要

| 范围 | 当前结果 |
| --- | --- |
| R0 安装与启动 | 已完成本地锁文件校验、包构建、隔离导入与 Dash 页面验证 |
| R1 缓存与配额 | 已完成缓存优先、过期宽限、官方额度刷新和 SQLite 原子预算预留 |
| R2 来源闭环 | 已拒绝未知来源、重复对象和无依据关系，所有候选关系保留来源与置信度 |
| R3 运行与持久化 | 已完成显式 Run/Bundle 关联、派生缓存和进程安全数据库连接 |
| R4 预热与交互 | 已完成三个预热主题、后台进度/取消、时间筛选、回放、聚焦和导出 |
| R5 离线验收 | 已通过 60 项离线测试、Ruff 和 Git diff 检查 |
| 待外部环境验证 | 真实知乎接口契约、Docker 镜像构建与公网部署 |

## 1. 修改目标

本轮修改不扩展产品边界，只把当前原型修成一个可信、可控、可重复演示的最小闭环：

1. 知乎搜索调用不能突破本地日预算或官方剩余额度。
2. 所有 Question、Claim、Event 和候选关系都必须回到本次输入中的真实知乎来源。
3. 三个预热主题在无 Access Secret、无模型密钥或额度耗尽时仍可完整浏览。
4. 用户编辑后的查询才是实际执行的查询。
5. 干净环境和容器能够按文档直接启动。
6. 运行状态、缓存命中、真实请求、过期数据和失败原因可被准确观察。

本轮不增加外部数据源，不引入 Agent 工作流、向量数据库、Neo4j、Redis、Celery、用户系统或 OAuth。继续使用已经选定的 Dash、Dash Cytoscape、requests-cache、SQLite、Instructor 和 Pydantic。

## 2. 实施顺序与合并规则

修改分为六个阶段。每个阶段单独提交、单独更新 `CHANGELOG.md` 的 `Unreleased`，通过本阶段验收后才能进入下一阶段。

| 阶段 | 目标 | 阻断级别 |
| --- | --- | --- |
| R0 | 恢复可安装、可测试、可启动的基线 | 阻断全部后续工作 |
| R1 | 修复缓存判定和配额硬上限 | 阻断任何真实 API 验证 |
| R2 | 建立来源闭环和严格图谱校验 | 阻断真实模型结果展示 |
| R3 | 修复运行生命周期、事务和派生缓存 | 阻断预热资产生成 |
| R4 | 接通预热、后台执行和核心交互 | 阻断公网演示 |
| R5 | 完成容错、测试、文档和 v0.2.0 发布 | 最终交付门槛 |

真实知乎接口验证只能在 R1 自动测试全部通过后进行，并固定使用一条查询。后续测试优先复用 HTTP 缓存和已保存快照。

## 3. R0：建立干净运行基线

### 3.1 包与入口

修改 `pyproject.toml`：

- 为 `src` 布局声明标准构建后端和包发现规则。
- 增加 `epistree-demo` 命令入口，入口只负责读取配置、创建 Dash 应用并启动服务。
- 将 `app.py` 的启动部分提取为 `main()`，导入模块时不启动服务器。
- 保留 Python 3.14，不在本轮扩大版本矩阵。

修改 Docker 构建顺序：

1. 先复制 `pyproject.toml` 和 `uv.lock`。
2. 使用 `uv sync --frozen --no-dev --no-install-project` 安装锁定依赖。
3. 再复制 `src`，安装当前项目。
4. 容器入口执行锁定环境中的 `epistree-demo`。

### 3.2 配置初始化

- 应用启动时创建 `DATA_DIR`，目录不可写时返回明确启动错误。
- 创建页面和查看预热资产不要求任何凭据。
- `KnowledgeExtractor` 改为首次真正抽取时才创建，不能阻断查询构造、静态页面或预热浏览。

### 3.3 验收

- 在不读取项目 `.env` 的临时目录中，`uv run --isolated` 可以导入包。
- 无任何凭据时，首页、Dash layout 和依赖端点均返回 200。
- Docker 镜像可构建并通过健康检查。
- 测试不能依赖开发者机器上的 `.env`、HTTP 缓存或 SQLite 数据。

## 4. R1：重做缓存与配额控制流

### 4.1 统一返回契约

在知乎适配层增加一个内部结果对象 `SearchOutcome`，统一包含：

| 字段 | 含义 |
| --- | --- |
| `response` | 通过 Pydantic 校验的知乎搜索响应 |
| `cache_state` | `fresh`、`stale` 或 `miss` |
| `observed_at` | 数据实际获取时间 |
| `network_attempts` | 本次操作真实发出的 HTTP 请求次数 |
| `warning` | 过期回退、部分条目异常等可展示说明 |

业务层不再通过零散布尔值猜测缓存状态。

### 4.2 请求顺序

每条查询固定按以下顺序执行：

```text
规范化查询
  → requests-cache only_if_cached 查询
  → 命中 fresh：直接返回，不读取官方额度，不增加本地计数
  → 命中 stale：先保留为可用降级候选
  → 未命中：读取本次 Run 已缓存的官方额度快照
  → 官方剩余为 0：返回 QUOTA_EXHAUSTED 或 stale 候选
  → SQLite BEGIN IMMEDIATE 预占一次本地调用
  → 发出真实请求
  → 成功后保存响应和业务快照
  → 短时失败且存在 stale：返回 stale 并明确标记
```

`requests-cache 1.3.x` 已提供 `only_if_cached`、`from_cache` 和过期响应能力，继续使用其公开接口，不另写 HTTP 缓存实现。

### 4.3 本地预算事务

用一个数据库方法替换“先读取、请求后再加一”的现有逻辑：

```text
reserve_daily_call(date, limit) -> bool
```

该方法在同一 `BEGIN IMMEDIATE` 事务中完成：

1. 读取当天已用次数。
2. 若达到上限则回滚并返回 `false`。
3. 未达到上限则加一并提交。

每一次真实 HTTP 尝试都必须先预占，包括 Tenacity 发起的重试。缓存读取和官方额度查询不占本地知乎搜索预算。已经预占但请求失败的次数不退回，以保证统计只会偏保守。

### 4.4 官方额度

- 每个 Run 最多读取一次官方 `zhihu_search` 额度，结果只保存在当前 Run 上下文中。
- 全部查询都命中缓存时不读取额度。
- 官方额度接口失败时，不将剩余额度推断为零；只允许本地缓存或 stale 降级，暂停新的真实搜索。
- 页面同时显示“本地 Demo 余额”和“官方搜索余额”，不混成一个数字。

### 4.5 验收

- 本地余额为零时，网络请求次数严格为零。
- 官方余额为零时，网络请求次数严格为零。
- 相同查询二次运行只命中缓存，本地计数不变。
- 两个并发 Run 争抢最后一个名额时，最多一个成功预占。
- 超时后的每次真实重试都有独立预算记录。
- 缓存持久化内容不包含 Access Secret 或时间戳请求头。

## 5. R2：建立不可绕过的来源闭环

### 5.1 两层校验

Pydantic 模型继续负责结构校验；新增领域校验函数负责本次运行上下文：

```text
validate_bundle_against_sources(bundle, source_map) -> GraphBundle
```

校验规则：

- 所有节点和关系的 `source_refs` 非空。
- 每个 `source_id` 必须存在于本次模型输入 `source_map`。
- quote 非空时必须能在对应来源的实际输入文本中找到；找不到时删除 quote，但不能删除或替换真实来源 ID。
- Claim 的 `question_id` 必须指向已存在 Question。
- 关系两端必须是已存在 Claim。
- 节点 ID 和关系 ID 分别唯一。
- 校验顺序与模型输出节点顺序无关。

未知 Question 不再自动补造，虚假 Source 不再静默跳过，缺失 URL 不再替换成 `example.com`。结构错误统一返回 `MODEL_VALIDATION_FAILED`，上游字段错误统一返回 `UPSTREAM_SCHEMA_CHANGED`。

### 5.2 展示闭环

- Source 节点连接到实际引用它的 Question、Claim、Event 或候选关系，不再全部连接到 Topic。
- Claim 详情直接展示来源标题、作者、摘要和“打开知乎原文”。
- 边详情展示关系类型、置信度和支持该关系的来源。
- 所有 AI 推断关系保留 `model_candidate` 标识，不将置信度包装成事实概率。

### 5.3 验收

- 伪造 `source_id` 必须导致 Bundle 被拒绝。
- Claim 写在 Question 前面仍可正确校验。
- 重复节点或关系 ID 必须被拒绝。
- 每个可见知识节点至少有一个可打开的真实知乎链接。
- 从任意 Claim 最多两次点击可到达知乎原文。

## 6. R3：修复运行生命周期、事务和派生缓存

### 6.1 Run 状态机

状态只允许按以下路径变化：

```text
queued → running → completed
                 ↘ failed
                 ↘ cancelled
```

- `run_id` 在进入异常处理前初始化；只有真实存在的 Run 才能写失败状态。
- 转入 `running` 时写入 `started_at`。
- 终态写入 `finished_at`。
- 失败时保留已经获得的来源和查询观测。
- `complete_run` 使用 `save_bundle` 返回的真实 `bundle_id`，不生成第二个随机 ID。

### 6.2 持久化边界

- 一条成功搜索响应对应的 QueryObservation、Source、SourceSnapshot 和关联排名在一个业务事务中写入。
- 日预算预占使用独立短事务，不能与外部 HTTP 请求放在同一个长事务里。
- 每条来源快照保存该条内容对应的原始条目，不在每个 SourceSnapshot 中重复保存整份搜索响应。

### 6.3 抽取缓存键

缓存键从“手工拼接部分字段”改为对实际模型输入的规范化 JSON 求 SHA-256，并额外包含：

- `prompt_version`
- `graph_schema_version`
- `model_name`
- 输入截断策略版本

标题、作者、修改时间或送入模型的正文变化时必须未命中；未进入模型的指标变化不应强制重新抽取。

### 6.4 验收

- 每个 completed Run 都指向真实存在的 GraphBundle。
- 每个 failed Run 都有正确的 `run_id`、错误码和完成时间。
- 任意写入步骤故障时，不产生半条搜索观测。
- 模型输入变化时抽取缓存未命中，完全相同输入时命中。

## 7. R4：恢复完整 Demo 交互

### 7.1 预热资产

定义版本化 `WarmupAsset`：

| 字段 | 内容 |
| --- | --- |
| `asset_version` | 预热文件结构版本 |
| `topic` | 主题 |
| `queries` | 实际执行过的查询 |
| `bundle` | 已校验 GraphBundle |
| `sources` | 完整来源列表 |
| `generated_at` | 资产生成时间 |
| `data_observed_at` | 来源观测时间范围 |
| `prompt/model/schema` | 派生结果版本信息 |

应用启动时加载完整资产。点击预热主题直接渲染资产，不调用知乎和模型。自定义搜索缺少凭据时禁用并说明原因，但不能影响预热浏览。

预热文件只能由正式管线从真实知乎响应生成，不能手工美化或伪造。三个主题在 R0–R3 全部通过后再由用户确定并生成。

### 7.2 查询编辑

- Pattern-matching ID 使用稳定数字索引，不把可编辑查询文本本身当作组件 ID。
- 生成回调读取所有 query input 和 checklist 的当前值。
- 执行前再次进行去空、去重、长度校验和最多 6 条限制。
- 页面展示“缓存命中数、预计最多真实调用数、本地余额”，确认后才执行。

### 7.3 后台执行

使用 Dash 官方 `DiskcacheManager`：

- 搜索、抽取和绘图管线放入 `background=True` 回调。
- 使用官方 progress 输出显示“搜索、去重、抽取、绘图”。
- 使用官方 cancel 输入终止任务。
- 运行中禁用查询和生成按钮，并以 `run_id` 防止重复提交。
- 取消只改变当前 Run，不删除已写入的来源或缓存。

### 7.4 图谱与导出

- 使用 `tapNodeData` 和 `tapEdgeData` 分别处理节点、边详情。
- 时间筛选仅使用知乎 `EditTime` 和明确抽取的 `occurred_at`，缺失值归入“时间不详”。
- 导出改用 Dash `dcc.Download` 与 `dcc.send_string`，按钮本身不承载链接属性。
- JSON 导出包含 Bundle 版本、来源和运行元数据，便于复现，不包含凭据和完整 HTTP 请求头。

### 7.5 验收

- 编辑、删除或取消的查询不会被执行。
- 点击预热主题后，在断网和无凭据条件下仍能完整浏览。
- 长任务不阻塞页面，能显示进度并取消。
- 运行期间不能重复提交。
- 节点、边、时间筛选和 JSON 下载均实际可用。

## 8. R5：容错、测试与发布

### 8.1 上游容错

- 401/403 立即失败，不重试。
- 429 遵守明确的 `Retry-After`，没有明确等待时间时本次 Run 停止，不循环消耗额度。
- 5xx、Timeout 和 ConnectionError 最多重试一次；每次请求前重新执行本地预算预占。
- 单个条目字段异常时记录结构化 warning；全部条目无法解析时返回 `UPSTREAM_SCHEMA_CHANGED`，不能伪装成搜索无结果。
- stale 回退必须显示原观测时间和“过期缓存”文字。

### 8.2 测试矩阵

必须补齐以下测试：

1. 干净环境安装、导入和 Dash smoke test。
2. 无 `.env`、无凭据时的预热浏览。
3. 本地额度为零、官方额度为零和并发最后一个名额。
4. fresh、stale、miss 三种缓存状态。
5. 429、5xx、超时和重试计数。
6. 虚假来源、重复 ID、乱序节点和无来源关系。
7. 查询编辑、取消和最多 6 条限制。
8. Run 成功、失败、取消及 Bundle 外键一致性。
9. 预热资产版本不兼容时的明确错误。
10. 导出文件可解析且不包含凭据。

测试必须在导入应用前通过 fixture 或 monkeypatch 设置环境，禁止读取开发者 `.env`。所有 HTTP 测试使用 `responses`，默认阻止未注册网络请求。现有空的重试测试必须实现。

### 8.3 文档与版本

- README 更新为当前实现状态，加入本地启动、环境变量、预热浏览和 Docker 启动方式。
- CHANGELOG 在开发过程中持续写入 `Unreleased`。
- R0–R5 全部通过后，将功能版本发布为 `0.2.0`，同步更新 `VERSION` 和 `pyproject.toml`，再创建 `v0.2.0` 标签。
- 发布说明明确：关系是模型候选、数据仅来自知乎开放接口、Demo 有本地额度限制。

### 8.4 最终发布门槛

正式公网发布前，以下条件必须同时满足。当前本地 v0.2.0 候选已满足可在本机验证的项目，外部环境项继续保留为明确限制：

- `pytest` 在无本地 `.env` 的干净环境全部通过。
- Ruff 无 E、F、I 类错误。
- Docker 冷启动成功，重启后预热和缓存仍存在。
- 一次真实知乎 contract test 成功，随后相同查询真实调用数为零。
- Access Secret、模型密钥不出现在 Git、前端、日志、SQLite、HTTP 缓存和导出文件中。
- 三个预热主题均能离线完整演示。
- 页面显示真实调用、缓存状态、数据时间和 AI 候选标识。

## 9. 实施中必须暂停汇报的情况

遇到以下情况不继续自行扩大方案，应先向用户汇报：

1. 知乎实际额度字段、搜索字段或认证协议与当前已验证契约不一致。
2. 必须调用未文档化接口、爬虫或其他数据源才能完成核心体验。
3. 12 条来源无法在已选模型上稳定通过结构化输出，且降低到 8 条后仍失败。
4. 部署平台不能提供持久化卷，导致缓存和预热资产在重启后丢失。
5. 修复需要新增 Redis、Celery、图数据库或另一套前端框架。
6. 来源严格校验导致主要预热主题无法形成至少 3 条有效来源。

## 10. 建议提交序列

```text
fix(packaging): make clean installs and container entrypoint reproducible
fix(quota): enforce cache-first official and local search budgets
fix(provenance): reject graph objects without input-source support
fix(persistence): make run lifecycle and bundle linkage consistent
feat(warmup): render versioned precomputed demo assets offline
feat(ui): honor edited queries and add background progress
feat(graph): connect evidence and expose edge and time details
test(demo): cover clean environment quota provenance and callbacks
docs(release): document runnable demo and prepare v0.2.0 changelog
```

该顺序保证每个提交都可以单独审查和回滚，也能避免在配额与来源约束尚未可信时继续堆叠界面功能。
