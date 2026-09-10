"""Epistree Demo — Dash application entry point.

Single page: input → query preview → search → extract → knowledge world tree.
"""

from __future__ import annotations

import json
import os
from urllib.parse import quote as _urlquote

import dash
import dash_cytoscape as cyto
from dash import ALL, DiskcacheManager, Input, Output, State, callback, ctx, dcc, html, no_update

from .config import settings
from .models import SearchItem
from .presenter import present
from .service import DemoService
from .warmup import get_warmup_topics_list, load_warmup_topics

# ── app init ──────────────────────────────────────────────────────────────

app = dash.Dash(
    __name__,
    title="Epistree · 知识世界树",
    assets_folder=os.path.join(os.path.dirname(__file__), "assets"),
    suppress_callback_exceptions=True,
    background_callback_manager=DiskcacheManager(),
    external_stylesheets=[
        "https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800"
        "&family=IBM+Plex+Mono:wght@400;500;600&display=swap",
    ],
    external_scripts=[
        # tsParticles（particles.js 已停更，调研结论 §2.3）；CDN 不可用时静默降级
        "https://cdn.jsdelivr.net/npm/tsparticles@3/tsparticles.bundle.min.js",
    ],
)

server = app.server

# Warmup topics — loaded from DATA_DIR
WARMUP_TOPICS = get_warmup_topics_list()

# ── 世界树视觉语法 stylesheet（设计文档 §5.2 / §5.3）────────────────────
# 植物隐喻（ContactTrees 的 leaves & fruits 手法 + OneZoom 木质锥形枝干）：
# 节点不用几何色块，改为内联 SVG —— Claim=果实 / Question=花 /
# Source=叶 / Event=星火 / Topic=种子。cytoscape 的 background-image
# 支持 SVG data URI（须带 XML 头、utf8 编码、不用 base64）。

def _svg_uri(body: str, w: int = 64, h: int = 64) -> str:
    svg = ('<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE svg>'
           f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
           f'viewBox="0 0 {w} {h}">{body}</svg>')
    return "data:image/svg+xml;utf8," + _urlquote(svg, safe="")


def _fruit_svg(main: str, light: str, rim: str, halo: str | None = None) -> str:
    """果实：径向渐变球体 + 高光斑 + 短果柄；halo=自带光晕圈（替代
    cytoscape underlay——它只画圆角矩形，圆果后面露方板）。"""
    halo_ring = (f'<circle cx="32" cy="34" r="31" fill="{halo}" opacity="0.28"/>'
                 if halo else "")
    return _svg_uri(
        f'<defs><radialGradient id="g" cx="35%" cy="30%" r="85%">'
        f'<stop offset="0%" stop-color="{light}"/>'
        f'<stop offset="55%" stop-color="{main}"/>'
        f'<stop offset="100%" stop-color="{rim}"/></radialGradient></defs>'
        + halo_ring +
        '<circle cx="32" cy="34" r="26" fill="url(#g)"/>'
        '<ellipse cx="24" cy="24" rx="8" ry="5" fill="#ffffff" opacity="0.4" '
        'transform="rotate(-25 24 24)"/>'
        '<path d="M32 9 q2 -5 7 -7" stroke="#8d6e63" stroke-width="2.5" '
        'fill="none" stroke-linecap="round"/>')


def _flower_svg(petal: str, petal_deep: str, core: str) -> str:
    """花：六瓣 + 花心（Question = 问题之花）。"""
    petals = "".join(
        f'<ellipse cx="32" cy="15" rx="8.5" ry="14" fill="{petal}" opacity="0.92" '
        f'transform="rotate({a} 32 32)"/>' for a in range(0, 360, 60))
    inner = "".join(
        f'<ellipse cx="32" cy="19" rx="5" ry="9" fill="{petal_deep}" opacity="0.85" '
        f'transform="rotate({a} 32 32)"/>' for a in range(30, 360, 60))
    return _svg_uri(petals + inner
                    + f'<circle cx="32" cy="32" r="7.5" fill="{core}"/>')


def _leaf_svg() -> str:
    """叶子：渐变叶片 + 叶脉（Source = 证据叶）。"""
    return _svg_uri(
        '<defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0%" stop-color="#a5d6a7"/>'
        '<stop offset="100%" stop-color="#2e7d32"/></linearGradient></defs>'
        '<path d="M32 6 C51 15 56 36 32 58 C8 36 13 15 32 6 Z" fill="url(#lg)"/>'
        '<path d="M32 11 L32 53 M32 22 L41 18 M32 22 L23 18 M32 34 L42 29 '
        'M32 34 L22 29 M32 45 L40 41 M32 45 L24 41" stroke="#1b5e20" '
        'stroke-width="1.6" opacity="0.65" stroke-linecap="round"/>')


def _spark_svg() -> str:
    """星火：光晕 + 四角星芒（Event = 里程碑火花）。"""
    return _svg_uri(
        '<defs><radialGradient id="sg" cx="50%" cy="50%" r="50%">'
        '<stop offset="0%" stop-color="#fff3e0"/>'
        '<stop offset="45%" stop-color="#ffb56b"/>'
        '<stop offset="100%" stop-color="#f26d21" stop-opacity="0"/>'
        '</radialGradient></defs>'
        '<circle cx="32" cy="32" r="30" fill="url(#sg)"/>'
        '<path d="M32 8 L37 27 L56 32 L37 37 L32 56 L27 37 L8 32 L27 27 Z" '
        'fill="#ffd54f"/>')


def _seed_svg() -> str:
    """种子：琥珀光球（Topic 树根，树由此生长）。"""
    return _svg_uri(
        '<defs><radialGradient id="tg" cx="40%" cy="35%" r="90%">'
        '<stop offset="0%" stop-color="#ffe9a8"/>'
        '<stop offset="50%" stop-color="#ffb300"/>'
        '<stop offset="100%" stop-color="#5d4037"/></radialGradient></defs>'
        '<circle cx="32" cy="32" r="30" fill="url(#tg)"/>'
        '<circle cx="32" cy="32" r="30" fill="none" stroke="#ffd54f" '
        'stroke-opacity="0.45" stroke-width="2"/>', w=72, h=72)


_IMG = {
    "claim": _fruit_svg("#66bb6a", "#d7f0d8", "#1b5e20"),
    "sprout": _fruit_svg("#8bf09a", "#e8ffee", "#00a047", halo="#7cfc90"),
    "withered": _fruit_svg("#8d8a80", "#c9c5ba", "#45423c"),
    "consensus": _fruit_svg("#ffd54f", "#fff8e1", "#ff8f00", halo="#ffd54f"),
    "question": _flower_svg("#79c0ff", "#3d6fc4", "#e3f2fd"),
    "source": _leaf_svg(),
    "event": _spark_svg(),
    "topic": _seed_svg(),
}

