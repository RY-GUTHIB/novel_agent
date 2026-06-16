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

from novel_agent.llm.client import generate, parse_json, parse_json_array
from novel_agent.core.models import (
    CharacterProfile, LocationProfile, WorldSetting,
    PlotRule, CharacterKnowledge, SectFaction, SceneEvent,
    ItemProfile,
)
from novel_agent.core.memory import MemoryManager
from novel_agent.core.continuity import ContinuityGuard
from novel_agent.core.foreshadow import ForeshadowTracker
from novel_agent.core.rag import RAGStore
from novel_agent.core.validator import ContractValidator, format_violations_report
from .prompts import (
    CHAPTER_WRITER_SYSTEM_PROMPT, CHAPTER_WRITER_USER_PROMPT,
    CHAPTER_REVISER_SYSTEM_PROMPT, CHAPTER_REVISER_USER_PROMPT,
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
        self.validator = ContractValidator()

    # ========== 核心生成 ==========

    def write_chapter(self, chapter: int, title: str, summary: str,
                       time_tag: str, location: str, characters: List[str],
                       temperature: float = config.TEMPERATURE,
                       logic_constraints: str = "") -> tuple:
        """返回 (content, settings_json) 以便审校通过后调用 finalize_chapter 回写设定"""
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
            logic_constraints=logic_constraints,
        )

        # 3. 调用 LLM（一次调用同时生成正文 + 设定 JSON）
        raw_output = generate(system_prompt=system_prompt, user_prompt=user_prompt,
                              temperature=temperature, max_tokens=config.MAX_TOKENS)

        # 4. 解析：分离正文和设定 JSON
        content, settings_json = self._split_output_and_settings(raw_output)

        # 5. 审校前处理：只做 RAG 存储，不写任何设定（推迟到 finalize_chapter）
        self._post_write(chapter, title, content, summary, time_tag, location, characters,
                         settings_json=settings_json)

        return content, settings_json

    def revise_chapter(self, chapter: int, title: str, original_content: str,
                        review_report: str, summary: str, time_tag: str,
                        location: str, characters: List[str],
                        temperature: float = 0.3,
                        logic_constraints: str = "") -> tuple:
        """返回 (content, settings_json) 以便审校通过后调用 finalize_chapter 回写设定"""
        generation_contract = self.memory.get_generation_contract(chapter, characters)
        system_prompt = CHAPTER_REVISER_SYSTEM_PROMPT.format(word_target=config.CHAPTER_WORD_TARGET)
        user_prompt = self._build_reviser_user_prompt(
            chapter, title, review_report, original_content, summary,
            time_tag, location, characters, generation_contract,
            logic_constraints=logic_constraints,
        )

        raw_output = generate(system_prompt=system_prompt, user_prompt=user_prompt,
                              temperature=temperature, max_tokens=config.MAX_TOKENS)

        content, settings_json = self._split_output_and_settings(raw_output)

        self._post_write(chapter, title, content, summary, time_tag, location, characters,
                         settings_json=settings_json)
        return content, settings_json

    # ========== Prompt 构建 ==========

    def _build_writer_user_prompt(self, chapter, title, summary, time_tag,
                                    location, characters, generation_contract,
                                    logic_constraints: str = "") -> str:
        character_prompts = "\n\n".join(
            self.memory.get_character_prompt(c) for c in characters if c in self.memory.characters
        )
        continuity_prompt = self.continuity.generate_continuity_prompt(
            chapter,
            plot_rules_text=self.memory.get_active_rules_prompt(),
            character_knowledge_text=self.memory.get_character_knowledge_prompt(chapter=chapter),
        )
        rag_context = self._get_rag_context(chapter, title, summary, characters)

        # 设定提取上下文
        char_summary_text = self._build_char_summary(characters)
        existing_ws_text = ", ".join(sorted(self.memory.world_settings.keys())) if self.memory.world_settings else "（无）"
        existing_loc_text = ", ".join(sorted(self.memory.locations.keys())) if self.memory.locations else "（无）"
        existing_sect_text = ", ".join(sorted(self.memory.sect_factions.keys())) if self.memory.sect_factions else "（无）"
        existing_items_text = ", ".join(sorted(self.memory.items.keys())) if self.memory.items else "（无）"

        # 上一章结尾钩子
        prev_chapter_ending = self._get_prev_chapter_ending(chapter)
        # 风格锚点
        style_prompt = self.memory.get_style_prompt()
        # 逻辑约束（来自 LogicGuard，纯规则）
        if not logic_constraints:
            logic_constraints = "（无特殊逻辑约束）"
        
        # 构建状态快照
        state_snapshot = self.memory.build_state_snapshot(chapter, characters)
        
        return CHAPTER_WRITER_USER_PROMPT.format(
            chapter=chapter, title=title, summary=summary,
            time_tag=time_tag, location=location, characters="、".join(characters),
            generation_contract=generation_contract,
            prev_chapter_ending=prev_chapter_ending,
            style_prompt=style_prompt,
            logic_constraints=logic_constraints,
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
            state_snapshot=state_snapshot,
            char_summary_text=char_summary_text,
            existing_ws_text=existing_ws_text,
            existing_loc_text=existing_loc_text,
            existing_sect_text=existing_sect_text,
            existing_items_text=existing_items_text,
            rhythm=self._get_rhythm_for_chapter(chapter),
            beat_type=self._get_beat_type_for_chapter(chapter),
            hook_type=self._get_hook_type_for_chapter(chapter),
        )

    def _get_prev_chapter_ending(self, chapter: int) -> str:
        """读取上一章最后 200 字，用于钩子衔接"""
        if chapter <= 1:
            return "（这是第一章，无上一章）"
        prev_chapter = chapter - 1
        out_dir = Path(config.OUTPUT_DIR) / "chapters"
        prev_path = out_dir / f"chapter_{prev_chapter:03d}.md"
        if prev_path.exists():
            with open(prev_path, "r", encoding="utf-8") as f:
                text = f.read()
            # 取最后 200 字
            ending = text[-200:] if len(text) > 200 else text
            return f"（上一章结尾：...{ending.strip()}）"
        return "（上一章文件不存在）"

    def _build_char_summary(self, characters: list) -> str:
        """构建已有人物摘要（用于设定提取上下文）"""
        lines = []
        for name in characters:
            if name not in self.memory.characters:
                continue
            c = self.memory.characters[name]
            abilities_str = ", ".join(c.abilities)
            rels_str = ", ".join(f"{k}({v})" for k, v in c.relationships.items())
            parts = [
                f"  {name}：{c.gender}，{c.age}",
                f"修为={c.cultivation}" if c.cultivation else "修为=未知",
                f"位置={c.current_location or '未知'}",
                f"核心价值观={c.core_values}" if c.core_values else "",
                f"核心欲望={c.core_desire}" if c.core_desire else "",
                f"核心恐惧={c.core_fear}" if c.core_fear else "",
                f"核心缺陷={c.flaw}" if c.flaw else "",
                f"阵营={c.alignment}" if c.alignment else "",
                f"能力[{abilities_str}]",
                f"关系[{rels_str}]",
                f"状态={c.status}",
            ]
            lines.append("，".join(p for p in parts if p))
        return "\n".join(lines) if lines else "（无）"

    # ========== 章节节奏/爽点/钩子辅助方法 ==========

    # 钩子类型池（随机轮换，避免单调）
    _HOOK_TYPES = [
        "悬念式（抛出不可能的悬念，让读者忍不住翻下一章）",
        "反转式（推翻整章建立的认知，最后一行真相炸裂）",
        "信息炸弹式（章末扔出一个重磅信息，点燃读者好奇心）",
        "情绪悬停式（情绪爆发到一半戛然而止，吊住读者）",
        "动作未完成式（关键时刻打断，下一章继续）",
        "新设定钩（结尾甩出一个有冲击力的新规则/信息）",
        "留白反转钩（结尾是表象，下一章开头才是真相）",
    ]

    _BEAT_TYPES = [
        "打脸时刻（铺垫反差→反派嘲讽→主角碾压→围观震惊）",
        "实力碾压（主角展示远超同级的能力，众人震撼）",
        "身份反转（主角隐藏身份被揭露/更高身份暴露）",
        "突破时刻（主角修为突破，引发天地异象/众人瞩目）",
        "金句名场面（一段让人热血沸腾的台词或场景）",
        "意外反转（预期之外的剧情转折，读者拍大腿）",
        "收获时刻（主角获得重要物品/功法/机缘）",
        "感情推进（重要关系突破，表白/和解/决裂）",
    ]

    _RHYTHM_PATTERNS = [
        "铺垫(困境) → 转折(反转) → 爆发(碾压/打脸) → 释放(震惊/余韵)",
        "紧张(冲突升级) → 缓一口气 → 更紧张 → 以为结束了 → 最紧张 → 结束+钩子（过山车模式）",
        "线索A → 推理1 → 发现不对劲 → 线索B推翻推理1 → 新推理 → 更大秘密浮现（悬疑递进模式）",
        "低压(日常) → 冲突初现 → 压力增大 → 转折爆发 → 章末钩子（起承转爽模式）",
    ]

    def _get_rhythm_for_chapter(self, chapter: int) -> str:
        """根据章节号选择情绪曲线模式"""
        idx = (chapter - 1) % len(self._RHYTHM_PATTERNS)
        return self._RHYTHM_PATTERNS[idx]

    def _get_beat_type_for_chapter(self, chapter: int) -> str:
        """根据章节号选择本章爽点类型"""
        idx = (chapter - 1) % len(self._BEAT_TYPES)
        return self._BEAT_TYPES[idx]

    def _get_hook_type_for_chapter(self, chapter: int) -> str:
        """根据章节号选择章末钩子类型"""
        idx = (chapter - 1) % len(self._HOOK_TYPES)
        return self._HOOK_TYPES[idx]

    # ========== 伏笔公开接口（供 CLI 调用）==========

    def finalize_foreshadows(self, content: str, chapter: int, characters: list):
        """审校通过后，从最终版本正文提取伏笔并自动回收（公开方法）"""
        new_fs = self._extract_foreshadows(content, chapter)
        for fs_content in new_fs:
            self.foreshadow.plant(chapter=chapter, content=fs_content, type="mystery",
                                  related_characters=characters, importance=2)
        resolved_count = self.foreshadow.auto_resolve(content, chapter)
        if resolved_count:
            print(f"  [伏笔回收] 自动回收 {resolved_count} 个伏笔")
        if new_fs:
            print(f"  [伏笔提取] 提取 {len(new_fs)} 个新伏笔")
            for fs in new_fs:
                print(f"    - {fs[:50]}...")
        self.foreshadow._save()
        try:
            self.foreshadow.export_to_markdown()
        except (IOError, OSError) as e:
            print(f"  [WARN] 伏笔总览导出失败: {e}")

    def _build_reviser_user_prompt(self, chapter, title, review_report, original_content,
                                     summary, time_tag, location, characters,
                                     generation_contract, logic_constraints: str = "") -> str:
        character_prompts = "\n\n".join(
            self.memory.get_character_prompt(c) for c in characters if c in self.memory.characters
        )
        continuity_prompt = self.continuity.generate_continuity_prompt(
            chapter,
            plot_rules_text=self.memory.get_active_rules_prompt(),
            character_knowledge_text=self.memory.get_character_knowledge_prompt(chapter=chapter),
        )
        prev_chapter_ending = self._get_prev_chapter_ending(chapter)
        style_prompt = self.memory.get_style_prompt()
        if not logic_constraints:
            logic_constraints = "（无特殊逻辑约束）"

        # 构建状态快照
        state_snapshot = self.memory.build_state_snapshot(chapter, characters)

        return CHAPTER_REVISER_USER_PROMPT.format(
            chapter=chapter, title=title, review_report=review_report,
            original_content=original_content, summary=summary,
            time_tag=time_tag, location=location, characters="、".join(characters),
            generation_contract=generation_contract,
            prev_chapter_ending=prev_chapter_ending,
            style_prompt=style_prompt,
            logic_constraints=logic_constraints,
            continuity_prompt=continuity_prompt,
            character_prompts=character_prompts or "（无）",
            world_settings=self.memory.get_world_settings_prompt(),
            sect_factions=self.memory.get_sect_factions_prompt(),
            plot_rules=self.memory.get_active_rules_prompt(),
            character_knowledge=self.memory.get_character_knowledge_prompt(chapter=chapter),
            relationship_details=self.memory.get_all_relationships_prompt(),
            scene_events=self.memory.get_scene_events_prompt(chapter=chapter),
            foreshadow_prompt=self.foreshadow.generate_foreshadow_prompt(chapter),
            state_snapshot=state_snapshot,
        )

    def _get_rag_context(self, chapter, title, summary, characters) -> str:
        if not self.rag:
            return "（无相关前文片段）"
        try:
            # B方案：多维度检索，确保覆盖物品传递、关键对话等细节
            all_results = []

            # 维度1：章节大纲+人物（原有）
            rag_query = f"{title} {summary} {' '.join(characters)}"
            results = self.rag.search(rag_query, filter_chapter_lt=chapter, top_k=3)
            all_results.extend(results)

            # 维度2：各角色近期言行（防止物品重复交付、对话重复等）
            for char in characters[:3]:  # 只检索前3个主要角色
                char_results = self.rag.search(
                    f"{char} 给了 递给 交给 获得 拿到 得到 发生 说了",
                    filter_chapter_lt=chapter, top_k=2
                )
                all_results.extend(char_results)

            # 去重 + 按章节排序
            seen = set()
            unique_results = []
            for r in sorted(all_results, key=lambda x: x.get("metadata", {}).get("chapter", 0)):
                doc_key = r["document"][:60]
                if doc_key not in seen:
                    seen.add(doc_key)
                    unique_results.append(r)

            if unique_results:
                parts = []
                for r in unique_results[:8]:  # 最多8条，避免prompt过长
                    meta = r.get("metadata", {})
                    ch = meta.get("chapter", "?")
                    parts.append(f"  [第{ch}章片段] {r['document'][:300]}")
                return "## 🔍 前文相关片段（RAG检索，请据此避免重复情节）\n" + "\n---\n".join(parts)
        except (IOError, OSError, json.JSONDecodeError, ValueError) as e:
            print(f"  [WARN] RAG 检索失败: {e}")
        return "（无相关前文片段）"

    # ========== 写后处理 ==========

    def _post_write(self, chapter, title, content, summary, time_tag,
                     location, characters, skip_scan=False, settings_json=None):
        """审校前处理：只做 RAG 存储（无副作用），所有设定回写推迟到 finalize_chapter"""
        # RAG 存储（审校前就可以存，不影响数据正确性）
        if self.rag:
            try:
                self.rag.add_chapter(chapter, title, content)
            except (IOError, OSError, json.JSONDecodeError, ValueError) as e:
                print(f"  [WARN] RAG 存储失败: {e}")

    def finalize_chapter(self, chapter: int, content: str, summary: str,
                         time_tag: str, location: str, characters: list,
                         settings_json: str = None):
        """审校通过/审校上限后的统一设定回写入口。
        所有人物/物品/地理位置/连续性/伏笔/世界设定等不可逆操作都在这里执行，
        确保错误内容不会被写入数据层。
        以后有新的设定回写需求，统一加在这个方法里。
        """
        # 0. 契约校验（最终版本校验）
        violations = self.validator.validate(content, chapter, characters, self.memory)
        if violations:
            report = format_violations_report(violations)
            print(f"\n{report}")
            high_count = sum(1 for v in violations if v.severity == "高")
            if high_count > 0:
                print(f"  ⚠️ 最终版本仍有 {high_count} 个高严重性契约违反，已记录但继续回写")

        # 1. 应用所有设定（人物/物品/位置/势力/世界设定/场景事件）
        if settings_json:
            try:
                parsed = json.loads(settings_json) if isinstance(settings_json, str) else settings_json
                if parsed:
                    self._apply_all_settings(parsed, chapter)
            except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
                print(f"  [WARN] 设定回写失败: {e}")

        # 2. 连续性更新
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
        self.continuity.save_all()

        # 3. 伏笔提取/回收
        new_fs = self._extract_foreshadows(content, chapter)
        for fs_content in new_fs:
            self.foreshadow.plant(chapter=chapter, content=fs_content, type="mystery",
                                  related_characters=characters, importance=2)
        resolved_count = self.foreshadow.auto_resolve(content, chapter)
        if resolved_count:
            print(f"  [伏笔回收] 自动回收 {resolved_count} 个伏笔")
        if new_fs:
            print(f"  [伏笔提取] 提取 {len(new_fs)} 个新伏笔")
        self.foreshadow._save()

        # 4. 更新伏笔总览
        try:
            self.foreshadow.export_to_markdown()
        except (IOError, OSError) as e:
            print(f"  [WARN] 伏笔总览导出失败: {e}")

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
            settings_json = parse_json(settings_text)
            if settings_json:
                print(f"  [合并解析] 正文 {len(content)} 字，设定 JSON 解析成功")
                return content, settings_json
            else:
                print(f"  [合并解析] 正文 {len(content)} 字，设定 JSON 解析失败，将 fallback")
                return content, None
        else:
            print(f"  [合并解析] 未找到分隔符，正文 {len(raw_output)} 字")
            return raw_output, None

    def _apply_all_settings(self, parsed: dict, chapter: int):
        """统一回写所有设定（人物/物品/位置/势力/世界设定/场景事件/连续性）。
        只应在审校通过后由 finalize_chapter 调用。以后有新设定类型，统一加在这里。"""
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
            self._apply_items(parsed.get("items", []), chapter)
            self._apply_style(parsed.get("style", {}))
        except (KeyError, ValueError, TypeError, AttributeError) as e:
            print(f"  [WARN] 设定回写失败: {e}")

    # ========== 伏笔提取 ==========

    def _extract_foreshadows(self, content: str, chapter: int) -> List[str]:
        """从正文中正则提取伏笔（不调 LLM）
        只匹配显式标记 [FS: xxx]，不匹配正文中无意的方括号内容。
        要求内容至少 4 个中文字符，过滤误匹配。
        """
        results = []
        # 提取 [FS: xxx] 标记，要求内容至少 2 个中文字符（允许短伏笔如"破局"）
        # 使用普通字符串（非 raw），避免 Python 3.12+ 的无效转义警告
        results.extend(re.findall('\\[FS:\\s*([\\u4e00-\\u9fa5][\\u4e00-\\u9fa5\\s，。！？、；：""''（）…—0-9-]{1,}?)\\s*\\]', content))
        results.extend(re.findall('FS：\\s*([\\u4e00-\\u9fa5][\\u4e00-\\u9fa5\\s，。！？、；：""''（）…—0-9-]{1,}?)(?:\\r?\\n|$)', content))
        results.extend(re.findall('\\[FS：\\s*([\\u4e00-\\u9fa5][\\u4e00-\\u9fa5\\s，。！？、；：""''（）…—0-9-]{1,}?)\\s*\\]', content))
        return list(set(results))

    # ========== 设定提取（已合并到写作 prompt 的 ===SETTINGS_JSON=== 输出，以下方法已废弃）==========
    # _extract_and_save_world_settings 和 _call_settings_extractor 已移除，使用 _apply_settings 代替

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
                for field_name in ["cultivation", "current_location", "appearance", "personality", "status",
                                    "goals", "notes", "core_values", "core_desire", "core_fear",
                                    "flaw", "alignment", "background", "speaking_style"]:
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
            self.continuity.add_location(LocationProfile(
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

    def _apply_items(self, items: list, chapter: int):
        """应用物品更新（方案1+2+5：从 SETTINGS_JSON 解析物品变化）"""
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
                    # 物品转移
                    self.memory.transfer_item(
                        name, from_holder=old_holder, to_holder=new_holder,
                        chapter=chapter, reason=updates.get("description", ""),
                    )
                else:
                    # 非转移性更新
                    for k in ["type", "description", "status", "notes"]:
                        v = updates.get(k, "")
                        if v:
                            setattr(existing, k, v)
                updated_count += 1

        if new_count or updated_count:
            self.memory._save_items()
            parts = []
            if new_count:
                parts.append(f"新增 {new_count} 个物品")
            if updated_count:
                parts.append(f"更新 {updated_count} 个物品")
            print(f"  [设定提取·物品] {', '.join(parts)}")

    # ========== JSON 解析工具 ==========

    def _apply_style(self, style_updates: dict):
        """应用风格锚点更新（从 SETTINGS_JSON 的 style 字段）"""
        if not style_updates or not isinstance(style_updates, dict):
            return
        self.memory.update_style(style_updates)

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
