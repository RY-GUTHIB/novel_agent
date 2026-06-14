"""
continuity.py - 时间线 + 空间线守卫（防崩坏）

功能：
1. 记录每条时间线事件（章节、时间标签、事件、涉及人物、地点）
2. 记录空间地图（地点拓扑、人物位置随时间变化）
3. 生成新章节前，自动检测冲突并警告/修正
4. 持久化到 data/timeline.json 和 data/spacemap.json
"""

import json
import config
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict, field


# ============ 数据结构 ============

@dataclass
class TimelineEvent:
    """时间线事件"""
    chapter: int           # 发生章节
    time_tag: str          # 时间描述（如"第三年春"、"事发后第7天"）
    event: str             # 事件摘要
    characters: List[str]  # 涉及人物
    location: str = ""    # 发生地点
    importance: int = 1   # 重要性 1-5（主线事件高）


@dataclass
class CharacterLocation:
    """某章节某人物的位置记录（支持同一章多场景）"""
    chapter: int
    character: str
    location: str
    scene: str = ""       # 场景标识（如"开场"、"中段"、"结尾"）
    note: str = ""        # 附加说明（如"通过传送阵到达"、"飞剑赶路半日"）


@dataclass
class SpaceNode:
    """地点节点（空间地图）"""
    name: str
    description: str = ""
    type: str = "city"           # city/mountain/sect/forest/dungeon/other
    connected_to: List[str] = field(default_factory=list)  # 可到达的相邻地点
    travel_time: Dict[str, str] = field(default_factory=dict)  # {相邻地点: "3天路程"}
    first_appeared: int = 1
    notable_characters: List[str] = field(default_factory=list)


# ============ 主守卫类 ============