CYTO_STYLESHEET: list[dict] = [
    # 节点基础：单行标签 + 深底可读性描边；方位由 lab-* class 决定（退火放置）
    {"selector": "node", "style": {
        "content": "data(label)", "fontSize": "12px", "color": "#e8eaf0",
        "textValign": "bottom", "textMarginY": 8,
        "textOutlineColor": "#0a0a0f",
        "textOutlineWidth": 2, "fontFamily": "Inter, sans-serif",
        "transition-property": "opacity, background-color, border-color",
        "transition-duration": "0.4s",
    }},
    # 标签方位 class（模拟退火放置结果；Imhof 优先右/左，避免压父枝）
    {"selector": ".lab-r", "style": {"textValign": "center", "textHalign": "right", "textMarginY": 0, "textMarginX": 8}},
    {"selector": ".lab-l", "style": {"textValign": "center", "textHalign": "left", "textMarginY": 0, "textMarginX": -8}},
    {"selector": ".lab-b", "style": {"textValign": "bottom", "textHalign": "center", "textMarginX": 0, "textMarginY": 8}},
    {"selector": ".lab-t", "style": {"textValign": "top", "textHalign": "center", "textMarginX": 0, "textMarginY": -8}},
    {"selector": ".lab-br", "style": {"textValign": "bottom", "textHalign": "right", "textMarginX": 6, "textMarginY": 6}},
    {"selector": ".lab-bl", "style": {"textValign": "bottom", "textHalign": "left", "textMarginX": -6, "textMarginY": 6}},
    {"selector": ".lab-tr", "style": {"textValign": "top", "textHalign": "right", "textMarginX": 6, "textMarginY": -6}},
    {"selector": ".lab-tl", "style": {"textValign": "top", "textHalign": "left", "textMarginX": -6, "textMarginY": -6}},
    # Topic 树根：琥珀种子光球，深色文字置于球内
    {"selector": ".topic", "style": {
        "shape": "ellipse", "width": 108, "height": 108,
        "backgroundColor": "#ffb300", "backgroundFill": "solid",
        "backgroundImage": _IMG["topic"],
        "backgroundWidth": "100%", "backgroundHeight": "100%",
        "borderWidth": 0,
        "color": "#1a1207", "textOutlineWidth": 0, "fontWeight": "bold",
        "fontSize": "13px", "textValign": "center", "textMarginY": 0,
        "textMaxWidth": "76px",
        # Cytoscape underlay is rectangular; the seed SVG already contains a round halo.
        "underlayOpacity": 0,
    }},
    # Question：蓝色六瓣花（主枝锚点，标签常驻）
    {"selector": ".question", "style": {
        "shape": "ellipse", "width": 60, "height": 60,
        "backgroundColor": "#3d6fc4", "backgroundFill": "solid",
        "backgroundImage": _IMG["question"],
        "backgroundWidth": "100%", "backgroundHeight": "100%",
        "borderWidth": 0,
        "underlayColor": "#4c9aff", "underlayOpacity": 0.16, "underlayPadding": 8,
        "fontSize": "13px", "fontWeight": 600,
        "textWrap": "wrap", "textMaxWidth": "110px",
    }},
    # Claim：果实（径向渐变球体），大小=证据数，透明度=置信度；
    # 标签默认隐藏，选中/生长高光时显现（避免文字堆砌，详情看右栏）
    {"selector": ".claim", "style": {
        "shape": "ellipse",
        "width": "mapData(evidence_count, 0, 6, 42, 84)",
        "height": "mapData(evidence_count, 0, 6, 42, 84)",
        "backgroundColor": "#66bb6a", "backgroundFill": "solid",
        "backgroundImage": _IMG["claim"],
        "backgroundWidth": "100%", "backgroundHeight": "100%",
        "borderWidth": 0,
        "opacity": "mapData(confidence, 0, 1, 0.55, 1)",
        "content": "",
        "fontSize": "11px", "fontWeight": 600, "textMarginY": 6,
    }},
    # 新芽：嫩绿果实（光晕烘在 SVG 里）
    {"selector": ".claim.sprout", "style": {
        "backgroundImage": _IMG["sprout"],
    }},
    # 枯枝：枯萎的灰果 + 降透明度
    {"selector": ".claim.withered", "style": {
        "backgroundImage": _IMG["withered"], "opacity": 0.45,
    }},
    # 共识：金色果实（光晕烘在 SVG 里）
    {"selector": ".claim.consensus", "style": {
        "backgroundImage": _IMG["consensus"],
    }},
    # Event：星火（光晕四角星芒），里程碑感；标签默认隐藏
    {"selector": ".event", "style": {
        "shape": "ellipse", "width": 56, "height": 56,
        "backgroundColor": "#f26d21", "backgroundFill": "solid",
        "backgroundImage": _IMG["event"],
        "backgroundWidth": "100%", "backgroundHeight": "100%",
        "borderWidth": 0,
        "underlayColor": "#ff8a3d", "underlayOpacity": 0.2, "underlayPadding": 10,
        "opacity": "mapData(confidence, 0, 1, 0.6, 1)",
        "content": "",
        "fontSize": "12px", "fontWeight": 600,
        "textWrap": "wrap", "textMaxWidth": "110px",
    }},
    # Source：绿色证据小叶，标签默认隐藏（选中时才显示）
    {"selector": ".source", "style": {
        "shape": "ellipse", "width": 20, "height": 20,
        "backgroundColor": "#43a047", "backgroundFill": "solid",
        "backgroundImage": _IMG["source"],
        "backgroundWidth": "100%", "backgroundHeight": "100%",
        "borderWidth": 0, "opacity": 0.85,
        "content": "",
        "fontSize": "9px", "textMarginY": 4,
    }},
    # 标签按需显现：选中节点（金环）或生长/事件高光时
    {"selector": "node:selected", "style": {
        "content": "data(label)", "fontSize": "12px", "fontWeight": 600,
        "underlayOpacity": 0, "borderWidth": 2, "borderColor": "#ffd54f",
    }},
    # 边基础：有机树枝 = unbundled-bezier 弯边，圆头，无箭头，粗细按 data(w)
    {"selector": "edge", "style": {
        "curveStyle": "unbundled-bezier", "edgeDistances": "node-position",
        "width": 2, "lineCap": "round",
        "lineColor": "rgba(141,110,99,.5)",
        "targetArrowShape": "none",
        "transition-property": "opacity, line-color",
        "transition-duration": "0.4s",
    }},
    # S 形弯枝：控制点交替左右偏（OneZoom 的不对称控制点手法）
    {"selector": ".bend-left", "style": {
        "controlPointWeights": [0.25, 0.75], "controlPointDistances": [-34, 26],
    }},
    {"selector": ".bend-right", "style": {
        "controlPointWeights": [0.25, 0.75], "controlPointDistances": [26, -34],
    }},
    # 主干/分枝：达·芬奇枝粗 + 木质渐变（嫩梢浅 → 老木深）
    {"selector": ".trunk", "style": {
        "width": "data(w)",
        "lineFill": "linear-gradient",
        "lineGradientStopColors": "rgba(188,170,164,.8) rgba(109,76,65,.9)",
    }},
    {"selector": ".branch", "style": {
        "width": "data(w)",
        "lineFill": "linear-gradient",
        "lineGradientStopColors": "rgba(129,199,132,.55) rgba(109,76,65,.8)",
    }},
    # 证据细枝（Source 叶子）
    {"selector": ".evidence", "style": {
        "width": 1, "lineColor": "rgba(161,136,127,.4)",
    }},
    # 关系边：颜色承载语义 + 保留箭头表达演化方向；只有关系边显示标签
    {"selector": ".rel-supports, .rel-contradicts, .rel-evolves_into", "style": {
        "curveStyle": "bezier", "targetArrowShape": "triangle", "arrowScale": 0.9,
        "content": "data(label)", "fontSize": "10px", "fontWeight": 600,
        "color": "#c3c9dd",
        "textRotation": "autorotate", "textOutlineColor": "#0a0a0f",
        "textOutlineWidth": 3, "minZoomedFontSize": 7,
    }},
    {"selector": ".rel-supports", "style": {
        "lineStyle": "solid", "lineColor": "rgba(76,175,80,.75)",
        "targetArrowColor": "rgba(76,175,80,.75)",
    }},
    {"selector": ".rel-contradicts", "style": {
        "lineStyle": "dashed", "lineColor": "rgba(255,82,82,.75)",
        "targetArrowColor": "rgba(255,82,82,.75)",
    }},
    {"selector": ".rel-evolves_into", "style": {
        "lineStyle": "solid", "lineColor": "rgba(179,136,255,.75)",
        "targetArrowColor": "rgba(179,136,255,.75)",
    }},
    # 聚焦交互（M5）：其余淡出 / 邻居高亮
    {"selector": ".faded", "style": {"opacity": 0.12, "underlayOpacity": 0}},
    {"selector": "edge.faded", "style": {"opacity": 0.06}},
    {"selector": ".highlighted", "style": {
        "underlayOpacity": 0, "borderWidth": 2, "borderColor": "#65f6b5",
        "content": "data(label)", "fontSize": "12px", "fontWeight": 600,
    }},
    {"selector": "edge.highlighted", "style": {
        "width": 3.5, "opacity": 1,
        "lineColor": "#ffd54f", "targetArrowColor": "#ffd54f",
    }},
]


