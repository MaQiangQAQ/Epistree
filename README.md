# Epistree

> 输入一个主题，看到这个领域的知识是怎样一步一步长出来的。

Epistree 是一个以知乎开放数据为核心的时序知识发现与演化分析系统。它从知乎内容中发现与研究主题相关的事件、问题、观点和证据，建模知识的产生、分化、争议、修正、淘汰与汇聚过程，并将其呈现为可交互的“知识世界树”。

## 项目状态

**v0.3.0 · 茂盛世界树与 Signal Garden 交互**

当前仓库包含可启动的 Dash Demo：预热主题可在无凭据、断网条件下浏览；自定义搜索使用知乎开放接口、SQLite 日预算和 requests-cache，并把模型候选严格回链到本次来源。关系是 `model_candidate`，不代表自动事实判定。

### 当前 Demo 能做什么

- 点击 `RAG`、`大模型微调`、`视觉大模型`、`AI Agent`、`大模型推理加速与量化`、`大模型强化学习与长思维链` 六个预热主题，零真实调用秒级加载已保存的知乎来源和世界树。
- 用“纵向时间、横向分叉”的确定性布局查看 Topic、Question、Claim、Event 和 Source；植物隐喻内联呈现花（问题）、果（观点）、叶（来源）。
- 点击节点聚焦上下游关系并保持植物形态，在右栏核对摘要、作者、时间和知乎原文；点击空白处或按 `Esc` 退出聚焦。
- 按年份筛选、拖动时间滑块或平滑播放生长过程（支持断点续播），并将当前完整图谱导出为 JSON。
- 输入自定义主题后先编辑查询，再在官方剩余额度和本地日预算共同约束下执行知乎搜索与一次结构化抽取。

预热图谱是可复现的演示快照，不等同于实时知乎结果；所有自动生成关系都以候选关系展示。

## 本地启动

```bash
uv sync --frozen
uv run epistree-demo
```

浏览器打开 `http://localhost:8050`。预热资产从 `DATA_DIR`（默认 `.data`）读取，点击主题不会调用知乎或模型；该目录属于部署数据，Git 不跟踪，换机或部署时需要单独挂载 `warmup_*.json`。缺少预热资产时首页仍可启动，对应按钮不会伪造结果。自定义搜索前请通过环境变量配置 `ZHIHU_ACCESS_SECRET` 与 `LLM_API_KEY`；程序不会自动读取仓库 `.env`。本地可先填写 `.env`，再执行 `set -a; source .env; set +a` 将变量仅注入当前终端会话。

Docker 启动：

```bash
docker build -t epistree-demo .
docker run --rm -p 8050:8050 -v "$PWD/.data:/data" epistree-demo
```

## 核心问题

传统搜索告诉用户“有哪些资料”，普通问答给出“现在的答案”。Epistree 尝试回答更上游的问题：

- 一个知识主张最早在何时出现？
- 什么事件触发了新问题和新观点？
- 不同观点如何分叉、争论和彼此修正？
- 哪些主张被证据支持，哪些被反例推翻？
- 一个领域为什么会形成今天的认知？

## 核心模型

Epistree 的基础知识对象包括：

| 对象 | 含义 |
| --- | --- |
| Topic | 用户研究的主题 |
| Event | 驱动认知变化的事实性事件 |
| Question | 某一阶段人们尝试理解的问题 |
| Claim | 围绕问题提出的可验证知识主张 |
| Evidence | 支持或反驳主张的证据 |
| Source | 可追溯的原始内容与位置 |

系统不只记录静态关系，还要识别 `triggers`、`answered_by`、`supports`、`contradicts`、`evolves_into`、`refines` 和 `supersedes` 等演化关系。

## 处理流程

```text
研究主题
  ↓
主题扩展与研究规划
  ↓
知乎问题、回答与内容证据发现
  ↓
去重、清洗与时间对齐
  ↓
Event / Question / Claim / Evidence 抽取
  ↓
问题链与观点演化建模
  ↓
可追溯的知识世界树
```

时间是系统的主轴。实现时需区分内容发布时间、事件发生时间和知识有效时间，避免将“何时谈论”与“何时发生”混为一谈。

## MVP 范围

首个可运行版本聚焦于一条最小闭环：

1. 用户输入一个研究主题。
2. 扩展检索词并发现知乎问题与高质量回答。
3. 抽取 Event、Question、Claim 和 Source。
4. 执行时间对齐与 Claim 聚类。
5. 判断触发、回答、支持、反驳和演化关系。
6. 生成可交互、可回溯来源的世界树。

MVP 默认不接入外部新闻、论文或其他社区，也不承诺完整的学术知识图谱或自动事实判定。模型产生的关系必须保留置信度和原始来源。

## 仓库结构

```text
.
├── README.md                  # 项目入口
├── CHANGELOG.md               # 逐版本变更记录
├── VERSION                    # 当前版本号
├── ROADMAP.md                 # 分阶段实施路线
├── CONTRIBUTING.md            # 开发与版本约定
├── docs/ENGINEERING_DESIGN.md # 可分阶段实施的工程设计
├── docs/DEMO_DESIGN.md        # 单实例可行 Demo 完整设计
├── docs/DEMO_REMEDIATION_PLAN.md # 当前 Demo 修改实施方案
├── docs/EPISTREE_FRONTEND_DESIGN.md # 已落地的前端视觉与交互设计
├── src/epistree_demo/          # Dash 应用、数据契约与服务实现
├── tests/                      # 离线单元与回归测试
├── 知识世界树_系统构想.md   # 完整产品与系统设计
└── .agents/skills/zhihu/      # 项目内知乎工具说明
```

随着实现展开，源代码、测试、样例与技术文档将按职责分离。

## 版本与变更记录

项目使用 [Semantic Versioning](https://semver.org/) 形式的 `MAJOR.MINOR.PATCH` 版本号。每次发布必须：

1. 更新 `VERSION`。
2. 将 `CHANGELOG.md` 中的未发布内容归入新版本。
3. 记录发布日期、用户可感知变化和不兼容项。
4. 创建与版本号一致的 Git 标签。

开发期间的所有变更先写入 `Unreleased`，不允许在发布时补写一份与实际开发脱节的记录。详见 [CHANGELOG.md](CHANGELOG.md) 和 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 设计文档

产品长期构想见 [《知识世界树：系统构想》](知识世界树_系统构想.md)。完整工程的模块边界、统一契约、知乎配额与缓存策略、技术选型对比和分阶段验收见 [《Epistree 初步工程设计》](docs/ENGINEERING_DESIGN.md)。单实例、单数据库 Demo 的目标设计见 [《Epistree 可行 Demo 完整设计》](docs/DEMO_DESIGN.md)；已执行的修复与验收边界见 [《Epistree Demo 修改实施方案》](docs/DEMO_REMEDIATION_PLAN.md)；当前界面的视觉语义、布局和交互依据见 [《Epistree 前端设计方案》](docs/EPISTREE_FRONTEND_DESIGN.md)。
