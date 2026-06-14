"""
backfill_spatial.py - 从已写章节中补录空间移动数据到 character_locations.json 和 spacemap.json
"""
import json
import config
from continuity import ContinuityGuard, SpaceNode
from generator import generate

config.set_project("苍穹独狼")
continuity = ContinuityGuard()

# 读取所有章节
import os
chapters = []
ch_dir = "projects/苍穹独狼/output/chapters/"
for fname in sorted(os.listdir(ch_dir)):
    if fname.startswith("chapter_") and fname.endswith(".md"):
        ch_num = int(fname.replace("chapter_", "").replace(".md", ""))
        with open(os.path.join(ch_dir, fname), "r", encoding="utf-8") as f:
            content = f.read()
        chapters.append((ch_num, content))

chapters.sort(key=lambda x: x[0])

print(f"共 {len(chapters)} 章待处理")

for ch_num, content in chapters:
    print(f"\n--- 处理第{ch_num}章 ---")

    # 截取内容（太长会超 token 限制）
    text = content[:8000]

    prompt = f"""请从以下小说章节中，提取人物的空间移动信息和地点连通关系。

## 需要提取的内容

### 1. 人物空间移动
- 人物从一个地点移动到另一个地点
- 移动方式（御剑、步行、传送阵、飞行法器等）
- 移动耗时
- 场景标识（开场/中段/结尾）

### 2. 地点连通关系
- 正文中提到两地之间的行程时间
- 两地之间是否可以互相到达

## 输出格式（严格 JSON，不要其他内容）

{{
    "spatial_movements": [
        {{"character": "人物名", "from_location": "起始地点", "to_location": "目标地点", "scene": "场景标识", "travel_method": "移动方式", "travel_time": "耗时", "note": "补充"}}
    ],
    "spacemap_updates": [
        {{"from_location": "地点A", "to_location": "地点B", "travel_time": "行程时间", "is_bidirectional": true}}
    ]
}}

如果某类没有数据，输出空数组。

章节内容：
""" + text

    try:
        result = generate(
            system_prompt="你是小说空间分析专家，擅长从正文中提取人物移动轨迹和地点连通关系。",
            user_prompt=prompt,
            temperature=0.2,
            max_tokens=1024,
        )

        parsed = None
        try:
            parsed = json.loads(result)
        except json.JSONDecodeError:
            import re
            match = re.search(r'\{[\s\S]*\}', result)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                except json.JSONDecodeError:
                    parsed = None

        if not parsed:
            print(f"  未能解析 LLM 输出，跳过")
            continue

        # 处理空间移动
        movement_count = 0
        for item in parsed.get("spatial_movements", []):
            char_name = item.get("character", "").strip()
            to_loc = item.get("to_location", "").strip()
            if not char_name or not to_loc:
                continue
            scene = item.get("scene", "")
            travel_method = item.get("travel_method", "")
            travel_time = item.get("travel_time", "")
            note_parts = []
            if travel_method:
                note_parts.append(travel_method)
            if travel_time:
                note_parts.append(travel_time)
            if item.get("note", ""):
                note_parts.append(item["note"])
            note = "，".join(note_parts)

            continuity.add_character_location(
                chapter=ch_num,
                character=char_name,
                location=to_loc,
                scene=scene,
                note=note,
            )
            movement_count += 1

        if movement_count > 0:
            print(f"  记录 {movement_count} 条人物移动")

        # 处理地点连通
        spacemap_count = 0
        for item in parsed.get("spacemap_updates", []):
            from_loc = item.get("from_location", "").strip()
            to_loc = item.get("to_location", "").strip()
            if not from_loc or not to_loc:
                continue
            travel_time = item.get("travel_time", "")
            is_bidir = item.get("is_bidirectional", True)

            if from_loc in continuity.spacemap:
                node = continuity.spacemap[from_loc]
                if to_loc not in node.connected_to:
                    node.connected_to.append(to_loc)
                if travel_time:
                    node.travel_time[to_loc] = travel_time
            else:
                continuity.add_location(SpaceNode(
                    name=from_loc,
                    connected_to=[to_loc],
                    travel_time={to_loc: travel_time} if travel_time else {},
                ))

            if is_bidir:
                if to_loc in continuity.spacemap:
                    node = continuity.spacemap[to_loc]
                    if from_loc not in node.connected_to:
                        node.connected_to.append(from_loc)
                    if travel_time:
                        node.travel_time[from_loc] = travel_time
                else:
                    continuity.add_location(SpaceNode(
                        name=to_loc,
                        connected_to=[from_loc],
                        travel_time={from_loc: travel_time} if travel_time else {},
                    ))
            spacemap_count += 1

        if spacemap_count > 0:
            print(f"  更新 {spacemap_count} 条地点连通")

    except Exception as e:
        print(f"  处理失败: {e}")

# 最终保存
continuity.save_all()
print("\n✅ 补录完成")
