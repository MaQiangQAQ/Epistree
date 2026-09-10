"""CytoscapePresenter — domain objects → Dash Cytoscape elements.

Matches section 5.6 of DEMO_DESIGN.md, extended with the visual-grammar
semantics of docs/EPISTREE_FRONTEND_DESIGN.md §5:

  - node state classes: sprout (新芽) / withered (枯枝) / consensus (共识)
  - data.evidence_count → node size (证据数 = 影响力)
  - data.year → time axis layout (纵向 = 时间) and playback slicing
"""

from __future__ import annotations

from .models import (
    GraphBundle,
    SearchItem,
)


def present(bundle: GraphBundle, sources: list[SearchItem]) -> tuple[list[dict], list[dict]]:
    """Convert GraphBundle + sources to Cytoscape nodes and edges.

    Returns (nodes, edges) lists suitable for Dash Cytoscape `elements`.
    """
    source_map = {s.source_id: s for s in sources}
    source_year = {sid: (s.edit_time.year if s.edit_time else None)
                   for sid, s in source_map.items()}
    nodes: list[dict] = []
    edges: list[dict] = []
    node_ids: set[str] = set()

    # ── relation-derived state (computed up front, on original ids) ──────
    supports_in: dict[str, int] = {}
    contradicted: set[str] = set()
    superseded: set[str] = set()
    evolved_targets: set[str] = set()
    for r in bundle.relations:
        if r.relation_type == "supports":
            supports_in[r.target_node_id] = supports_in.get(r.target_node_id, 0) + 1
        elif r.relation_type == "contradicts":
            contradicted.add(r.target_node_id)
        elif r.relation_type == "evolves_into":
            superseded.add(r.source_node_id)
            evolved_targets.add(r.target_node_id)

    def _refs_year(refs) -> int | None:
        years = [source_year.get(r.source_id) for r in refs]
        years = [y for y in years if y]
        return max(years) if years else None

    def _claim_state(c) -> str:
        """Visual state class: withered > consensus > sprout (design doc §5.2)."""
        if c.id in contradicted or c.id in superseded:
            return "withered"
        if supports_in.get(c.id, 0) >= 2:
            return "consensus"
        if c.id in evolved_targets:
            return "sprout"
        return ""

    # Topic node
    topic_id = f"topic:{_safe_id(bundle.topic)}"
    nodes.append({
        "data": {
            "id": topic_id,
            "label": bundle.topic[:40],
            "node_type": "topic",
            "full_text": bundle.topic,
        },
        "classes": "topic",
    })
    node_ids.add(topic_id)

    # Question nodes
    for q in bundle.questions:
        qid = _ensure_id(q.id, "question", node_ids)
        nodes.append({
            "data": {
                "id": qid,
                "label": q.text[:30],
                "node_type": "question",
                "full_text": q.text,
                "year": _refs_year(q.source_refs),
                "evidence_count": len(q.source_refs),
                "source_refs": [r.model_dump() for r in q.source_refs],
            },
            "classes": "question",
        })
        edges.append({
            "data": {
                "id": f"e:{qid}->{topic_id}",
                "source": qid,
                "target": topic_id,
                "label": "answers",
                "edge_type": "contains",
            },
            "classes": "solid trunk",
        })

    # Claim nodes
    claim_id_map: dict[str, str] = {}
    for c in bundle.claims:
        cid = _ensure_id(c.id, "claim", node_ids)
        claim_id_map[c.id] = cid
        state = _claim_state(c)
        nodes.append({
            "data": {
                "id": cid,
                "label": c.text[:16],
                "node_type": "claim",
                "full_text": c.text,
                "confidence": c.confidence,
                "year": _refs_year(c.source_refs),
                "evidence_count": len(c.source_refs),
                "source_refs": [r.model_dump() for r in c.source_refs],
            },
            "classes": f"claim {state}".strip(),
        })
        # Edge: Claim -> Question
        qid_target = f"question:{_safe_id(c.question_id)}"
        if qid_target in node_ids:
            edges.append({
                "data": {
                    "id": f"e:{cid}->{qid_target}",
                    "source": cid,
                    "target": qid_target,
                    "label": "contains",
                    "edge_type": "contains",
                },
                "classes": "solid branch",
            })

    # Event nodes
    for e in bundle.events:
        eid = _ensure_id(e.id, "event", node_ids)
        year = None
        if e.occurred_at:
            try:
                year = int(str(e.occurred_at)[:4])
            except ValueError:
                year = None
        nodes.append({
            "data": {
                "id": eid,
                "label": f"{e.text[:24]} · {e.occurred_at or '时间不详'}",
                "node_type": "event",
                "full_text": e.text,
                "occurred_at": e.occurred_at or "",
                "confidence": e.confidence,
                "year": year or _refs_year(e.source_refs),
                "evidence_count": len(e.source_refs),
                "source_refs": [r.model_dump() for r in e.source_refs],
            },
            "classes": "event",
        })
        # Event -> Topic
        edges.append({
            "data": {
                "id": f"e:{eid}->{topic_id}",
                "source": eid,
                "target": topic_id,
                "label": "mentioned_in",
                "edge_type": "contains",
            },
            "classes": "solid trunk",
        })

    # Candidate relations (edges between claims)
    _REL_LABEL = {"supports": "支持", "contradicts": "反驳", "evolves_into": "演化为"}
    for r in bundle.relations:
        src = claim_id_map.get(r.source_node_id)
        tgt = claim_id_map.get(r.target_node_id)
        if src and tgt:
            edges.append({
                "data": {
                    "id": f"e:{r.id}",
                    "source": src,
                    "target": tgt,
                    "label": _REL_LABEL.get(r.relation_type, r.relation_type),
                    "edge_type": r.relation_type,
                    "confidence": r.confidence,
                    "source_refs": [s.model_dump() for s in r.source_refs],
                },
                "classes": f"dashed rel-{r.relation_type}",
            })

    # Source nodes are evidence objects. Link each source to the concrete
    # knowledge nodes/relations that cite it; do not imply every source
    # supports the topic merely because it was returned by search.
    seen_source_ids = _collect_all_source_ids(bundle)
    for sid in seen_source_ids:
        src = source_map.get(sid)
        if not src:
            continue
        sid_clean = _safe_id(sid)
        snid = f"source:{sid_clean}"
        if snid in node_ids:
            continue
        node_ids.add(snid)
        title = src.title or src.author_name or sid[:20]
        nodes.append({
            "data": {
                "id": snid,
                "label": title[:16],
                "node_type": "source",
                "full_text": src.content_text[:300],
                "url": str(src.url),
                "author_name": src.author_name,
                "edit_time": src.edit_time.isoformat() if src.edit_time else None,
                "year": src.edit_time.year if src.edit_time else None,
                "source_id": sid,
            },
            "classes": "source",
        })
        cited_nodes = []
        for n in nodes:
            refs = n["data"].get("source_refs", [])
            if any(ref.get("source_id") == sid for ref in refs):
                cited_nodes.append(n["data"]["id"])
        for target in cited_nodes:
            edges.append({
                "data": {"id": f"e:{snid}->{target}", "source": snid, "target": target,
                         "label": "evidence", "edge_type": "evidence", "source_id": sid},
                "classes": "solid evidence",
            })

    _assign_positions(nodes, edges)
    return nodes, edges