# ── service (lazy singleton) ──────────────────────────────────────────────

_service: DemoService | None = None
_service_pid: int | None = None


def get_service() -> DemoService:
    global _service, _service_pid
    current_pid = os.getpid()
    if _service is None or _service_pid != current_pid:
        if _service is not None:
            _service.db.close()
        _service = DemoService()
        _service_pid = current_pid
    return _service


# ── layout ───────────────────────────────────────────────────────────────


def _legend_swatch(color: str, extra_class: str = "") -> html.Span:
    return html.Span(className=f"legend-swatch {extra_class}".strip(),
                     style={"background": color} if color else {})


app.layout = html.Div(
    className="app-shell",
    children=[
        # 氛围层
        html.Div(className="bg-glow"),
        html.Div(className="bg-grid"),
        html.Div(className="scanline"),
        html.Div(id="particles-bg"),

        # ── 顶栏 ──────────────────────────────────────────────────────
        html.Header(className="topbar", children=[
            html.Div(className="brand", children=[
                html.Span(className="brand-logo", children=[
                    html.Span(className="brand-orbit"),
                    html.Span("E", className="brand-glyph"),
                ]),
                html.Div([
                    html.Div([
                        html.Span("EPISTREE", className="brand-name"),
                        html.Span("LIVE", className="live-chip"),
                    ], className="brand-line"),
                    html.Div("ZHIHU KNOWLEDGE EVOLUTION ENGINE", className="brand-sub"),
                ]),
            ]),
            html.Div(className="topbar-controls", children=[
                html.Div(className="command-input", children=[
                    html.Span("⌕", className="command-icon"),
                    dcc.Input(
                        id="topic-input",
                        type="text",
                        placeholder="探索一个知识主题…",
                        maxLength=50,
                    ),
                    html.Span("↵", className="key-hint"),
                ]),
                html.Div(className="command-actions", children=[
                    html.Button("构建查询", id="btn-build-queries", className="btn btn-secondary"),
                    html.Button([html.Span(className="btn-spark"), "生成世界树"],
                                id="btn-generate", className="btn btn-primary", disabled=True),
                    html.Button("停止", id="btn-cancel", className="btn btn-ghost"),
                    html.Button("导出", id="btn-export", className="btn btn-ghost"),
                ]),
            ]),
            html.Div(id="quota-info", className="quota-info"),
        ]),

        # 预热主题
        html.Div(className="warmup-row", children=[
            html.Span("QUICK ACCESS", className="warmup-label"),
            *[html.Button(t, id=f"warmup-{i}", className="btn warmup-btn")
              for i, t in enumerate(WARMUP_TOPICS)],
            html.Span("选择预载知识域 · 0 API CALL", className="warmup-note"),
        ]),

        # 进度线
        html.Div(id="progress-area", className="progress-area"),

        # 查询预览
        html.Div(id="query-list", className="query-list"),

        # ── 主区三栏 ──────────────────────────────────────────────────
        html.Div(className="main-grid", children=[
            # 左栏：图例 + 年轮时间带
            html.Aside(className="sidebar-left", children=[
                html.Div(className="glass-panel legend-panel", children=[
                    html.Div([html.Span("01"), "知识语法"], className="panel-title"),
                    html.Div(className="legend-item", children=[
                        _legend_swatch("var(--c-topic)"),
                        html.Div([html.Div("Topic 主题", className="legend-name"),
                                  html.Div("种子——研究主题 / 树根", className="legend-desc")]),
                    ]),
                    html.Div(className="legend-item", children=[
                        _legend_swatch("var(--c-question)"),
                        html.Div([html.Div("Question 问题", className="legend-name"),
                                  html.Div("花——推动知识产生的问题", className="legend-desc")]),
                    ]),
                    html.Div(className="legend-item", children=[
                        _legend_swatch("var(--c-claim)"),
                        html.Div([html.Div("Claim 观点", className="legend-name"),
                                  html.Div("果实——某一阶段的知识主张", className="legend-desc")]),
                    ]),
                    html.Div(className="legend-item", children=[
                        _legend_swatch("var(--c-event)"),
                        html.Div([html.Div("Event 事件", className="legend-name"),
                                  html.Div("星火——触发讨论的外部事件", className="legend-desc")]),
                    ]),
                    html.Div(className="legend-item", children=[
                        _legend_swatch("var(--c-source)"),
                        html.Div([html.Div("Source 来源", className="legend-name"),
                                  html.Div("叶——知乎回答 / 文章等证据", className="legend-desc")]),
                    ]),
                    html.Div(className="legend-item", children=[
                        _legend_swatch("", "sprout"),
                        html.Div([html.Div("新芽", className="legend-name"),
                                  html.Div("近期活跃的活跃观点", className="legend-desc")]),
                    ]),
                    html.Div(className="legend-item", children=[
                        _legend_swatch("", "withered"),
                        html.Div([html.Div("枯枝", className="legend-name"),
                                  html.Div("被反驳或失效的观点", className="legend-desc")]),
                    ]),
                    html.Div(className="legend-item", children=[
                        _legend_swatch("", "consensus"),
                        html.Div([html.Div("共识", className="legend-name"),
                                  html.Div("获得多方支持的观点", className="legend-desc")]),
                    ]),
                    html.Div("纵向 = 时间（下旧上新） · 横向 = 观点分叉 · "
                             "节点大小 = 证据数 · 透明度 = 置信度 · "
                             "点击节点查看详情，Esc 退出聚焦",
                             className="legend-note"),
                ]),
                html.Div(className="glass-panel timeband-panel", children=[
                    html.Div([html.Span("02"), "时间信号"], className="panel-title"),
                    html.Div(id="time-band",
                             children=[html.Div("生成世界树后按年份点亮",
                                                className="legend-desc")]),
                ]),
            ]),

            # 中央画布
            html.Main(className="canvas-wrap", children=[
                html.Div(className="canvas-hud", children=[
                    html.Div("KNOWLEDGE TOPOLOGY", className="hud-kicker"),
                    html.Div("知识演化场", className="hud-title"),
                    html.Div("时间向上生长 · 观点横向分化", className="hud-sub"),
                ]),
                html.Div(className="canvas-status", children=[
                    html.Span(className="status-dot"),
                    html.Span("INTERACTIVE CANVAS"),
                ]),
                cyto.Cytoscape(
                    id="cytoscape-graph",
                    className="cytoscape-container",
                    layout={
                        "name": "preset",
                        "fit": True,
                        "padding": 40,
                        "animate": True,
                        "animationDuration": 600,
                        "animationEasing": "ease-out",
                    },
                    style={"width": "100%", "height": "100%"},
                    elements=[],
                    stylesheet=CYTO_STYLESHEET,
                ),
                html.Div(id="year-axis", className="year-axis"),
                html.Div(className="canvas-hints", children=[
                    html.Span("SCROLL / ZOOM"),
                    html.Span("DRAG / NAVIGATE"),
                    html.Span("CLICK / INSPECT"),
                ]),
            ]),

            # 右栏：详情 + 来源
            html.Aside(className="sidebar-right", children=[
                html.Div(className="glass-panel detail-panel", children=[
                    html.Div([html.Span("03"), "节点情报"], className="panel-title"),
                    html.Div(id="node-detail", className="node-detail",
                             children="点击节点查看详情"),
                ]),
                html.Div(className="glass-panel sources-panel", children=[
                    html.Div(id="source-list", className="source-list"),
                ]),
            ]),
        ]),

        # ── 底栏：时间回放 + 时间筛选 ─────────────────────────────────
        html.Footer(className="bottombar glass-panel", children=[
            html.Div(className="timeline-identity", children=[
                html.Span("EVOLUTION", className="timeline-kicker"),
                html.Span("知识生长回放", className="timeline-title"),
            ]),
            html.Button("▶", id="btn-play", className="btn btn-primary play-btn",
                        style={"width": "auto", "padding": "0 14px"}),
            dcc.Slider(
                id="time-slider",
                min=0, max=0, value=0, step=1,
                marks={},
                className="time-slider",
                tooltip={"placement": "bottom", "always_visible": False},
            ),
            html.Span("TIME RANGE", className="control-label"),
            dcc.Dropdown(
                id="time-filter", options=[
                    {"label": "全部时间", "value": "all"},
                    {"label": "2024", "value": "2024"},
                    {"label": "2025", "value": "2025"},
                    {"label": "2026", "value": "2026"},
                    {"label": "时间不详", "value": "unknown"},
                ],
                value="all", clearable=False,
                style={"width": "150px"},
                className="dash-dropdown",
            ),
        ]),

        dcc.Store(id="run-state", data={"run_id": None, "queries": [], "topic": "", "status": "idle"}),
        dcc.Store(id="graph-bundle-store", data=None),
        dcc.Store(id="sources-store", data=None),
        dcc.Store(id="progress-store", data={"step": "", "progress": 0, "status": "idle"}),
        dcc.Store(id="elements-store", data=None),
        dcc.Store(id="years-store", data=[]),
        dcc.Store(id="playback-state", data={"playing": False, "step_idx": -1}),
        dcc.Store(id="focus-store", data={"node_id": None}),
        html.Button(id="btn-esc", style={"display": "none"}),
        dcc.Download(id="download-json"),
        dcc.Interval(id="progress-interval", interval=500, disabled=True),
        dcc.Interval(id="playback-interval", interval=450, disabled=True),
    ],
)


