"""
visualizer.py - 三大可视化生成器

生成：
1. timeline.html        - 可视化时间线（vis-timeline）
2. character_map.html   - 人物关系图（vis-network）
3. world_map.html       - 世界地图（vis-network拓扑图）

所有 HTML 内嵌 JS/CSS，离线可用。
"""

import json
import config
from pathlib import Path
from typing import Dict

from novel_agent.core.memory import MemoryManager
from novel_agent.core.continuity import ContinuityGuard

# ============ 内嵌 JS/CSS（离线可用）============

def _load_vendor(file_name: str) -> str:
    """读取 vendor 目录下的 JS/CSS 文件内容"""
    vendor_path = Path(__file__).parent.parent.parent / "vendor" / file_name
    if vendor_path.exists():
        with open(vendor_path, "r", encoding="utf-8") as f:
            return f.read()
    # 回退：文件不存在时用 CDN
    cdn_map = {
        "vis-timeline-graph2d.min.js": "https://unpkg.com/vis-timeline@7.7.2/standalone/umd/vis-timeline-graph2d.min.js",
        "vis-timeline-graph2d.min.css": "https://unpkg.com/vis-timeline@7.7.2/styles/vis-timeline-graph2d.min.css",
        "vis-network.min.js": "https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js",
    }
    return cdn_map.get(file_name, "")


# ============ 时间线可视化 ============

def generate_timeline_html(continuity: ContinuityGuard,
                           output_path: str = None,
                           project_name: str = "") -> str:
    """
    生成时间线 HTML（vis-timeline）
    横轴：章节 + 时间标签
    纵轴：多人物并行轨道
    """
    data = continuity.export_timeline_for_viz()

    # 防御性去重：按 chapter+event 去重，保留第一次
    seen_events = set()
    deduped = []
    for event in data:
        key = (event.get("chapter", 0), event.get("event", ""))
        if key not in seen_events:
            seen_events.add(key)
            deduped.append(event)
    data = deduped

    # 人物名归一：去掉"（xxx）"后缀
    for event in data:
        event["characters"] = [
            re.sub(r"\（.*?\）", "", c).strip()
            for c in event.get("characters", [])
            if re.sub(r"\（.*?\）", "", c).strip()
        ]

    # 构建 vis-timeline 数据格式
    items = []
    groups = []

    # 收集所有人物，构建分组
    all_chars = set()
    for event in data:
        all_chars.update(event.get("characters", []))

    char_to_group = {}
    for i, char in enumerate(sorted(all_chars)):
        char_to_group[char] = i
        groups.append({"id": i, "content": char})

    # 构建事件 items
    for event in data:
        # 时间线：用章节号作为 x 轴位置
        start = event["chapter"]
        # 涉及人物（取第一个作为主分组，其余用 className 标注）
        main_char = event["characters"][0] if event["characters"] else "未知"
        group_id = char_to_group.get(main_char, 0)

        items.append({
            "id": f"evt{event['chapter']}_{event['importance']}",
            "group": group_id,
            "content": f"第{event['chapter']}章：{event['event'][:30]}...",
            "title": f"<b>第{event['chapter']}章 [{event['time_tag']}]</b><br>{event['event']}<br>人物：{', '.join(event['characters'])}<br>地点：{event['location']}",
            "start": start,
            "importance": event["importance"],
        })

    # 内嵌 CSS/JS
    vis_css = _load_vendor("vis-timeline-graph2d.min.css")
    vis_js = _load_vendor("vis-timeline-graph2d.min.js")
    # 判断是内嵌还是CDN引用
    if len(vis_css) > 1000:
        css_tag = f"<style>\n{vis_css}\n</style>"
    else:
        css_tag = f'<link href="{vis_css}" rel="stylesheet">'
    if len(vis_js) > 1000:
        js_tag = f"<script>\n{vis_js}\n</script>"
    else:
        js_tag = f'<script src="{vis_js}"></script>'

    # 生成 HTML
    title_prefix = f"{project_name} - " if project_name else ""
    html = _TIMELINE_TEMPLATE.format(
        css_tag=css_tag,
        js_tag=js_tag,
        groups_json=json.dumps(groups, ensure_ascii=False),
        items_json=json.dumps(items, ensure_ascii=False),
        title_prefix=title_prefix,
    )

    out_path = Path(output_path or config.OUTPUT_DIR) / "timeline.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    return str(out_path)


# ============ 人物关系图可视化 ============

