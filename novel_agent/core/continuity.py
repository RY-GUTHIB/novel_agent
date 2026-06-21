"""
continuity.py - 时间线 + 空间线守卫（防崩坏）

功能：
1. 记录每条时间线事件
2. 记录空间地图（地点拓扑、人物位置随时间变化）
3. 生成新章节前，自动检测冲突并警告
4. 持久化到 data/timeline.json 和 data/spacemap.json
"""

import re
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List
from .models import TimelineEvent, CharacterLocation, LocationProfile
from .file_utils import atomic_write_json, parse_chinese_number, parse_travel_time, JsonRepositoryMixin


class ContinuityGuard(JsonRepositoryMixin):
    """时间线 + 空间线守卫"""

    def __init__(self, data_dir: str, enable_continuity_check: bool = True):
        self.data_dir = Path(data_dir)
        self.timeline: List[TimelineEvent] = []
        self.spacemap: Dict[str, LocationProfile] = {}
        self.character_locations: List[CharacterLocation] = []
        self.absolute_day: float = 0  # 故事已过天数（累计）
        self.enable_continuity_check = enable_continuity_check
        self._time_updated_chapters: set = set()  # 已累计天数的章节集合
        self._load_all()
        # 从已加载的 timeline 重建时间已更新章节集合
        self._time_updated_chapters = {e.chapter for e in self.timeline}

    # ========== 加载/保存 ==========

    def _load_all(self):
        self._load_timeline()
        self._load_spacemap()
        self._load_character_locations()
        self._load_absolute_day()

    def save_all(self):
        self.save_timeline()
        self.save_spacemap()
        self.save_character_locations()
        self.save_absolute_day()

    # ========== 时间线 ==========

    def save_timeline(self):
        self._save_json("timeline.json", [asdict(e) for e in self.timeline])

    def _load_timeline(self):
        data = self._load_json("timeline.json", default=[])
        self.timeline = [TimelineEvent(**d) for d in data]

    def add_event(self, chapter: int, time_tag: str, event: str,
                  characters: List[str], location: str = "", importance: int = 1):
        cleaned_chars = []
        for c in characters:
            c_clean = re.sub(r"（.*?）", "", c).strip()
            if c_clean and c_clean not in cleaned_chars:
                cleaned_chars.append(c_clean)

        new_event = TimelineEvent(
            chapter=chapter, time_tag=time_tag, event=event,
            characters=cleaned_chars, location=location, importance=importance,
        )
        self.timeline.append(new_event)
        self.save_timeline()

        if chapter not in self._time_updated_chapters:
            self._time_updated_chapters.add(chapter)
            self.update_absolute_day(time_tag)

    def get_events_for_chapter(self, chapter: int) -> List[TimelineEvent]:
        return [e for e in self.timeline if e.chapter == chapter]

    def get_events_for_character(self, character: str) -> List[TimelineEvent]:
        return [e for e in self.timeline if character in e.characters]

    # ========== 累计时间轴 ==========

    def save_absolute_day(self):
        self._save_json("absolute_day.json", self.absolute_day)

    def _load_absolute_day(self):
        data = self._load_json("absolute_day.json", default=0)
        self.absolute_day = data if isinstance(data, (int, float)) else 0

    @staticmethod
    def _parse_time_elapsed(time_tag: str) -> float:
        """从 time_tag 解析与上一章的时间间隔（天数），用于累计时间轴"""
        return parse_travel_time(time_tag)

    @staticmethod
    def _parse_chinese_number(num_str: str) -> float:
        """解析中文数字/阿拉伯数字为 float"""
        return float(parse_chinese_number(num_str))

    def update_absolute_day(self, time_tag: str):
        """根据本章 time_tag 更新累计天数"""
        elapsed = self._parse_time_elapsed(time_tag)
        if elapsed > 0:
            self.absolute_day += elapsed
            self.save_absolute_day()

    # ========== 空间 ==========

    def save_spacemap(self):
        self._save_json("spacemap.json", {k: asdict(v) for k, v in self.spacemap.items()})

    def _load_spacemap(self):
        data = self._load_json("spacemap.json")
        if isinstance(data, list):
            data = {d["name"]: d for d in data}
        self.spacemap = {k: LocationProfile(**v) for k, v in data.items()}

    def add_location(self, node: LocationProfile):
        self.spacemap[node.name] = node
        self.save_spacemap()

    # ========== 人物位置 ==========

    def save_character_locations(self):
        self._save_json("character_locations.json", [asdict(cl) for cl in self.character_locations])

    def _load_character_locations(self):
        data = self._load_json("character_locations.json")
        self.character_locations = [CharacterLocation(**d) for d in data]

    def add_character_location(self, chapter: int, character: str,
                               location: str, scene: str = "", note: str = ""):
        existing = [cl for cl in self.character_locations
                    if cl.chapter == chapter and cl.character == character and cl.scene == scene]
        if existing:
            existing[0].location = location
            existing[0].note = note
        else:
            self.character_locations.append(CharacterLocation(
                chapter=chapter, character=character, location=location, scene=scene, note=note,
            ))
        self.save_character_locations()

    def get_character_location(self, character: str, chapter: int) -> str:
        records = [cl for cl in self.character_locations
                   if cl.character == character and cl.chapter <= chapter]
        if not records:
            return ""
        return sorted(records, key=lambda x: x.chapter)[-1].location

    def get_location_characters(self, location: str, chapter: int) -> List[str]:
        result = []
        for cl in self.character_locations:
            if cl.chapter <= chapter and cl.location == location:
                recent = self.get_character_location(cl.character, chapter)
                if recent == location:
                    result.append(cl.character)
        return list(set(result))

    # ========== 冲突检测 ==========

    def check_continuity(self, chapter: int,
                          new_characters: Dict[str, str],
                          new_time_tag: str = "") -> List[str]:
        if not self.enable_continuity_check:
            return []
        warnings = []
        for character, location in new_characters.items():
            last_loc = self.get_character_location(character, chapter - 1)
            if last_loc and last_loc != location:
                if last_loc in self.spacemap:
                    node = self.spacemap[last_loc]
                    if location not in node.connected_to:
                        warnings.append(
                            f"⚠️ 空间矛盾：{character} 在第{chapter-1}章位于「{last_loc}」，"
                            f"第{chapter}章突然出现在「{location}」（两地不相邻，需说明交通/传送方式）"
                        )
                else:
                    warnings.append(
                        f"⚠️ 空间矛盾：{character} 位置从「{last_loc}」跳到「{location}」，请确认移动方式已描述"
                    )
        return warnings

    def generate_continuity_prompt(self, chapter: int,
                                    plot_rules_text: str = "",
                                    character_knowledge_text: str = "") -> str:
        lines = ["【前文连续性摘要（生成本章必读）】"]

        if self.absolute_day > 0:
            lines.append(f"\n⏱️ 故事已过：约 {self.absolute_day:.1f} 天")
            lines.append("  （如果本章涉及时间跳跃，请在 time_tag 中标注，如「三日后」「又过半月」）")

        recent_events = [e for e in self.timeline if chapter - 3 <= e.chapter < chapter]
        if recent_events:
            lines.append("## 近期事件：")
            for e in recent_events:
                lines.append(f"  第{e.chapter}章 [{e.time_tag}]：{e.event}（涉及：{', '.join(e.characters)}）")

        # C方案：已完成关键事件列表（防止重复情节）
        # 只保留最近20章的关键事件，更早的事件由RAG补充检索
        min_chapter = max(1, chapter - 20)
        all_events = [e for e in self.timeline if min_chapter <= e.chapter < chapter]
        if all_events:
            # 按重要性取 top 20 条
            key_events = sorted(all_events, key=lambda x: -x.importance)[:20]
            lines.append("\n## ⚠️ 已发生的关键事件（禁止重复！）：")
            for e in key_events:
                lines.append(f"  第{e.chapter}章：{e.event}")
            lines.append("  以上事件已经发生过，本章不要重复！")

        all_chars = set()
        for e in recent_events:
            all_chars.update(e.characters)

        if all_chars:
            lines.append("\n## 人物当前位置（必须据此写空间过渡）：")
            for char in sorted(all_chars):
                char_recs = [cl for cl in self.character_locations
                             if cl.character == char and cl.chapter < chapter]
                if char_recs:
                    last_rec = sorted(char_recs, key=lambda x: (x.chapter, x.scene))[-1]
                    note_str = f"（{last_rec.note}）" if last_rec.note else ""
                    lines.append(f"  {char}：第{last_rec.chapter}章末位于「{last_rec.location}」{note_str}")
                else:
                    lines.append(f"  {char}：位置未知")

        lines.extend([
            "\n## ⚠️ 空间过渡规则（必须遵守）：",
            "  1. 如果本章场景与前一章末尾位置不同，必须交代移动过程",
            "  2. 不允许人物瞬移——除非有传送阵/遁术等设定支撑，且必须描写",
            "  3. 非相邻地点之间移动需标注时间消耗（参照下文地点拓扑）",
        ])

        # 时间一致性：注入上一章的时间信息和季节
        prev_event = None
        for e in reversed(self.timeline):
            if e.chapter < chapter:
                prev_event = e
                break
        if prev_event:
            lines.append("\n## ⚠️ 时间一致性约束（必须遵守）：")
            lines.append(f"  上一章（第{prev_event.chapter}章）时间：{prev_event.time_tag}")
            if prev_event.season:
                lines.append(f"  上一章季节：{prev_event.season}")
            if prev_event.time_elapsed:
                lines.append(f"  距再上一章时间间隔：{prev_event.time_elapsed}")
            lines.append("  1. 本章时间标签必须晚于上一章，不能时间倒流")
            lines.append("  2. 季节描写必须与上一章季节连贯（除非明确写了\"数月后\"等跨季过渡）")
            lines.append("  3. 一天/半日内不能跨越需要数日路程的距离（除非有传送手段且明写）")
            lines.append("  4. 不要在单章中同时出现冬季和夏季的特征描写")

        if plot_rules_text and plot_rules_text != "（无特殊剧情规则）":
            lines.append(f"\n{plot_rules_text}")

        if character_knowledge_text and character_knowledge_text != "（无角色认知记录）":
            lines.append(f"\n{character_knowledge_text}")

        lines.append("\n## 地点拓扑（移动路径参考）：")
        for name, node in self.spacemap.items():
            conns = node.connected_to
            travel = node.travel_time
            if conns:
                conn_details = [f"{t}（{travel.get(t, '')}）" if travel.get(t) else t for t in conns]
                lines.append(f"  {name} → 可达：{', '.join(conn_details)}")
            else:
                lines.append(f"  {name}（无已知通道）")

        return "\n".join(lines)

    # ========== 导出（给可视化用）==========

    def export_timeline_for_viz(self) -> List[Dict]:
        return [
            {"chapter": e.chapter, "time_tag": e.time_tag, "event": e.event,
             "characters": e.characters, "location": e.location, "importance": e.importance}
            for e in sorted(self.timeline, key=lambda x: (x.chapter, x.importance))
        ]

    def export_spacemap_for_viz(self) -> Dict:
        nodes = [
            {"id": name, "label": name, "type": node.type,
             "description": node.description, "first_chapter": node.first_appeared}
            for name, node in self.spacemap.items()
        ]
        edges = []
        for name, node in self.spacemap.items():
            for target in node.connected_to:
                edges.append({"from": name, "to": target, "travel_time": node.travel_time.get(target, "")})
        return {"nodes": nodes, "edges": edges}