# ── 布局：有机树形 ──────────────────────────────────────────────────────
# 调研结论（OneZoom natural_pre_calc.js / Gource dirnode.cpp）：
# 真树感 = ①分叉角由子树权重驱动（非等分）②枝粗按达·芬奇规则守恒衰减
# ③S 形弯枝（stylesheet 的 unbundled-bezier 承担）④固定种子抖动破对称

_TRUNK_LEN = 230.0   # 树干基准长度
_DECAY = 0.80        # 每级枝条长度衰减
_YEAR_LEN = 65.0     # 每跨一年枝条加长（纵向=时间）
_SEED = 20260909     # 固定种子：每次渲染树形一致


def _assign_positions(nodes: list[dict], edges: list[dict]) -> None:
    """Attach organic tree positions to every node, in place.

    Topic 为树根（底部中央），Question 为主枝，Claim 为分枝，Event 挂在
    树干低处，Source 为末梢小叶。分叉角按子树权重「中心外扩」分配（重者
    继承主干方向），枝长按深度衰减并随年份差加长（纵向=时间）。
    同时给每条树边写入 data.w（枝粗，达·芬奇 β=2.2 守恒）和弯曲方向
    class（bend-left/right，stylesheet 转成 S 形贝塞尔）。
    """
    import math
    import random

    rng = random.Random(_SEED)
    by_id = {n["data"]["id"]: n for n in nodes}
    years = [n["data"].get("year") for n in nodes if n["data"].get("year")]
    y_min = min(years) if years else 0

    children: dict[str, list[str]] = {}
    edge_of: dict[tuple[str, str], dict] = {}
    attached_sources: set[str] = set()
    for e in edges:
        d = e["data"]
        et = d.get("edge_type")
        if et == "contains":
            children.setdefault(d["target"], []).append(d["source"])
            edge_of[(d["source"], d["target"])] = e
        elif et == "evidence" and d["source"] not in attached_sources:
            # Source 叶子只长在其首个引用节点上
            attached_sources.add(d["source"])
            children.setdefault(d["target"], []).append(d["source"])
            edge_of[(d["source"], d["target"])] = e

    def _weight(nid: str, _memo: dict[str, float] = {}) -> float:
        if nid not in _memo:
            base = {"source": 0.6, "event": 0.8}.get(by_id[nid]["data"]["node_type"], 1.0)
            _memo[nid] = base + sum(_weight(c) for c in children.get(nid, []))
        return _memo[nid]

    def _width(nid: str, _memo: dict[str, float] = {}) -> float:
        if nid not in _memo:
            kids = children.get(nid, [])
            _memo[nid] = 1.6 if not kids else max(
                1.6, sum(_width(c) ** 2.2 for c in kids) ** (1 / 2.2))
        return _memo[nid]

    def _grow_children(nid: str, origin: tuple[float, float], angle: float,
                       depth: int) -> None:
        kids = children.get(nid, [])
        if not kids:
            return
        n = len(kids)
        spread = min(0.32 * n, 1.2) if depth == 0 else min(0.36 * n, 2.4)
        offs = [0.0] if n == 1 else [
            -spread / 2 + spread * i / (n - 1) for i in range(n)]
        center_out = sorted(range(n), key=lambda i: (abs(offs[i]), i))
        for rank, kid in enumerate(sorted(kids, key=lambda k: (-_weight(k), k))):
            off = offs[center_out[rank]] + rng.gauss(0, 0.045)
            kid_year = by_id[kid]["data"].get("year")
            ln = (_TRUNK_LEN * (_DECAY ** depth)
                  + ((kid_year - y_min) * _YEAR_LEN if kid_year else 30)
                  + rng.uniform(-14, 14))
            # 同层枝条径向交错长短，填满树冠避免挤在同一圆弧上
            ln *= 1 + 0.18 * ((rank % 3) - 1)
            ntype = by_id[kid]["data"]["node_type"]
            if ntype == "source":
                ln *= 0.38
            elif ntype == "event":
                ln *= 0.62
            x = origin[0] + math.sin(angle + off) * ln
            y = origin[1] - math.cos(angle + off) * ln  # 屏幕 y 向下，树向上长
            by_id[kid]["position"] = {"x": x, "y": y}
            e = edge_of.get((kid, nid))
            if e is not None:
                e["data"]["w"] = round(min(12.0, _width(kid) * 1.9), 2)
                bend = "bend-left" if off < -0.02 else (
                    "bend-right" if off > 0.02 else "bend-straight")
                e["classes"] = (e.get("classes", "") + " " + bend).strip()
            _grow_children(kid, (x, y), angle + off, depth + 1)

    placed: set[str] = set()
    for root in nodes:
        if root["data"]["node_type"] == "topic":
            root["position"] = {"x": 0.0, "y": 0.0}
            placed.add(root["data"]["id"])
            _grow_children(root["data"]["id"], (0.0, 0.0), 0.0, 0)
            placed.update(_all_descendants(children, root["data"]["id"]))

    # 碰撞消解：过近节点相互推开（主要推开，纵向轻推保持时间层次）
    placed_nodes = [n for n in nodes
                    if "position" in n and n["data"]["node_type"] != "topic"]
    for _ in range(3):
        moved = False
        for i, a in enumerate(placed_nodes):
            for b in placed_nodes[i + 1:]:
                dx = b["position"]["x"] - a["position"]["x"]
                dy = b["position"]["y"] - a["position"]["y"]
                dist = math.hypot(dx, dy)
                if 0.1 < dist < 78:
                    push = (78 - dist) / 2 * 0.7
                    ux, uy = dx / dist, dy / dist
                    a["position"]["x"] -= ux * push
                    a["position"]["y"] -= uy * push * 0.4
                    b["position"]["x"] += ux * push
                    b["position"]["y"] += uy * push * 0.4
                    moved = True
        if not moved:
            break

    # 未挂到树上的孤儿节点：排在树根下方，不参与分叉
    orphans = [n for n in nodes if n["data"]["id"] not in placed]
    for i, n in enumerate(orphans):
        n["position"] = {"x": (i - (len(orphans) - 1) / 2) * 130.0, "y": 180.0}

    _assign_label_classes(nodes)


