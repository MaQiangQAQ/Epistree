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

# Warmup topics — loaded from DATA_DIR with curated exhibition order
ORDERED_TOPICS = [
    "RAG",
    "大模型微调",
    "视觉大模型",
    "AI Agent 智能体",
    "大模型推理加速与量化",
    "大模型强化学习与长思维链",
]
_available_topics = get_warmup_topics_list()
WARMUP_TOPICS = [t for t in ORDERED_TOPICS if t in _available_topics] + [
    t for t in _available_topics if t not in ORDERED_TOPICS
]

TOPIC_ICONS = {
    "RAG": "🌿",
    "大模型微调": "🧬",
    "视觉大模型": "👁️",
    "AI Agent 智能体": "🤖",
    "大模型推理加速与量化": "⚡",
    "大模型强化学习与长思维链": "🧠",
}


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
    # 节点基础：默认无常驻文字；仅关键主枝与选中节点显现文字，保证树木繁茂通透
    {"selector": "node", "style": {
        "content": "", "fontSize": "12px", "color": "#e8eaf0",
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
        "backgroundColor": "transparent", "backgroundOpacity": 0,
        "backgroundImage": _IMG["topic"],
        "backgroundWidth": "100%", "backgroundHeight": "100%",
        "borderWidth": 0,
        "color": "#1a1207", "textOutlineWidth": 0, "fontWeight": "bold",
        "fontSize": "13px", "textValign": "center", "textMarginY": 0,
        "textMaxWidth": "76px",
        "content": "data(label)",
        # Cytoscape underlay is rectangular; the seed SVG already contains a round halo.
        "underlayOpacity": 0,
    }},
    # Question：蓝色六瓣花（主枝关键锚点，唯一常驻文字导览）
    {"selector": ".question", "style": {
        "shape": "ellipse", "width": 62, "height": 62,
        "backgroundColor": "transparent", "backgroundOpacity": 0,
        "backgroundImage": _IMG["question"],
        "backgroundWidth": "100%", "backgroundHeight": "100%",
        "borderWidth": 0,
        "underlayColor": "#4c9aff", "underlayOpacity": 0.2, "underlayPadding": 8,
        "fontSize": "12px", "fontWeight": 700, "color": "#f0f4ff",
        "textWrap": "wrap", "textMaxWidth": "120px",
        "content": "data(label)",
    }},
    # Claim：果实（径向渐变球体），大小=证据数，透明度=置信度；
    # 标签默认隐藏，选中/生长高光时显现（避免文字堆砌，详情看右栏）
    {"selector": ".claim", "style": {
        "shape": "ellipse",
        "width": "mapData(evidence_count, 0, 6, 42, 84)",
        "height": "mapData(evidence_count, 0, 6, 42, 84)",
        "backgroundColor": "transparent", "backgroundOpacity": 0,
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
        "backgroundColor": "transparent", "backgroundOpacity": 0,
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
        "backgroundColor": "transparent", "backgroundOpacity": 0,
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
    # 主干/分枝/根系：达·芬奇枝粗 + 木质渐变（嫩梢浅 → 老木深）
    {"selector": ".root", "style": {
        "width": "data(w)",
        "lineFill": "linear-gradient",
        "lineGradientStopColors": "rgba(141,110,99,.9) rgba(62,39,35,.95)",
    }},
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
    # 关系边：颜色承载语义 + 保留箭头表达演化方向；默认无字，悬浮/选中/高光显现
    {"selector": ".rel-supports, .rel-contradicts, .rel-evolves_into", "style": {
        "curveStyle": "bezier", "targetArrowShape": "triangle", "arrowScale": 0.8,
        "content": "", "fontSize": "10px", "fontWeight": 600,
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
    # 聚焦交互：其余隐去（柔和退后），但绝不退化成纯圆点（保持花/果/叶真实植物轮廓）
    {"selector": ".faded", "style": {"opacity": 0.32, "underlayOpacity": 0}},
    {"selector": "edge.faded", "style": {"opacity": 0.18}},
    {"selector": ".highlighted", "style": {
        "underlayOpacity": 0.35, "underlayColor": "#65f6b5", "underlayPadding": 6,
        "borderWidth": 3, "borderColor": "#65f6b5", "opacity": 1.0, "zIndex": 990,
    }},
    {"selector": "node.highlighted.claim, node.highlighted.question, node.highlighted.topic", "style": {
        "content": "data(label)", "fontSize": "12px", "fontWeight": 700,
        "color": "#fff", "textOutlineColor": "#0a0a0f", "textOutlineWidth": 3,
    }},
    {"selector": "node.highlighted.source", "style": {
        "content": "",
    }},
    {"selector": "edge:selected, edge.highlighted", "style": {
        "width": 3.5, "opacity": 1, "content": "",
        "lineColor": "#ffd54f", "targetArrowColor": "#ffd54f", "zIndex": 980,
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


# ── helpers ──────────────────────────────────────────────────────────────

def _build_source_list(sources: list[SearchItem] | list[dict]) -> html.Div:
    if not sources:
        return html.Div("暂无来源", className="annotation")

    def _get_val(s, key, default=None):
        if isinstance(s, dict):
            return s.get(key, default)
        return getattr(s, key, default)

    # 排序：高赞同优先，丰富正文优先
    sorted_sources = sorted(
        sources,
        key=lambda s: (_get_val(s, "vote_up_count") or 0, len(_get_val(s, "content_text") or "")),
        reverse=True,
    )

    def _render_item(s, idx: int):
        author = _get_val(s, "author_name") or "知乎答主"
        votes = _get_val(s, "vote_up_count") or 0
        vote_badge = f"▲ {votes}" if votes > 0 else ""
        raw_time = _get_val(s, "edit_time")
        year_str = str(raw_time)[:4] if raw_time else ""
        url = str(_get_val(s, "url") or "")
        title = _get_val(s, "title") or "知乎回答"
        return html.Div(
            className="source-item-compact",
            children=[
                html.Div(className="source-item-meta", children=[
                    html.Span(f"#{idx+1}", className="source-item-index"),
                    html.Span(author, className="source-item-author"),
                    html.Span(vote_badge, className="source-item-votes") if vote_badge else None,
                    html.Span(year_str, className="source-item-year") if year_str else None,
                ]),
                html.A(
                    title,
                    href=url,
                    target="_blank",
                    className="source-item-link",
                    title=title,
                ),
            ],
        )

    # 默认精选展示 Top 6 核心高赞文献，大幅压缩高度
    featured_sources = sorted_sources[:6]
    remaining_sources = sorted_sources[6:]

    featured_items = [_render_item(s, i) for i, s in enumerate(featured_sources)]

    more_section = None
    if remaining_sources:
        remaining_items = [_render_item(s, i + 6) for i, s in enumerate(remaining_sources)]
        more_section = html.Details(
            className="source-details-expand",
            children=[
                html.Summary(
                    f"展开更多文献（余下 {len(remaining_sources)} 篇 · 点击展开/收起）▼",
                    className="source-expand-summary",
                ),
                html.Div(remaining_items, className="source-remaining-list"),
            ],
        )

    return html.Div([
        html.Div(className="source-list-header", children=[
            html.Span("知乎权威文献", className="source-header-title"),
            html.Span(f"共 {len(sources)} 篇", className="source-count-badge"),
        ]),
        html.Div(featured_items, className="source-featured-list"),
        more_section,
    ])


def _legend_swatch(color: str, extra_class: str = "") -> html.Span:
    return html.Span(className=f"legend-swatch {extra_class}".strip(),
                     style={"background": color} if color else {})


def _is_edge(el: dict) -> bool:
    d = el.get("data", {})
    return "source" in d and "target" in d


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


# ── initial showcase load & in-memory exhibition cache ────────────────────

_warmup_cache = load_warmup_topics()
_PRECOMPUTED_TOPICS: dict[str, dict] = {}
for _t in WARMUP_TOPICS:
    _asset = _warmup_cache.get(_t)
    if _asset:
        _b = _asset["bundle"]
        _s = _asset["sources"]
        _nodes, _edges = present(_b, _s)
        _elem = _nodes + _edges
        _years = sorted({_n["data"]["year"] for _n in _nodes if _n["data"].get("year")})
        _counts = _year_counts(_elem)
        _marks = {i: str(y) for i, y in enumerate(_years)}
        _marks[len(_years)] = "全部"
        _PRECOMPUTED_TOPICS[_t] = {
            "bundle": _b,
            "sources": _s,
            "elements": _elem,
            "years": _years,
            "counts": _counts,
            "marks": _marks,
            "source_list": _build_source_list(_s),
            "time_band": _build_time_band(_years, _counts, None),
            "year_axis": [html.Span(str(y)) for y in _years],
            "bundle_dump": _b.model_dump(mode="json"),
            "sources_dump": [s.model_dump(mode="json") for s in _s],
            "queries": _asset.get("queries", []),
            "btn_classes": [
                f"btn warmup-btn active" if t == _t else "btn warmup-btn"
                for t in WARMUP_TOPICS
            ],
        }

_default_topic = WARMUP_TOPICS[0] if WARMUP_TOPICS else "RAG"
_init_cached = _PRECOMPUTED_TOPICS.get(_default_topic)

if _init_cached:
    _init_bundle = _init_cached["bundle"]
    _init_sources = _init_cached["sources"]
    _init_elements = _init_cached["elements"]
    _init_source_list = _init_cached["source_list"]
    _init_bundle_store = _init_cached["bundle_dump"]
    _init_sources_store = _init_cached["sources_dump"]
    _init_run_state = {
        "run_id": None,
        "queries": _init_cached.get("queries", []),
        "topic": _default_topic,
        "status": "completed",
        "warmup": True,
    }
else:
    _init_elements = []
    _init_source_list = html.Div("暂无信源", className="annotation")
    _init_bundle_store = None
    _init_sources_store = []
    _init_run_state = {"status": "idle"}


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
                        html.Span("EXHIBITION", className="live-chip"),
                    ], className="brand-line"),
                    html.Div("ZHIHU FRONTIER AI KNOWLEDGE WORLD TREE", className="brand-sub"),
                ]),
            ]),
            html.Div(className="topbar-center", children=[
                html.Div(className="pavilion-pills", children=[
                    html.Button(
                        [
                            html.Span(f"展区 {i+1}", className="pavilion-badge"),
                            html.Span(TOPIC_ICONS.get(t, "🌱"), style={"marginRight": "4px"}),
                            html.Span(t),
                        ],
                        id=f"warmup-{i}",
                        className=f"btn warmup-btn {'active' if i == 0 else ''}",
                    )
                    for i, t in enumerate(WARMUP_TOPICS)
                ]),
            ]),
            html.Div(className="topbar-controls", children=[
                html.Div(
                    id="quota-info",
                    className="quota-info",
                    children=[
                        html.Span(f"当前展区：{_default_topic} · 378 节点全景", className="tag tag-cache"),
                    ],
                ),
                html.Button([html.Span("↓ "), "导出当前图谱"], id="btn-export", className="btn btn-secondary"),
            ]),
        ]),


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
                html.Div(className="glass-panel metrics-panel", children=[
                    html.Div([html.Span("02"), "展区生态"], className="panel-title"),
                    html.Div(className="metrics-grid", children=[
                        html.Div(className="metric-card", children=[
                            html.Span("14", className="metric-val"),
                            html.Span("问题主枝", className="metric-lbl"),
                        ]),
                        html.Div(className="metric-card", children=[
                            html.Span("42", className="metric-val"),
                            html.Span("演进观点", className="metric-lbl"),
                        ]),
                        html.Div(className="metric-card", children=[
                            html.Span("14", className="metric-val"),
                            html.Span("孕育根系", className="metric-lbl"),
                        ]),
                        html.Div(className="metric-card", children=[
                            html.Span(f"{len(_init_sources)}", className="metric-val"),
                            html.Span("知乎文献", className="metric-lbl"),
                        ]),
                    ]),
                    html.Div(id="time-band", style={"display": "none"}),
                ]),
            ]),

            # 中央画布
            html.Main(className="canvas-wrap", children=[
                html.Div(className="canvas-hud", children=[
                    html.Div("KNOWLEDGE TOPOLOGY", className="hud-kicker"),
                    html.Div("知识演化场", className="hud-title"),
                    html.Div("时间向上生长 · 观点横向分化", className="hud-sub"),
                    html.Button("🌿 退出聚焦 / 显示全景", id="btn-reset-focus", className="btn-hud-reset",
                                title="点击恢复全树视角 (快捷键: ESC / 点击画布空白)"),
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
                    elements=_init_elements,
                    stylesheet=CYTO_STYLESHEET,
                ),
                html.Div(id="year-axis", style={"display": "none"}),
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
                             children="点击树上任意节点（果实/花朵/星火/叶片）查看论据与知乎真实引文"),
                ]),
                html.Div(className="glass-panel sources-panel", children=[
                    html.Div(id="source-list", className="source-list", children=_init_source_list),
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

        dcc.Store(id="run-state", data=_init_run_state),
        dcc.Store(id="graph-bundle-store", data=_init_bundle_store),
        dcc.Store(id="sources-store", data=_init_sources_store),
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


# ── warmup topics → render the matching exhibition asset ─────────────────

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
    tid = ctx.triggered_id
    if tid:
        topic = _warmup_topic_for_trigger(tid)
        if topic:
            return topic
    for trig in (ctx.triggered or []):
        prop_id = trig.get("prop_id", "")
        cand_id = prop_id.split(".")[0]
        topic = _warmup_topic_for_trigger(cand_id)
        if topic:
            return topic
    return None


@callback(
    Output("cytoscape-graph", "elements", allow_duplicate=True),
    Output("cytoscape-graph", "layout", allow_duplicate=True),
    Output("node-detail", "children", allow_duplicate=True),
    Output("source-list", "children", allow_duplicate=True),
    Output("quota-info", "children", allow_duplicate=True),
    Output("graph-bundle-store", "data", allow_duplicate=True),
    Output("sources-store", "data", allow_duplicate=True),
    Output("run-state", "data", allow_duplicate=True),
    *[Output(f"warmup-{i}", "className") for i in range(len(WARMUP_TOPICS))],
    *_WARMUP_INPUTS,
    prevent_initial_call=True,
)
def _show_warmup(*_clicks):
    topic = _triggered_warmup_topic()
    if topic is None:
        return [no_update] * (8 + len(WARMUP_TOPICS))
    cached = _PRECOMPUTED_TOPICS.get(topic)
    if not cached:
        return [no_update] * (8 + len(WARMUP_TOPICS))
    return (
        cached["elements"],
        {"name": "preset", "fit": True, "padding": 40, "animate": True, "animationDuration": 600, "animationEasing": "ease-out"},
        "点击树上任意节点查看论据与知乎真实引文",
        cached["source_list"],
        html.Span(f"当前展区：{topic} · {len(cached['elements'])} 元素繁茂知识树", className="tag tag-cache"),
        cached["bundle_dump"],
        cached["sources_dump"],
        {
            "run_id": None,
            "queries": cached.get("queries", []),
            "topic": topic,
            "status": "completed",
            "warmup": True,
        },
        *cached["btn_classes"],
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

    node_type_names = {
        "question": "🌿 核心议题主枝",
        "claim": "🍎 观点论断果实",
        "source": "🍃 知乎专业文献绿叶",
        "event": "✨ 奠基历史深根",
        "topic": "🌳 知识世界树种子",
    }
    type_display = node_type_names.get(node_type, f"类型：{node_type}")

    header_row = html.Div(
        style={
            "display": "flex",
            "justifyContent": "space-between",
            "alignItems": "center",
            "marginBottom": "6px",
        },
        children=[
            html.Div(type_display, className="node-detail-label"),
            html.Button("✕ 退出聚焦", id="btn-unfocus-panel",
                        style={"fontSize": "10px", "padding": "2px 8px",
                               "background": "rgba(255,255,255,0.08)",
                               "border": "1px solid rgba(255,255,255,0.15)",
                               "borderRadius": "10px", "color": "#94a3b8", "cursor": "pointer"},
                        title="退出聚焦，显示完整全树"),
        ],
    )

    children = [header_row]
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
        topic = bundle_data.get("topic") if isinstance(bundle_data, dict) else None
        if topic and topic in _PRECOMPUTED_TOPICS:
            elements = _PRECOMPUTED_TOPICS[topic]["elements"]
        else:
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



# ── time playback：生长动画与时间回放（设计文档 §6.1）────────────────────

# fit=True 会重缩放视口；回放期间每 tick 都 fit 会造成持续晃动，
# 因此只有开始播放/拖动滑块时 fit，interval 逐帧生长时保持视口不动
_LAYOUT_FIT = {"name": "preset", "fit": True, "padding": 40,
               "animate": True, "animationDuration": 600, "animationEasing": "ease-out"}
_LAYOUT_NOFIT = {"name": "preset", "fit": False,
                 "animate": True, "animationDuration": 600, "animationEasing": "ease-out"}


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
    prevent_initial_call=False,
)
def _prepare_playback(bundle_data, sources_data):
    if not bundle_data:
        return [no_update] * 9
    topic = bundle_data.get("topic") if isinstance(bundle_data, dict) else None
    if topic and topic in _PRECOMPUTED_TOPICS:
        cached = _PRECOMPUTED_TOPICS[topic]
        return (
            cached["elements"],
            cached["years"],
            len(cached["years"]),
            cached["marks"],
            len(cached["years"]),
            {"playing": False, "step_idx": -1},
            True,
            cached["time_band"],
            cached["year_axis"],
        )
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
        if state.get("playing"):  # 暂停：保留当前 step_idx，停止定时器
            return no_update, no_update, {**state, "playing": False}, True, no_update
        # 播放 / 恢复播放：检查是否处于暂停位置
        cur_idx = state.get("step_idx", -1)
        if cur_idx == -1 or cur_idx >= len(steps):
            # 从一颗种子开始长：首帧只露树根。不重 fit——当前视口已是全图取景，
            # 相机不动，整棵树在同一坐标系内逐节点长出，不会有任何瞬间出现
            return (_slice_elements(elements, -1, steps), _LAYOUT_NOFIT,
                    {"playing": True, "step_idx": -1}, False,
                    _build_time_band(years, counts, years[0] - 1))
        else:
            # 暂停后继续播放：从当前暂停步继续生长，不重置到根节点
            cur_year = (step_years[cur_idx]
                        if 0 <= cur_idx < len(step_years) else None)
            return (_slice_elements(elements, cur_idx, steps), _LAYOUT_NOFIT,
                    {"playing": True, "step_idx": cur_idx}, False,
                    _build_time_band(years, counts, cur_year))

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


# ── 聚焦交互：点击节点高亮枝干/果实/绿叶脉络，保留全树花果绿意 ────────

def _strip_focus_classes(el: dict) -> dict:
    cls = " ".join(c for c in el.get("classes", "").split() if c not in ("faded", "highlighted"))
    return {**el, "classes": cls}


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
    if not nid:
        return no_update, no_update

    if (focus or {}).get("node_id") == nid:
        # 再次点击同一节点 → 取消聚焦，恢复全景
        return [_strip_focus_classes(el) for el in elements], {"node_id": None}

    node_type = node_data.get("node_type", "")

    edge_list = []
    node_map = {}
    for el in elements:
        if _is_edge(el):
            edge_list.append(el)
        else:
            node_map[el["data"]["id"]] = el["data"]

    hl_nodes = {nid}
    hl_edges = set()

    if node_type == "question" or nid.startswith("q_"):
        # 议题主枝：议题 + 中心种子 + 该议题下全部观点果实 + 各果实所属全部文献绿叶/花朵
        claims = set()
        for el in elements:
            if not _is_edge(el):
                d = el["data"]
                if d.get("node_type") == "claim" and d.get("question_id") == nid:
                    claims.add(d["id"])
        for e in edge_list:
            d = e["data"]
            if d["source"] == nid and d["target"] in node_map and node_map[d["target"]].get("node_type") == "claim":
                claims.add(d["target"])
            elif d["target"] == nid and d["source"] in node_map and node_map[d["source"]].get("node_type") == "claim":
                claims.add(d["source"])

        sources = set()
        for e in edge_list:
            d = e["data"]
            if d["source"] in claims and d["target"] in node_map and node_map[d["target"]].get("node_type") == "source":
                sources.add(d["target"])
            elif d["target"] in claims and d["source"] in node_map and node_map[d["source"]].get("node_type") == "source":
                sources.add(d["source"])

        # 关联中心主题
        for e in edge_list:
            d = e["data"]
            if (d["source"] == nid and d["target"].startswith("topic:")) or (d["target"] == nid and d["source"].startswith("topic:")):
                hl_nodes.add(d["source"] if d["source"].startswith("topic:") else d["target"])

        hl_nodes.update(claims)
        hl_nodes.update(sources)

        for e in edge_list:
            d = e["data"]
            if d["source"] in hl_nodes and d["target"] in hl_nodes:
                hl_edges.add(d.get("id"))

    elif node_type == "claim" or nid.startswith("c_"):
        # 观点果实：果实 + 所属主枝 + 所引文献绿叶 + 认知关系(支持/反驳/演化)相连的果实
        parent_q = node_data.get("question_id")
        if parent_q:
            hl_nodes.add(parent_q)

        for e in edge_list:
            d = e["data"]
            if d["source"] == nid:
                hl_nodes.add(d["target"])
                hl_edges.add(d.get("id"))
            elif d["target"] == nid:
                hl_nodes.add(d["source"])
                hl_edges.add(d.get("id"))

    elif node_type == "source" or nid.startswith("source:") or nid.startswith("zhihu:"):
        # 文献绿叶：绿叶 + 引用该文献的果实 + 所属主枝
        citing_claims = set()
        for e in edge_list:
            d = e["data"]
            if d["source"] == nid:
                citing_claims.add(d["target"])
                hl_edges.add(d.get("id"))
            elif d["target"] == nid:
                citing_claims.add(d["source"])
                hl_edges.add(d.get("id"))
        hl_nodes.update(citing_claims)
        for cid in citing_claims:
            c_data = node_map.get(cid, {})
            if c_data.get("question_id"):
                hl_nodes.add(c_data["question_id"])

    elif node_type == "event" or nid.startswith("e_"):
        # 历史深根：深根 + 中心种子 + 演化指向的观点
        for e in edge_list:
            d = e["data"]
            if d["source"] == nid:
                hl_nodes.add(d["target"])
                hl_edges.add(d.get("id"))
            elif d["target"] == nid:
                hl_nodes.add(d["source"])
                hl_edges.add(d.get("id"))

    elif node_type == "topic" or nid.startswith("topic:"):
        # 中心种子：显示全景
        return [_strip(el) for el in elements], {"node_id": None}

    else:
        for e in edge_list:
            d = e["data"]
            if d["source"] == nid:
                hl_nodes.add(d["target"])
                hl_edges.add(d.get("id"))
            elif d["target"] == nid:
                hl_nodes.add(d["source"])
                hl_edges.add(d.get("id"))

    # 聚焦交互：聚焦子图赋予高光（highlighted），其余柔和退隐（faded），绝不退化成纯圆点
    out = []
    for el in elements:
        base = _strip_focus_classes(el)
        if _is_edge(el):
            eid = el["data"].get("id")
            is_hl = eid in hl_edges or (el["data"]["source"] in hl_nodes and el["data"]["target"] in hl_nodes)
            if is_hl:
                base["classes"] = (base.get("classes", "") + " highlighted").strip()
            else:
                base["classes"] = (base.get("classes", "") + " faded").strip()
        else:
            nid_el = el["data"].get("id")
            if nid_el in hl_nodes:
                base["classes"] = (base.get("classes", "") + " highlighted").strip()
            else:
                base["classes"] = (base.get("classes", "") + " faded").strip()
        out.append(base)

    return out, {"node_id": nid}


@callback(
    Output("cytoscape-graph", "elements", allow_duplicate=True),
    Output("focus-store", "data", allow_duplicate=True),
    Output("node-detail", "children", allow_duplicate=True),
    Input("btn-esc", "n_clicks"),
    Input("btn-reset-focus", "n_clicks"),
    Input("btn-unfocus-panel", "n_clicks"),
    State("cytoscape-graph", "elements"),
    State("focus-store", "data"),
    prevent_initial_call=True,
)
def _esc_unfocus(_n1, _n2, _n3, elements, focus):
    """多通道退出聚焦：ESC 按键、画布全景重置按钮、右面板退出按钮、画布空白点击。"""
    if not elements:
        return no_update, no_update, no_update
    out = [_strip_focus_classes(el) for el in elements]
    default_hint = "点击树上任意节点查看论据与知乎真实引文"
    return out, {"node_id": None}, default_hint


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
