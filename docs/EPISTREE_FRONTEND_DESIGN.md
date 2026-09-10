# Epistree「知识世界树」Demo 前端设计方案

> 版本：v0.2（2026-09-10）
> 状态：核心方案已在 v0.2.0 Demo 落地
> 适用对象：`src/epistree_demo`（Dash + dash-cytoscape 单页应用）

> 实现说明：已落地深色三栏界面、内联 SVG 节点语义、确定性时间树布局、年轮时间带、年份筛选、分步回放、节点聚焦与 Esc 退出；粒子背景和键盘增强失败时静默降级。缩放驱动的信息密度与更大规模图谱性能仍属于后续迭代。

---

## 0. 设计结论（TL;DR）

**gitgraph 的版式（纵向时间轴 + 横向分支泳道）× Gource 的回放生长动画 × OneZoom 的缩放信息密度 × Linear 的深色配色纪律**——四套已被大众验证的方案组合，全部可在 Dash + dash-cytoscape 上低成本落地，无需自研渲染、无需 fork 组件。

不做：3D、bloom 后期处理、力导向大图、自绘 canvas 树。

---

## 1. 设计目标与约束

### 1.1 目标

- 黑客松评委在 **10 秒内**看懂"这是一棵随时间长出来的知识树"；
- 30 秒内被生长动画和氛围感打动（炫酷）；
- 3 分钟内能通过点击/筛选理解"知识如何分叉、修正、汇聚"（有用）。

### 1.2 主题锚点

严格落地《知识世界树_系统构想.md》第八章"世界树视觉语义"：树干高度=时间、分叉=新观点/新问题、枯枝=被证伪、汇聚=共识、新芽=新观点、年轮=阶段增量。前端不是装饰，是**时序知识可视化语法**的渲染器。

### 1.3 技术约束（来自调研的硬结论）

| 约束 | 依据 |
|---|---|
| 不用力导向布局（cose/fcose） | Obsidian/Logseq 社区公认裸力导向大图"美而无用"（"more fun to look at than navigate"）；且力导向首屏漂移数秒，与确定性时间叙事冲突 |
| 不 fork dash-cytoscape、不注册自定义 cytoscape 插件 | Plotly 社区多人踩坑：assets 注入扩展 JS 会报 `cytoscape is not defined`，唯一出路是重新 npm build |
| 拿不到 cy 实例，`ele.animate()` API 不可用 | 动画改走"分批更新 elements + layout animate"官方路径 |
| 节点控制在 200–500 以内 | TheBrain 大图卡顿的前车之鉴；叙事性 demo 本来不需要更多 |
| hover 高频回调走服务器有延迟 | 邻居高亮用点击触发或 clientside callback |

---

## 2. 同类方案调研：学什么、不学什么

调研了 20+ 个相关产品/项目，核心证据如下。

### 2.1 知识图谱可视化类

| 参考 | 受欢迎证据 | 学什么 | 不学什么 |
|---|---|---|---|
| **Obsidian Graph View** | "最具辨识度的元素"、产品营销主视觉 | 深色底、节点大小=度数、颜色分组、time-lapse 生长动画 | 全局力导向大图（社区吐槽"美而无用"） |
| **Juggl**（Obsidian 插件，**基于 Cytoscape.js**） | GitHub 821 stars | **证明目标技术栈能产出社区认可的交互品质**；stylesheet 声明式样式 + 渐进展开 | — |
| **Neo4j Bloom** | 第三方评测 9.4/10，"非技术人员图探索"标杆 | 规则化样式系统（类型→颜色/图标/尺寸的声明式映射）；右键展开邻居 | 复杂查询语言 |
| **TheBrain** | 公认"最直观的思维导航" | 焦点节点居中 + 语义分区（父上子下）+ 点击后弹性重排 | 大图性能坑（论坛常见抱怨） |
| **Kumu** | 学术系统图事实标准 | Focus 模式（点击后其余元素淡出） | — |
| **Roam Discourse Graph** | 学术圈知名 | **节点类型定义 Question/Claim/Evidence/Source，与本项目几乎一一对应**；类型用颜色+图标区分 | — |
| **Heptabase** | Product Hunt 高赞，研究者推崇 | zoom-in 后节点显示内容摘要而非只有标题 | 白板自由布局 |
| **Cosmograph**（cosmos.gl） | 1.2k stars，2025 加入 OpenJS 基金会 | 内置 Timeline 时间回放控件与图联动的产品形态 | WebGL 百万节点渲染 |
| **3d-force-graph** | 6.4k stars，"好看的知识图谱 demo"主流 | 边上流动粒子=演化方向；发光感 | 3D 本体 |

