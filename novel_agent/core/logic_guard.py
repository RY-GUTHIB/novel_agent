"""
logic_guard.py - 逻辑约束引擎（纯规则，不调 LLM）

在 write_chapter 调用前，从结构化数据中提取所有硬约束，
构建一段精炼的「本章写作约束」文本注入 Writer prompt。

约束来源：
- characters.json：人物档案（实力、关系、认知）
- plot_rules.json：当前生效的剧情规则
- timeline.json：已发生的关键事件（禁止重复）
- items：物品归属（禁止重复赠与）
- character_knowledge.json：角色已知信息边界
"""

from typing import List, Dict, Optional


class LogicGuard:
    """逻辑约束引擎 —— 纯规则提取，生成前注入"""

    def __init__(self, memory_manager, continuity_guard):
        self.memory = memory_manager
        self.continuity = continuity_guard

    def build_constraints(self, chapter: int,
                          characters: List[str],
                          location: str) -> str:
        """
        构建本章写作约束文本。
        分四个区块：认知边界、关系立场、实力边界、物品红线。
        """
        sections = []

        # 1. 认知边界
        kb_section = self._build_knowledge_boundary(chapter, characters)
        if kb_section:
            sections.append(kb_section)

        # 2. 关系立场
        rel_section = self._build_relationship_stance(characters)
        if rel_section:
            sections.append(rel_section)

        # 3. 实力边界
        power_section = self._build_power_boundary(characters)
        if power_section:
            sections.append(power_section)

        # 5. 已发生关键事件（禁止重复）
        event_section = self._build_completed_events(chapter)
        if event_section:
            sections.append(event_section)

        # 6. 当前生效规则
        rule_section = self._build_active_rules()
        if rule_section:
            sections.append(rule_section)

        if not sections:
            return "（无特殊逻辑约束）"

        return "\n\n".join(sections)

    # ====== 认知边界 ======

    def _build_knowledge_boundary(self, chapter: int,
                                   characters: List[str]) -> str:
        """提取本章角色的已知信息边界（防止角色知道不该知道的事）"""
        knowledge = self.memory.character_knowledge
        if not knowledge:
            return ""

        # 找出本章出场角色已知的信息
        lines = ["【认知边界（⚠️ 严格按此写角色反应，不可跨越信息差）】"]
        has_content = False

        for ck in knowledge:
            if ck.character in characters and ck.chapter_learned <= chapter:
                lines.append(f"  - {ck.character} 已知：{ck.knowledge}"
                             f"（来源：{ck.source}，第{ck.chapter_learned}章获知）")
                has_content = True

        if not has_content:
            return ""

        lines.append("  ⚠️ 角色不能对未获知的信息表现出惊讶、好奇或首次获知以外的反应。")
        return "\n".join(lines)

    # ====== 关系立场 ======

    def _build_relationship_stance(self, characters: List[str]) -> str:
        """提取本章出场角色之间的关系立场（防止立场突变）"""
        if not self.memory.characters:
            return ""

        lines = ["【关系立场（⚠️ 角色互动必须遵守此立场，不可突变）】"]
        has_content = False

        for char_name in characters:
            if char_name not in self.memory.characters:
                continue
            char = self.memory.characters[char_name]
            for other, rel_detail in char.relationships_detail.items():
                if other in characters and isinstance(rel_detail, dict):
                    stance = rel_detail.get("stance", "neutral")
                    rel_type = rel_detail.get("type", "")
                    met_ch = rel_detail.get("met_chapter", 0)
                    lines.append(f"  {char_name} ↔ {other}：{rel_type}，立场={stance}"
                                 f"（第{met_ch}章相识）")
                    has_content = True
            # 也检查简单关系
            for other, rel in char.relationships.items():
                if other in characters and other not in char.relationships_detail:
                    lines.append(f"  {char_name} ↔ {other}：{rel}，立场=未记录")
                    has_content = True

        if has_content:
            lines.append("  ⚠️ 友好关系不能突然反目（除非有充分铺垫）；敌对关系不能突然亲密。")
            return "\n".join(lines)
        return ""

    # ====== 实力边界 ======

    def _build_power_boundary(self, characters: List[str]) -> str:
        """提取本章出场角色的实力/修为边界"""
        if not self.memory.characters:
            return ""

        lines = ["【实力边界（⚠️ 战斗描写必须遵守此修为等级）】"]
        has_content = False

        for char_name in characters:
            if char_name not in self.memory.characters:
                continue
            char = self.memory.characters[char_name]
            if char.cultivation:
                lines.append(f"  {char_name}：{char.cultivation}"
                             f"{' | 能力：' + '、'.join(char.abilities) if char.abilities else ''}")
                has_content = True

        if has_content:
            lines.append("  ⚠️ 角色不能施展超越其修为的能力（除非本章明确描写突破）。")
            lines.append("  ⚠️ 实力对比必须自洽：境界高的角色不应被境界低的角色轻松碾压。")
            return "\n".join(lines)
        return ""

    # ====== 已完成事件 ======

    def _build_completed_events(self, chapter: int) -> str:
        """已完成的关键事件（禁止重复情节）"""
        events = [e for e in self.continuity.timeline if e.chapter < chapter]
        if not events:
            return ""

        key_events = sorted(events, key=lambda x: -x.importance)[:15]
        lines = ["【已完成的关键事件（⚠️ 禁止重复这些情节）】"]
        for e in key_events:
            lines.append(f"  第{e.chapter}章：{e.event}")

        lines.append("  ⚠️ 以上事件已经发生过，本章请勿重复类似情节。")
        return "\n".join(lines)

    # ====== 当前规则 ======

    def _build_active_rules(self) -> str:
        """当前生效的剧情规则"""
        rules = self.memory.plot_rules
        active_rules = {k: v for k, v in rules.items() if not v.overridden}
        if not active_rules:
            return ""

        lines = ["【当前生效的剧情规则（⚠️ 不可违反）】"]
        for key, rule in active_rules.items():
            lines.append(f"  - {rule.rule_text}（第{rule.chapter_introduced}章引入）")

        lines.append("  ⚠️ 角色行为不得违反以上任何一条规则。")
        return "\n".join(lines)