class ContinuityGuard:
    """时间线 + 空间线守卫"""

    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir or config.DATA_DIR)
        self.timeline: List[TimelineEvent] = []
        self.spacemap: Dict[str, SpaceNode] = {}       # name -> SpaceNode
        self.character_locations: List[CharacterLocation] = []  # 按章节记录人物位置
        self._load_all()

    # ---------- 持久化 ----------
    def _load_all(self):
        self._load_timeline()
        self._load_spacemap()
        self._load_character_locations()

    def save_all(self):
        self._save_timeline()
        self._save_spacemap()
        self._save_character_locations()

    def _save_json(self, filename: str, data):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with open(self.data_dir / filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_json(self, filename: str):
        path = self.data_dir / filename
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    def _save_timeline(self):
        data = [asdict(e) for e in self.timeline]
        self._save_json("timeline.json", data)

    def _load_timeline(self):
        data = self._load_json("timeline.json")
        self.timeline = [TimelineEvent(**d) for d in data]

    def _save_spacemap(self):
        data = {k: asdict(v) for k, v in self.spacemap.items()}
        self._save_json("spacemap.json", data)

    def _load_spacemap(self):
        data = self._load_json("spacemap.json")
        # 兼容旧格式（list）
        if isinstance(data, list):
            data = {d["name"]: d for d in data}
        self.spacemap = {k: SpaceNode(**v) for k, v in data.items()}

    def _save_character_locations(self):
        data = [asdict(cl) for cl in self.character_locations]
        self._save_json("character_locations.json", data)

    def _load_character_locations(self):
        data = self._load_json("character_locations.json")
        self.character_locations = [CharacterLocation(**d) for d in data]

    # ---------- 时间线操作 ----------
    def add_event(self, chapter: int, time_tag: str, event: str,
                  characters: List[str], location: str = "",
                  importance: int = 1):
        """添加时间线事件（同章节已存在则覆盖，防止大纲+实际章节重复）"""
        # 人物名归一：去掉"（xxx）"后缀
        cleaned_chars = []
        for c in characters:
            import re
            c_clean = re.sub(r"\（.*?\）", "", c).strip()
            if c_clean and c_clean not in cleaned_chars:
                cleaned_chars.append(c_clean)

        # 同章节已存在则覆盖（按 chapter 去重）
        existing_idx = None
        for i, e in enumerate(self.timeline):
            if e.chapter == chapter:
                existing_idx = i
                break
        new_event = TimelineEvent(
            chapter=chapter,
            time_tag=time_tag,
            event=event,
            characters=cleaned_chars,
            location=location,
            importance=importance,
        )
        if existing_idx is not None:
            self.timeline[existing_idx] = new_event
        else:
            self.timeline.append(new_event)
        self._save_timeline()

    def get_events_for_chapter(self, chapter: int) -> List[TimelineEvent]:
        """获取某章节的时间线事件"""
        return [e for e in self.timeline if e.chapter == chapter]

    def get_events_for_character(self, character: str) -> List[TimelineEvent]:
        """获取某人物参与的所有事件"""
        return [e for e in self.timeline if character in e.characters]

    # ---------- 空间线操作 ----------
    def add_location(self, node: SpaceNode):
        """添加/更新地点"""
        self.spacemap[node.name] = node
        self._save_spacemap()

    def add_character_location(self, chapter: int, character: str,
                               location: str, scene: str = "", note: str = ""):
        """记录某章节某人物的位置（支持同一章多场景）"""
        # 同章同人物同场景 → 覆盖；同章同人物不同场景 → 追加
        existing = [cl for cl in self.character_locations
                    if cl.chapter == chapter and cl.character == character and cl.scene == scene]
        if existing:
            existing[0].location = location
            existing[0].note = note
        else:
            self.character_locations.append(CharacterLocation(
                chapter=chapter,
                character=character,
                location=location,
                scene=scene,
                note=note,
            ))
        self._save_character_locations()

    def get_character_location(self, character: str, chapter: int) -> str:
        """获取某人物在某章节的位置（向前查找最近记录）"""
        records = [cl for cl in self.character_locations
                   if cl.character == character and cl.chapter <= chapter]
        if not records:
            return ""
        # 取最近的一条
        return sorted(records, key=lambda x: x.chapter)[-1].location

    def get_location_characters(self, location: str, chapter: int) -> List[str]:
        """获取某地点在某章节有哪些人物"""
        result = []
        for cl in self.character_locations:
            if cl.chapter <= chapter and cl.location == location:
                # 检查该人物在此章节后是否离开了（简化处理：取最近记录）
                recent = self.get_character_location(cl.character, chapter)
                if recent == location:
                    result.append(cl.character)
        return list(set(result))

    # ---------- 冲突检测 ----------
    def check_continuity(self, chapter: int,
                          new_characters: Dict[str, str],  # {人物: 位置}
                          new_time_tag: str = "") -> List[str]:
        """
        生成新章节前的冲突检测
        :param chapter: 待生成章节号
        :param new_characters: 本章涉及人物及其位置
        :param new_time_tag: 本章时间标签
        :return: 冲突警告列表（空列表表示无冲突）
        """
        if not config.ENABLE_CONTINUITY_CHECK:
            return []

        warnings = []

        # 1. 空间矛盾检测
        for character, location in new_characters.items():
            last_loc = self.get_character_location(character, chapter - 1)
            if last_loc and last_loc != location:
                # 检查两地是否相邻（可通过旅行到达）
                if last_loc in self.spacemap:
                    node = self.spacemap[last_loc]
                    if location not in node.connected_to:
                        warnings.append(
                            f"⚠️ 空间矛盾：{character} 在第{chapter-1}章位于「{last_loc}」，"
                            f"第{chapter}章突然出现在「{location}」（两地不相邻，"
                            f"需说明交通/传送方式）"
                        )
                else:
                    warnings.append(
                        f"⚠️ 空间矛盾：{character} 位置从「{last_loc}」"
                        f"跳到「{location}」，请确认移动方式已描述"
                    )

        # 2. 死亡悖论检测（需配合 memory.py 使用，此处留接口）
        # 3. 时间跳跃过大警告
        if new_time_tag and self.timeline:
            # 简化：若时间标签中出现"年"且前一章也是"年"，做简单检查
            pass  # 详细时间解析较复杂，留给 prompt 层处理

        return warnings

    def generate_continuity_prompt(self, chapter: int, plot_rules_text: str = "", character_knowledge_text: str = "") -> str:
        """
        生成连续性摘要（注入新章节 prompt，保持连贯）
        """
        lines = ["【前文连续性摘要（生成本章必读）】"]

        # 最近3章的时间线事件
        recent_events = [e for e in self.timeline
                         if chapter - 3 <= e.chapter < chapter]
        if recent_events:
            lines.append("## 近期事件：")
            for e in recent_events:
                lines.append(f"  第{e.chapter}章 [{e.time_tag}]：{e.event}"
                             f"（涉及：{', '.join(e.characters)}）")

        # 本章涉及人物的当前位置（取最近一章的最后一个场景位置）
        all_chars = set()
        for e in recent_events:
            all_chars.update(e.characters)

        if all_chars:
            lines.append("\n## 人物当前位置（必须据此写空间过渡）：")
            for char in sorted(all_chars):
                # 获取该人物最近的所有位置记录
                char_recs = [cl for cl in self.character_locations
                             if cl.character == char and cl.chapter < chapter]
                if char_recs:
                    last_rec = sorted(char_recs, key=lambda x: (x.chapter, x.scene))[-1]
                    note_str = f"（{last_rec.note}）" if last_rec.note else ""
                    lines.append(f"  {char}：第{last_rec.chapter}章末位于「{last_rec.location}」{note_str}")
                else:
                    lines.append(f"  {char}：位置未知")

        # 空间过渡提醒
        lines.append("\n## ⚠️ 空间过渡规则（必须遵守）：")
        lines.append("  1. 如果本章场景与前一章末尾位置不同，必须交代移动过程（如'御剑飞行半日'、'穿过回廊来到后山'）")
        lines.append("  2. 不允许人物瞬移——除非有传送阵/遁术等设定支撑，且必须描写")
        lines.append("  3. 非相邻地点之间移动需标注时间消耗（参照下文地点拓扑）")

        # 剧情规则提醒
        if plot_rules_text and plot_rules_text != "（无特殊剧情规则）":
            lines.append(f"\n{plot_rules_text}")

        # 角色认知提醒
        if character_knowledge_text and character_knowledge_text != "（无角色认知记录）":
            lines.append(f"\n{character_knowledge_text}")

        # 世界观关键设定提醒
        lines.append("\n## 地点拓扑（移动路径参考）：")
        for name, node in self.spacemap.items():
            conns = node.connected_to
            travel = node.travel_time
            if conns:
                conn_details = []
                for t in conns:
                    tt = travel.get(t, "")
                    conn_details.append(f"{t}（{tt}）" if tt else t)
                lines.append(f"  {name} → 可达：{', '.join(conn_details)}")
            else:
                lines.append(f"  {name}（无已知通道）")

        return "\n".join(lines)

    # ---------- 导出（给可视化用）----------
    def export_timeline_for_viz(self) -> List[Dict]:
        """导出时间线数据（供 timeline.html）"""
        return [
            {
                "chapter": e.chapter,
                "time_tag": e.time_tag,
                "event": e.event,
                "characters": e.characters,
                "location": e.location,
                "importance": e.importance,
            }
            for e in sorted(self.timeline, key=lambda x: (x.chapter, x.importance))
        ]

    def export_spacemap_for_viz(self) -> Dict:
        """导出空间地图数据（供 world_map.html）"""
        nodes = [
            {
                "id": name,
                "label": name,
                "type": node.type,
                "description": node.description,
                "first_chapter": node.first_appeared,
            }
            for name, node in self.spacemap.items()
        ]
        edges = []
        for name, node in self.spacemap.items():
            for target in node.connected_to:
                edges.append({
                    "from": name,
                    "to": target,
                    "travel_time": node.travel_time.get(target, ""),
                })
        return {"nodes": nodes, "edges": edges}