### 2.2 树/演化/时间线类

| 参考 | 受欢迎证据 | 学什么 |
|---|---|---|
| **Gource** | 13.1k stars，演化叙事动画事实标准 | 深色太空底 + 发光树 + **时间回放驱动生长动画** + 事件发生时的高亮光束 |
| **OneZoom Tree of Life** | "The Google Earth of Biology"，222 万物种 | 分叉角度+枝条粗细编码重要性；**缩放驱动信息密度**（放大才显示细节标签） |
| **gitgraph.js / Learn Git Branching** | 3k / 34k stars | **纵向=时间、横向泳道=分支的正交构图**——与"纵向时间、横向观点分叉"完全同构；新节点从父节点"长出"的入场动效 |
| **D3 tidy tree** | D3 113k stars 的经典案例 | Reingold-Tilford tidy 布局保证分叉不重叠；enter/update/exit transition 范式 |
| **AntV G6 dendrogram** | 12.3k stars | **布局方向 BT（根在底、向上生长）原生支持**；rankSep 映射时间间隔；边上流动虚线表示"仍在演进" |
| **ECharts tree** | 67k stars，国内最熟 | 点击折叠/展开子树的平滑过渡（750ms） |
| **Histropedia** | 普拉多博物馆、英国议会采用 | 时间轴上分色分层卡片——可做侧栏时间刻度带 |
| **Connected Papers / Litmaps** | 学术界标配 | 确定性坐标轴（Litmaps 横轴=发表日期）让"演化"有空间锚点；大小/颜色双重编码 |

### 2.3 氛围与动效类

| 参考 | 学什么 |
|---|---|
| **Linear / Vercel 深色 SaaS 美学** | 配色纪律：非纯黑底色（`#0a0a0f` 级）、四级灰面板、发丝边框、**单一强调色**（克制到只用在关键处）。黑客松场景下"熟悉感"是优点 |
| **WikiGalaxy**（Google Experiments + WIRED 报道） | "知识=星空"配色（深蓝黑底+暖色发光节点）；点击后邻接光束高亮 |
| **GSAP 缓动规范** | UI 微交互统一 `expo.out`（≈ `cubic-bezier(0.16, 1, 0.3, 1)`），300–500ms；入场快起慢落 |
| **tsParticles**（非 particles.js，后者已停更） | 慢速漂浮小光点背景，数量 ≤60 避免抢帧率 |
| **玻璃拟态** | 只在侧边控制面板用（`backdrop-filter: blur(12px)`）；**不盖在 canvas 上方**（合成层性能坑） |

### 2.4 调研的反面教训（同样重要）

1. Logseq 用户原话："graph is way too messy to be practical" → 必须确定性布局；
2. Obsidian 全局图"more fun to look at than navigate" → 导航靠局部聚焦（点击下钻），不靠大图拖来拖去；
3. TheBrain 大图动画 janky → 节点数设上限；
4. particles.js 已停更 → 用 tsParticles；
5. 玻璃拟态在 landing page 已"退烧" → 只用于面板浮层，不当主视觉。

---

## 3. 总体视觉概念

**「暗夜星空下，一棵知识之树自下而上生长」**

- 画布 = 深空（近黑蓝紫底 + 稀疏慢速星点粒子 + 一抹低透明度绿色光晕）；
- 树 = 发光体：主干从画面底部（过去）向顶部（现在）生长，枝条向两侧分叉；
- 时间回放 = 叙事主线：按下"播放"，树从根部一节一节长出来，事件节点在对应年份亮起，被证伪的枝条随后枯萎变灰；
- 语义即视觉：新芽（亮绿脉冲）、枯枝（灰褐虚线）、汇聚（金色合流节点）、年轮（左侧时间带逐环点亮）。

一句话设计定位：**Gource 的灵魂，gitgraph 的骨架，Linear 的皮。**

---

## 4. 页面布局