def generate_character_map_html(memory_mgr: MemoryManager,
                                 output_path: str = None,
                                 project_name: str = "") -> str:
    """
    生成人物关系图 HTML（vis-network 力导向图）
    节点 = 人物，边 = 关系
    """
    nodes = memory_mgr.export_characters_for_viz()
    edges = memory_mgr.export_character_relations()

    # 节点样式（根据阵营/状态调整颜色）
    for node in nodes:
        # 重要性 → 节点大小
        size_map = {1: 20, 2: 30, 3: 40, 4: 50, 5: 60}
        node["size"] = size_map.get(node.get("importance", 1), 30)
        # 状态 → 颜色
        color_map = {
            "alive": "#4CAF50",   # 绿色：存活
            "dead": "#F44336",     # 红色：死亡
            "missing": "#FF9800",  # 橙色：失踪
        }
        node["color"] = color_map.get(node.get("status", "alive"), "#4CAF50")
        node["font"] = {"size": 14, "color": "#333"}

    # 边样式（根据关系类型关键词调整颜色）
    edge_color_keywords = {
        "师": "#2196F3",       # 师徒/师父/弟子 → 蓝色
        "恋": "#E91E63",      # 恋人/暗恋/爱 → 粉红
        "情": "#E91E63",      # 情侣/情人 → 粉红
        "敌": "#F44336",      # 敌对/仇人 → 红色
        "仇": "#F44336",      # 仇敌/宿敌 → 红色
        "盟": "#4CAF50",      # 盟友/同盟 → 绿色
        "亲": "#9C27B0",      # 亲人/亲属 → 紫色
        "兄": "#9C27B0",      # 兄弟/姐妹 → 紫色
        "友": "#00BCD4",      # 朋友/挚友 → 青色
        "竹": "#00BCD4",      # 青梅竹马 → 青色
        "同": "#00BCD4",      # 同门/同学 → 青色
    }
    for edge in edges:
        rel = edge.get("relation", "")
        # 关键词匹配颜色
        edge_color = "#999"
        for keyword, color in edge_color_keywords.items():
            if keyword in rel:
                edge_color = color
                break
        edge["color"] = {"color": edge_color, "opacity": 0.8}
        edge["width"] = 2
        edge["title"] = rel  # hover 显示完整关系
        edge["label"] = rel[:8]  # 边上显示关系标签（截取前8字）
        # 有向边：箭头指向 to（表示 from 对 to 的关系）
        edge["arrows"] = {"to": {"enabled": True, "scaleFactor": 0.5}}

    # 内嵌 JS
    vis_js = _load_vendor("vis-network.min.js")
    if len(vis_js) > 1000:
        js_tag = f"<script>\n{vis_js}\n</script>"
    else:
        js_tag = f'<script src="{vis_js}"></script>'

    title_prefix = f"{project_name} - " if project_name else ""
    html = _CHARACTER_MAP_TEMPLATE.format(
        js_tag=js_tag,
        nodes_json=json.dumps(nodes, ensure_ascii=False),
        edges_json=json.dumps(edges, ensure_ascii=False),
        title_prefix=title_prefix,
    )

    out_path = Path(output_path or config.OUTPUT_DIR) / "character_map.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    return str(out_path)


# ============ 世界地图可视化 ============

def generate_world_map_html(continuity: ContinuityGuard,
                            output_path: str = None,
                            project_name: str = "") -> str:
    """
    生成世界地图 HTML（vis-network 拓扑图）
    节点 = 地点，边 = 可到达路线
    """
    data = continuity.export_spacemap_for_viz()
    nodes = data["nodes"]
    edges = data["edges"]

    # 地点类型 → 节点颜色和形状
    type_color = {
        "city": "#2196F3",       # 蓝色：城市
        "mountain": "#795548",    # 棕色：山脉
        "sect": "#9C27B0",        # 紫色：宗门
        "forest": "#4CAF50",      # 绿色：森林
        "dungeon": "#F44336",     # 红色：副本/秘境
        "other": "#9E9E9E",       # 灰色：其他
    }
    type_shape = {
        "city": "box",
        "mountain": "diamond",
        "sect": "star",
        "forest": "ellipse",
        "dungeon": "triangle",
        "other": "dot",
    }

    for node in nodes:
        t = node.get("type", "other")
        node["color"] = {"background": type_color.get(t, "#9E9E9E"), "border": "#333"}
        node["shape"] = type_shape.get(t, "ellipse")
        node["font"] = {"size": 14}
        node["title"] = f"<b>{node['label']}</b><br>类型：{t}<br>首次出现：第{node.get('first_chapter', '?')}章<br>{node.get('description', '')}"

    for edge in edges:
        edge["color"] = {"color": "#666", "opacity": 0.5}
        edge["width"] = 2
        edge["title"] = edge.get("travel_time", "可到达")
        edge["arrows"] = ""  # 无箭头（双向）

    # 内嵌 JS
    vis_js = _load_vendor("vis-network.min.js")
    if len(vis_js) > 1000:
        js_tag = f"<script>\n{vis_js}\n</script>"
    else:
        js_tag = f'<script src="{vis_js}"></script>'

    title_prefix = f"{project_name} - " if project_name else ""
    html = _WORLD_MAP_TEMPLATE.format(
        js_tag=js_tag,
        nodes_json=json.dumps(nodes, ensure_ascii=False),
        edges_json=json.dumps(edges, ensure_ascii=False),
        title_prefix=title_prefix,
    )

    out_path = Path(output_path or config.OUTPUT_DIR) / "world_map.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    return str(out_path)


# ============ 统一入口 ============

