"""
settings_applier.py - SETTINGS_JSON 设定回写器

从 writer.py 提取，封装所有 _apply_* 方法，
减轻 WriterAgent（~1050行→~650行）的职责。
"""

from .memory import MemoryManager
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
        except (KeyError, ValueError, TypeError, AttributeError) as e:
            print(f"  [ERROR] 设定回写失败: {e}")
            raise

    def apply_characters(self, items: list, chapter: int):
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
                            if existing:
                                existing["level"] = skill_data.get("level", existing.get("level", "初学"))
                                existing["cost"] = skill_data.get("cost", existing.get("cost", ""))
                                existing["note"] = skill_data.get("note", existing.get("note", ""))
                            else:
                                char.learned_skills.append({
                                    "skill": skill_name,
                                    "source": skill_data.get("source", "未知"),
                                    "level": skill_data.get("level", "初学"),
                                    "cost": skill_data.get("cost", ""),
                                    "note": skill_data.get("note", ""),
                                })
                updated_count += 1

        if new_count or updated_count:
            self.memory.save_characters()
            parts = []
            if new_count:
                parts.append(f"新增 {new_count} 个人物")
            if updated_count:
                parts.append(f"更新 {updated_count} 个人物")
            print(f"  [设定提取·人物] {', '.join(parts)}")

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
            print(f"  [设定提取·世界] 新增 {count} 条世界设定")

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
                    type=updates.get("type", "city"), connected_to=updates.get("connected_to", []),
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
            print(f"  [设定提取·地点] {', '.join(parts)}")

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
            print(f"  [设定提取·空间] 记录 {count} 条人物移动")

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

            self._update_spacemap_edge(from_loc, to_loc, travel_time)
            if is_bidir:
                self._update_spacemap_edge(to_loc, from_loc, travel_time)
            count += 1
        if count:
            self.continuity.save_spacemap()
            print(f"  [设定提取·连通] 更新 {count} 条地点连通")

    def _update_spacemap_edge(self, from_loc: str, to_loc: str, travel_time: str):
        if from_loc in self.continuity.spacemap:
            node = self.continuity.spacemap[from_loc]
            if to_loc not in node.connected_to:
                node.connected_to.append(to_loc)
            if travel_time:
                node.travel_time[to_loc] = travel_time
        else:
            self.continuity.add_location(LocationProfile(
                name=from_loc, connected_to=[to_loc],
                travel_time={to_loc: travel_time} if travel_time else {},
            ))

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
            print(f"  [设定提取·规则] 新增 {count} 条剧情规则")

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
            print(f"  [设定提取·认知] 新增 {count} 条角色认知")

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
            print(f"  [设定提取·势力] {', '.join(parts)}")

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
            print(f"  [设定提取·场景] 新增 {count} 条场景事件")

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
            print(f"  [设定提取·物品] {', '.join(parts)}")

    def apply_tasks(self, tasks: list, chapter: int):
        new_count = updated_count = 0
        for t in tasks:
            if not isinstance(t, dict):
                continue
            task_id = t.get("id", "").strip()
            if not task_id:
                continue
            if task_id not in self.memory.tasks:
                self.memory.add_task(TaskProfile(
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
                new_count += 1
            elif task_id in self.memory.tasks:
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
            print(f"  [设定提取·任务] {', '.join(parts)}")

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
            print(f"  [设定提取·时间线] 新增 {count} 个时间线事件")

    def apply_style(self, style_updates: dict):
        if not style_updates or not isinstance(style_updates, dict):
            return
        self.memory.update_style(style_updates)