# ── warmup topics → fill input and render the matching asset ─────────────

_WARMUP_INPUTS = [Input(f"warmup-{i}", "n_clicks") for i in range(len(WARMUP_TOPICS))]


def _warmup_topic_for_trigger(trigger_id: object) -> str | None:
    if not isinstance(trigger_id, str) or not trigger_id.startswith("warmup-"):
        return None
    try:
        index = int(trigger_id.removeprefix("warmup-"))
        return WARMUP_TOPICS[index]
    except (ValueError, IndexError):
        return None


def _triggered_warmup_topic() -> str | None:
    return _warmup_topic_for_trigger(ctx.triggered_id)


@callback(
    Output("topic-input", "value"),
    *_WARMUP_INPUTS,
    prevent_initial_call=True,
)
def _fill_topic(*_clicks):
    return _triggered_warmup_topic() or no_update


@callback(
    Output("cytoscape-graph", "elements", allow_duplicate=True),
    Output("node-detail", "children", allow_duplicate=True),
    Output("source-list", "children", allow_duplicate=True),
    Output("quota-info", "children", allow_duplicate=True),
    Output("graph-bundle-store", "data", allow_duplicate=True),
    Output("sources-store", "data", allow_duplicate=True),
    Output("run-state", "data", allow_duplicate=True),
    Output("btn-generate", "disabled", allow_duplicate=True),
    *_WARMUP_INPUTS,
    prevent_initial_call=True,
)
def _show_warmup(*_clicks):
    topic = _triggered_warmup_topic()
    if topic is None:
        return [no_update] * 8
    asset = load_warmup_topics().get(topic)
    if not asset:
        return [no_update] * 8
    bundle, sources = asset["bundle"], asset["sources"]
    nodes, edges = present(bundle, sources)
    return (
        nodes + edges,
        "点击节点查看详情",
        _build_source_list(sources),
        html.Div("📦 预热资产：离线缓存（0 次真实调用）"),
        bundle.model_dump(mode="json"),
        [s.model_dump(mode="json") for s in sources],
        {
            "run_id": None,
            "queries": asset.get("queries", []),
            "topic": topic,
            "status": "completed",
            "warmup": True,
        },
        True,
    )


