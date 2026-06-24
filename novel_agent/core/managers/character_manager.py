import dataclasses
from pathlib import Path
from typing import Dict, List, Optional

from ..models import CharacterProfile
from ..file_utils import JsonRepositoryMixin


class CharacterManager(JsonRepositoryMixin):
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self._characters: Dict[str, CharacterProfile] = {}
        self._load()

    def _load(self):
        data = self._load_json("characters.json")
        valid_fields = {f.name for f in dataclasses.fields(CharacterProfile)}
        for name, d in data.items():
            filtered = {k: v for k, v in d.items() if k in valid_fields}
            self._characters[name] = CharacterProfile(**filtered)

    def save(self):
        data = {k: dataclasses.asdict(v) for k, v in self._characters.items()}
        self._save_json("characters.json", data)

    def all(self) -> Dict[str, CharacterProfile]:
        return self._characters

    def get(self, name: str) -> Optional[CharacterProfile]:
        return self._characters.get(name)

    def add(self, profile: CharacterProfile):
        self._characters[profile.name] = profile

    def update(self, name: str, **kwargs):
        if name not in self._characters:
            return
        char = self._characters[name]
        for k, v in kwargs.items():
            if hasattr(char, k):
                setattr(char, k, v)
        self.save()

    def get_prompt(self, name: str) -> str:
        if name not in self._characters:
            return ""
        c = self._characters[name]
        lines = [
            f"【人物：{c.name}】",
            f"性别：{c.gender}，年龄：{c.age}" + (f"，修为：{c.cultivation}" if c.cultivation else ""),
            f"当前位置：{c.current_location or '未知'}",
            f"外貌：{c.appearance}",
            f"性格：{c.personality}",
            f"背景：{c.background}",
            f"目标：{c.goals}",
        ]
        if c.faction:
            lines.append(f"所属势力：{c.faction}" + (f"（{c.faction_status}）" if c.faction_status else ""))
        if c.core_values:
            lines.append(f"核心价值观：{c.core_values}")
        if c.core_desire:
            lines.append(f"核心欲望：{c.core_desire}")
        if c.core_fear:
            lines.append(f"核心恐惧：{c.core_fear}")
        if c.flaw:
            lines.append(f"核心缺陷：{c.flaw}")
        if c.alignment:
            lines.append(f"阵营倾向：{c.alignment}")
        lines.extend([
            f"语言风格：{c.speaking_style}",
            f"能力：{', '.join(c.abilities)}",
        ])
        if c.learned_skills:
            skill_lines = [f"  - {s.get('skill', '')}（{s.get('level', '初学')}）" +
                           (f"，消耗：{s.get('cost', '')}" if s.get('cost') else "") +
                           (f"，备注：{s.get('note', '')}" if s.get('note') else "") +
                           (f"，进度：{s.get('progress', 0)*100:.0f}%" if s.get('progress') else "") +
                           (f"，习得：第{s['chapter_learned']}章" if s.get('chapter_learned') else "")
                           for s in c.learned_skills]
            lines.append("已学技能：\n" + "\n".join(skill_lines))
        if c.relationships_detail:
            lines.append("人物关系（详细）：")
            stance_map = {"friendly": "🟢友好", "neutral": "⚪中立", "hostile": "🔴敌对", "adversarial": "🟠对立"}
            for other, detail in c.relationships_detail.items():
                rel_type = detail.get("type", detail.get("relation", ""))
                stance = detail.get("stance", "neutral")
                stance_tag = stance_map.get(stance, stance)
                met_ch = detail.get("met_chapter", detail.get("chapter_met", 0))
                met_ctx = detail.get("met_context", detail.get("how_met", ""))
                key_events = detail.get("key_events", [])
                parts = [f"{other}（{rel_type}·{stance_tag}）"]
                if met_ch > 0:
                    parts.append(f"第{met_ch}章认识")
                if met_ctx:
                    parts.append(f"「{met_ctx}」")
                if key_events:
                    parts.append("事件：" + "；".join(key_events))
                lines.append(f"  - {'，'.join(parts)}")
        elif c.relationships:
            lines.append(f"人物关系：{c.relationships}")
        lines.append(f"当前状态：{c.status}")
        return "\n".join(lines)

    def get_all_prompts(self) -> str:
        return "\n\n".join(self.get_prompt(n) for n in self._characters)

    def validate_chapter_characters(self, chapter: int, characters: List[str]) -> List[str]:
        warnings = []
        for char_name in characters:
            if char_name not in self._characters:
                continue
            c = self._characters[char_name]
            if c.status == "dead":
                warnings.append(f"⚠️ 预检：{char_name} 已标记为死亡（status=dead），但本章计划出场。如非复活剧情请修正。")
        return warnings

    def export_relations(self) -> List[Dict]:
        edges = []
        for name, char in self._characters.items():
            for other, relation in char.relationships.items():
                if other in self._characters:
                    edges.append({"from": name, "to": other, "relation": relation})
        return edges

    def export_for_viz(self) -> List[Dict]:
        return [
            {"id": name, "label": name, "status": char.status, "importance": self._calc_importance(char)}
            for name, char in self._characters.items()
        ]

    @staticmethod
    def _calc_importance(char: CharacterProfile) -> int:
        score = 0
        if char.first_appeared <= 3:
            score += 2
        if char.arc:
            score += 1
        if len(char.relationships) >= 3:
            score += 1
        return min(max(score, 1), 5)
