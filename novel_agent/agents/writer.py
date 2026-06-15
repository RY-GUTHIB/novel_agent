"""
writer_agent.py - 章节写作 Agent

职责：
1. 根据大纲生成本章内容
2. 注入前文摘要、人物状态、伏笔提醒
3. 更新 continuity 和 foreshadow 状态
"""

import json
import logging
import re
import config
from pathlib import Path
from typing import List

from novel_agent.llm.client import generate
from novel_agent.core.models import (
    CharacterProfile, LocationProfile, WorldSetting,
    PlotRule, CharacterKnowledge, SectFaction, SceneEvent, SpaceNode,
)
from novel_agent.core.memory import MemoryManager
from novel_agent.core.continuity import ContinuityGuard
from novel_agent.core.foreshadow import ForeshadowTracker
from novel_agent.core.rag import RAGStore
from .prompts import (
    CHAPTER_WRITER_SYSTEM_PROMPT, CHAPTER_WRITER_USER_PROMPT,
    CHAPTER_REVISER_SYSTEM_PROMPT, CHAPTER_REVISER_USER_PROMPT,
    SETTINGS_EXTRACT_PROMPT, SETTINGS_EXTRACT_SYSTEM_PROMPT,
    FORESHADOW_SCAN_PROMPT, FORESHADOW_SCAN_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)