# ── build queries ────────────────────────────────────────────────────────

@callback(
    Output("query-list", "children"),
    Output("btn-generate", "disabled"),
    Output("run-state", "data", allow_duplicate=True),
    Input("btn-build-queries", "n_clicks"),
    State("topic-input", "value"),
    State("run-state", "data"),
    prevent_initial_call=True,
)
def _build_queries(n, topic, run_state):
    if not topic or len(topic.strip()) < 2:
        return "请输入 2–50 个字符的主题", True, run_state

    topic = topic.strip()
    try:
        queries = get_service().build_queries(topic)
    except ValueError as e:
        return html.Div(f"主题错误：{e}", style={"color": "#c62828"}), True, run_state

    children = [
        html.Div(f"主题：{topic}", style={"fontWeight": 600, "marginBottom": "8px"}),
    ]
    for q in queries:
        children.append(
            html.Div(className="query-item", children=[
                dcc.Checklist(
                    options=[{"label": "", "value": "active"}],
                    value=["active"],
                    id={"type": "query-check", "index": len(children)},
                    style={"marginRight": "4px"},
                ),
                dcc.Input(
                    value=q,
                    maxLength=200,
                    style={"flex": 1, "padding": "4px 8px", "border": "1px solid #ddd", "borderRadius": "4px"},
                    id={"type": "query-input", "index": len(children)},
                ),
            ])
        )

    run_state = {**run_state, "queries": queries, "topic": topic, "status": "queries_built"}
    return children, False, run_state


# ── generate world tree (full pipeline) ──────────────────────────────────

@callback(
    Output("cytoscape-graph", "elements"),
    Output("node-detail", "children"),
    Output("source-list", "children"),
    Output("quota-info", "children"),
    Output("graph-bundle-store", "data"),
    Output("sources-store", "data"),
    Output("run-state", "data", allow_duplicate=True),
    Output("btn-generate", "disabled", allow_duplicate=True),
    Input("btn-generate", "n_clicks"),
    State("btn-cancel", "n_clicks"),
    State("run-state", "data"),
    State("topic-input", "value"),
    State({"type": "query-input", "index": ALL}, "value"),
    State({"type": "query-check", "index": ALL}, "value"),
    background=True,
    cancel=[Input("btn-cancel", "n_clicks")],
    progress=Output("progress-store", "data"),
    running=[(Output("btn-generate", "disabled"), True, False)],
    prevent_initial_call=True,
)
def _generate(set_progress, n, _cancel_clicks, run_state, topic, edited_queries=None, checks=None):
    if not topic or len(topic.strip()) < 2:
        return [no_update] * 8

    topic = topic.strip()
    svc = get_service()

    try:
        # Create run
        run_id = svc.create_run(topic)

        # Get queries from run_state or build fresh
        submitted_query_state = edited_queries is not None or checks is not None
        queries = [q for q, active in zip(edited_queries or [], checks or [])
                   if q and active and "active" in active]
        if submitted_query_state and not queries:
            svc.fail_run(run_id, "INVALID_QUERY", "NO_ACTIVE_QUERIES: 至少保留一条查询")
            return (
                [], html.Div("⚠ 未选择任何查询，未发起网络请求。", className="tag tag-warning"),
                "", "", None, None, {**run_state, "status": "failed"}, True,
            )
        if not queries:
            queries = run_state.get("queries", []) or svc.build_queries(topic)

        # Search
        svc.db.update_run_status(run_id, "running")
        if set_progress:
            set_progress({"run_id": run_id, "step": "搜索", "progress": 25, "status": "running"})
        selected_sources, stats = svc.execute_search(run_id, queries)
        if svc.get_run(run_id)["status"] == "cancelled":
            if set_progress:
                set_progress({"run_id": run_id, "step": "已取消", "progress": 0, "status": "cancelled"})
            return [], "", "", "", None, None, {**run_state, "run_id": run_id, "status": "cancelled"}, True

        if len(selected_sources) < 3:
            run_status = "failed"
            svc.fail_run(run_id, "INSUFFICIENT_SOURCES",
                         f"仅找到 {len(selected_sources)} 条唯一来源，需要至少 3 条")
            quota_info = html.Div([
                html.Span(f"⚠ 来源不足：{len(selected_sources)} 条唯一来源"),
            ])
            return [], "", "", quota_info, None, None, {**run_state, "status": run_status}, True

        # Extract knowledge
        if set_progress:
            set_progress({"run_id": run_id, "step": "抽取", "progress": 70, "status": "running"})
        bundle, bundle_id = svc.extract_knowledge_with_id(topic, selected_sources)

        if not bundle.claims:
            svc.fail_run(run_id, "NO_CLAIMS", "模型未提取到任何 Claim")
            quota_info = html.Div([
                html.Span(f"⚠ 模型未能提取 Claim（{len(bundle.questions)} 个问题）"),
            ])
            return [], "", "", quota_info, None, None, {**run_state, "status": "failed"}, True

        # Complete run
        svc.complete_run(run_id, bundle, stats, bundle_id)

        # Present
        nodes, edges = present(bundle, selected_sources)
        elements = nodes + edges

        detail_html = "点击节点查看详情"
        source_html = _build_source_list(selected_sources)
        quota_info = _build_quota_info(stats)

        run_state = {
            **run_state, "run_id": run_id, "bundle_id": bundle_id,
            "stats": stats, "status": "completed",
        }

        if set_progress:
            set_progress({"run_id": run_id, "step": "完成", "progress": 100, "status": "completed"})
        return (
            elements, detail_html, source_html, quota_info,
            bundle.model_dump(mode="json"),
            [s.model_dump(mode="json") for s in selected_sources],
            run_state, False,
        )

    except PermissionError:
        svc.fail_run(run_id, "AUTH_REQUIRED", "知乎 Access Secret 未配置")
        return (
            [],
            html.Div("❌ 知乎 API 认证失败。请配置 ZHIHU_ACCESS_SECRET。",
                     style={"color": "#c62828", "padding": "16px"}),
            "", "",
            None, None,
            {**run_state, "status": "failed"}, True,
        )
    except ValueError as e:
        error_msg = str(e)
        svc.fail_run(run_id, "MODEL_VALIDATION_FAILED", error_msg)
        return (
            [], html.Div("⚠ 来源或模型结果校验失败，请稍后重试。", className="tag tag-warning"),
            "", "", None, None, {**run_state, "status": "failed"}, True,
        )
    except RuntimeError as e:
        error_msg = str(e)
        if "MODEL_VALIDATION_FAILED" in error_msg:
            svc.fail_run(run_id, "MODEL_VALIDATION_FAILED", error_msg)
            return (
                [], html.Div("⚠ 模型输出验证失败，请稍后重试。", style={"color": "#e65100", "padding": "16px"}),
                "", "", None, None, {**run_state, "status": "failed"}, True,
            )
        svc.fail_run(run_id, "UPSTREAM_FAILED", error_msg)
        return (
            [], html.Div(f"⚠ {error_msg}", style={"color": "#e65100", "padding": "16px"}),
            "", "", None, None, {**run_state, "status": "failed"}, True,
        )


