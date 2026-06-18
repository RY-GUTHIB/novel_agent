"""
memory.py - 世界观/人物档案管理

负责维护：人物、地点、世界观设定、剧情规则、角色认知、势力、场景事件
所有数据持久化到 data/ 目录下的 JSON 文件。
"""

import dataclasses
from pathlib import Path
from typing import Dict, List, Optional
from .models import (
    CharacterProfile, LocationProfile, WorldSetting,
    PlotRule, CharacterKnowledge, SectFaction, SceneEvent,
    ItemProfile, StyleProfile, TaskProfile,
)
from .file_utils import atomic_write_json, JsonRepositoryMixin
from .managers import ItemTracker, TaskTracker, StyleManager


class MemoryManager(JsonRepositoryMixin):
    """世界观与人物档案管理器"""

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.characters: Dict[str, CharacterProfile] = {}
        self.locations: Dict[str, LocationProfile] = {}
        self.world_settings: Dict[str, WorldSetting] = {}
        self.plot_rules: Dict[str, PlotRule] = {}
        self.character_knowledge: Dict[str, List[CharacterKnowledge]] = {}
        self.sect_factions: Dict[str, SectFaction] = {}
        self.scene_events: List[SceneEvent] = []
        # 子管理器（从 MemoryManager 提取的独立领域）
        self.item_tracker = ItemTracker(data_dir)
        self.task_tracker = TaskTracker(data_dir)
        self.style_manager = StyleManager(data_dir)
        # 别名——保持对调用方的兼容（直接 self.items / self.tasks / self.style）
        self.items = self.item_tracker.items
        self.tasks = self.task_tracker.tasks
        self.style = self.style_manager.style
        self._load_all()

    # ========== 加载/保存 ==========

    def _load_all(self):
        self._load_characters()
        self._load_locations()
        self._load_world_settings()
        self._load_plot_rules()
        self._load_character_knowledge()
        self._load_sect_factions()
        self._load_scene_events()
        # 子管理器在各自 __init__ 中已加载，无需重复

    def save_all(self):
        self.save_characters()
        self.save_locations()
        self.save_world_settings()
        self.save_plot_rules()
        self.save_character_knowledge()
        self.save_sect_factions()
        self.save_scene_events()
        self.item_tracker.save()
        self.style_manager.save()
        self.task_tracker.save()

    # ========== 人物 ==========

    def save_characters(self):
        data = {k: dataclasses.asdict(v) for k, v in self.characters.items()}
        self._save_json("characters.json", data)

    def _load_characters(self):
        data = self._load_json("characters.json")
        valid_fields = {f.name for f in dataclasses.fields(CharacterProfile)}
        for name, d in data.items():
            filtered = {k: v for k, v in d.items() if k in valid_fields}
            self.characters[name] = CharacterProfile(**filtered)

    def add_character(self, profile: CharacterProfile):
        self.characters[profile.name] = profile

    def update_character_status(self, name: str, **kwargs):
        if name not in self.characters:
            return
        char = self.characters[name]
        for k, v in kwargs.items():
            if hasattr(char, k):
                setattr(char, k, v)
        self.save_characters()

    # ========== 地点 ==========

    def save_locations(self):
        data = {k: dataclasses.asdict(v) for k, v in self.locations.items()}
        self._save_json("locations.json", data)

    def _load_locations(self):
        data = self._load_json("locations.json")
        for name, d in data.items():
            self.locations[name] = LocationProfile(**d)

    def add_location(self, profile: LocationProfile):
        self.locations[profile.name] = profile

    # ========== 世界观设定 ==========

    def save_world_settings(self):
        data = {k: dataclasses.asdict(v) for k, v in self.world_settings.items()}
        self._save_json("world_settings.json", data)

    def _load_world_settings(self):
        data = self._load_json("world_settings.json")
        for key, d in data.items():
            self.world_settings[key] = WorldSetting(**d)

    def add_world_setting(self, setting: WorldSetting):
        self.world_settings[setting.key] = setting

    # ========== 剧情规则 ==========

    def save_plot_rules(self):
        data = {k: dataclasses.asdict(v) for k, v in self.plot_rules.items()}
        self._save_json("plot_rules.json", data)

    def _load_plot_rules(self):
        data = self._load_json("plot_rules.json")
        if isinstance(data, list):
            data = {r.get("condition", f"rule_{i}"): r for i, r in enumerate(data) if isinstance(r, dict)}
        self.plot_rules = {}
        for key, d in data.items():
            self.plot_rules[key] = PlotRule(**d)

    def add_plot_rule(self, rule: PlotRule):
        self.plot_rules[rule.condition] = rule
        self.save_plot_rules()

    # ========== 角色认知 ==========

    def save_character_knowledge(self):
        data = {k: [dataclasses.asdict(i) for i in v] for k, v in self.character_knowledge.items()}
        self._save_json("character_knowledge.json", data)

    def _load_character_knowledge(self):
        data = self._load_json("character_knowledge.json")
        self.character_knowledge = {}
        for char_name, items in data.items():
            if isinstance(items, list):
                self.character_knowledge[char_name] = [
                    CharacterKnowledge(**item) for item in items if isinstance(item, dict)
                ]

    def add_character_knowledge(self, knowledge: CharacterKnowledge):
        if knowledge.character not in self.character_knowledge:
            self.character_knowledge[knowledge.character] = []
        existing = self.character_knowledge[knowledge.character]
        for k in existing:
            if k.knowledge == knowledge.knowledge:
                return
        existing.append(knowledge)
        self.save_character_knowledge()

    # ========== 势力/宗派 ==========

    def save_sect_factions(self):
        data = {k: dataclasses.asdict(v) for k, v in self.sect_factions.items()}
        self._save_json("sect_factions.json", data)

    def _load_sect_factions(self):
        data = self._load_json("sect_factions.json")
        if isinstance(data, list):
            data = {}
        self.sect_factions = {}
        valid_fields = {f.name for f in dataclasses.fields(SectFaction)}
        for name, d in data.items():
            if isinstance(d, dict):
                filtered = {k: v for k, v in d.items() if k in valid_fields}
                self.sect_factions[name] = SectFaction(**filtered)

    def add_sect_faction(self, faction: SectFaction):
        self.sect_factions[faction.name] = faction
        self.save_sect_factions()

    def update_sect_faction(self, name: str, **kwargs):
        if name not in self.sect_factions:
            return
        faction = self.sect_factions[name]
        for k, v in kwargs.items():
            if hasattr(faction, k):
                if isinstance(getattr(faction, k), list) and isinstance(v, list):
                    existing = getattr(faction, k)
                    for item in v:
                        if item not in existing:
                            existing.append(item)
                elif v:
                    setattr(faction, k, v)
        self.save_sect_factions()

    # ========== 场景事件 ==========

    def save_scene_events(self):
        data = [dataclasses.asdict(e) for e in self.scene_events]
        self._save_json("scene_events.json", data)

    def _load_scene_events(self):
        data = self._load_json("scene_events.json")
        self.scene_events = []
        if isinstance(data, list):
            valid_fields = {f.name for f in dataclasses.fields(SceneEvent)}
            for item in data:
                if isinstance(item, dict):
                    filtered = {k: v for k, v in item.items() if k in valid_fields}
                    self.scene_events.append(SceneEvent(**filtered))

    def add_scene_event(self, event: SceneEvent):
        self.scene_events.append(event)
        self.save_scene_events()

    # ========== Prompt 生成 ==========

    def get_character_prompt(self, name: str) -> str:
        if name not in self.characters:
            return ""
        c = self.characters[name]
        lines = [
            f"【人物：{c.name}】",
            f"性别：{c.gender}，年龄：{c.age}" + (f"，修为：{c.cultivation}" if c.cultivation else ""),
            f"当前位置：{c.current_location or '未知'}",
            f"外貌：{c.appearance}",
            f"性格：{c.personality}",
            f"背景：{c.background}",
            f"目标：{c.goals}",
        ]
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

    def get_all_characters_prompt(self) -> str:
        return "\n\n".join(self.get_character_prompt(n) for n in self.characters)

    def get_location_prompt(self, name: str) -> str:
        if name not in self.locations:
            return ""
        loc = self.locations[name]
        return f"【地点：{loc.name}】\n类型：{loc.type}\n描述：{loc.description}\n相邻地点：{', '.join(loc.connected_to)}"

    def get_world_settings_prompt(self) -> str:
        lines = ["【世界观设定】"]
        for key, s in self.world_settings.items():
            lines.append(f"- {key}：{s.value}")
        return "\n".join(lines)

    def get_active_rules_prompt(self) -> str:
        active_rules = [r for r in self.plot_rules.values() if not r.overridden]
        if not active_rules:
            return "（无特殊剧情规则）"
        lines = ["【当前生效的剧情规则（角色行为必须遵守）】"]
        for r in active_rules:
            source = f"（{r.source_character}于第{r.chapter_introduced}章声明）" if r.source_character else f"（第{r.chapter_introduced}章声明）"
            lines.append(f"  ⚖️ IF「{r.condition}」→ THEN「{r.consequence}」{source}")
            lines.append(f"     原文：「{r.rule_text}」")
        lines.append("\n⚠️ 以上规则已被正文明确声明，后续章节中角色行为必须遵守，不得违反。如需修改规则，必须在正文中给出合理解释并标记覆盖。")
        return "\n".join(lines)

    def get_character_knowledge_prompt(self, chapter: int = 0) -> str:
        if not self.character_knowledge:
            return "（无角色认知记录）"
        lines = ["【角色已知信息（写作时必须遵守——角色不能对已知信息表现惊讶）】"]
        for char_name, knowledge_list in self.character_knowledge.items():
            known_by_chapter = [k for k in knowledge_list if k.chapter_learned <= chapter] if chapter > 0 else knowledge_list
            if not known_by_chapter:
                continue
            lines.append(f"\n  🧠 {char_name} 已知：")
            for k in known_by_chapter:
                source_tag = f"（{k.source}，第{k.chapter_learned}章）"
                detail_tag = f" —— {k.detail}" if k.detail else ""
                lines.append(f"    - {k.knowledge}{source_tag}{detail_tag}")
        if len(lines) == 1:
            return "（无角色认知记录）"
        lines.append("\n⚠️ 以上角色已在正文中获知这些信息。后续章节中，角色对这些信息不应再表现出惊讶、好奇或首次获知的反应。")
        return "\n".join(lines)

    def get_sect_factions_prompt(self) -> str:
        if not self.sect_factions:
            return "（无势力/宗派记录）"
        lines = ["【势力/宗派档案】"]
        for name, f in self.sect_factions.items():
            lines.append(f"\n  🏛️ {name}（{f.type}）")
            if f.description:
                lines.append(f"    描述：{f.description}")
            if f.strength:
                lines.append(f"    实力：{f.strength}")
            if f.hierarchy:
                lines.append(f"    层级：{' → '.join(f.hierarchy)}")
            if f.key_members:
                lines.append(f"    核心成员：{', '.join(f.key_members)}")
            if f.allies:
                lines.append(f"    盟友：{', '.join(f.allies)}")
            if f.enemies:
                lines.append(f"    敌对：{', '.join(f.enemies)}")
            if f.location:
                lines.append(f"    所在地：{f.location}")
            if f.rules:
                lines.append(f"    门规：{'；'.join(f.rules)}")
        return "\n".join(lines)

    def get_all_relationships_prompt(self) -> str:
        stance_map = {"friendly": "🟢友好", "neutral": "⚪中立", "hostile": "🔴敌对", "adversarial": "🟠对立"}
        lines = ["【人物关系详细记录（审校时用于判断角色是否应该认识、关系立场是否正确）】"]
        has_detail = False
        for name, char in self.characters.items():
            if not char.relationships_detail:
                continue
            for other, detail in char.relationships_detail.items():
                has_detail = True
                rel_type = detail.get("type", detail.get("relation", "未知"))
                stance = detail.get("stance", "neutral")
                stance_tag = stance_map.get(stance, stance)
                met_ch = detail.get("met_chapter", detail.get("chapter_met", 0))
                met_ctx = detail.get("met_context", detail.get("how_met", ""))
                key_events = detail.get("key_events", [])
                parts = [f"  {name} ↔ {other}（{rel_type}·{stance_tag}）"]
                if met_ch > 0:
                    parts.append(f"：第{met_ch}章")
                if met_ctx:
                    parts.append(f"，在「{met_ctx}」中认识")
                if key_events:
                    parts.append(f"，关键事件：「{'」「'.join(key_events)}」")
                lines.append("".join(parts))
        if not has_detail:
            lines.append("  （暂无详细关系记录）")
        lines.extend([
            "", "⚠️ 审校时必须检查：",
            "  1. 如果角色A和角色B在关系记录中已认识，则后续章节中双方不应表现出互不认识。",
            "  2. 如果关系记录中两个角色的立场是「敌对/对立」，则后续章节中不应突然表现亲密无间，除非有充分剧情转折。",
            "  3. 如果关系记录中两个角色的立场是「友好」，则后续章节中不应突然反目成仇，除非有充分剧情铺垫。",
            "  4. 如果正文中出现了密切互动但关系记录中未记载，需标记为中/低严重性问题并建议补充关系记录。",
        ])
        return "\n".join(lines)

    def get_scene_events_prompt(self, chapter: int = 0) -> str:
        if not self.scene_events:
            return "（无场景事件记录）"
        events = self.scene_events
        if chapter > 0:
            events = [e for e in events if e.chapter < chapter]
        if not events:
            return "（无场景事件记录）"
        lines = ["【场景事件记录（审校时用于检查事件发生地点是否正确）】"]
        recent = sorted(events, key=lambda e: e.chapter, reverse=True)[:20]
        for e in recent:
            chars = f"（{', '.join(e.characters)}）" if e.characters else ""
            lines.append(f"  第{e.chapter}章·{e.location}：{e.event}{chars}")
        return "\n".join(lines)

    def get_generation_contract(self, chapter: int, characters: List[str]) -> str:
        """生成「一致性契约」—— 写作前必须遵守的硬性约束清单"""
        stance_map = {"friendly": "🟢友好", "neutral": "⚪中立", "hostile": "🔴敌对", "adversarial": "🟠对立"}
        lines = [
            f"【第{chapter}章 一致性契约（写作前必须逐条确认，不可违反）】",
            "",
            "⚠️ 以下事实已在正文中确立，是本书的「宪法」。新章节不得与以下任何一条矛盾。",
            "⚠️ 如果本章需要「揭示真相推翻旧认知」，必须在正文中给出充分的转折描写，并在 SETTINGS_JSON 中回写。",
            "",
        ]
        has_content = False

        for char_name in characters:
            if char_name not in self.characters:
                continue
            c = self.characters[char_name]
            has_content = True

            # 人物卡标题
            status_tag = ""
            if c.status == "dead":
                status_tag = " ⚰️【已死亡——本章不得出场，除非回忆/幻象】"
            elif c.status == "missing":
                status_tag = " ❓【失踪——本章不得直接出场，除非交代行踪】"
            lines.append(f"  ═══ {char_name}{status_tag} ═══")

            # 不可改变的事实（强约束）
            if c.personality:
                lines.append(f"  🔒 性格锁定：{c.personality}")
                lines.append(f"     → 本章中 {char_name} 的所有言行必须符合此性格，不得性格突变。")
            if c.speaking_style:
                lines.append(f"  🔒 语言风格锁定：{c.speaking_style}")
                lines.append(f"     → {char_name} 的对话风格必须与以上一致。")
            if c.cultivation:
                lines.append(f"  🔒 修为锁定：{c.cultivation}")
                lines.append(f"     → 不得低于或远超此修为（除非本章明确描写突破/受伤降级）。")
            if c.current_location:
                lines.append(f"  📍 上一章末位置：{c.current_location}")
                lines.append(f"     → 如果本章 {char_name} 出现在其他地点，必须描写移动过程（交通方式/耗时）。")
            if c.background:
                lines.append(f"  🔒 背景锁定：{c.background}")
                lines.append(f"     → {char_name} 的出身/历史不得被篡改。")

            # 关系立场（强约束）
            if c.relationships_detail:
                lines.append(f"  🔒 关系立场锁定：")
                for other, detail in c.relationships_detail.items():
                    rel_type = detail.get("type", "")
                    stance = detail.get("stance", "neutral")
                    stance_tag = stance_map.get(stance, stance)
                    lines.append(f"     → {char_name} ↔ {other}：{rel_type}（{stance_tag}）")
                    key_events = detail.get("key_events", [])
                    if key_events:
                        lines.append(f"       历史事件：{'；'.join(key_events)}")
                lines.append(f"     ⚠️ 友好不能突然反目，敌对不能突然亲密，除非本章有充分转折描写。")

            # 角色已知信息（强约束）
            if char_name in self.character_knowledge:
                known = [k for k in self.character_knowledge[char_name] if k.chapter_learned <= chapter]
                if known:
                    lines.append(f"  🔒 已知信息锁定（{char_name} 已经知道，不得再表现出惊讶/好奇）：")
                    for k in known:
                        lines.append(f"     → {k.knowledge}（第{k.chapter_learned}章获知，来源：{k.source}）")
                    lines.append(f"     ⚠️ 如果本章 {char_name} 需要「表现出惊讶」，必须是针对新信息，不能是对以上已知信息的反应。")

        active_rules = [r for r in self.plot_rules.values() if not r.overridden]
        if active_rules:
            has_content = True
            lines.append(f"\n  ═══ 剧情规则（宪法级别，不可违反）═══")
            for r in active_rules:
                source = f"（{r.source_character}，第{r.chapter_introduced}章）" if r.source_character else f"（第{r.chapter_introduced}章）"
                lines.append(f"  ⚖️ IF「{r.condition}」→ THEN「{r.consequence}」{source}")
            lines.append(f"  ⚠️ 以上规则已在正文中明确声明。违反任何一条都是剧情 Bug。")

        lines.append(f"\n  ═══ 出场人物关系网 ═══")
        has_rel = False
        for i, a in enumerate(characters):
            for b in characters[i+1:]:
                if a in self.characters and b in self.characters:
                    char_a = self.characters[a]
                    if b in char_a.relationships_detail:
                        has_rel = True
                        detail = char_a.relationships_detail[b]
                        rel_type = detail.get("type", "")
                        stance = detail.get("stance", "neutral")
                        stance_tag = stance_map.get(stance, stance)
                        lines.append(f"  🔗 {a} ↔ {b}：{rel_type}（{stance_tag}）")
        if not has_rel:
            lines.append(f"  （出场人物之间暂无已记录的关系）")

        if not has_content:
            return "（无特殊一致性约束）"
        lines.append(f"\n  ⛔ 以上所有约束均为硬性宪法级别。违反任何一条都将导致剧情矛盾，审校时会标记为「高」严重性。")
        return "\n".join(lines)

    def validate_chapter_characters(self, chapter: int, characters: List[str]) -> List[str]:
        warnings = []
        for char_name in characters:
            if char_name not in self.characters:
                continue
            c = self.characters[char_name]
            if c.status == "dead":
                warnings.append(f"⚠️ 预检：{char_name} 已标记为死亡（status=dead），但本章计划出场。如非复活剧情请修正。")
        return warnings

    # ========== 物品状态追踪（委派给 ItemTracker）==========

    def _load_items(self):
        self.item_tracker._load()

    def save_items(self):
        self.item_tracker.save()

    def add_item(self, item: ItemProfile):
        self.item_tracker.add(item)

    def get_item(self, name: str) -> Optional[ItemProfile]:
        return self.item_tracker.get(name)

    def update_item(self, name: str, **kwargs):
        self.item_tracker.update(name, **kwargs)

    def transfer_item(self, item_name: str, from_holder: str, to_holder: str,
                      chapter: int, reason: str = ""):
        self.item_tracker.transfer(item_name, from_holder, to_holder, chapter, reason)

    def build_state_snapshot(self, chapter: int, characters: list, timeline_events: list = None) -> str:
        """构建「当前世界状态快照」——写作和审校前注入 prompt，防止事实矛盾。

        提取：人物修为、身份、位置、物品归属、已揭示设定、未兑现承诺。
        """
        parts = []

        # 1. 人物修为 + 身份 + 位置
        parts.append("## 📋 人物当前状态")
        for name in characters:
            if name not in self.characters:
                continue
            c = self.characters[name]
            fields = [f"- **{name}**"]
            if c.cultivation:
                fields.append(f"修为={c.cultivation}")
            if c.current_location:
                fields.append(f"位置={c.current_location}")
            # 从 relationships 提取关键身份信息（如"叶家家主"、"大长老"）
            if c.relationships:
                id_tags = []
                for other, rel in c.relationships.items():
                    if rel in ("家主", "族长", "大长老", "长老", "宗主", "掌门", "师父", "徒弟", "父亲", "母亲", "舅舅", "兄弟"):
                        id_tags.append(f"{rel}({other})")
                if id_tags:
                    fields.append(f"关系身份={', '.join(id_tags)}")
            if c.status and c.status != "alive":
                fields.append(f"状态={c.status}")
            parts.append("，".join(fields))

        # 2. 物品归属（含后续转移记录和禁止操作）
        parts.append("\n## 📦 关键物品归属（当前）")
        if self.items:
            for name, item in self.items.items():
                parts.append(
                    f"- {name}（{item.type}）：第{item.first_appeared}章由「{item.first_giver}」"
                    f"给予「{item.current_holder}」，当前状态={item.status}"
                )
                if item.subsequent_transfers:
                    for t in item.subsequent_transfers:
                        parts.append(f"  → 第{t['chapter']}章：{t['from']} → {t['to']}（{t['reason']}）")
                if item.prohibited_actions:
                    parts.append(f"  ⛔ 禁止操作：{', '.join(item.prohibited_actions)}")
            parts.append("⚠️ 以上物品已有归属，后文不得再次出现「他人将同一物品赠予/交给角色」的情节！")
        else:
            parts.append("（无）")

        # 3. 已揭示的核心设定（最近5条，避免冗余）
        parts.append("\n## 🌍 已揭示的世界设定摘要")
        ws_keys = list(self.world_settings.keys())
        recent_ws = ws_keys[-5:] if len(ws_keys) > 5 else ws_keys
        for key in recent_ws:
            if key in self.world_settings:
                s = self.world_settings[key]
                parts.append(f"- {key}：{s.value[:80]}")
        if not recent_ws:
            parts.append("（无）")

        # 4. 承诺清单（未兑现的规则、物品禁止操作、时间死线）
        has_commitments = False
        commitment_parts = []

        # 4a. 未兑现的剧情规则（出场人物声明的规则）
        active_rules = [r for r in self.plot_rules.values() if not r.overridden]
        if active_rules:
            commitment_parts.append("\n🔴 剧情规则：")
            for r in active_rules:
                commitment_parts.append(f"  - 第{r.chapter_introduced}章「{r.rule_text[:60]}」")
                commitment_parts.append(f"    → IF {r.condition} THEN {r.consequence}")
            has_commitments = True

        # 4b. 物品禁止操作
        if self.items:
            item_warnings = []
            for name, item in self.items.items():
                if item.prohibited_actions:
                    item_warnings.append(f"  - {name}：⛔ {', '.join(item.prohibited_actions)}")
            if item_warnings:
                commitment_parts.append("\n🔴 物品禁止操作：")
                commitment_parts.extend(item_warnings)
                has_commitments = True

        # 4c. 时间死线（从 timeline 中提取包含"天后""之后""内"的时间约束）
        if timeline_events:
            deadline_events = []
            for e in timeline_events:
                if e.chapter >= chapter:
                    continue
                tt = e.time_tag or ""
                # 检测时间约束关键词
                deadline_keywords = ["天后", "之后", "之内", "前", "马上", "立刻", "尽快", "三日内", "三日后"]
                if any(kw in tt for kw in deadline_keywords) or any(kw in (e.event or "") for kw in deadline_keywords):
                    deadline_events.append(e)
            if deadline_events:
                commitment_parts.append("\n🟡 时间死线：")
                for e in deadline_events[-5:]:  # 最近5条
                    commitment_parts.append(f"  - 第{e.chapter}章：{e.time_tag} — {e.event[:60]}")
                has_commitments = True

        if has_commitments:
            parts.append("\n## ⚠️ 承诺清单（本章写作前必须逐条确认，违反任何一条即为bug）")
            parts.extend(commitment_parts)
        else:
            parts.append("\n## ⚠️ 承诺清单：（无未兑现承诺）")

        # 5. 任务清单（活跃的长线任务/目标）
        active_tasks = self.get_active_tasks(current_chapter=chapter, limit=5)
        if active_tasks:
            parts.append("\n## 🎯 任务清单（活跃，跨章节长线任务）")
            for t in active_tasks:
                parts.append(f"- [{t.status}] {t.name}：{t.description}")
                if t.progress:
                    parts.append(f"    当前进度：{t.progress}")
        else:
            parts.append("\n## 🎯 任务清单：（无活跃任务）")

        return "\n".join(parts)

    # ========== 风格锚点（委派给 StyleManager）==========

    def _load_style(self):
        self.style_manager._load()
        # 保持 self.style 引用同步
        self.style = self.style_manager.style

    def save_style(self):
        self.style_manager.save()

    def update_style(self, updates: dict):
        self.style_manager.update(updates)
        self.style = self.style_manager.style

    def get_style_prompt(self) -> str:
        return self.style_manager.get_prompt()

    # ========== 任务清单（委派给 TaskTracker）==========

    def save_tasks(self):
        self.task_tracker.save()

    def _load_tasks(self):
        self.task_tracker._load()
        self.tasks = self.task_tracker.tasks

    def get_active_tasks(self, current_chapter: int = 99999, limit: int = 5) -> List[TaskProfile]:
        return self.task_tracker.get_active(current_chapter, limit)

    def add_task(self, task: TaskProfile):
        self.task_tracker.add(task)
        self.tasks = self.task_tracker.tasks

    def complete_task(self, task_id: str, chapter: int):
        self.task_tracker.complete(task_id, chapter)
        self.tasks = self.task_tracker.tasks

    def update_task_progress(self, task_id: str, progress: str):
        self.task_tracker.update_progress(task_id, progress)
        self.tasks = self.task_tracker.tasks

    # ========== 导出（给可视化用）==========

    def export_character_relations(self) -> List[Dict]:
        edges = []
        for name, char in self.characters.items():
            for other, relation in char.relationships.items():
                if other in self.characters:
                    edges.append({"from": name, "to": other, "relation": relation})
        return edges

    def export_characters_for_viz(self) -> List[Dict]:
        return [
            {
                "id": name, "label": name, "status": char.status,
                "importance": self._calc_importance(char),
            }
            for name, char in self.characters.items()
        ]

    def _calc_importance(self, char: CharacterProfile) -> int:
        score = 0
        if char.first_appeared <= 3:
            score += 2
        if char.arc:
            score += 1
        if len(char.relationships) >= 3:
            score += 1
        return min(max(score, 1), 5)