def _all_descendants(children: dict[str, list[str]], nid: str) -> set[str]:
    out: set[str] = set()
    stack = list(children.get(nid, []))
    while stack:
        cur = stack.pop()
        if cur in out:
            continue
        out.add(cur)
        stack.extend(children.get(cur, []))
    return out


# ── 标签放置：地图学 8 方位 + Imhof 优先级 + 模拟退火（d3-labeler 算法）──
# 调研结论：Cytoscape.js 无内置标签避让（issue #2872 仍 open），只能在
# Python 端预算方位、编码为 class。能量函数 = 标签互叠面积 + 压节点罚 +
# 方位偏好罚（右>左>下>上>四角，避免压住上方父枝）。

_LAB_FONT = {"question": 13, "event": 12, "claim": 10, "source": 8}
_LAB_NODE_R = {"topic": 55, "question": 34, "claim": 44, "event": 30, "source": 10}
_LAB_WRAP_W = {"question": 110, "event": 110}   # 仅问题/事件标签折行
_LAB_CANDS = ("lab-r", "lab-l", "lab-b", "lab-t", "lab-br", "lab-bl", "lab-tr", "lab-tl")
_LAB_PREF = {"lab-r": 0, "lab-l": 1, "lab-b": 2, "lab-t": 3,
             "lab-br": 4, "lab-bl": 4, "lab-tr": 5, "lab-tl": 5}