# ── node click detail ────────────────────────────────────────────────────

@callback(
    Output("node-detail", "children", allow_duplicate=True),
    Input("cytoscape-graph", "tapNodeData"),
    State("sources-store", "data"),
    prevent_initial_call=True,
)
def _node_click(node_data, sources_data):
    if not node_data:
        return "点击节点查看详情"

    node_type = node_data.get("node_type", "unknown")
    label = node_data.get("label", "")
    full_text = node_data.get("full_text", "")
    source_refs = node_data.get("source_refs", [])

    children = []
    children.append(html.Div(f"类型：{node_type}", className="node-detail-label"))
    children.append(html.H3(label))

    if full_text:
        children.append(html.P(full_text, style={"fontSize": "13px", "color": "#333"}))

    if node_type == "claim":
        conf = node_data.get("confidence", 0)
        children.append(html.Div([
            html.Span("model_candidate", className="tag tag-candidate"),
            html.Span(f" 置信度：{conf:.2f}", style={"fontSize": "12px", "color": "#888"}),
        ]))

    if node_data.get("occurred_at"):
        children.append(html.Div(f"时间：{node_data['occurred_at']}", style={"fontSize": "12px", "color": "#888"}))

    if node_type == "source":
        url = node_data.get("url", "")
        author = node_data.get("author_name", "")
        if url:
            children.append(html.A("打开知乎原文", href=url, target="_blank",
                                   style={"display": "block", "marginTop": "8px"}))
        if author:
            children.append(html.Div(f"作者：{author}", style={"fontSize": "12px", "color": "#888", "marginTop": "4px"}))

    if source_refs and node_type != "source":
        children.append(html.Div("来源引用：", className="node-detail-label"))
        source_map = {s.get("source_id"): s for s in (sources_data or [])}
        ref_details = []
        for ref in source_refs:
            source = source_map.get(ref.get("source_id"), {})
            if source:
                ref_details.append(html.Div([
                    html.A(source.get("title", ref.get("source_id", "来源")),
                           href=source.get("url", ""), target="_blank"),
                    html.Div(f"作者：{source.get('author_name', '')}"),
                    html.Div(source.get("content_text", "")[:240]),
                ], className="source-reference"))
            else:
                ref_details.append(html.Div(ref.get("source_id", "?")))
        children.append(html.Div(ref_details))

    children.append(html.Div("AI 提取，请查看来源", className="annotation", style={"marginTop": "12px"}))
    return children


@callback(
    Output("node-detail", "children", allow_duplicate=True),
    Input("cytoscape-graph", "tapEdgeData"),
    State("sources-store", "data"),
    prevent_initial_call=True,
)
def _edge_click(edge_data, sources_data):
    if not edge_data:
        return no_update
    refs = edge_data.get("source_refs", [])
    source_map = {s.get("source_id"): s for s in (sources_data or [])}
    source_details = []
    for ref in refs:
        source = source_map.get(ref.get("source_id"), {})
        if source:
            source_details.append(html.Div([
                html.A(source.get("title", "知乎来源"), href=source.get("url", ""),
                       target="_blank"),
                html.Div(f"作者：{source.get('author_name', '')}"),
                html.Div(source.get("content_text", "")[:240]),
            ], className="source-reference"))
    return html.Div([
        html.Div("类型：候选关系", className="node-detail-label"),
        html.H3(edge_data.get("label", "关系")),
        html.Div(f"置信度：{edge_data.get('confidence', 0):.2f}"),
        html.Div("model_candidate · AI 推断，请查看来源", className="annotation"),
        html.Div(source_details or ["暂无可展示来源"]),
    ])


@callback(
    Output("cytoscape-graph", "elements", allow_duplicate=True),
    Input("time-filter", "value"),
    State("cytoscape-graph", "elements"),
    State("graph-bundle-store", "data"),
    State("sources-store", "data"),
    prevent_initial_call=True,
)
def _time_filter(value, elements, bundle_data=None, sources_data=None):
    if not elements and not bundle_data:
        return no_update
    if bundle_data:
        from .models import GraphBundle, SearchItem
        full_nodes, full_edges = present(
            GraphBundle.model_validate(bundle_data),
            [SearchItem.model_validate(item) for item in (sources_data or [])],
        )
        elements = full_nodes + full_edges
    if value in (None, "all"):
        return elements
    source_map = {s.get("source_id"): s for s in (sources_data or [])}
    visible = []
    allowed = set(str(value).split(","))
    visible_ids = set()
    for element in elements:
        data = element.get("data", {})
        if "source" in data:
            visible.append(element)
            continue
        if data.get("node_type") == "topic":
            visible.append(element)
            visible_ids.add(data.get("id"))
            continue
        occurred = data.get("occurred_at")
        years = {str(occurred)[:4]} if occurred else set()
        edit_time = data.get("edit_time")
        if edit_time:
            years.add(str(edit_time)[:4])
        for ref in data.get("source_refs", []):
            edit_time = source_map.get(ref.get("source_id", ""), {}).get("edit_time")
            if edit_time:
                years.add(str(edit_time)[:4])
        matches = not years if value == "unknown" else bool(years & allowed)
        if not matches:
            continue
        visible.append(element)
        if "id" in data:
            visible_ids.add(data["id"])
    return [e for e in visible if e.get("data", {}).get("source") in visible_ids
            and e.get("data", {}).get("target") in visible_ids or "source" not in e.get("data", {})]


@callback(
    Output("run-state", "data", allow_duplicate=True),
    Output("progress-store", "data", allow_duplicate=True),
    Input("btn-cancel", "n_clicks"),
    State("progress-store", "data"),
    prevent_initial_call=True,
)
def _cancel_run(_n, progress):
    run_id = (progress or {}).get("run_id")
    if not run_id:
        return no_update, {"status": "idle", "step": "", "progress": 0}
    get_service().cancel_run(run_id)
    return {"run_id": run_id, "status": "cancelled"}, {
        "run_id": run_id, "status": "cancelled", "step": "已取消", "progress": 0,
    }


@callback(Output("progress-area", "children"), Input("progress-store", "data"))
def _show_progress(progress):
    if not progress or progress.get("status") in (None, "idle"):
        return no_update
    return html.Div(
        f"{progress.get('step', '处理中')} · {progress.get('progress', 0)}%",
        className="progress-tag",
    )


# ── time playback：生长动画与时间回放（设计文档 §6.1）────────────────────

