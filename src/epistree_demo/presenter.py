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
        q_label = q.text.split("：")[0][:18] if "：" in q.text else (q.text.split(":")[0][:18] if ":" in q.text else q.text[:18])
        nodes.append({
            "data": {
                "id": qid,
                "label": q_label,
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
            "classes": "solid root",
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
    """Attach towering giant tree positions to every node, in place.

    - Topic 为地表树基 (0, 0)。
    - Event 为地底历史根系 (y > 0 向下 140° 扇形深扎，形成根深蒂固历史底蕴)。
    - Trunk 为垂直拔地而起的核心主干 (y: 0 -> -850)。
    - Question 主枝不再在原点扎堆，而是沿主干不同高度错落向左右两侧宽幅舒展 (140°~160° 宽幅树冠)。
    - Claim 分枝沿各 Question 展开，形成二级次级枝桠。
    - Source 叶片簇生于 Claim/Question 末梢，形成茂密繁盛的树冠绿叶。
    - 达·芬奇枝粗守恒衰减 + S 形贝塞尔弯曲类名 + 模拟退火标签避让。
    """
    import math
    import random

    rng = random.Random(_SEED)
    by_id = {n["data"]["id"]: n for n in nodes}
    edge_by_ends = {(e["data"]["source"], e["data"]["target"]): e for e in edges}

    # Locate Topic root
    topic_node = next((n for n in nodes if n["data"]["node_type"] == "topic"), None)
    topic_id = topic_node["data"]["id"] if topic_node else "topic:root"
    if topic_node:
        topic_node["position"] = {"x": 0.0, "y": 0.0}

    # 1. 地底历史根系：Events 向下深入地底 (y > 0)
    event_nodes = [n for n in nodes if n["data"]["node_type"] == "event"]
    num_events = len(event_nodes)
    for j, enode in enumerate(event_nodes):
        t_root = j / max(1, num_events - 1)
        # 向下扇形 (115° 到 245°，指向土壤地底)
        root_angle = math.pi - 1.15 + t_root * 2.3 + rng.gauss(0, 0.03)
        root_r = 160.0 + (j % 3) * 45.0 + rng.uniform(-10, 10)
        rx = math.sin(root_angle) * root_r
        ry = -math.cos(root_angle) * root_r  # cos < 0 => ry > 0 (地底下)
        enode["position"] = {"x": round(rx, 1), "y": round(ry, 1)}
        e = edge_by_ends.get((enode["data"]["id"], topic_id))
        if e:
            e["data"]["w"] = 4.8
            bend = "bend-left" if rx < 0 else "bend-right"
            e["classes"] = f"solid root {bend}"

    # 2. 垂直粗壮主干与错落主枝：Questions 沿主干高度向左右大角度伸展 (y < 0)
    question_nodes = [n for n in nodes if n["data"]["node_type"] == "question"]
    num_q = len(question_nodes)
    q_angles: dict[str, float] = {}

    for k, qnode in enumerate(question_nodes):
        t_trunk = (k + 0.5) / max(1, num_q)
        # 沿主干垂直向上分布：从 y = -150 到 y = -820
        y_attach = - (140.0 + t_trunk * 680.0)
        x_attach = math.sin(t_trunk * math.pi * 1.2) * 26.0 + rng.uniform(-6, 6)

        # 左右交替出枝
        is_left = (k % 2 == 0)
        if t_trunk < 0.38:
            # 低位大主枝：几乎水平向两侧极度宽幅舒展 (72°~82°)，形成宽阔基座
            ang = -1.30 if is_left else 1.30
            b_len = 350.0 + rng.uniform(-15, 15)
        elif t_trunk < 0.72:
            # 中位主枝：斜向外上方舒展 (52°~62°)
            ang = -0.98 if is_left else 0.98
            b_len = 310.0 + rng.uniform(-15, 15)
        else:
            # 高位与树冠主枝：直冲高空拱卫树顶 (25°~35°)
            ang = -0.48 if is_left else 0.48
            b_len = 260.0 + rng.uniform(-15, 15)

        qx = x_attach + math.sin(ang) * b_len
        qy = y_attach - math.cos(ang) * b_len
        qnode["position"] = {"x": round(qx, 1), "y": round(qy, 1)}
        q_angles[qnode["data"]["id"]] = ang

        e = edge_by_ends.get((qnode["data"]["id"], topic_id))
        if e:
            # 主枝粗度按达·芬奇递减 (底端 14px，顶端 8px)
            e["data"]["w"] = round(max(7.5, 14.5 - t_trunk * 6.5), 2)
            bend = "bend-left" if qx < 0 else "bend-right"
            e["classes"] = f"solid trunk {bend}"

    # 3. 观点分支：Claims 沿各 Question 主枝向外形成次级枝桠
    claims_by_q: dict[str, list[dict]] = {}
    for cnode in [n for n in nodes if n["data"]["node_type"] == "claim"]:
        for qnode in question_nodes:
            if (cnode["data"]["id"], qnode["data"]["id"]) in edge_by_ends:
                claims_by_q.setdefault(qnode["data"]["id"], []).append(cnode)
                break

    c_angles: dict[str, float] = {}
    for qid, c_list in claims_by_q.items():
        q_pos = by_id[qid]["position"]
        parent_ang = q_angles.get(qid, 0.0)
        num_c = len(c_list)
        c_spread = min(1.6, 0.42 * num_c)
        for m, cnode in enumerate(c_list):
            offset = 0.0 if num_c == 1 else (-c_spread / 2 + c_spread * m / (num_c - 1))
            c_ang = parent_ang + offset + rng.gauss(0, 0.04)
            c_len = 160.0 + (m % 2) * 28.0 + rng.uniform(-10, 10)
            cx = q_pos["x"] + math.sin(c_ang) * c_len
            cy = q_pos["y"] - math.cos(c_ang) * c_len
            cnode["position"] = {"x": round(cx, 1), "y": round(cy, 1)}
            c_angles[cnode["data"]["id"]] = c_ang
            e = edge_by_ends.get((cnode["data"]["id"], qid))
            if e:
                e["data"]["w"] = 4.2
                bend = "bend-left" if cx < q_pos["x"] else "bend-right"
                e["classes"] = f"solid branch {bend}"

    # 4. 树冠绿叶：Sources 簇生于 Claim / Question 外围
    sources_by_target: dict[str, str] = {}
    for e in edges:
        if e["data"].get("edge_type") == "evidence":
            src_id = e["data"]["source"]
            tgt_id = e["data"]["target"]
            if src_id not in sources_by_target:
                sources_by_target[src_id] = tgt_id

    target_to_sources: dict[str, list[str]] = {}
    for sid, tid in sources_by_target.items():
        target_to_sources.setdefault(tid, []).append(sid)

    for tid, s_list in target_to_sources.items():
        t_pos = by_id[tid].get("position", {"x": 0.0, "y": 0.0})
        num_s = len(s_list)
        bias_ang = math.atan2(t_pos["y"], t_pos["x"]) if (t_pos["x"] != 0 or t_pos["y"] != 0) else -math.pi/2
        s_spread = min(1.8, 0.35 * num_s)
        for s_idx, sid in enumerate(s_list):
            s_offset = 0.0 if num_s == 1 else (-s_spread / 2 + s_spread * s_idx / (num_s - 1))
            leaf_ang = bias_ang + s_offset + rng.gauss(0, 0.05)
            leaf_dist = 72.0 + (s_idx % 2) * 22.0 + rng.uniform(-8, 8)
            sx = t_pos["x"] + math.cos(leaf_ang) * leaf_dist
            sy = t_pos["y"] + math.sin(leaf_ang) * leaf_dist
            by_id[sid]["position"] = {"x": round(sx, 1), "y": round(sy, 1)}
            e = edge_by_ends.get((sid, tid))
            if e:
                e["data"]["w"] = 1.4

    # 5. 碰撞消解：过近节点微调推开
    placed_nodes = [n for n in nodes if "position" in n and n["data"]["node_type"] != "topic"]
    for _ in range(3):
        moved = False
        for i, a in enumerate(placed_nodes):
            for b in placed_nodes[i + 1:]:
                dx = b["position"]["x"] - a["position"]["x"]
                dy = b["position"]["y"] - a["position"]["y"]
                dist = math.hypot(dx, dy)
                min_dist = 68.0 if (a["data"]["node_type"] != "source" and b["data"]["node_type"] != "source") else 38.0
                if 0.1 < dist < min_dist:
                    push = (min_dist - dist) / 2 * 0.7
                    ux, uy = dx / dist, dy / dist
                    a["position"]["x"] -= round(ux * push, 1)
                    a["position"]["y"] -= round(uy * push * 0.4, 1)
                    b["position"]["x"] += round(ux * push, 1)
                    b["position"]["y"] += round(uy * push * 0.4, 1)
                    moved = True
        if not moved:
            break

    # 兜底：未挂载节点排在侧边
    placed = {n["data"]["id"] for n in nodes if "position" in n}
    orphans = [n for n in nodes if n["data"]["id"] not in placed]
    for i, n in enumerate(orphans):
        n["position"] = {"x": (i - (len(orphans) - 1) / 2) * 120.0, "y": 260.0}

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
    """为每个常驻标签主枝（Question）选一个标签方位 class，最小化重叠与父枝遮挡。"""
    import math
    import random

    items = [n for n in nodes
             if n["data"]["node_type"] == "question" and "position" in n]
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

    n = len(items)
    # Precompute single cost: preference + obstacle penalties
    single_costs: list[list[float]] = []
    for i in range(n):
        row: list[float] = []
        for c in range(len(_LAB_CANDS)):
            box = cand_boxes[i][c]
            cost = _LAB_PREF[_LAB_CANDS[c]] * 20.0
            for ob in obstacles:
                if _overlap(box, ob) > 0:
                    cost += 30.0
            row.append(cost)
        single_costs.append(row)

    assign = [0] * n  # 初始全部 lab-r（Imhof 最优方位）
    cur_e = sum(single_costs[i][assign[i]] for i in range(n))
    for i in range(n):
        bi = cand_boxes[i][assign[i]]
        for j in range(i + 1, n):
            ov = _overlap(bi, cand_boxes[j][assign[j]])
            if ov > 0:
                cur_e += ov * 0.5

    best, best_e = list(assign), cur_e
    rng = random.Random(_SEED + 1)
    temp = 50.0

    for _ in range(1500):
        i = rng.randrange(n)
        old = assign[i]
        cand = rng.randrange(len(_LAB_CANDS))
        if cand == old:
            continue
        old_box = cand_boxes[i][old]
        new_box = cand_boxes[i][cand]

        delta = single_costs[i][cand] - single_costs[i][old]
        for j in range(n):
            if j == i:
                continue
            bj = cand_boxes[j][assign[j]]
            ov_new = _overlap(new_box, bj)
            ov_old = _overlap(old_box, bj)
            if ov_new != ov_old:
                delta += (ov_new - ov_old) * 0.5

        if delta < 0 or rng.random() < math.exp(-delta / max(temp, 1e-6)):
            assign[i] = cand
            cur_e += delta
            if cur_e < best_e:
                best, best_e = list(assign), cur_e
        temp *= 0.995

    for n_item, c in zip(items, best):
        n_item["classes"] = (n_item.get("classes", "") + " " + _LAB_CANDS[c]).strip()




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