def generate_all_visualizations(memory_mgr: MemoryManager,
                                continuity: ContinuityGuard,
                                output_path: str = None,
                                project_name: str = "") -> Dict[str, str]:
    """一键生成所有三个可视化"""
    results = {}
    results["timeline"] = generate_timeline_html(continuity, output_path, project_name)
    results["character_map"] = generate_character_map_html(memory_mgr, output_path, project_name)
    results["world_map"] = generate_world_map_html(continuity, output_path, project_name)
    return results


# ============ HTML 模板 ============

_TIMELINE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>{title_prefix}小说时间线</title>
    {css_tag}
    <style>
        body {{ font-family: "Microsoft YaHei", sans-serif; margin: 20px; background: #f5f5f5; }}
        h1 {{ color: #333; }}
        #timeline {{ background: white; border-radius: 8px; padding: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .legend {{ margin-top: 10px; font-size: 12px; color: #666; }}
    </style>
</head>
<body>
    <h1>{title_prefix}小说时间线</h1>
    <p class="legend">横轴：章节 | 纵轴：人物轨道 | 点击节点查看详情</p>
    <div id="timeline" style="height: 600px;"></div>

    {js_tag}
    <script>
        const groups = new vis.DataSet({groups_json});
        const items = new vis.DataSet({items_json});

        const container = document.getElementById("timeline");
        const options = {{
            width: "100%",
            height: "100%",
            stack: true,
            verticalScroll: true,
            zoomKey: true,
            orientation: "top",
            format: {{
                minorLabels: {{
                    year: "第{{id}}章",
                }}
            }}
        }};
        const timeline = new vis.Timeline(container, items, groups, options);
    </script>
</body>
</html>"""

_CHARACTER_MAP_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>{title_prefix}人物关系图</title>
    <style>
        body {{ font-family: "Microsoft YaHei", sans-serif; margin: 20px; background: #f5f5f5; }}
        h1 {{ color: #333; }}
        #network {{ background: white; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .legend {{ margin-top: 10px; font-size: 12px; }}
        .legend span {{ display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 5px; }}
    </style>
</head>
<body>
    <h1>{title_prefix}人物关系图</h1>
    <div class="legend">
        <span style="background:#4CAF50"></span>存活
        <span style="background:#F44336"></span>死亡
        <span style="background:#FF9800"></span>失踪
    </div>
    <div id="network" style="height: 700px;"></div>

    {js_tag}
    <script>
        const nodes = new vis.DataSet({nodes_json});
        const edges = new vis.DataSet({edges_json});

        const container = document.getElementById("network");
        const data = {{ nodes: nodes, edges: edges }};
        const options = {{
            nodes: {{
                shape: "dot",
                size: 30,
                font: {{ size: 14, color: "#333" }},
            }},
            edges: {{
                smooth: {{ type: "continuous" }},
                font: {{ size: 12, align: "middle" }},
            }},
            layout: {{
                randomSeed: 42,
            }},
            physics: {{
                stabilization: {{ enabled: true, iterations: 500 }},
                barnesHut: {{ gravitationalConstant: -3000, springLength: 150 }},
            }},
            interaction: {{
                hover: true,
                tooltipDelay: 200,
            }},
        }};
        const network = new vis.Network(container, data, options);
    </script>
</body>
</html>"""

_WORLD_MAP_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>{title_prefix}世界地图</title>
    <style>
        body {{ font-family: "Microsoft YaHei", sans-serif; margin: 20px; background: #f5f5f5; }}
        h1 {{ color: #333; }}
        #network {{ background: white; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .legend {{ margin-top: 10px; font-size: 12px; }}
        .legend span {{ display: inline-block; width: 12px; height: 12px; margin-right: 5px; border-radius: 2px; }}
    </style>
</head>
<body>
    <h1>{title_prefix}世界地图</h1>
    <div class="legend">
        <span style="background:#2196F3"></span>城市
        <span style="background:#795548"></span>山脉
        <span style="background:#9C27B0"></span>宗门
        <span style="background:#4CAF50"></span>森林
        <span style="background:#F44336"></span>秘境/副本
    </div>
    <div id="network" style="height: 700px;"></div>

    {js_tag}
    <script>
        const nodes = new vis.DataSet({nodes_json});
        const edges = new vis.DataSet({edges_json});

        const container = document.getElementById("network");
        const data = {{ nodes: nodes, edges: edges }};
        const options = {{
            nodes: {{
                shape: "dot",
                size: 30,
                font: {{ size: 14, color: "#333" }},
            }},
            edges: {{
                smooth: {{ type: "curvedCW" }},
                font: {{ size: 11, align: "middle" }},
            }},
            layout: {{
                randomSeed: 43,
            }},
            physics: {{
                stabilization: {{ enabled: true, iterations: 500 }},
                barnesHut: {{ gravitationalConstant: -2000, springLength: 120 }},
            }},
            interaction: {{
                hover: true,
                tooltipDelay: 200,
                navigationButtons: true,
            }},
        }};
        const network = new vis.Network(container, data, options);
    </script>
</body>
</html>"""