# fit=True 会重缩放视口；回放期间每 tick 都 fit 会造成持续晃动，
# 因此只有开始播放/拖动滑块时 fit，interval 逐帧生长时保持视口不动
_LAYOUT_FIT = {"name": "preset", "fit": True, "padding": 40,
               "animate": True, "animationDuration": 600, "animationEasing": "ease-out"}
_LAYOUT_NOFIT = {"name": "preset", "fit": False,
                 "animate": True, "animationDuration": 600, "animationEasing": "ease-out"}

def _is_edge(el: dict) -> bool:
    d = el.get("data", {})
    return "source" in d and "target" in d


# 逐节点生长顺序：同一年里 question（枝）先于 event / claim（果）
_GROW_ORDER = {"question": 0, "event": 1, "claim": 2}


def _build_steps(elements: list[dict]) -> list[list[str]]:
    """构造逐节点生长序列：每步 = 1 个知识节点 + 挂在它身上的 source 叶子。

    按 (year, question→event→claim, id) 排序，保证父枝先于子叶登场；
    按年切片只有 3 帧、视觉上像跳变，逐步生长才有「树在长」的感觉。
    """
    host_of: dict[str, str] = {}
    parent_of: dict[str, str] = {}
    for el in elements:
        if not _is_edge(el):
            continue
        if el["data"].get("edge_type") == "evidence":
            host_of.setdefault(el["data"]["source"], el["data"]["target"])
        elif el["data"].get("edge_type") == "contains":
            parent_of[el["data"]["source"]] = el["data"]["target"]
    key_nodes = [el for el in elements
                 if not _is_edge(el)
                 and el["data"].get("node_type") in _GROW_ORDER]
    key_nodes.sort(key=lambda el: (el["data"].get("year") or 9999,
                                   _GROW_ORDER[el["data"]["node_type"]],
                                   el["data"]["id"]))
    by_id = {el["data"]["id"]: el for el in key_nodes}
    emitted: set[str] = set()
    steps: list[list[str]] = []

    def _emit(el: dict) -> None:
        """按时间序登场，但父枝（question）必须先于其子节点长出。"""
        nid = el["data"]["id"]
        if nid in emitted:
            return
        parent = by_id.get(parent_of.get(nid, ""))
        if parent is not None:
            _emit(parent)
        emitted.add(nid)
        leaves = sorted(sid for sid, host in host_of.items() if host == nid)
        steps.append([nid, *leaves])

    for el in key_nodes:
        _emit(el)
    # 兜底：没被任何知识节点引用的 source（正常不会发生）
    attached = {nid for step in steps for nid in step}
    leftovers = sorted(el["data"]["id"] for el in elements
                       if not _is_edge(el)
                       and el["data"].get("node_type") == "source"
                       and el["data"]["id"] not in attached)
    if leftovers:
        steps.append(leftovers)
    return steps


def _slice_elements(elements: list[dict], step_idx: int | None,
                    steps: list[list[str]]) -> list[dict]:
    """Return elements visible after step_idx growth steps (None = 全部).

    Topic（树根）始终可见；当前步新登场的节点附加高光（Gource 式事件
    高光，突出「刚长出来」的部分）；边只在两端节点均可见时保留。
    step_idx = -1 时只显示树根。
    """
    visible_ids = {el["data"]["id"] for el in elements
                   if not _is_edge(el) and el["data"].get("node_type") == "topic"}
    if step_idx is None:
        visible_ids |= {el["data"]["id"] for el in elements if not _is_edge(el)}
    else:
        for step in steps[:step_idx + 1]:
            visible_ids.update(step)
    current_ids = (set(steps[step_idx])
                   if step_idx is not None and 0 <= step_idx < len(steps)
                   else set())
    out = []
    for el in elements:
        if _is_edge(el):
            d = el["data"]
            if d["source"] in visible_ids and d["target"] in visible_ids:
                out.append(el)
            continue
        d = el["data"]
        if d["id"] not in visible_ids:
            continue
        node = {**el, "data": dict(d)}
        cls = node.get("classes", "")
        if d["id"] in current_ids and "highlighted" not in cls:
            node["classes"] = (cls + " highlighted").strip()
        out.append(node)
    return out