```
┌────────────────────────────────────────────────────────────┐
│ 顶栏：Epistree logo + 主题输入框 + [生成世界树] + 配额标签      │
├──────────┬─────────────────────────────────────┬───────────┤
│ 左栏      │                                     │ 右栏       │
│ 图例      │        世界树画布（Cytoscape）        │ 节点详情    │
│ 视觉语义   │                                     │ （玻璃面板） │
│ 时间带    │   ↑ 现在                              │           │
│ （年轮）   │   │  主干/分支                        │ 来源引用    │
│ 播放控制   │   ↓ 过去                              │ 置信度     │
├──────────┴─────────────────────────────────────┴───────────┤
│ 底栏：时间滑块（回放控制）+ 年份筛选 + 导出                     │
└────────────────────────────────────────────────────────────┘
```

- **画布居中最大化**，是当前单栏堆叠布局的最大改动：输入区收进顶栏，详情面板从画布下方移到右侧（参照 Bloom/Connected Papers 的侧栏范式）；
- 左栏图例常驻（黑客松评委自助读懂视觉语义的关键，调研中 Bloom Perspective 面板的对应物）；
- 预热主题按钮保留在顶栏输入框旁，作为"示例"下拉或 chips。

---

## 5. 世界树视觉语法（核心）

### 5.1 布局：确定性坐标，自下而上

- **不用**当前的 `breadthfirst`（根在顶、与"生长"方向相反），也**不用**力导向；
- 后端预计算坐标（Python 端，纯数据变换），前端 `layout={'name': 'preset'}`：
  - `y = -(时间戳) × 系数`：根（最早）在底部，新芽在顶部；
  - `x = 分支泳道索引 × lane_width`：每个一级观点分支一条纵向"泳道"（gitgraph 模式），分叉时子分支 x 偏移、汇聚时 x 收敛取均值；
  - 泳道内按主题/阵营分同色系色相；
- 备选：`cyto.load_extra_layouts()` 后用 dagre `rankDir: 'BT'` 自动生成主干-分支，再手动微调（G6 调研确认 BT 是"向上生长"的原生方向）；
- 无时间的节点（时间不详）放到画布底部一条"待定带"，不混入时间轴。

### 5.2 节点语义映射表

| 元素 | 视觉 | Cytoscape 实现路径 |
|---|---|---|
| Topic（主题/树根） | 大尺寸圆角矩形，金绿渐变感（内联 SVG data-URI 径向渐变模拟 glow），常驻标签 | `shape: round-rectangle`，`background-image` |
| Question（问题） | 菱形，蓝色系（#4C9AFF 级） | `shape: diamond` |
| Claim（观点） | 椭圆，绿色系；大小=证据数/引用数映射 | `width/height: mapData(...)` |
| Event（事件） | 六边形/星形，橙金色，挂在时间轴上的"里程碑"感 | `shape: hexagon` |
| Source（来源） | 小方形，灰色低透明度，zoom-in 才显示 | `min-zoomed-font-size` |
| **新芽**（近期活跃观点） | 亮绿 + 脉冲光环（underlay 呼吸动画） | stylesheet class + 步进改 `underlay-opacity` |
| **枯枝**（被证伪/失效） | 灰褐色、`opacity: 0.35`、入边改虚线、可加 ✕ 徽章 | class selector：`line-style: dashed` |
| **汇聚/共识** | 节点放大（入度映射）+ 金色描边 `#FFC107` | `border-width/border-color` |
| **断枝**（突然中断） | 边末端无箭头、短截虚线 | class selector |
| 节点置信度 | 透明度映射（构想文档：透明度=证据充分程度） | `opacity: mapData(confidence, 0, 1, 0.4, 1)` |
| 节点影响力 | 大小映射（构想文档：大小=影响力） | `mapData` |

### 5.3 边语义映射表

| 关系 | 视觉 |
|---|---|
| 主干/演化方向 | 贝塞尔曲线（`curve-style: bezier`），粗细分级：**主干粗、末梢细**（借鉴分形树 taper，子枝=父枝×0.7） |
| supports | 实线，绿色调 |
| contradicts | 虚线，红橙色调（当前 `dashed` class 的延续，换配色） |
| refines/replaces | 实线带箭头，蓝紫色调 |
| evidence（Source→节点） | 极细灰线，默认低透明度，zoom-in 可见 |
| "仍在演进"的活跃路径 | 流动虚线动画（`line-dash-pattern` + 步进偏移，G6 调研确认的表达手法） |

