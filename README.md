# Epistree · 知识世界树

> 输入一个主题，看到这个领域的知识是怎样一步一步长出来的。

[![Release](https://img.shields.io/github/v/release/MaQiangQAQ/Epistree)](https://github.com/MaQiangQAQ/Epistree/releases)
[![Python](https://img.shields.io/badge/python-3.14+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Epistree（知识世界树）** 是一个时序知识发现与演化分析系统。它从高质量讨论与专业内容中，发现与特定领域相关的关键事件、核心问题、多元观点与论据，建模知识的产生、分化、争议、修正与汇聚过程，并将其呈现为一棵清晰可交互的“知识世界树”。

---

## 🌟 核心特性

- 🌳 **时序知识演化**：打破传统搜索碎片化的图文列表，以“纵向时间发展、横向观点分叉”的形态重现认知发展脉络。
- 🌿 **生动植物隐喻**：以花（问题之花）、果（观点结论）、叶（来源证据）为视觉语法，直观反映知识生态的茂盛度与演进。
- 🔍 **真实来源可追溯**：每个节点均严密锚定真实讨论与创作者经验，点击即可调出情报抽屉核对原文背景与论据。
- 🎬 **动态时间回放**：支持时间轴自由拖拽与平滑步进播放，直观体验知识在不同年份阶段的破土与分叉生长。
- 🚀 **开箱即用展区**：预置大模型微调、RAG、AI Agent、视觉大模型、推理加速量化、强化学习长思维链等 6 大前沿主题，无需配置即可秒级体验。

---

## 🚀 快速上手

### 环境要求
- [uv](https://docs.astral.sh/uv/) (推荐) 或 Python 3.14+

### 本地运行

```bash
# 克隆仓库
git clone https://github.com/MaQiangQAQ/Epistree.git
cd Epistree

# 安装依赖并启动
uv sync
uv run epistree-demo
```

浏览器访问 `http://localhost:8050` 即可开始探索。

### Docker 运行

```bash
docker build -t epistree-demo .
docker run --rm -p 8050:8050 epistree-demo
```

---

## ⚙️ 配置说明（可选）

如需启用自定义主题在线搜索与结构化抽取，可在本地根目录配置 `.env` 文件（参考 `.env.example`）：

```bash
ZHIHU_ACCESS_SECRET=your_zhihu_secret    # 知乎开放平台 Access Secret
LLM_BASE_URL=https://api.openai.com/v1     # 兼容 OpenAI 的 API 端点
LLM_API_KEY=your_llm_api_key              # 大模型 API Key
LLM_MODEL=deepseek-v4-flash                # 模型名称
```

> **提示**：未配置 API 凭证时，系统默认运行在离线预热演示模式下，可完整浏览所有预置主题与全部交互功能。

---

## 📂 仓库结构

```text
.
├── src/epistree_demo/     # Web 应用主程序与视觉呈现
│   ├── app.py             # Dash 应用入口与页面布局
│   ├── presenter.py       # 世界树图谱生成与样式控制
│   ├── extractor.py       # 结构化模型抽取逻辑
│   └── zhihu_client.py    # 开放数据检索与配额治理
├── tests/                 # 单元测试与端到端回归
├── docs/                  # 详细架构与前端设计文档
└── pyproject.toml         # 项目配置与依赖管理
```

---

## 🤝 贡献与反馈

欢迎提交 Issue 或 Pull Request！详细贡献规范请参考 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

## 📄 开源协议

本项目采用 [MIT License](LICENSE) 开源。

