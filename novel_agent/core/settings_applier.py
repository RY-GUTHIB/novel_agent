"""
settings_applier.py - SETTINGS_JSON 设定回写器
"""

import logging

from .memory import MemoryManager

logger = logging.getLogger(__name__)
from .continuity import ContinuityGuard
from .models import (
    CharacterProfile, LocationProfile, WorldSetting,
    PlotRule, CharacterKnowledge, SectFaction, SceneEvent,
    ItemProfile, TaskProfile,
)


class SettingsApplier:
    """SETTINGS_JSON 设定回写器——只应在审校通过后调用。"""

    def __init__(self, memory: MemoryManager, continuity: ContinuityGuard):
        self.memory = memory
        self.continuity = continuity

    def apply_all(self, parsed: dict, chapter: int):
        """统一回写所有设定（人物/物品/位置/势力/世界设定/场景事件/连续性）。"""
        if not parsed:
            return
        try:
            self.apply_characters(parsed.get("characters", []), chapter)
            self.apply_world_settings(parsed.get("world_settings", []), chapter)
            self.apply_locations(parsed.get("locations", []), chapter)
            self.apply_spatial_movements(parsed.get("spatial_movements", []), chapter)
            self.apply_spacemap_updates(parsed.get("spacemap_updates", []))
            self.apply_plot_rules(parsed.get("plot_rules", []), chapter)
            self.apply_character_knowledge(parsed.get("character_knowledge", []), chapter)
            self.apply_sect_factions(parsed.get("sect_factions", []), chapter)
            self.apply_scene_events(parsed.get("scene_events", []), chapter)
            self.apply_items(parsed.get("items", []), chapter)
            self.apply_tasks(parsed.get("tasks", []), chapter)
            self.apply_timeline_events(parsed.get("timeline_events", []), chapter)
            self.apply_style(parsed.get("style", {}))
            self.apply_arc_events(parsed.get("arc_events", []), chapter)
            # 回写本章摘要到大纲
            summary_text = parsed.get("summary", "").strip()
            if summary_text:
                try:
                    self.memory.outline_manager.backfill_summary(chapter, summary_text)
                except Exception as e:
                    logger.warning("摘要回写大纲失败: %s", e)
        except (KeyError, ValueError, TypeError, AttributeError) as e:
            logger.error("设定回写失败: %s", e)
            raise

    # 路人名字（完全匹配才判定为路人，名字含职业/身份的有名字角色不跳过）
    # 注意：子串匹配（如"掌柜"匹配"王掌柜"）会导致误跳过，因此只做完全匹配
    _MINOR_NAME_KEYWORDS = (
        # 餐饮/服务
        "小二", "店小二", "伙计", "跑堂",
        "掌柜", "老板",
        # 仆役/杂役
        "小厮", "仆人", "下人", "杂役", "奴仆", "丫鬟", "侍女", "侍从",
        # 兵卒/守卫（单独出现时无名字）
        "守卫", "兵卒", "士兵", "晓卒", "卫兵", "亲兵",
        # 泛指/匿名
        "路人", "百姓", "平民", "民众", "群众", "围观", "过客", "行人",
        "乞丐", "流民", "难民",
        "匿名", "无名", "某某", "某人",
        # 商贩
        "小贩", "摊贩", "商贩", "货郎",
        # 门派底层（单独出现时无名字）
        "外门弟子", "杂役弟子", "记名弟子",
        # 其他功能性称呼
        "媒婆", "稳婆", "仵作", "轿夫", "马夫", "船夫",
        # 复合称呼（LLM 可能直接输出的完整称呼）
        "店小二", "守门侍卫", "巡逻兵卒", "杂役弟子", "外门执事",
    )

    def _is_minor_character(self, name: str) -> bool:
        """判断是否为路人角色（仅完全匹配关键词才跳过，含名字的不跳过）"""
        return name in self._MINOR_NAME_KEYWORDS

    def apply_characters(self, items: list, chapter: int):
        new_count = updated_count = skipped_minor = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "").strip()
            is_new = item.get("is_new", False)
            updates = item.get("updates", {})

            if is_new:
                # 路人不记录：信息极少的人物跳过
                if self._is_minor_character(name):
                    skipped_minor += 1
                    logger.debug("跳过路人角色：%s", name)
                    continue
                new_char = CharacterProfile(
                    name=name, gender=updates.get("gender", ""), age=updates.get("age", ""),
                    appearance=updates.get("appearance", ""), personality=updates.get("personality", ""),
                    background=updates.get("background", ""), goals=updates.get("goals", ""),
                    speaking_style=updates.get("speaking_style", ""), abilities=updates.get("abilities", []),
                    relationships=updates.get("relationships", {}), status=updates.get("status", "alive"),
                    first_appeared=chapter, arc=updates.get("arc", ""), notes=updates.get("notes", ""),
                    learned_skills=updates.get("learned_skills", []),
                    faction=updates.get("faction", ""), faction_status=updates.get("faction_status", ""),
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
                for field_name in ["cultivation", "current_location", "appearance", "personality", "status",
                                    "goals", "notes", "core_values", "core_desire", "core_fear",
                                    "flaw", "alignment", "background", "speaking_style", "faction", "faction_status"]:
                    val = updates.get(field_name, "")
                    if val:
                        setattr(char, field_name, val)
                for skill_data in updates.get("learned_skills", []):
                    if isinstance(skill_data, dict):
                        skill_name = skill_data.get("skill", "")
                        if skill_name:
                            existing = next((s for s in char.learned_skills if s.get("skill") == skill_name), None)
                            new_progress = skill_data.get("progress", 0.0)
                            if existing:
                                old_progress = existing.get("progress", 0.0)
                                if isinstance(new_progress, (int, float)) and isinstance(old_progress, (int, float)):
                                    if new_progress < old_progress:
                                        logger.warning(
                                            "技能进度倒退: %s.%s %.2f→%.2f (第%d章), 已拒绝降级",
                                            name, skill_name, old_progress, new_progress, chapter,
                                        )
                                        new_progress = old_progress
                                existing["level"] = skill_data.get("level", existing.get("level", "初学"))
                                existing["cost"] = skill_data.get("cost", existing.get("cost", ""))
                                existing["note"] = skill_data.get("note", existing.get("note", ""))
                                existing["progress"] = new_progress if isinstance(new_progress, (int, float)) else old_progress
                                existing["last_updated_chapter"] = chapter
                            else:
                                char.learned_skills.append({
                                    "skill": skill_name,
                                    "source": skill_data.get("source", "未知"),
                                    "level": skill_data.get("level", "初学"),
                                    "cost": skill_data.get("cost", ""),
                                    "note": skill_data.get("note", ""),
                                    "progress": new_progress if isinstance(new_progress, (int, float)) else 0.0,
                                    "chapter_learned": chapter,
                                    "last_updated_chapter": chapter,
                                })
                updated_count += 1

        if new_count or updated_count or skipped_minor:
            self.memory.save_characters()
            parts = []
            if new_count:
                parts.append(f"新增 {new_count} 个人物")
            if updated_count:
                parts.append(f"更新 {updated_count} 个人物")
            if skipped_minor:
                parts.append(f"跳过路人 {skipped_minor} 个")
            logger.info("人物: %s", ', '.join(parts))

    def apply_world_settings(self, items: list, chapter: int):
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
            self.memory.save_world_settings()
            logger.info("世界: 新增 %d 条世界设定", count)

    def apply_locations(self, items: list, chapter: int):
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
                    type=updates.get("type", "city"), connected_to=[],
                    first_appeared=chapter, notable_characters=updates.get("notable_characters", []),
                    notes=updates.get("notes", ""),
                ))
                new_count += 1
            elif name in self.memory.locations:
                loc = self.memory.locations[name]
                desc = updates.get("description", "")
                if desc and desc not in loc.description:
                    loc.description = (loc.description.rstrip("。；") + "；" + desc) if loc.description else desc
                    for nc in updates.get("notable_characters", []):
                        if nc and nc not in loc.notable_characters:
                            loc.notable_characters.append(nc)
                    notes = updates.get("notes", "")
                    if notes:
                        loc.notes = (loc.notes + "；" + notes) if loc.notes else notes
                    updated_count += 1

        if new_count or updated_count:
            self.memory.save_locations()
            parts = []
            if new_count:
                parts.append(f"新增 {new_count} 个地点")
            if updated_count:
                parts.append(f"更新 {updated_count} 个地点")
            logger.info("地点: %s", ', '.join(parts))

    def apply_spatial_movements(self, items: list, chapter: int):
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
            self.continuity.save_character_locations()
            logger.info("空间: 记录 %d 条人物移动", count)

    def apply_spacemap_updates(self, items: list):
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
            direction = item.get("direction", "").strip()

            self._update_spacemap_edge(from_loc, to_loc, travel_time, direction)
            reverse_dir = self._reverse_direction(direction) if direction else ""
            if is_bidir:
                self._update_spacemap_edge(to_loc, from_loc, travel_time, reverse_dir)
            count += 1
        if count:
            self.continuity.save_spacemap()
            for loc_name in list(self.continuity.spacemap.keys()):
                if loc_name not in self.memory.locations:
                    node = self.continuity.spacemap[loc_name]
                    self.memory.add_location(LocationProfile(
                        name=loc_name, description=node.description,
                        type=node.type, connected_to=[],
                        first_appeared=node.first_appeared,
                        notable_characters=list(node.notable_characters),
                        notes=node.notes,
                    ))
            self.memory.save_locations()
            logger.info("连通: 更新 %d 条地点连通", count)

    def _update_spacemap_edge(self, from_loc: str, to_loc: str,
                               travel_time: str, direction: str = ""):
        if from_loc in self.continuity.spacemap:
            node = self.continuity.spacemap[from_loc]
            if to_loc not in node.connected_to:
                node.connected_to.append(to_loc)
            if travel_time:
                node.travel_time[to_loc] = travel_time
            if direction:
                node.relative_position[to_loc] = direction
        else:
            rp = {to_loc: direction} if direction else {}
            existing = self.memory.locations.get(from_loc)
            if existing:
                self.continuity.add_location(LocationProfile(
                    name=from_loc, description=existing.description,
                    type=existing.type, connected_to=[to_loc],
                    travel_time={to_loc: travel_time} if travel_time else {},
                    relative_position=rp,
                    first_appeared=existing.first_appeared,
                    notable_characters=list(existing.notable_characters),
                    notes=existing.notes,
                ))
            else:
                self.continuity.add_location(LocationProfile(
                    name=from_loc, connected_to=[to_loc],
                    travel_time={to_loc: travel_time} if travel_time else {},
                    relative_position=rp,
                ))

    @staticmethod
    def _reverse_direction(d: str) -> str:
        """反转方向，支持"正东三百里"→"正西三百里"等"""
        prefixes = ["正", "偏", "约", "大约"]
        for p in prefixes:
            if d.startswith(p):
                return p + SettingsApplier._reverse_direction(d[len(p):])
        dir_chars = ["东南", "西北", "东北", "西南", "东", "南", "西", "北"]
        mapping = {
            "东": "西", "西": "东", "南": "北", "北": "南",
            "东南": "西北", "西北": "东南", "东北": "西南", "西南": "东北",
        }
        for dc in dir_chars:
            if d.startswith(dc):
                return mapping[dc] + d[len(dc):]
        return ""

    def apply_plot_rules(self, items: list, chapter: int):
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
            logger.info("规则: 新增 %d 条剧情规则", count)

    def apply_character_knowledge(self, items: list, chapter: int):
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
            logger.info("认知: 新增 %d 条角色认知", count)

    def apply_sect_factions(self, items: list, chapter: int):
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
            logger.info("势力: %s", ', '.join(parts))

    def apply_scene_events(self, items: list, chapter: int):
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
            logger.info("场景: 新增 %d 条场景事件", count)

    def apply_items(self, items: list, chapter: int):
        new_count = updated_count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "").strip()
            if not name:
                continue
            is_new = item.get("is_new", False)
            updates = item.get("updates", {})

            if is_new:
                self.memory.add_item(ItemProfile(
                    name=name,
                    type=updates.get("type", ""),
                    description=updates.get("description", ""),
                    first_appeared=chapter,
                    first_giver=updates.get("first_giver", ""),
                    current_holder=updates.get("current_holder", ""),
                    prohibited_actions=["give_again_by_other", "duplicate"],
                    status=updates.get("status", "active"),
                    notes=updates.get("notes", ""),
                ))
                new_count += 1
            elif name in self.memory.items:
                existing = self.memory.items[name]
                old_holder = existing.current_holder
                new_holder = updates.get("current_holder", "")
                if new_holder and new_holder != old_holder:
                    self.memory.transfer_item(
                        name, from_holder=old_holder, to_holder=new_holder,
                        chapter=chapter, reason=updates.get("description", ""),
                    )
                else:
                    for k in ["type", "description", "status", "notes"]:
                        v = updates.get(k, "")
                        if v:
                            setattr(existing, k, v)
                updated_count += 1

        if new_count or updated_count:
            self.memory.save_items()
            parts = []
            if new_count:
                parts.append(f"新增 {new_count} 个物品")
            if updated_count:
                parts.append(f"更新 {updated_count} 个物品")
            logger.info("物品: %s", ', '.join(parts))

    def apply_tasks(self, tasks: list, chapter: int):
        from novel_agent.core.dedup import dedup_tasks
        new_count = updated_count = 0
        parsed = []
        for t in tasks:
            if not isinstance(t, dict):
                continue
            task_id = t.get("id", "").strip()
            if not task_id:
                continue
            # 先去重（名称 + 章节）
            parsed.append(TaskProfile(
                id=task_id,
                name=t.get("name", ""),
                description=t.get("description", ""),
                status=t.get("status", "active"),
                chapter_created=chapter,
                chapter_completed=None,
                progress=t.get("progress", ""),
                related_items=t.get("related_items", []),
                related_characters=t.get("related_characters", []),
            ))
        deduped = dedup_tasks(parsed, self.memory.tasks)
        for tp in deduped:
            self.memory.add_task(tp)
            new_count += 1
        # 更新已有任务（按 ID 匹配）
        for t in tasks:
            if not isinstance(t, dict):
                continue
            task_id = t.get("id", "").strip()
            if not task_id or task_id not in self.memory.tasks:
                continue
            updates = t.get("updates", {})
            prog = t.get("progress", "") or updates.get("progress", "")
            status = t.get("status", "") or updates.get("status", "")
            if prog:
                self.memory.update_task_progress(task_id, prog)
            if status == "completed":
                self.memory.complete_task(task_id, chapter)
            updated_count += 1

        if new_count or updated_count:
            self.memory.save_tasks()
            parts = []
            if new_count:
                parts.append(f"新增 {new_count} 个任务")
            if updated_count:
                parts.append(f"更新 {updated_count} 个任务")
            logger.info("任务: %s", ', '.join(parts))

    def apply_timeline_events(self, events: list, chapter: int):
        count = 0
        for evt in events:
            if not isinstance(evt, dict):
                continue
            time_tag = evt.get("time_tag", "")
            event_desc = evt.get("event", "").strip()
            if not event_desc:
                continue
            chars = evt.get("characters", [])
            loc = evt.get("location", "")
            importance = evt.get("importance", 1)
            self.continuity.add_event(
                chapter=chapter, time_tag=time_tag, event=event_desc,
                characters=chars, location=loc, importance=importance,
            )
            count += 1
        if count:
            logger.info("时间线: 新增 %d 个时间线事件", count)

    def apply_arc_events(self, items: list, chapter: int):
        count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            char = item.get("character", "").strip()
            element = item.get("element", "").strip()
            event_type = item.get("event_type", "").strip()
            desc = item.get("description", "").strip()
            if not char or not element or not event_type or not desc:
                continue
            if element not in ("core_value", "core_desire", "core_fear", "flaw"):
                continue
            if event_type not in ("explored", "challenged", "changed", "resolved"):
                continue
            self.memory.arc_tracker.record(
                character=char, chapter=chapter,
                element=element, event_type=event_type,
                description=desc,
                new_value=item.get("new_value", ""),
            )
            count += 1
        if count:
            logger.info("成长弧: 新增 %d 个弧事件", count)

    def apply_style(self, style_updates: dict):
        if not style_updates or not isinstance(style_updates, dict):
            return
        self.memory.update_style(style_updates)
