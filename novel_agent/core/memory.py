"""
memory.py - 世界观/人物档案管理

MemoryManager 作为编排器，将各领域委托给子 Manager。
所有外部调用方式不变（通过 property 代理保持向后兼容）。
"""

import re
from pathlib import Path
from typing import Dict, List, Optional

from .models import (
    CharacterProfile, LocationProfile, WorldSetting,
    PlotRule, CharacterKnowledge, SectFaction, SceneEvent,
    ItemProfile, StyleProfile, TaskProfile,
)
from .managers import (
    ItemTracker, TaskTracker, StyleManager,
    CharacterManager, LocationManager, WorldSettingManager,
    PlotRuleManager, CharacterKnowledgeManager, SectFactionManager,
    SceneEventManager, OutlineManager, CorrectionHistoryManager,
    ArcTracker, ReviewHistoryManager,
)
import config as _cfg


class MemoryManager:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.main_character: str = ""

        # 子管理器
        self.character_manager = CharacterManager(data_dir)
        self.location_manager = LocationManager(data_dir)
        self.world_setting_manager = WorldSettingManager(data_dir)
        self.plot_rule_manager = PlotRuleManager(data_dir)
        self.character_knowledge_manager = CharacterKnowledgeManager(data_dir)
        self.sect_faction_manager = SectFactionManager(data_dir)
        self.scene_event_manager = SceneEventManager(data_dir)
        self.outline_manager = OutlineManager(data_dir)
        self.correction_history_manager = CorrectionHistoryManager(data_dir)
        self.item_tracker = ItemTracker(data_dir)
        self.task_tracker = TaskTracker(data_dir)
        self.style_manager = StyleManager(data_dir)
        self.arc_tracker = ArcTracker(data_dir)
        self.review_history = ReviewHistoryManager(data_dir)

        # 别名引用（保持 self.items / self.tasks / self.style 写法）
        self.items = self.item_tracker.items
        self.tasks = self.task_tracker.tasks
        self.style = self.style_manager.style

    # ========== Property 代理（保持 memory.characters / memory.outline 等直接访问）==========

    @property
    def characters(self) -> Dict[str, CharacterProfile]:
        return self.character_manager._characters

    @characters.setter
    def characters(self, value):
        if isinstance(value, dict):
            self.character_manager._characters.clear()
            self.character_manager._characters.update(value)

    @property
    def locations(self) -> Dict[str, LocationProfile]:
        return self.location_manager._locations

    @locations.setter
    def locations(self, value):
        if isinstance(value, dict):
            self.location_manager._locations.clear()
            self.location_manager._locations.update(value)

    @property
    def world_settings(self) -> Dict[str, WorldSetting]:
        return self.world_setting_manager._settings

    @world_settings.setter
    def world_settings(self, value):
        if isinstance(value, dict):
            self.world_setting_manager._settings.clear()
            self.world_setting_manager._settings.update(value)

    @property
    def plot_rules(self) -> Dict[str, PlotRule]:
        return self.plot_rule_manager._rules

    @plot_rules.setter
    def plot_rules(self, value):
        if isinstance(value, dict):
            self.plot_rule_manager._rules.clear()
            self.plot_rule_manager._rules.update(value)

    @property
    def character_knowledge(self) -> Dict[str, List[CharacterKnowledge]]:
        return self.character_knowledge_manager._knowledge

    @character_knowledge.setter
    def character_knowledge(self, value):
        if isinstance(value, dict):
            self.character_knowledge_manager._knowledge.clear()
            self.character_knowledge_manager._knowledge.update(value)

    @property
    def sect_factions(self) -> Dict[str, SectFaction]:
        return self.sect_faction_manager._factions

    @sect_factions.setter
    def sect_factions(self, value):
        if isinstance(value, dict):
            self.sect_faction_manager._factions.clear()
            self.sect_faction_manager._factions.update(value)

    @property
    def scene_events(self) -> List[SceneEvent]:
        return self.scene_event_manager._events

    @scene_events.setter
    def scene_events(self, value):
        if isinstance(value, list):
            self.scene_event_manager._events.clear()
            self.scene_event_manager._events.extend(value)

    @property
    def outline(self) -> dict:
        return self.outline_manager._outline

    @outline.setter
    def outline(self, value):
        if isinstance(value, dict):
            self.outline_manager._outline = value
            self.outline_manager._rebuild_chapter_days()

    @property
    def correction_history(self) -> List[Dict]:
        return self.correction_history_manager._history

    @correction_history.setter
    def correction_history(self, value):
        if isinstance(value, list):
            self.correction_history_manager._history.clear()
            self.correction_history_manager._history.extend(value)

    # ========== 批量加载/保存 ==========

    # 批量加载已内联到各子管理器 __init__，此处不再需要

    def save_all(self):
        self.character_manager.save()
        self.location_manager.save()
        self.world_setting_manager.save()
        self.plot_rule_manager.save()
        self.character_knowledge_manager.save()
        self.sect_faction_manager.save()
        self.scene_event_manager.save()
        self.correction_history_manager.save()
        self.item_tracker.save()
        self.style_manager.save()
        self.task_tracker.save()
        self.arc_tracker.save()
        self.review_history.save()

    # ========== 人物（委派给 CharacterManager）==========

    def save_characters(self):
        self.character_manager.save()

    def add_character(self, profile: CharacterProfile):
        self.character_manager.add(profile)

    def update_character_status(self, name: str, **kwargs):
        self.character_manager.update(name, **kwargs)

    def get_character_prompt(self, name: str) -> str:
        return self.character_manager.get_prompt(name)

    def get_all_characters_prompt(self) -> str:
        return self.character_manager.get_all_prompts()

    def validate_chapter_characters(self, chapter: int, characters: List[str]) -> List[str]:
        return self.character_manager.validate_chapter_characters(chapter, characters)

    def export_character_relations(self) -> List[Dict]:
        return self.character_manager.export_relations()

    def export_characters_for_viz(self) -> List[Dict]:
        return self.character_manager.export_for_viz()

    # ========== 地点（委派给 LocationManager）==========

    def save_locations(self):
        self.location_manager.save()

    def add_location(self, profile: LocationProfile):
        self.location_manager.add(profile)

    def get_location_prompt(self, name: str) -> str:
        return self.location_manager.get_prompt(name)

    # ========== 世界观设定（委派给 WorldSettingManager）==========

    def save_world_settings(self):
        self.world_setting_manager.save()

    def add_world_setting(self, setting: WorldSetting):
        self.world_setting_manager.add(setting)

    def get_world_settings_prompt(self) -> str:
        return self.world_setting_manager.get_prompt(locations_manager=self.location_manager)

    # ========== 剧情规则（委派给 PlotRuleManager）==========

    def save_plot_rules(self):
        self.plot_rule_manager.save()

    def add_plot_rule(self, rule: PlotRule):
        self.plot_rule_manager.add(rule)

    def get_active_rules_prompt(self) -> str:
        return self.plot_rule_manager.get_active_prompt()

    # ========== 角色认知（委派给 CharacterKnowledgeManager）==========

    def save_character_knowledge(self):
        self.character_knowledge_manager.save()

    def add_character_knowledge(self, knowledge: CharacterKnowledge):
        self.character_knowledge_manager.add(knowledge)

    def get_character_knowledge_prompt(self, chapter: int = 0) -> str:
        return self.character_knowledge_manager.get_prompt(chapter, self.main_character)

    # ========== 势力/宗派（委派给 SectFactionManager）==========

    def save_sect_factions(self):
        self.sect_faction_manager.save()

    def add_sect_faction(self, faction: SectFaction):
        self.sect_faction_manager.add(faction)

    def update_sect_faction(self, name: str, **kwargs):
        self.sect_faction_manager.update(name, **kwargs)

    def get_sect_factions_prompt(self) -> str:
        return self.sect_faction_manager.get_prompt()

    # ========== 场景事件（委派给 SceneEventManager）==========

    def save_scene_events(self):
        self.scene_event_manager.save()

    def add_scene_event(self, event: SceneEvent):
        self.scene_event_manager.add(event)

    def get_scene_events_prompt(self, chapter: int = 0) -> str:
        return self.scene_event_manager.get_prompt(chapter)

    # ========== 大纲（委派给 OutlineManager）==========

    def _rebuild_chapter_days(self, outline: dict = None):
        self.outline_manager.rebuild_chapter_days(outline)

    def get_day_gap(self, chapter: int) -> int:
        return self.outline_manager.get_day_gap(chapter)

    def get_outline_context_prompt(self, chapter: int) -> str:
        return self.outline_manager.get_outline_context_prompt(chapter)

    # ========== 修正历史（委派给 CorrectionHistoryManager）==========

    def add_correction(self, chapter: int, issue_type: str, issue: str, fix: str, source: str = "manual") -> str:
        return self.correction_history_manager.add(chapter, issue_type, issue, fix, source)

    def get_correction_history_prompt(self, chapter: int, limit: int = 10) -> str:
        return self.correction_history_manager.get_prompt(chapter, limit)

    # ========== 物品（委派给 ItemTracker，保留 memory.save_items / add_item 等）==========

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

    # ========== 任务清单（委派给 TaskTracker）==========

    def save_tasks(self):
        self.task_tracker.save()

    def _load_tasks(self):
        self.task_tracker._load()
        self.tasks = self.task_tracker.tasks

    def get_active_tasks(self, current_chapter: int = 99999, limit: int = 0) -> List[TaskProfile]:
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

    # ========== 风格锚点（委派给 StyleManager）==========

    def _load_style(self):
        self.style_manager._load()
        self.style = self.style_manager.style

    def save_style(self):
        self.style_manager.save()

    def update_style(self, updates: dict):
        self.style_manager.update(updates)
        self.style = self.style_manager.style

    def get_style_prompt(self) -> str:
        return self.style_manager.get_prompt()

    # ========== 人物成长弧（委派给 ArcTracker）==========

    def add_arc_event(self, character: str, chapter: int, element: str,
                      event_type: str, description: str, new_value: str = ""):
        self.arc_tracker.record(character, chapter, element, event_type,
                                description, new_value)

    def get_character_arc(self, character: str):
        return self.arc_tracker.get_character_arc(character)

    def get_arc_prompt(self, character: str, up_to_chapter: int = 9999) -> str:
        return self.arc_tracker.get_arc_prompt(character, up_to_chapter)

    def get_all_arcs_prompt(self, up_to_chapter: int = 9999) -> str:
        return self.arc_tracker.get_all_arcs_prompt(up_to_chapter)

    # ========== 审校历史（委派给 ReviewHistoryManager）==========

    def record_review_score(self, chapter: int, scores: dict, overall: float):
        self.review_history.record(chapter, scores, overall)

    def get_review_calibration_prompt(self, chapter: int) -> str:
        return self.review_history.get_calibration_prompt(chapter)

    # ========== 跨域方法（stay in MemoryManager）==========

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

    def build_state_snapshot(self, chapter: int, characters: list, timeline_events: list = None, chapter_summary: str = "") -> str:
        """构建「当前世界状态快照」"""
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
            if c.relationships:
                id_tags = []
                for other, rel in c.relationships.items():
                    if rel in ("家主", "族长", "大长老", "长老", "宗主", "掌门", "师父", "徒弟", "父亲", "母亲", "舅舅", "兄弟"):
                        id_tags.append(f"{rel}({other})")
                if id_tags:
                    fields.append(f"关系身份={', '.join(id_tags)}")
            if c.status and c.status != "alive":
                fields.append(f"状态={c.status}")
            if c.learned_skills:
                skill_strs = []
                for s in c.learned_skills:
                    pct = f"{s.get('progress', 0)*100:.0f}%" if s.get('progress') else ""
                    ch = f"第{s['last_updated_chapter']}章" if s.get('last_updated_chapter') else ""
                    tag = f"({pct}{'/' + ch if ch else ''})" if pct or ch else ""
                    skill_strs.append(f"{s.get('skill', '')}{tag}")
                if skill_strs:
                    fields.append(f"技能={', '.join(skill_strs)}")
            parts.append("，".join(fields))

        if chapter_summary:
            mentioned_skills = set()
            for name in characters:
                if name in self.characters:
                    c = self.characters[name]
                    for s in c.learned_skills:
                        sk = s.get("skill", "")
                        if sk and sk in chapter_summary and sk not in mentioned_skills:
                            mentioned_skills.add(sk)
            for item_name, item in self.items.items():
                desc = getattr(item, "description", "") or ""
                if item_name in chapter_summary or any(w in chapter_summary for w in [item_name]):
                    pass
            if mentioned_skills:
                parts.append(f"\n## 📖 本章涉及技能/功法")
                for sk in sorted(mentioned_skills):
                    parts.append(f"- {sk}")

        # 2. 物品归属
        parts.append("\n## 📦 关键物品归属（当前）")
        held_items = {}
        for char_name in characters:
            for name, item in self.items.items():
                if item.current_holder == char_name:
                    held_items[name] = item
        summary_items = {}
        if chapter_summary:
            for name, item in self.items.items():
                if name in chapter_summary:
                    summary_items[name] = item
        relevant_items = {**summary_items, **held_items}
        if relevant_items:
            for name, item in relevant_items.items():
                parts.append(
                    f"- {name}（{item.type}）：{item.description}；第{item.first_appeared}章由「{item.first_giver}」"
                    f"给予「{item.current_holder}」，当前状态={item.status}"
                )
                if item.subsequent_transfers:
                    for t in item.subsequent_transfers:
                        parts.append(f"  → 第{t['chapter']}章：{t['from']} → {t['to']}（{t['reason']}）")
                if item.prohibited_actions:
                    parts.append(f"  ⛔ 禁止操作：{', '.join(item.prohibited_actions)}")
            parts.append("⚠️ 以上物品已有归属，后文不得再次出现「他人将同一物品赠予/交给角色」的情节！")
        else:
            parts.append("（本章无相关物品）")

        # 3. 已揭示的核心设定
        parts.append("\n## 🌍 已揭示的世界设定摘要")
        if self.world_settings:
            for key, s in self.world_settings.items():
                parts.append(f"- {key}：{s.value}")
        else:
            parts.append("（无）")

        # 4. 承诺清单
        has_commitments = False
        commitment_parts = []

        active_rules = [r for r in self.plot_rules.values() if not r.overridden]
        if active_rules:
            commitment_parts.append("\n🔴 剧情规则：")
            for r in active_rules:
                commitment_parts.append(f"  - 第{r.chapter_introduced}章「{r.rule_text}」")
                commitment_parts.append(f"    → IF {r.condition} THEN {r.consequence}")
            has_commitments = True

        if self.items:
            item_warnings = []
            for name, item in self.items.items():
                if item.prohibited_actions:
                    item_warnings.append(f"  - {name}：⛔ {', '.join(item.prohibited_actions)}")
            if item_warnings:
                commitment_parts.append("\n🔴 物品禁止操作：")
                commitment_parts.extend(item_warnings)
                has_commitments = True

        if timeline_events:
            deadline_events = []
            for e in timeline_events:
                if e.chapter >= chapter:
                    continue
                tt = e.time_tag or ""
                deadline_keywords = ["天后", "之后", "之内", "前", "马上", "立刻", "尽快", "三日内", "三日后"]
                if any(kw in tt for kw in deadline_keywords) or any(kw in (e.event or "") for kw in deadline_keywords):
                    deadline_events.append(e)
            if deadline_events:
                commitment_parts.append("\n🟡 时间死线：")
                for e in deadline_events:
                    commitment_parts.append(f"  - 第{e.chapter}章：{e.time_tag} — {e.event}")
                has_commitments = True

        if has_commitments:
            parts.append("\n## ⚠️ 承诺清单（本章写作前必须逐条确认，违反任何一条即为bug）")
            parts.extend(commitment_parts)
        else:
            parts.append("\n## ⚠️ 承诺清单：（无未兑现承诺）")

        # 5. 任务清单
        active_tasks = self.get_active_tasks(current_chapter=chapter)
        if active_tasks:
            parts.append("\n## 🎯 任务清单（活跃，跨章节长线任务）")
            for t in active_tasks:
                parts.append(f"- [{t.status}] {t.name}：{t.description}")
                if t.progress:
                    parts.append(f"    当前进度：{t.progress}")
        else:
            parts.append("\n## 🎯 任务清单：（无活跃任务）")

        return "\n".join(parts)

    def get_generation_contract(self, chapter: int, characters: List[str]) -> str:
        """一致性契约"""
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

            status_tag = ""
            if c.status == "dead":
                status_tag = " ⚰️【已死亡——本章不得出场，除非回忆/幻象】"
            elif c.status == "missing":
                status_tag = " ❓【失踪——本章不得直接出场，除非交代行踪】"
            lines.append(f"  ═══ {char_name}{status_tag} ═══")

            if c.personality:
                lines.append(f"  🔒 性格锁定：{c.personality}")
                lines.append(f"     → 本章中 {char_name} 的所有言行必须符合此性格，不得性格突变。")
            if c.speaking_style:
                lines.append(f"  🔒 语言风格锁定：{c.speaking_style}")
                lines.append(f"     → {char_name} 的对话风格必须与以上一致。")
            if c.cultivation:
                lines.append(f"  🔒 修为锁定：{c.cultivation}")
                lines.append(f"  → 不得低于或远超此修为（除非本章明确描写突破/受伤降级）。")
                lines.append(f"  → 其他角色提及 {char_name} 修为时也必须使用「{c.cultivation}」，"
                             f"除非描写了隐藏气息/易容等刻意隐瞒行为。")
            if c.learned_skills:
                for s in c.learned_skills:
                    sk = s.get("skill", "")
                    prog = s.get("progress", 0)
                    ch_lrn = s.get("chapter_learned", 0)
                    ch_upd = s.get("last_updated_chapter", ch_lrn)
                    pct = f"{prog*100:.0f}%" if isinstance(prog, (int, float)) and prog > 0 else ""
                    if sk:
                        lines.append(f"  🔒 技能锁定：{sk}（进度{' ' + pct if pct else '未知'}，第{ch_lrn}章习得，最新更新第{ch_upd}章）")
                        lines.append(f"     → {sk} 的技能进度/等级只能提升不能倒退。")
            if c.current_location:
                lines.append(f"  📍 上一章末位置：{c.current_location}")
                lines.append(f"     → 如果本章 {char_name} 出现在其他地点，必须描写移动过程（交通方式/耗时）。")
            if c.background:
                lines.append(f"  🔒 背景锁定：{c.background}")
                lines.append(f"     → {char_name} 的出身/历史不得被篡改。")

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

        lines.append(f"\n  ═══ 时间跨度约束 ═══")
        gap = self.outline_manager.get_day_gap(chapter)
        cur_day = self.outline_manager.get_chapter_day(chapter)
        if gap >= 2:
            time_word = "前天" if gap == 2 else f"{gap}天前"
            lines.append(f"  ⏱️ 距第{chapter-1}章已过 {gap} 天")
            lines.append(f"     → 引用第{chapter-1}章事件时，应使用「{time_word}」，不得使用「昨天」。")
            if cur_day:
                lines.append(f"  📅 当前是故事第 {cur_day} 天")
        elif gap == 1 and cur_day:
            lines.append(f"  📅 当前是故事第 {cur_day} 天（距上章1天，正常）")
        elif cur_day:
            lines.append(f"  📅 当前是故事第 {cur_day} 天（距上章无间隔，同一天事件）")
        else:
            lines.append(f"  （无天数数据）")

        anchor_re = re.compile(r'(?:' + r'\d+' + r'|' + '[零一二三四五六七八九十百千]+' + r')[年月天]前')
        anchors = []
        for key, ws in self.world_settings.items():
            if anchor_re.search(ws.value):
                anchors.append(f"  📅 {key}：{ws.value[:60]}")
        for char_name, char in self.characters.items():
            if char.background and anchor_re.search(char.background) and char_name in characters:
                anchors.append(f"  📅 {char_name}背景：{char.background[:60]}")
        if anchors:
            lines.append(f"\n  ═══ 叙事时间锚点（角色对话引用时必须使用正确时间描述） ═══")
            for a in anchors:
                lines.append(a)
            lines.append(f"  ⚠️ 以上事件在设定中有明确时间锚点。角色对话提及时应使用对应「X年前」时间词，不得写作「最近」「刚」「前些日子」等模糊描述。")

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

        absent_with_location = []
        for name, char in self.characters.items():
            if (name not in characters and char.current_location
                    and char.status != "dead" and char.first_appeared <= chapter):
                absent_with_location.append(f"  → {name}：{char.current_location}（第{char.first_appeared}章出场）")
        if absent_with_location:
            lines.append(f"\n  ═══ 未出场角色的空间位置（跨章追踪） ═══")
            for a in absent_with_location:
                lines.append(a)
            lines.append(f"  ⚠️ 以上角色不出场本章，但位置已存在于世界中。如果本章角色提及他们（回忆/传音/他人转述），"
                         f"空间位置必须与最后已知位置自洽，不得无理由出现在本章场景中。")

        active_tasks = self.get_active_tasks(current_chapter=chapter)
        if active_tasks:
            has_content = True
            lines.append(f"\n  ═══ 活跃任务（未完成的支线/承诺） ═══")
            for t in active_tasks:
                related = []
                if t.related_characters:
                    related.append(f"涉及人物：{', '.join(t.related_characters)}")
                if t.related_items:
                    related.append(f"涉及物品：{', '.join(t.related_items)}")
                tag = f"（{'；'.join(related)}）" if related else ""
                lines.append(f"  📋 {t.name}【{t.status}】{tag}")
                lines.append(f"     → {t.description}")
            lines.append(f"  ⚠️ 如果角色对话提及以上任务的时间期限/条件，必须与任务描述一致，不得自相矛盾。")

        if not has_content:
            return "（无特殊一致性约束）"
        lines.append(f"\n  ⛔ 以上所有约束均为硬性宪法级别。违反任何一条都将导致剧情矛盾，审校时会标记为「高」严重性。")
        return "\n".join(lines)