### 5.4 背景语义层

- **年轮/阶段色带**：画布左侧一条 HTML 时间带（纯 CSS/SVG，Dash 回调联动），每个时间段一格，回放到该时段时对应格点亮；Histropedia 式时间带的侧栏变体；
- **年份刻度**：画布左缘竖排年份文字（HTML 浮层，`pointer-events: none`），与 preset 布局的 y 坐标对齐；
- **星空粒子**：tsParticles 全屏 canvas（`position: fixed; z-index: -1`），≤60 个慢速光点，关闭鼠标连线；
- **光晕**：`body::before` 一个绿色系 `radial-gradient` blob + `blur(80px)`，零 JS。

---

## 6. 动画方案（流畅且炫酷的核心）

### 6.1 生长动画（招牌动作）

- **机制**：按时间切片分批更新 `elements`（追加该时间段的节点+边），layout 配 `animate: True, animationDuration: 600, animationEasing: 'ease-out'`——新节点从父节点附近"飞入"目标位置（Learn Git Branching 式入场）；
- **驱动**：两种并存——
  - **播放模式**：`dcc.Interval`（≈800ms/步）自动逐年推进，Gource 式叙事回放；
  - **手动模式**：底栏 `dcc.Slider` 拖动年份，Cosmograph Timeline 式联动；
- **事件高光**：回放到 Event 节点时给它加临时 class（脉冲金边），播完移除（Gource 光束的低成本版）；
- **枯萎动画**：某观点被后续反驳时，对应分支节点在两步内从绿过渡到灰褐+降透明度（步进式 stylesheet 变更近似 `ele.animate` 的颜色动画）。

### 6.2 微交互动画

| 场景 | 动效 | 实现 |
|---|---|---|
| 按钮 hover | `translateY(-2px)` + 阴影加深 | CSS transition |
| 面板/详情出现 | 淡入 + 8px 上移 | CSS animation |
| 点击节点聚焦 | 其余节点淡出至 `opacity: 0.15`，邻居保持（Kumu Focus 模式 / WikiGalaxy 光束） | tap 回调改 stylesheet |
| 点击下钻 | 切换为该节点 1–2 跳子图（TheBrain 式局部聚焦），再点"返回全图"恢复 | elements 替换 + layout animate |
| 全部 UI transition | 统一 `cubic-bezier(0.16, 1, 0.3, 1)`（≈ GSAP expo.out），300–500ms | CSS 变量 |

### 6.3 性能红线

- 节点 ≤500；动画期间不跑力导向；
- 粒子 ≤60，且 canvas 在 Cytoscape 下层；
- `backdrop-filter` 面板不覆盖画布。

---

## 7. 设计 Tokens

### 7.1 配色（深色优先，Linear 纪律 + 生命之树绿金强调）

```text
--bg-deep:      #0a0a0f   /* 页面底（非纯黑） */
--bg-panel-1:   #0f1011
--bg-panel-2:   #141518
--bg-panel-3:   #191a1b
--border-hairline: rgba(255,255,255,.08)
--text-primary: #e8eaf0
--text-secondary: #8b8fa3

/* 节点类型色（高饱和，深底上发光感） */
--c-topic:    #ffd54f  /* 金：主题/主干/共识 */
--c-question: #4c9aff  /* 蓝：问题 */
--c-claim:    #4caf50  /* 绿：观点 */
--c-event:    #ff8a3d  /* 橙：事件 */
--c-source:   #6b7280  /* 灰：来源 */

/* 状态色 */
--c-sprout:   #7cfc90  /* 新芽亮绿 */
--c-withered: #5a5348  /* 枯枝灰褐 */
--c-consensus:#ffc107  /* 共识金描边 */
```

单一强调色原则：绿→金渐变只用于 Topic/共识/主 CTA，其余界面元素保持灰度（Linear 的克制）。

### 7.2 字体与动效

- 字体：Inter（UI）+ JetBrains Mono（数字/年份/配额信息），Google Fonts 经 `external_stylesheets` 引入；
- 缓动变量：`--ease-out-expo: cubic-bezier(0.16, 1, 0.3, 1)`；
- 圆角：面板 12px，控件 6–8px；
- 玻璃面板：`background: rgba(255,255,255,.05); backdrop-filter: blur(12px); border: 1px solid rgba(255,255,255,.1)`。