class WriterAgent:
    """章节写作 Agent"""

    def __init__(self, memory_mgr: MemoryManager, continuity_guard: ContinuityGuard,
                  foreshadow_tracker: ForeshadowTracker, rag_store: RAGStore = None,
                  genre: str = "玄幻", style: str = "热血"):
        self.memory = memory_mgr
        self.continuity = continuity_guard
        self.foreshadow = foreshadow_tracker
        self.rag = rag_store
        self.genre = genre
        self.style = style

    # ========== 核心生成 ==========

    def write_chapter(self, chapter: int, title: str, summary: str,
                       time_tag: str, location: str, characters: List[str],
                       temperature: float = config.TEMPERATURE) -> str:
        # 1. 冲突检测 + 预检
        char_loc_map = {char: location for char in characters}
        warnings = self.continuity.check_continuity(chapter, char_loc_map, time_tag)
        pre_warnings = self.memory.validate_chapter_characters(chapter, characters)
        if pre_warnings:
            for w in pre_warnings:
                print(f"    {w}")
        generation_contract = self.memory.get_generation_contract(chapter, characters)

        # 2. 构建 prompt
        system_prompt = CHAPTER_WRITER_SYSTEM_PROMPT.format(
            genre=self.genre, style=self.style, word_target=config.CHAPTER_WORD_TARGET,
        )
        user_prompt = self._build_writer_user_prompt(
            chapter, title, summary, time_tag, location, characters, generation_contract,
        )

        # 3. 调用 LLM（一次调用同时生成正文 + 设定 JSON）
        raw_output = generate(system_prompt=system_prompt, user_prompt=user_prompt,
                              temperature=temperature, max_tokens=config.MAX_TOKENS)

        # 4. 解析：分离正文和设定 JSON
        content, settings_json = self._split_output_and_settings(raw_output)

        # 5. 后处理
        self._post_write(chapter, title, content, summary, time_tag, location, characters,
                         settings_json=settings_json)

        return content

    def revise_chapter(self, chapter: int, title: str, original_content: str,
                        review_report: str, summary: str, time_tag: str,
                        location: str, characters: List[str],
                        temperature: float = 0.3) -> str:
        generation_contract = self.memory.get_generation_contract(chapter, characters)
        system_prompt = CHAPTER_REVISER_SYSTEM_PROMPT.format(word_target=config.CHAPTER_WORD_TARGET)
        user_prompt = self._build_reviser_user_prompt(
            chapter, title, review_report, original_content, summary,
            time_tag, location, characters, generation_contract,
        )

        raw_output = generate(system_prompt=system_prompt, user_prompt=user_prompt,
                              temperature=temperature, max_tokens=config.MAX_TOKENS)

        content, settings_json = self._split_output_and_settings(raw_output)

        self._post_write(chapter, title, content, summary, time_tag, location, characters,
                         skip_scan=True, settings_json=settings_json)
        return content

    # ========== Prompt 构建 ==========

    def _build_writer_user_prompt(self, chapter, title, summary, time_tag,
                                    location, characters, generation_contract) -> str:
        character_prompts = "\n\n".join(
            self.memory.get_character_prompt(c) for c in characters if c in self.memory.characters
        )
        continuity_prompt = self.continuity.generate_continuity_prompt(
            chapter,
            plot_rules_text=self.memory.get_active_rules_prompt(),
            character_knowledge_text=self.memory.get_character_knowledge_prompt(chapter=chapter),
        )
        rag_context = self._get_rag_context(chapter, title, summary, characters)

        # 设定提取上下文（合并到写作 prompt 中，省掉单独的 LLM 调用）
        char_summary_text = self._build_char_summary(characters)
        existing_ws_text = ", ".join(sorted(self.memory.world_settings.keys())) if self.memory.world_settings else "（无）"
        existing_loc_text = ", ".join(sorted(self.memory.locations.keys())) if self.memory.locations else "（无）"
        existing_sect_text = ", ".join(sorted(self.memory.sect_factions.keys())) if self.memory.sect_factions else "（无）"

        return CHAPTER_WRITER_USER_PROMPT.format(
            chapter=chapter, title=title, summary=summary,
            time_tag=time_tag, location=location, characters="、".join(characters),
            generation_contract=generation_contract,
            continuity_prompt=continuity_prompt,
            character_prompts=character_prompts or "（无）",
            world_settings=self.memory.get_world_settings_prompt(),
            sect_factions=self.memory.get_sect_factions_prompt(),
            plot_rules=self.memory.get_active_rules_prompt(),
            character_knowledge=self.memory.get_character_knowledge_prompt(chapter=chapter),
            relationship_details=self.memory.get_all_relationships_prompt(),
            scene_events=self.memory.get_scene_events_prompt(chapter=chapter),
            foreshadow_prompt=self.foreshadow.generate_foreshadow_prompt(chapter),
            rag_context=rag_context,
            char_summary_text=char_summary_text,
            existing_ws_text=existing_ws_text,
            existing_loc_text=existing_loc_text,
            existing_sect_text=existing_sect_text,
        )

    def _build_char_summary(self, characters: list) -> str:
        """构建已有人物摘要（用于设定提取上下文）"""
        lines = []
        for name in characters:
            if name not in self.memory.characters:
                continue
            c = self.memory.characters[name]
            abilities_str = ", ".join(c.abilities)
            rels_str = ", ".join(f"{k}({v})" for k, v in c.relationships.items())
            lines.append(
                f"  {name}：{c.gender}，{c.age}，修为={c.cultivation}，"
                f"能力[{abilities_str}]，关系[{rels_str}]，状态={c.status}"
            )
        return "\n".join(lines) if lines else "（无）"

    def _build_reviser_user_prompt(self, chapter, title, review_report, original_content,
                                     summary, time_tag, location, characters,
                                     generation_contract) -> str:
        character_prompts = "\n\n".join(
            self.memory.get_character_prompt(c) for c in characters if c in self.memory.characters
        )
        continuity_prompt = self.continuity.generate_continuity_prompt(
            chapter,
            plot_rules_text=self.memory.get_active_rules_prompt(),
            character_knowledge_text=self.memory.get_character_knowledge_prompt(chapter=chapter),
        )

        return CHAPTER_REVISER_USER_PROMPT.format(
            chapter=chapter, title=title, review_report=review_report,
            original_content=original_content, summary=summary,
            time_tag=time_tag, location=location, characters="、".join(characters),
            generation_contract=generation_contract,
            continuity_prompt=continuity_prompt,
            character_prompts=character_prompts or "（无）",
            world_settings=self.memory.get_world_settings_prompt(),
            sect_factions=self.memory.get_sect_factions_prompt(),
            plot_rules=self.memory.get_active_rules_prompt(),
            character_knowledge=self.memory.get_character_knowledge_prompt(chapter=chapter),
            relationship_details=self.memory.get_all_relationships_prompt(),
            scene_events=self.memory.get_scene_events_prompt(chapter=chapter),
            foreshadow_prompt=self.foreshadow.generate_foreshadow_prompt(chapter),
        )

    def _get_rag_context(self, chapter, title, summary, characters) -> str:
        if not self.rag:
            return "（无相关前文片段）"
        try:
            rag_query = f"{title} {summary} {' '.join(characters)}"
            rag_results = self.rag.search(rag_query, filter_chapter_lt=chapter)
            if rag_results:
                return "\n\n---\n\n".join(r["document"] for r in rag_results)
        except Exception:
            pass
        return "（无相关前文片段）"

    # ========== 写后处理 ==========

    def _post_write(self, chapter, title, content, summary, time_tag,
                     location, characters, skip_scan=False, settings_json=None):
        # 提取伏笔
        new_fs = self._extract_foreshadows(content, chapter, skip_scan=skip_scan)
        for fs_content in new_fs:
            self.foreshadow.plant(chapter=chapter, content=fs_content, type="mystery",
                                  related_characters=characters, importance=2)

        # 更新连续性
        self.continuity.add_event(chapter=chapter, time_tag=time_tag, event=summary,
                                  characters=characters, location=location, importance=3)
        for char in characters:
            existing = [cl for cl in self.continuity.character_locations
                        if cl.chapter == chapter and cl.character == char]
            if not existing:
                self.continuity.add_character_location(chapter=chapter, character=char,
                                                       location=location, note="粗粒度回退")
            if char in self.memory.characters:
                self.memory.update_character_status(char, notes=f"第{chapter}章出现于{location}")

        # RAG 存储
        if self.rag:
            try:
                self.rag.add_chapter(chapter, title, content)
            except Exception:
                pass

        # 保存
        self.continuity.save_all()
        self.foreshadow._save()

        # 应用设定（从合并输出中解析）
        if settings_json:
            self._apply_settings(settings_json, chapter)
        else:
            print(f"  [设定] 未解析到设定 JSON，跳过（下一次 write 会补录）")

        # 更新伏笔总览
        try:
            self.foreshadow.export_to_markdown()
        except Exception:
            pass

    # ========== 输出解析 ==========

    @staticmethod
    def _split_output_and_settings(raw_output: str) -> tuple:
        """从 LLM 输出中分离正文和设定 JSON"""
        separator = "===SETTINGS_JSON==="
        if separator in raw_output:
            parts = raw_output.split(separator, 1)
            content = parts[0].strip()
            settings_text = parts[1].strip()
            # 移除可能的 ```json ... ``` 包裹
            settings_text = re.sub(r'^```json\s*', '', settings_text)
            settings_text = re.sub(r'\s*```$', '', settings_text)
            settings_json = WriterAgent._parse_json(settings_text)
            if settings_json:
                print(f"  [合并解析] 正文 {len(content)} 字，设定 JSON 解析成功")
                return content, settings_json
            else:
                print(f"  [合并解析] 正文 {len(content)} 字，设定 JSON 解析失败，将 fallback")
                return content, None
        else:
            print(f"  [合并解析] 未找到分隔符，正文 {len(raw_output)} 字")
            return raw_output, None

    def _apply_settings(self, parsed: dict, chapter: int):
        """应用从合并输出中解析的设定 JSON（复用原有 9 个方法）"""
        if not parsed:
            return
        try:
            self._apply_characters(parsed.get("characters", []), chapter)
            self._apply_world_settings(parsed.get("world_settings", []), chapter)
            self._apply_locations(parsed.get("locations", []), chapter)
            self._apply_spatial_movements(parsed.get("spatial_movements", []), chapter)
            self._apply_spacemap_updates(parsed.get("spacemap_updates", []))
            self._apply_plot_rules(parsed.get("plot_rules", []), chapter)
            self._apply_character_knowledge(parsed.get("character_knowledge", []), chapter)
            self._apply_sect_factions(parsed.get("sect_factions", []), chapter)
            self._apply_scene_events(parsed.get("scene_events", []), chapter)
        except Exception as e:
            print(f"  [WARN] 设定应用失败: {e}")

    # ========== 伏笔提取 ==========

    def _extract_foreshadows(self, content: str, chapter: int, skip_scan: bool = False) -> List[str]:
        results = []
        results.extend(re.findall(r'\[FS:\s*(.*?)\s*\]', content))
        results.extend(re.findall(r'FS：\s*(.*?)(?:\r?\n|$)', content))
        results.extend(re.findall(r'\[FS：\s*(.*?)\s*\]', content))

        if skip_scan:
            return list(set(results))

        try:
            scan_result = generate(
                system_prompt=FORESHADOW_SCAN_SYSTEM_PROMPT,
                user_prompt=FORESHADOW_SCAN_PROMPT.format(content=content[-2000:]),
                temperature=0.3, max_tokens=512,
            )
            fs_list = self._parse_json_array(scan_result)
            for fs in fs_list:
                if isinstance(fs, dict) and "content" in fs:
                    results.append(fs["content"])
        except Exception as e:
            print(f"  [WARN] LLM 伏笔扫描失败: {e}")

        return list(set(results))

    # ========== 设定提取（拆分为独立方法）==========

    def _extract_and_save_world_settings(self, content: str, chapter: int):
        try:
            parsed = self._call_settings_extractor(content, chapter)
            if not parsed:
                print("  [设定提取] 未能解析 LLM 输出，跳过")
                return

            self._apply_characters(parsed.get("characters", []), chapter)
            self._apply_world_settings(parsed.get("world_settings", []), chapter)
            self._apply_locations(parsed.get("locations", []), chapter)
            self._apply_spatial_movements(parsed.get("spatial_movements", []), chapter)
            self._apply_spacemap_updates(parsed.get("spacemap_updates", []))
            self._apply_plot_rules(parsed.get("plot_rules", []), chapter)
            self._apply_character_knowledge(parsed.get("character_knowledge", []), chapter)
            self._apply_sect_factions(parsed.get("sect_factions", []), chapter)
            self._apply_scene_events(parsed.get("scene_events", []), chapter)
        except Exception as e:
            print(f"  [WARN] 设定提取失败: {e}")

    def _call_settings_extractor(self, content: str, chapter: int):
        """调用 LLM 提取设定"""
        existing_ws_keys = set(self.memory.world_settings.keys())
        existing_loc_names = set(self.memory.locations.keys())
        existing_sect_names = set(self.memory.sect_factions.keys())

        char_summaries = []
        for name, c in self.memory.characters.items():
            abilities_str = ", ".join(c.abilities)
            rels_str = ", ".join(f"{k}({v})" for k, v in c.relationships.items())
            char_summaries.append(
                f"  {name}：{c.gender}，{c.age}，修为={c.cultivation}，"
                f"能力[{abilities_str}]，关系[{rels_str}]，状态={c.status}"
            )

        json_format_example = json.dumps({
            "characters": [{"name": "人物名", "is_new": True, "updates": {}}],
            "world_settings": [{"key": "设定名", "value": "设定描述"}],
            "sect_factions": [{"name": "势力名", "is_new": True, "updates": {}}],
            "locations": [{"name": "地点名", "is_new": False, "updates": {}}],
            "scene_events": [{"location": "地点", "scene": "场景", "event": "事件", "characters": [], "importance": 3}],
            "spatial_movements": [{"character": "人物", "from_location": "A", "to_location": "B", "scene": "", "travel_method": "", "travel_time": "", "note": ""}],
            "spacemap_updates": [{"from_location": "A", "to_location": "B", "travel_time": "", "is_bidirectional": True}],
            "plot_rules": [{"condition": "条件", "consequence": "结果", "rule_text": "原文", "source_character": ""}],
            "character_knowledge": [{"character": "角色", "knowledge": "知道了什么", "source": "怎么知道", "detail": ""}],
        }, ensure_ascii=False, indent=2)

        prompt = SETTINGS_EXTRACT_PROMPT.format(
            char_summary_text="\n".join(char_summaries) if char_summaries else "（无）",
            existing_ws_text=", ".join(sorted(existing_ws_keys)) if existing_ws_keys else "（无）",
            existing_loc_text=", ".join(sorted(existing_loc_names)) if existing_loc_names else "（无）",
            existing_sect_text=", ".join(sorted(existing_sect_names)) if existing_sect_names else "（无）",
            json_format_example=json_format_example,
            content=content,
        )

        result = generate(
            system_prompt=SETTINGS_EXTRACT_SYSTEM_PROMPT,
            user_prompt=prompt, temperature=0.2, max_tokens=2048,
        )
        return self._parse_json(result)

    def _apply_characters(self, items: list, chapter: int):
        new_count = updated_count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "").strip()
            is_new = item.get("is_new", False)
            updates = item.get("updates", {})

            if is_new:
                new_char = CharacterProfile(
                    name=name, gender=updates.get("gender", ""), age=updates.get("age", ""),
                    appearance=updates.get("appearance", ""), personality=updates.get("personality", ""),
                    background=updates.get("background", ""), goals=updates.get("goals", ""),
                    speaking_style=updates.get("speaking_style", ""), abilities=updates.get("abilities", []),
                    relationships=updates.get("relationships", {}), status=updates.get("status", "alive"),
                    first_appeared=chapter, arc=updates.get("arc", ""), notes=updates.get("notes", ""),
                )
                for other, ctx in updates.get("relationship_contexts", {}).items():
                    if isinstance(ctx, dict):
                        new_char.relationships_detail[other] = ctx
                self.memory.add_character(new_char)
                new_count += 1
            elif name in self.memory.characters:
                char = self.memory.characters[name]
                for ab in updates.get("abilities", []):
                    if ab and ab not in char.abilities:
                        char.abilities.append(ab)
                for other, rel in updates.get("relationships", {}).items():
                    if other and rel:
                        char.relationships[other] = rel
                for other, ctx in updates.get("relationship_contexts", {}).items():
                    if isinstance(ctx, dict) and other:
                        if other in char.relationships_detail:
                            existing = char.relationships_detail[other]
                            for k, v in ctx.items():
                                if k == "key_events" and isinstance(v, list):
                                    for evt in v:
                                        if evt not in existing.get("key_events", []):
                                            existing.setdefault("key_events", []).append(evt)
                                elif v:
                                    existing[k] = v
                        else:
                            char.relationships_detail[other] = ctx
                for field_name in ["cultivation", "appearance", "personality", "status", "goals", "notes"]:
                    val = updates.get(field_name, "")
                    if val:
                        setattr(char, field_name, val)
                updated_count += 1

        if new_count or updated_count:
            self.memory._save_characters()
            parts = []
            if new_count:
                parts.append(f"新增 {new_count} 个人物")
            if updated_count:
                parts.append(f"更新 {updated_count} 个人物")
            print(f"  [设定提取·人物] {', '.join(parts)}")

    def _apply_world_settings(self, items: list, chapter: int):
        count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            key, value = item.get("key", "").strip(), item.get("value", "").strip()
            if not key or not value:
                continue
            if key in self.memory.world_settings:
                old = self.memory.world_settings[key].value
                if value not in old:
                    self.memory.world_settings[key].value = old + "；" + value
            else:
                self.memory.add_world_setting(WorldSetting(key=key, value=value, chapter_introduced=chapter))
                count += 1
        if count:
            self.memory._save_world_settings()
            print(f"  [设定提取·世界] 新增 {count} 条世界设定")

    def _apply_locations(self, items: list, chapter: int):
        new_count = updated_count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "").strip()
            is_new = item.get("is_new", False)
            updates = item.get("updates", {})

            if is_new:
                self.memory.add_location(LocationProfile(
                    name=name, description=updates.get("description", ""),
                    type=updates.get("type", "city"), connected_to=updates.get("connected_to", []),
                    first_appeared=chapter, notable_characters=updates.get("notable_characters", []),
                    notes=updates.get("notes", ""),
                ))
                new_count += 1
            elif name in self.memory.locations:
                loc = self.memory.locations[name]
                desc = updates.get("description", "")
                if desc and desc not in loc.description:
                    loc.description = loc.description.rstrip("。") + "；" + desc
                for nc in updates.get("notable_characters", []):
                    if nc and nc not in loc.notable_characters:
                        loc.notable_characters.append(nc)
                notes = updates.get("notes", "")
                if notes:
                    loc.notes = (loc.notes + "；" + notes) if loc.notes else notes
                updated_count += 1

        if new_count or updated_count:
            self.memory._save_locations()
            parts = []
            if new_count:
                parts.append(f"新增 {new_count} 个地点")
            if updated_count:
                parts.append(f"更新 {updated_count} 个地点")
            print(f"  [设定提取·地点] {', '.join(parts)}")

    def _apply_spatial_movements(self, items: list, chapter: int):
        count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            char_name = item.get("character", "").strip()
            to_loc = item.get("to_location", "").strip()
            if not char_name or not to_loc:
                continue
            note_parts = [p for p in [item.get("travel_method", ""), item.get("travel_time", ""), item.get("note", "")] if p]
            self.continuity.add_character_location(
                chapter=chapter, character=char_name, location=to_loc,
                scene=item.get("scene", ""), note="，".join(note_parts),
            )
            count += 1
        if count:
            self.continuity._save_character_locations()
            print(f"  [设定提取·空间] 记录 {count} 条人物移动")

    def _apply_spacemap_updates(self, items: list):
        count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            from_loc = item.get("from_location", "").strip()
            to_loc = item.get("to_location", "").strip()
            if not from_loc or not to_loc:
                continue
            travel_time = item.get("travel_time", "")
            is_bidir = item.get("is_bidirectional", True)

            self._update_spacemap_edge(from_loc, to_loc, travel_time)
            if is_bidir:
                self._update_spacemap_edge(to_loc, from_loc, travel_time)
            count += 1
        if count:
            self.continuity._save_spacemap()
            print(f"  [设定提取·连通] 更新 {count} 条地点连通")

    def _update_spacemap_edge(self, from_loc: str, to_loc: str, travel_time: str):
        if from_loc in self.continuity.spacemap:
            node = self.continuity.spacemap[from_loc]
            if to_loc not in node.connected_to:
                node.connected_to.append(to_loc)
            if travel_time:
                node.travel_time[to_loc] = travel_time
        else:
            self.continuity.add_location(SpaceNode(
                name=from_loc, connected_to=[to_loc],
                travel_time={to_loc: travel_time} if travel_time else {},
            ))

    def _apply_plot_rules(self, items: list, chapter: int):
        count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            condition = item.get("condition", "").strip()
            consequence = item.get("consequence", "").strip()
            if not condition or not consequence:
                continue
            self.memory.add_plot_rule(PlotRule(
                condition=condition, consequence=consequence,
                rule_text=item.get("rule_text", "").strip() or f"若{condition}，则{consequence}",
                chapter_introduced=chapter,
                source_character=item.get("source_character", "").strip(),
            ))
            count += 1
        if count:
            print(f"  [设定提取·规则] 新增 {count} 条剧情规则")

    def _apply_character_knowledge(self, items: list, chapter: int):
        count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            char_name = item.get("character", "").strip()
            knowledge = item.get("knowledge", "").strip()
            if not char_name or not knowledge:
                continue
            self.memory.add_character_knowledge(CharacterKnowledge(
                character=char_name, chapter_learned=chapter,
                knowledge=knowledge, source=item.get("source", "未知").strip(),
                detail=item.get("detail", "").strip(),
            ))
            count += 1
        if count:
            print(f"  [设定提取·认知] 新增 {count} 条角色认知")

    def _apply_sect_factions(self, items: list, chapter: int):
        new_count = updated_count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "").strip()
            is_new = item.get("is_new", False)
            updates = item.get("updates", {})
            if not name:
                continue
            if is_new or name not in self.memory.sect_factions:
                self.memory.add_sect_faction(SectFaction(
                    name=name, type=updates.get("type", ""), description=updates.get("description", ""),
                    strength=updates.get("strength", ""), hierarchy=updates.get("hierarchy", []),
                    key_members=updates.get("key_members", []), allies=updates.get("allies", []),
                    enemies=updates.get("enemies", []), location=updates.get("location", ""),
                    rules=updates.get("rules", []), first_appeared=chapter, notes=updates.get("notes", ""),
                ))
                new_count += 1
            else:
                self.memory.update_sect_faction(name, **{k: v for k, v in updates.items() if v})
                updated_count += 1

        if new_count or updated_count:
            parts = []
            if new_count:
                parts.append(f"新增 {new_count} 个势力")
            if updated_count:
                parts.append(f"更新 {updated_count} 个势力")
            print(f"  [设定提取·势力] {', '.join(parts)}")

    def _apply_scene_events(self, items: list, chapter: int):
        count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            location = item.get("location", "").strip()
            event = item.get("event", "").strip()
            if not location or not event:
                continue
            self.memory.add_scene_event(SceneEvent(
                chapter=chapter, location=location, scene=item.get("scene", ""),
                event=event, characters=item.get("characters", []),
                importance=item.get("importance", 1),
            ))
            count += 1
        if count:
            print(f"  [设定提取·场景] 新增 {count} 条场景事件")

    # ========== JSON 解析工具 ==========

    @staticmethod
    def _parse_json(text: str):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return None

    @staticmethod
    def _parse_json_array(text: str) -> list:
        try:
            result = json.loads(text)
            return result if isinstance(result, list) else []
        except json.JSONDecodeError:
            pass
        match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if match:
            try:
                result = json.loads(match.group(1))
                return result if isinstance(result, list) else []
            except json.JSONDecodeError:
                pass
        return []

    # ========== 文件操作 ==========

    def save_chapter(self, chapter: int, title: str, content: str, output_dir: str = None):
        out_dir = Path(output_dir or config.OUTPUT_DIR)
        chapters_dir = out_dir / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)
        chapter_path = chapters_dir / f"chapter_{chapter:03d}.md"
        with open(chapter_path, "w", encoding="utf-8") as f:
            f.write(f"# 第{chapter}章 {title}\n\n{content}")

    def load_chapter(self, chapter: int, output_dir: str = None) -> str:
        out_dir = Path(output_dir or config.OUTPUT_DIR)
        chapter_path = out_dir / "chapters" / f"chapter_{chapter:03d}.md"
        if chapter_path.exists():
            with open(chapter_path, "r", encoding="utf-8") as f:
                return f.read()
        return ""