def _est_text_box(label: str, fs: float, wrap_w: float | None) -> tuple[float, float]:
    """估算标签 AABB 尺寸：CJK 全角≈fs，ASCII≈0.55fs；可折行时按宽度换行。"""
    import math as _m
    w = sum(1.0 if ord(ch) > 0x2E7F else 0.55 for ch in label) * fs
    if wrap_w and w > wrap_w:
        lines = _m.ceil(w / wrap_w)
        return wrap_w, lines * fs * 1.35
    return w, fs * 1.35


def _assign_label_classes(nodes: list[dict]) -> None:
    """为每个节点选一个标签方位 class，最小化重叠。固定种子可复现。"""
    import math
    import random

    items = [n for n in nodes
             if n["data"]["node_type"] in _LAB_FONT and "position" in n]
    if not items:
        return

    # 障碍物：所有节点的占位方块（含无标签的 topic）
    obstacles = []
    for n in nodes:
        if "position" not in n:
            continue
        r = _LAB_NODE_R.get(n["data"]["node_type"], 30)
        x, y = n["position"]["x"], n["position"]["y"]
        obstacles.append((x - r, y - r, x + r, y + r))

    # 每个节点的 8 个候选方位 AABB
    cand_boxes: list[list[tuple[float, float, float, float]]] = []
    for n in items:
        d = n["data"]
        x, y = n["position"]["x"], n["position"]["y"]
        r = _LAB_NODE_R[d["node_type"]]
        w, h = _est_text_box(d["label"], _LAB_FONT[d["node_type"]],
                             _LAB_WRAP_W.get(d["node_type"]))
        m = 8.0
        boxes = {
            "lab-r": (x + r + m, y - h / 2, x + r + m + w, y + h / 2),
            "lab-l": (x - r - m - w, y - h / 2, x - r - m, y + h / 2),
            "lab-b": (x - w / 2, y + r + m, x + w / 2, y + r + m + h),
            "lab-t": (x - w / 2, y - r - m - h, x + w / 2, y - r - m),
            "lab-br": (x + r * .7 + m, y + r * .7 + m, x + r * .7 + m + w, y + r * .7 + m + h),
            "lab-bl": (x - r * .7 - m - w, y + r * .7 + m, x - r * .7 - m, y + r * .7 + m + h),
            "lab-tr": (x + r * .7 + m, y - r * .7 - m - h, x + r * .7 + m + w, y - r * .7 - m),
            "lab-tl": (x - r * .7 - m - w, y - r * .7 - m - h, x - r * .7 - m, y - r * .7 - m),
        }
        cand_boxes.append([boxes[c] for c in _LAB_CANDS])

    def _overlap(a, b) -> float:
        ox = min(a[2], b[2]) - max(a[0], b[0])
        oy = min(a[3], b[3]) - max(a[1], b[1])
        return ox * oy if ox > 0 and oy > 0 else 0.0

    def _energy(assign: list[int]) -> float:
        e = 0.0
        boxes = [cand_boxes[i][c] for i, c in enumerate(assign)]
        for i in range(len(boxes)):
            e += _LAB_PREF[_LAB_CANDS[assign[i]]] * 20.0
            for ob in obstacles:
                if _overlap(boxes[i], ob) > 0:
                    e += 30.0
            for j in range(i + 1, len(boxes)):
                e += _overlap(boxes[i], boxes[j]) * 0.5
        return e

    n = len(items)
    assign = [0] * n  # 初始全部 lab-r（Imhof 最优方位）
    best, best_e = list(assign), _energy(assign)
    rng = random.Random(_SEED + 1)
    temp = 50.0
    cur_e = best_e
    for _ in range(1500):
        i = rng.randrange(n)
        old = assign[i]
        cand = rng.randrange(len(_LAB_CANDS))
        if cand == old:
            continue
        assign[i] = cand
        e = _energy(assign)
        if e < cur_e or rng.random() < math.exp(-(e - cur_e) / max(temp, 1e-6)):
            cur_e = e
            if e < best_e:
                best, best_e = list(assign), e
        else:
            assign[i] = old
        temp *= 0.995

    for n, c in zip(items, best):
        n["classes"] = (n.get("classes", "") + " " + _LAB_CANDS[c]).strip()




# ── helpers ───────────────────────────────────────────────────────────────

def _safe_id(text: str) -> str:
    """Produce a Cytoscape-safe ID from arbitrary text."""
    import hashlib
    if not text:
        return "unknown"
    if len(text) < 64 and all(c.isalnum() or c in "-_" for c in text):
        return text
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]


def _ensure_id(original_id: str, prefix: str, existing: set[str]) -> str:
    candidate = f"{prefix}:{_safe_id(original_id)}"
    if candidate not in existing:
        existing.add(candidate)
        return candidate
    # collision rarely happens, but handle it
    for i in range(100):
        candidate = f"{prefix}:{_safe_id(original_id)}_{i}"
        if candidate not in existing:
            existing.add(candidate)
            return candidate
    return candidate  # fallback


def _collect_all_source_ids(bundle: GraphBundle) -> set[str]:
    ids: set[str] = set()
    for q in bundle.questions:
        for r in q.source_refs:
            ids.add(r.source_id)
    for c in bundle.claims:
        for r in c.source_refs:
            ids.add(r.source_id)
    for e in bundle.events:
        for r in e.source_refs:
            ids.add(r.source_id)
    for r in bundle.relations:
        for sr in r.source_refs:
            ids.add(sr.source_id)
    return ids