---

## 8. 交互细节清单

1. **图例常驻**（左栏）：五类节点色块 + 新芽/枯枝/共识/断枝符号说明 + 一句"纵向=时间，横向=观点分叉"；
2. **点击节点** → 右侧详情面板：类型标签、全文、置信度、时间、来源引用（保留现有 `_node_click` 信息架构，仅换视觉容器）；
3. **点击空白** → 取消聚焦，恢复全图；
4. **双击 / 「下钻」按钮** → 局部子图（1–2 跳），顶部出现"← 返回全图"；
5. **缩放信息密度**（OneZoom 模式）：默认只显示 Topic/Question 标签，放大后 Claim/Source 标签经 `min-zoomed-font-size` 渐次显现；
6. **年份筛选**（现有 `time-filter` 的升级）：从下拉改为底栏时间滑块 + 播放键，与原"全部/2024/2025/2026/不详"选项兼容；
7. **进度反馈**：生成过程中的"搜索→抽取→完成"进度条保留，升级为顶栏下方的细发光进度线（expo.out 动画）；
8. **错误/空态**：来源不足、认证失败等沿用现有文案逻辑，视觉统一为玻璃面板内 warning 色块。

---

## 9. 技术可行性与避坑清单

### 9.1 官方支持路径（零 JS 或纯 CSS，全部已验证）

| 需求 | 路径 | 成本 |
|---|---|---|
| 生长/布局动画 | layout dict 传 `animate / animationDuration / animationEasing` + 分批更新 elements | 纯 Python |
| 确定坐标布局 | `preset`（Python 预算坐标）或 `cyto.load_extra_layouts()` 的 dagre `rankDir:'BT'` | 纯 Python |
| 邻接高亮/聚焦淡出 | stylesheet class + tap 回调（dash-cytoscape 官方 usage-stylesheet.py 完整示例） | 纯 Python |
| 枯枝/共识/新芽语义 | stylesheet class selector（含 `mapData` 映射） | 纯 Python |
| 年轮时间带/年份刻度 | HTML+CSS 浮层，Dash 回调联动 | 纯 Python + CSS |
| 粒子背景/光晕/玻璃面板 | 文件丢进 `assets/` 自动注入（文件名数字前缀控顺序） | 一次性 |
| 时间回放 | `dcc.Interval` / `dcc.Slider` 驱动 elements 切片 | 纯 Python |

### 9.2 明确不做（调研确认的坑）

1. ❌ fork dash-cytoscape / 注册 cxtmenu、automove 等 cytoscape 插件（`cytoscape is not defined` 坑）；
2. ❌ 力导向布局（cose/fcose）——首屏漂移 + 与时间叙事冲突；
3. ❌ 3D / WebGL / bloom 后期处理 / 边粒子流动——超出 Cytoscape 能力，对叙事非必需；
4. ❌ particles.js（已停更）——用 tsParticles；
5. ❌ 高频 hover 服务器回调——聚焦用 tap 或 clientside callback；
6. ❌ 玻璃面板盖住画布（backdrop-filter 合成层开销）。

---

## 10. 分期建议（黑客松时间盒）

**P0（必做，决定第一印象）**
深色配色 tokens、页面三段式重排（顶栏/画布/右栏）、preset 自下而上布局、五类节点+枯枝/共识视觉语义、图例左栏、播放式生长动画（Interval 分批追加 + layout animate）。

**P1（加分项）**
tsParticles 星空 + 光晕、年轮时间带、点击聚焦淡出、时间滑块手动回放、事件高光脉冲。

**P2（有余力再做）**
下钻局部图、缩放信息密度（`min-zoomed-font-size`）、流动虚线"仍在演进"路径、枯萎步进动画。

---

## 附：调研方法说明

本方案基于 2026-09-09 对 20+ 个参考产品/项目的并行调研（Obsidian/Neo4j Bloom/TheBrain/Kumu/Heptabase/Juggl/Discourse Graph/Cosmograph/3d-force-graph/Gource/OneZoom/gitgraph.js/Learn Git Branching/D3/ECharts/AntV G6/Histropedia/Connected Papers/Litmaps/WikiGalaxy/Linear 系深色美学/GSAP/tsParticles），证据含 GitHub star 数、社区论坛原话、第三方评测与官方文档。关键原始出处已在正文表格中注明。
