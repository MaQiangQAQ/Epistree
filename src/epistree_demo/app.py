"""Epistree Demo — Dash application entry point.

Single page: input → query preview → search → extract → knowledge world tree.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

import dash
import dash_cytoscape as cyto
from dash import Input, Output, State, callback, ctx, dcc, html, no_update

from .config import settings
from .models import GraphBundle, SearchItem
from .service import DemoService
from .presenter import present
from .warmup import load_warmup_topics, get_warmup_topics_list

# ── app init ──────────────────────────────────────────────────────────────

app = dash.Dash(
    __name__,
    title="Epistree",
    assets_folder=os.path.join(os.path.dirname(__file__), "assets"),
    suppress_callback_exceptions=True,
)

server = app.server

# Warmup topics — loaded from DATA_DIR
WARMUP_TOPICS = get_warmup_topics_list()

# ── service (lazy singleton) ──────────────────────────────────────────────

_service: DemoService | None = None


def get_service() -> DemoService:
    global _service
    if _service is None:
        _service = DemoService()
    return _service


# ── layout ───────────────────────────────────────────────────────────────

app.layout = html.Div(
    className="container",
    children=[
        html.Div(className="header", children=[
            html.H1("Epistree"),
            html.Span("知识世界树 Demo", style={"color": "#666", "fontSize": "14px"}),
        ]),

        html.Div(id="quota-info", className="stats-row"),

        html.Div(className="input-row", children=[
            dcc.Input(
                id="topic-input",
                type="text",
                placeholder="输入主题（如：大模型微调）",
                style={"width": "300px", "padding": "6px 10px", "borderRadius": "6px", "border": "1px solid #ccc"},
                maxLength=50,
            ),
            html.Button("生成查询", id="btn-build-queries", className="btn btn-primary"),
            html.Button("生成世界树", id="btn-generate", className="btn btn-primary", disabled=True),
            html.Button("导出 JSON", id="btn-export", className="btn btn-secondary"),
        ]),

        html.Div(className="input-row", children=[
            html.Span("预热主题：", style={"fontWeight": 600}),
            *[html.Button(t, id=f"warmup-{i}", className="btn warmup-btn") for i, t in enumerate(WARMUP_TOPICS)],
        ]),

        html.Div(id="query-list", className="query-list"),

        html.Div(id="progress-area", style={"display": "none"}),

        html.Div(className="graph-area", children=[
            cyto.Cytoscape(
                id="cytoscape-graph",
                className="cytoscape-container",
                layout={"name": "breadthfirst"},
                style={"width": "100%", "height": "500px"},
                elements=[],
                stylesheet=[
                    {"selector": "node", "style": {"content": "data(label)", "fontSize": "11px", "textValign": "center", "textWrap": "wrap", "textMaxWidth": "120px"}},
                    {"selector": ".topic", "style": {"backgroundColor": "#2e7d32", "borderColor": "#1b5e20", "shape": "ellipse", "width": 60, "height": 60, "color": "#fff"}},
                    {"selector": ".question", "style": {"backgroundColor": "#1565c0", "borderColor": "#0d47a1", "shape": "round-rectangle", "width": 100, "height": 40, "color": "#fff"}},
                    {"selector": ".claim", "style": {"backgroundColor": "#7b1fa2", "borderColor": "#4a148c", "shape": "ellipse", "width": 80, "height": 35, "color": "#fff"}},
                    {"selector": ".event", "style": {"backgroundColor": "#e65100", "borderColor": "#bf360c", "shape": "diamond", "width": 60, "height": 60, "color": "#fff"}},
                    {"selector": ".source", "style": {"backgroundColor": "#757575", "borderColor": "#424242", "shape": "rectangle", "width": 80, "height": 30, "color": "#fff"}},
                    {"selector": "edge", "style": {"width": 2, "curveStyle": "bezier", "targetArrowShape": "triangle", "targetArrowColor": "#888", "lineColor": "#888", "content": "data(label)", "fontSize": "10px", "textRotation": "autorotate"}},
                    {"selector": ".dashed", "style": {"lineStyle": "dashed", "lineColor": "#e65100", "targetArrowColor": "#e65100"}},
                    {"selector": ".solid", "style": {"lineStyle": "solid", "lineColor": "#666", "targetArrowColor": "#666"}},
                ],
            ),
            html.Div(id="node-detail", className="node-detail"),
        ]),

        html.Div(id="source-list", className="source-list"),

        dcc.Store(id="run-state", data={"run_id": None, "queries": [], "topic": "", "status": "idle"}),
        dcc.Store(id="graph-bundle-store", data=None),
        dcc.Store(id="sources-store", data=None),
        dcc.Store(id="progress-store", data={"step": "", "progress": 0, "status": "idle"}),
        dcc.Interval(id="progress-interval", interval=500, disabled=True),
    ],
)


# ── warmup topics → fill input ──────────────────────────────────────────

for i, topic in enumerate(WARMUP_TOPICS):
    @callback(
        Output("topic-input", "value"),
        Input(f"warmup-{i}", "n_clicks"),
        prevent_initial_call=True,
    )
    def _fill_topic(n, topic=topic):
        return topic


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
                    id={"type": "query-check", "index": q},
                    style={"marginRight": "4px"},
                ),
                dcc.Input(
                    value=q,
                    style={"flex": 1, "padding": "4px 8px", "border": "1px solid #ddd", "borderRadius": "4px"},
                    id={"type": "query-input", "index": q},
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
    State("run-state", "data"),
    State("topic-input", "value"),
    prevent_initial_call=True,
)
def _generate(n, run_state, topic):
    if not topic or len(topic.strip()) < 2:
        return [no_update] * 8

    topic = topic.strip()
    svc = get_service()

    try:
        # Create run
        run_id = svc.create_run(topic)

        # Get queries from run_state or build fresh
        queries = run_state.get("queries", [])
        if not queries:
            queries = svc.build_queries(topic)

        # Search
        svc.db.update_run_status(run_id, "running")
        selected_sources, stats = svc.execute_search(run_id, queries)

        if len(selected_sources) < 3:
            run_status = "failed"
            svc.fail_run(run_id, "INSUFFICIENT_SOURCES",
                         f"仅找到 {len(selected_sources)} 条唯一来源，需要至少 3 条")
            quota_info = html.Div([
                html.Span(f"⚠ 来源不足：{len(selected_sources)} 条唯一来源"),
            ])
            return [], "", "", quota_info, None, None, {**run_state, "status": run_status}, True

        # Extract knowledge
        bundle = svc.extract_knowledge(topic, selected_sources)

        if not bundle.claims:
            svc.fail_run(run_id, "NO_CLAIMS", "模型未提取到任何 Claim")
            quota_info = html.Div([
                html.Span(f"⚠ 模型未能提取 Claim（{len(bundle.questions)} 个问题）"),
            ])
            return [], "", "", quota_info, None, None, {**run_state, "status": "failed"}, True

        # Complete run
        svc.complete_run(run_id, bundle, stats)

        # Present
        nodes, edges = present(bundle, selected_sources)
        elements = nodes + edges

        detail_html = "点击节点查看详情"
        source_html = _build_source_list(selected_sources)
        quota_info = _build_quota_info(stats)

        run_state = {**run_state, "status": "completed"}

        return (
            elements, detail_html, source_html, quota_info,
            bundle.model_dump(mode="json"),
            [s.model_dump(mode="json") for s in selected_sources],
            run_state, False,
        )

    except PermissionError:
        svc.fail_run(run_id := "", "AUTH_REQUIRED", "知乎 Access Secret 未配置")
        return (
            [],
            html.Div("❌ 知乎 API 认证失败。请配置 ZHIHU_ACCESS_SECRET。",
                     style={"color": "#c62828", "padding": "16px"}),
            "", "",
            None, None,
            {**run_state, "status": "failed"}, True,
        )
    except RuntimeError as e:
        error_msg = str(e)
        if "MODEL_VALIDATION_FAILED" in error_msg:
            svc.fail_run(run_id := "", "MODEL_VALIDATION_FAILED", error_msg)
            return (
                [], html.Div(f"⚠ 模型输出验证失败，请稍后重试。", style={"color": "#e65100", "padding": "16px"}),
                "", "", None, None, {**run_state, "status": "failed"}, True,
            )
        raise


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
        children.append(html.Div(
            [html.Span(f"{r.get('source_id', '?')} ", style={"fontSize": "11px", "color": "#1565c0"}) for r in source_refs]
        ))

    children.append(html.Div("AI 提取，请查看来源", className="annotation", style={"marginTop": "12px"}))
    return children


# ── export JSON ──────────────────────────────────────────────────────────

@callback(
    Output("btn-export", "href"),
    Output("btn-export", "download"),
    Input("btn-export", "n_clicks"),
    State("graph-bundle-store", "data"),
    prevent_initial_call=True,
)
def _export_json(n, bundle_data):
    if not bundle_data:
        return no_update, no_update
    import base64
    data_str = json.dumps(bundle_data, ensure_ascii=False, indent=2)
    encoded = base64.b64encode(data_str.encode("utf-8")).decode("utf-8")
    return f"data:application/json;base64,{encoded}", "epistree_graph.json"


# ── layout switch on topic click ────────────────────────────────────────

@callback(
    Output("cytoscape-graph", "layout"),
    Input("cytoscape-graph", "tapNodeData"),
    State("cytoscape-graph", "layout"),
)
def _maybe_switch_layout(node_data, current_layout):
    if node_data and node_data.get("node_type") == "topic":
        return {"name": "breadthfirst", "roots": f"#{node_data['id']}"}
    return no_update


# ── helpers ──────────────────────────────────────────────────────────────

def _build_source_list(sources: list[SearchItem]) -> html.Div:
    if not sources:
        return html.Div("暂无来源", className="annotation")

    items = []
    for s in sources:
        items.append(html.Div([
            html.A(s.author_name or s.title, href=str(s.url), target="_blank"),
            html.Span(f" · {s.title[:80]}", style={"color": "#666", "fontSize": "12px"}),
        ], style={"padding": "4px 0", "borderBottom": "1px solid #f0f0f0"}))

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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    debug = os.environ.get("DASH_DEBUG", "0") == "1"
    app.run(debug=debug, port=port, host="0.0.0.0")