def _year_counts(elements: list[dict]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for el in elements:
        if _is_edge(el):
            continue
        d = el["data"]
        if d.get("node_type") in ("topic", "source"):
            continue
        y = d.get("year")
        if y:
            counts[y] = counts.get(y, 0) + 1
    return counts


def _build_time_band(years: list[int], counts: dict[int, int],
                     current_year: int | None) -> list:
    """年轮时间带：回放到哪一年，对应环点亮（含该年新增节点数）。"""
    if not years:
        return [html.Div("生成世界树后按年份点亮", className="legend-desc")]
    children = []
    for y in years:
        active = current_year is None or y <= current_year
        children.append(html.Div(
            className=f"timeband-year {'active' if active else ''}",
            children=[html.Span(className="ring"), html.Span(str(y)),
                      html.Span(f"+{counts.get(y, 0)}", className="count")],
        ))
    return children


@callback(
    Output("elements-store", "data"),
    Output("years-store", "data"),
    Output("time-slider", "max"),
    Output("time-slider", "marks"),
    Output("time-slider", "value"),
    Output("playback-state", "data"),
    Output("playback-interval", "disabled"),
    Output("time-band", "children"),
    Output("year-axis", "children"),
    Input("graph-bundle-store", "data"),
    State("sources-store", "data"),
    prevent_initial_call=True,
)
def _prepare_playback(bundle_data, sources_data):
    if not bundle_data:
        return [no_update] * 9
    from .models import GraphBundle, SearchItem
    nodes, edges = present(
        GraphBundle.model_validate(bundle_data),
        [SearchItem.model_validate(s) for s in (sources_data or [])],
    )
    elements = nodes + edges
    years = sorted({n["data"]["year"] for n in nodes if n["data"].get("year")})
    counts = _year_counts(elements)
    marks = {i: str(y) for i, y in enumerate(years)}
    marks[len(years)] = "全部"
    return (elements, years, len(years), marks, len(years),
            {"playing": False, "step_idx": -1}, True,
            _build_time_band(years, counts, None),
            [html.Span(str(y)) for y in years])


@callback(
    Output("cytoscape-graph", "elements", allow_duplicate=True),
    Output("cytoscape-graph", "layout", allow_duplicate=True),
    Output("playback-state", "data", allow_duplicate=True),
    Output("playback-interval", "disabled", allow_duplicate=True),
    Output("time-band", "children", allow_duplicate=True),
    Input("btn-play", "n_clicks"),
    Input("playback-interval", "n_intervals"),
    Input("time-slider", "value"),
    State("playback-state", "data"),
    State("elements-store", "data"),
    State("years-store", "data"),
    prevent_initial_call=True,
)
def _playback(_play, _tick, slider_value, state, elements, years):
    if not elements or not years:
        return [no_update] * 5
    state = state or {"playing": False, "step_idx": -1}
    counts = _year_counts(elements)
    steps = _build_steps(elements)
    year_of = {el["data"]["id"]: el["data"].get("year")
               for el in elements if not _is_edge(el)}
    step_years = [year_of.get(step[0]) for step in steps]
    trigger = ctx.triggered_id

    if trigger == "btn-play":
        if state.get("playing"):  # 暂停
            return no_update, no_update, {**state, "playing": False}, True, no_update
        # 从一颗种子开始长：首帧只露树根。不重 fit——当前视口已是全图取景，
        # 相机不动，整棵树在同一坐标系内逐节点长出，不会有任何瞬间出现
        return (_slice_elements(elements, -1, steps), _LAYOUT_NOFIT,
                {"playing": True, "step_idx": -1}, False,
                _build_time_band(years, counts, years[0] - 1))

    if trigger == "playback-interval":
        if not state.get("playing"):
            return [no_update] * 5
        nxt = state.get("step_idx", -1) + 1
        if nxt >= len(steps):  # 回放完毕：展示全图（含待定带），重新 fit
            return (_slice_elements(elements, None, steps), _LAYOUT_FIT,
                    {"playing": False, "step_idx": nxt}, True,
                    _build_time_band(years, counts, None))
        # 逐帧生长：视口保持不动，避免持续缩放晃动
        return (_slice_elements(elements, nxt, steps), _LAYOUT_NOFIT,
                {"playing": True, "step_idx": nxt}, False,
                _build_time_band(years, counts, step_years[nxt]))

    if trigger == "time-slider":
        if slider_value is None:
            return [no_update] * 5
        if slider_value >= len(years):  # 「全部」档
            return (_slice_elements(elements, None, steps), _LAYOUT_FIT,
                    {"playing": False, "step_idx": -1}, True,
                    _build_time_band(years, counts, None))
        year = years[slider_value]
        # 跳转到最后一个 year ≤ 目标年的生长步（此前该年全部可见）
        idx = max((i for i, y in enumerate(step_years)
                   if y is not None and y <= year), default=-1)
        return (_slice_elements(elements, idx, steps), _LAYOUT_FIT,
                {"playing": False, "step_idx": idx}, True,
                _build_time_band(years, counts, year))

    return [no_update] * 5


@callback(Output("btn-play", "children"), Input("playback-state", "data"))
def _play_label(state):
    return "Ⅱ" if (state or {}).get("playing") else "▶"


# ── 聚焦交互：点击节点高亮邻居、其余淡出（Kumu Focus / WikiGalaxy 光束）──

@callback(
    Output("cytoscape-graph", "elements", allow_duplicate=True),
    Output("focus-store", "data"),
    Input("cytoscape-graph", "tapNodeData"),
    State("cytoscape-graph", "elements"),
    State("focus-store", "data"),
    prevent_initial_call=True,
)
def _focus_node(node_data, elements, focus):
    if not node_data or not elements:
        return no_update, no_update
    nid = node_data.get("id")

    def _strip(el):
        return {**el, "classes": el.get("classes", "").replace(" faded", "").strip()}

    if (focus or {}).get("node_id") == nid:
        # 再次点击同一节点 → 取消聚焦
        return [_strip(el) for el in elements], {"node_id": None}

    neighbors = {nid}
    for el in elements:
        if _is_edge(el):
            d = el["data"]
            if d["source"] == nid:
                neighbors.add(d["target"])
            if d["target"] == nid:
                neighbors.add(d["source"])

    out = []
    for el in elements:
        base = _strip(el)
        if _is_edge(el):
            d = el["data"]
            connected = d["source"] == nid or d["target"] == nid
        else:
            connected = el["data"].get("id") in neighbors
        if not connected:
            base["classes"] = (base.get("classes", "") + " faded").strip()
        out.append(base)
    return out, {"node_id": nid}


@callback(
    Output("cytoscape-graph", "elements", allow_duplicate=True),
    Output("focus-store", "data", allow_duplicate=True),
    Input("btn-esc", "n_clicks"),
    State("cytoscape-graph", "elements"),
    State("focus-store", "data"),
    prevent_initial_call=True,
)
def _esc_unfocus(_n, elements, focus):
    """ESC 退出聚焦（02_keyboard.js 把 Esc 转成隐藏按钮点击）：全部恢复高亮。"""
    if not elements or not (focus or {}).get("node_id"):
        return no_update, no_update
    out = [{**el, "classes": el.get("classes", "").replace(" faded", "").strip()}
           for el in elements]
    return out, {"node_id": None}


# ── export JSON ──────────────────────────────────────────────────────────

@callback(
    Output("download-json", "data"),
    Input("btn-export", "n_clicks"),
    State("graph-bundle-store", "data"),
    State("sources-store", "data"),
    State("run-state", "data"),
    prevent_initial_call=True,
)
def _export_json(n, bundle_data, sources_data, run_state):
    if not bundle_data:
        return no_update
    payload = {
        "export_version": "v1",
        "bundle": bundle_data,
        "sources": sources_data or [],
        "run": run_state or {},
        "metadata": {
            "prompt_version": settings.prompt_version,
            "graph_schema_version": settings.graph_schema_version,
            "model_name": settings.llm_model,
        },
    }
    return dcc.send_string(json.dumps(payload, ensure_ascii=False, indent=2), "epistree_graph.json")


# ── helpers ──────────────────────────────────────────────────────────────

def _build_source_list(sources: list[SearchItem]) -> html.Div:
    if not sources:
        return html.Div("暂无来源", className="annotation")

    items = []
    for s in sources:
        items.append(html.Div([
            html.A(s.author_name or s.title, href=str(s.url), target="_blank"),
            html.Span(f" · {s.title[:80]}"),
        ], style={"padding": "6px 0", "borderBottom": "1px solid rgba(255,255,255,.06)"}))

    return html.Div([
        html.H3(f"来源列表（{len(sources)} 条）", style={"marginTop": 0}),
        *items,
    ])


def _build_quota_info(stats: dict) -> html.Div:
    return html.Div([
        html.Span(f"🔍 真实调用：{stats.get('real_api_calls', 0)}", className="tag tag-cache"),
        html.Span(f"📦 缓存命中：{stats.get('cache_hits', 0)}", className="tag tag-model"),
        html.Span(f"📄 总来源：{stats.get('total_items', 0)}", style={"marginLeft": "8px"}),
        html.Span(f"✅ 选中：{stats.get('unique_selected', 0)}", style={"marginLeft": "8px"}),
    ])


# ── main ─────────────────────────────────────────────────────────────────

def main() -> None:
    port = int(os.environ.get("PORT", 8050))
    debug = os.environ.get("DASH_DEBUG", "0") == "1"
    app.run(debug=debug, port=port, host="0.0.0.0")


if __name__ == "__main__":
    main()
