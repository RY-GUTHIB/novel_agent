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
    validate_settings_json, generate_settings_json_example,
)
from novel_agent.core.memory import MemoryManager
from novel_agent.core.continuity import ContinuityGuard
from novel_agent.core.foreshadow import ForeshadowTracker
from novel_agent.core.rag import RAGStore
from novel_agent.core.settings_applier import SettingsApplier
from novel_agent.core.validator import ContractValidator, format_violations_report
from novel_agent.core.file_utils import atomic_write_json, atomic_write_text
from .prompts import (
    CHAPTER_WRITER_SYSTEM_PROMPT, CHAPTER_WRITER_USER_PROMPT,
    CHAPTER_REVISER_SYSTEM_PROMPT, CHAPTER_REVISER_USER_PROMPT,
)

logger = logging.getLogger(__name__)

# 预编译正则（伏笔提取）
_FS_EXTRACT_1 = re.compile(r'\[FS:\s*([\u4e00-\u9fff][\u4e00-\u9fff\s，。！？、；：""''（）…—0-9-]{1,}?)\s*\]')
_FS_EXTRACT_2 = re.compile(r'FS：\s*([\u4e00-\u9fff][\u4e00-\u9fff\s，。！？、；：""''（）…—0-9-]{1,}?)(?:\r?\n|$)')
_FS_EXTRACT_3 = re.compile(r'\[FS：\s*([\u4e00-\u9fff][\u4e00-\u9fff\s，。！？、；：""''（）…—0-9-]{1,}?)\s*\]')


class WriterAgent:
    """章节写作 Agent"""

    def __init__(self, memory_mgr: MemoryManager, continuity_guard: ContinuityGuard,
                  foreshadow_tracker: ForeshadowTracker,
                  ctx: config.ProjectContext,
                  rag_store: RAGStore = None,
                  genre: str = "玄幻", style: str = "热血"):
        self.memory = memory_mgr
        self.continuity = continuity_guard
        self.foreshadow = foreshadow_tracker
        self.rag = rag_store
        self.genre = genre
        self.style = style
        self.validator = ContractValidator()
        self.ctx = ctx
        self._applier = SettingsApplier(self.memory, self.continuity)

    # ========== 核心生成 ==========

    def write_chapter(self, chapter: int, title: str, summary: str,
                       time_tag: str, location: str, characters: List[str],
                       temperature: float = None,
                       logic_constraints: str = "") -> tuple:
        """返回 (content, settings_json) 以便审校通过后调用 finalize_chapter 回写设定"""
        if temperature is None:
            temperature = config.TEMPERATURE
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
            settings_json_example=generate_settings_json_example(),
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

        return content, settings_json

    def revise_chapter(self, chapter: int, title: str, original_content: str,
                        review_report: str, summary: str, time_tag: str,
                        location: str, characters: List[str],
                        temperature: float = None,
                        logic_constraints: str = "") -> tuple:
        """返回 (content, settings_json) 以便审校通过后调用 finalize_chapter 回写设定"""
        if temperature is None:
            temperature = config.TEMPERATURE
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

        return content, settings_json

    def patch_chapter(self, chapter: int, title: str, original_content: str,
                      patches: list, summary: str, characters: List[str]) -> str:
        """定向修补：只修改问题段落，不重写整章。

        patches: [{severity, description, location_keyword}, ...]
        返回修补后的完整章节正文。
        """
        if not patches:
            return original_content

        # 按关键词定位问题段落
        paragraphs = original_content.split("\n\n")
        patch_tasks = []  # [(paragraph_idx, paragraph_text, patch_desc)]

        for p in patches:
            kw = p.get("location_keyword", "")
            if not kw:
                continue
            # 找包含关键词的段落
            for i, para in enumerate(paragraphs):
                if kw in para:
                    patch_tasks.append((i, para, p["description"]))
                    break

        if not patch_tasks:
            logger.info("定向修补：未找到可定位的段落，回退整章重写")
            return None  # 返回 None 表示失败，调用方应回退 revise_chapter

        # 构建修补 prompt（轻量版）
        patch_sections = []
        for i, para, desc in patch_tasks:
            # 取上下文：前1段 + 问题段 + 后1段
            ctx_start = max(0, i - 1)
            ctx_end = min(len(paragraphs), i + 2)
            context = "\n\n".join(paragraphs[ctx_start:ctx_end])
            patch_sections.append(
                f"### 问题段落（含前后上下文）\n```\n{context}\n```\n"
                f"### 修改要求\n{desc}\n"
                f"### 请输出修改后的段落（仅输出修改后的段落文本，不要包含上下文）"
            )

        patch_prompt = "\n\n---\n\n".join(patch_sections)

        system_prompt = (
            "你是一位小说修订编辑。请根据修改要求，对每个问题段落进行定向修补。\n"
            "只修改问题段落本身，保持前后文一致。只输出修改后的段落，用 --- 分隔。\n"
            "不要输出任何解释，不要输出原文，只输出修改后的段落。"
        )
        user_prompt = (
            f"第{chapter}章《{title}》定向修补\n\n"
            f"本章大纲：{summary}\n"
            f"出场人物：{'、'.join(characters)}\n\n"
            f"{patch_prompt}"
        )

        raw_output = generate(system_prompt=system_prompt, user_prompt=user_prompt,
                              temperature=0.2, max_tokens=2048)

        # 解析修改后的段落并替换
        revised_paras = [p.strip() for p in raw_output.split("---") if p.strip()]
        for idx, (para_idx, _, _) in enumerate(patch_tasks):
            if idx < len(revised_paras):
                paragraphs[para_idx] = revised_paras[idx]

        return "\n\n".join(paragraphs)

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
        existing_tasks_text = self._build_existing_tasks_text()

        # 上一章结尾钩子
        prev_chapter_ending = self._get_prev_chapter_ending(chapter)
        # 前章全文参考
        prev_chapters_content = self._get_prev_chapters_content(chapter)
        # 风格锚点
        style_prompt = self.memory.get_style_prompt()
        # 逻辑约束（来自 LogicGuard，纯规则）
        if not logic_constraints:
            logic_constraints = "（无特殊逻辑约束）"
        
        # 构建状态快照（含承诺清单，从 continuity 取时间线事件）
        timeline_events = self.continuity.timeline if self.continuity else None
        state_snapshot = self.memory.build_state_snapshot(chapter, characters, timeline_events)
        
        return CHAPTER_WRITER_USER_PROMPT.format(
            chapter=chapter, title=title, summary=summary,
            time_tag=time_tag, location=location, characters="、".join(characters),
            generation_contract=generation_contract,
            prev_chapter_ending=prev_chapter_ending,
            prev_chapters_content=prev_chapters_content,
            style_prompt=style_prompt,
            logic_constraints=logic_constraints,
            continuity_prompt=continuity_prompt,
            character_prompts=character_prompts or "（无）",
            world_settings=self.memory.get_world_settings_prompt(),
            sect_factions=self.memory.get_sect_factions_prompt(),
            foreshadow_prompt=self.foreshadow.generate_foreshadow_prompt(chapter),
            rag_context=rag_context,
            state_snapshot=state_snapshot,
            char_summary_text=char_summary_text,
            existing_ws_text=existing_ws_text,
            existing_loc_text=existing_loc_text,
            existing_sect_text=existing_sect_text,
            existing_items_text=existing_items_text,
            existing_tasks_text=existing_tasks_text,
            settings_json_example=generate_settings_json_example(),
            rhythm=self._get_rhythm_for_chapter(chapter),
            beat_type=self._get_beat_type_for_chapter(chapter),
            hook_type=self._get_hook_type_for_chapter(chapter),
        )

    def _build_existing_tasks_text(self) -> str:
        tasks = self.memory.get_active_tasks()
        if not tasks:
            return "（无）"
        lines = []
        for t in tasks:
            status_icon = "✅" if t.status == "completed" else "🔄" if t.status == "active" else "⏳"
            lines.append(f"- {status_icon} {t.id}：{t.name}（{t.status}，进度：{t.progress}）")
        return "\n".join(lines)

    def _get_prev_chapter_ending(self, chapter: int) -> str:
        """读取上一章最后 200 字，用于钩子衔接"""
        if chapter <= 1:
            return "（这是第一章，无上一章）"
        prev_chapter = chapter - 1
        out_dir = self.ctx.chapters_dir
        prev_path = out_dir / f"chapter_{prev_chapter:03d}.md"
        if prev_path.exists():
            with open(prev_path, "r", encoding="utf-8") as f:
                text = f.read()
            # 取最后 200 字
            ending = text[-200:] if len(text) > 200 else text
            return f"（上一章结尾：...{ending.strip()}）"
        return "（上一章文件不存在）"

    def _get_prev_chapters_content(self, chapter: int, max_chapters: int = 3, max_chars_per: int = 3000) -> str:
        """读取前 N 章内容，用于写作参考（过渡自然 + 防上下文冲突）"""
        if chapter <= 1:
            return "（这是第一章，无前章内容）"
        out_dir = self.ctx.chapters_dir
        parts = []
        for i in range(1, max_chapters + 1):
            prev = chapter - i
            if prev < 1:
                break
            prev_path = out_dir / f"chapter_{prev:03d}.md"
            if not prev_path.exists():
                continue
            with open(prev_path, "r", encoding="utf-8") as f:
                text = f.read()
            # 去掉 Markdown 标题行（第X章 XXX）
            content_only = re.sub(r'^# .+?\n', '', text, count=1).strip()
            # 截断超长章节，保留首尾关键内容
            if len(content_only) > max_chars_per:
                head = content_only[:max_chars_per // 2]
                tail = content_only[-(max_chars_per // 2):]
                content_only = head + "\n\n...（中间省略）...\n\n" + tail
            parts.append(f"### 第{prev}章\n{content_only}")
        if not parts:
            return "（前章文件不存在）"
        return "\n\n---\n\n".join(parts)

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

        # 构建状态快照（含承诺清单，从 continuity 取时间线事件）
        timeline_events = self.continuity.timeline if self.continuity else None
        state_snapshot = self.memory.build_state_snapshot(chapter, characters, timeline_events)

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

    # ========== 最终回写 ==========

    def finalize_chapter(self, chapter: int, content: str, summary: str,
                         time_tag: str, location: str, characters: list,
                         settings_json: str = None):
        """审校通过/审校上限后的统一设定回写入口。
        所有人物/物品/地理位置/连续性/伏笔/世界设定等不可逆操作都在这里执行，
        确保错误内容不会被写入数据层。
        以后有新的设定回写需求，统一加在这个方法里。
        """
        # 0. 契约校验（最终版本校验）
        parsed = None
        if settings_json:
            try:
                parsed = json.loads(settings_json) if isinstance(settings_json, str) else settings_json
            except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
                print(f"  [WARN] 设定 JSON 解析失败，契约校验跳过设定检查: {e}")

        # 校验 SETTINGS_JSON schema 完整性（检查 LLM 输出是否遗漏字段）
        if isinstance(parsed, dict):
            missing = validate_settings_json(parsed)
            if missing:
                print(f"  [WARN] SETTINGS_JSON 缺少 {len(missing)} 个字段: {', '.join(missing)}，缺失字段将回退默认值")

        violations = self.validator.validate(
            content, chapter, characters, self.memory,
            parsed_settings=parsed if isinstance(parsed, dict) else None,
            continuity_guard=self.continuity,
        )
        if violations:
            report = format_violations_report(violations)
            print(f"\n{report}")
            high_count = sum(1 for v in violations if v.severity == "高")
            if high_count > 0:
                print(f"  ⚠️ 最终版本仍有 {high_count} 个高严重性契约违反，已记录但继续回写")

        # 1. 应用所有设定（人物/物品/位置/势力/世界设定/场景事件）
        if parsed and isinstance(parsed, dict):
            self._applier.apply_all(parsed, chapter)

        # 2. 连续性更新
        self.continuity.add_event(chapter=chapter, time_tag=time_tag, event=summary,
                                  characters=characters, location=location, importance=3)

        # 收集已有精确位置的角色（来自 SETTINGS_JSON 的 spatial_movements）
        moved_chars = set()
        if parsed and isinstance(parsed, dict):
            for m in parsed.get("spatial_movements", []):
                if isinstance(m, dict) and m.get("character"):
                    moved_chars.add(m["character"])

        for char in characters:
            if char in moved_chars:
                continue  # 已有精确位置，跳过粗粒度回退
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
        self.foreshadow.save()

        # 4. RAG 存储（审校通过后才写入向量库，防止失败章节污染检索）
        if self.rag:
            try:
                self.rag.add_chapter(chapter, title, content)
            except (IOError, OSError, json.JSONDecodeError, ValueError) as e:
                print(f"  [WARN] RAG 存储失败: {e}")

        # 5. 更新伏笔总览
        try:
            self.foreshadow.export_to_markdown()
        except (IOError, OSError) as e:
            print(f"  [WARN] 伏笔总览导出失败: {e}")

    def review_loop(self, reviewer, chapter, title, content, summary, time_tag, location, characters, settings_json=None, logic_constraints=""):
        max_revisions = 3
        prev_score = None
        no_improvement_count = 0
        for rev in range(max_revisions + 1):
            report = reviewer.review_chapter(chapter, title, content,
                                              logic_constraints=logic_constraints,
                                              characters=characters)
            print(f"\n📋 审校报告（第{rev+1}次）：")
            print(report["raw_text"][:2000])
            print(f"\n结论：{report['verdict']} | 总分：{report['overall_score']}")

            if report["passed"]:
                print("\n✅ 审校通过！")
                break

            if rev >= max_revisions:
                print(f"\n⚠️ 已达最大修订次数（{max_revisions}），接受当前版本")
                break

            if prev_score is not None and report["overall_score"] <= prev_score:
                no_improvement_count += 1
            else:
                no_improvement_count = 0

            if no_improvement_count >= 2:
                print(f"\n⚠️ 连续{no_improvement_count}次修订分数未提升，跳过修订直接终止")
                break

            print(f"\n🔧 根据审校意见自动修改（第{rev+1}次修订）...")

            if report.get("patches"):
                print(f"  🎯 定向修补模式：发现 {len(report['patches'])} 个可定位问题")
                patched = self.patch_chapter(
                    chapter=chapter, title=title, original_content=content,
                    patches=report["patches"], summary=summary, characters=characters,
                )
                if patched:
                    content = patched
                    print("  定向修补完成，重新审校...")
                    prev_score = report["overall_score"]
                    continue
                else:
                    print("  ⚠️ 定向修补失败，回退整章重写")

            content, settings_json = self.revise_chapter(
                chapter=chapter, title=title, original_content=content,
                review_report=report["raw_text"], summary=summary,
                time_tag=time_tag, location=location, characters=characters,
                logic_constraints=logic_constraints,
            )
            print("  修订完成，重新审校...")

            prev_score = report["overall_score"]

        self.finalize_chapter(
            chapter=chapter, content=content, summary=summary,
            time_tag=time_tag, location=location, characters=characters,
            settings_json=settings_json,
        )
        return content, settings_json

    # ========== 输出解析 ==========

    def _split_output_and_settings(self, raw_output: str) -> tuple:
        """从 LLM 输出中分离正文和设定 JSON，同时剥离 PRE_FLIGHT_CHECK 自检段"""
        flight_marker = "===PRE_FLIGHT_CHECK==="
        settings_marker = "===SETTINGS_JSON==="

        # 正文始终在 ===PRE_FLIGHT_CHECK=== 之前（如果存在）
        if flight_marker in raw_output:
            content_part = raw_output.split(flight_marker, 1)[0]
        else:
            content_part = raw_output

        # SETTINGS_JSON 在 ===SETTINGS_JSON=== 之后（如果存在）
        if settings_marker in raw_output:
            _, after = raw_output.split(settings_marker, 1)
            settings_text = after.strip()
            settings_text = re.sub(r'^```json\s*', '', settings_text)
            settings_text = re.sub(r'\s*```$', '', settings_text)
            settings_json = parse_json(settings_text)
            if settings_json:
                print(f"  [合并解析] 正文 {len(content_part)} 字，设定 JSON 解析成功")
                return content_part.strip(), settings_json
            else:
                self._save_failed_settings(settings_text)
                print(f"  [合并解析] 正文 {len(content_part)} 字，设定 JSON 解析失败，已保存原始文本到 debug_settings.txt")
                return content_part.strip(), None
        else:
            print(f"  [合并解析] 未找到分隔符，正文 {len(content_part)} 字")
            return content_part.strip(), None

    def _save_failed_settings(self, settings_text: str):
        """保存解析失败的 SETTINGS_JSON 原始文本，方便排查问题"""
        from datetime import datetime
        debug_path = self.ctx.output_dir / "debug_settings.txt"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        content = (
            f"# 解析失败时间: {timestamp}\n"
            f"# 原始文本长度: {len(settings_text)} 字符\n"
            f"# 最后50字符: {settings_text[-50:]}\n"
            f"# ---\n\n{settings_text}"
        )
        atomic_write_text(debug_path, content)
        # 同时追加到日志
        debug_log = self.ctx.output_dir / "debug_settings.log"
        with open(debug_log, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"[{timestamp}] 解析失败，长度={len(settings_text)}\n")
            f.write(f"末尾50字符: {settings_text[-50:]}\n")
            f.write(f"{'='*60}\n")

    # ========== 伏笔提取 ==========

    def _extract_foreshadows(self, content: str, chapter: int) -> List[str]:
        """从正文中正则提取伏笔（不调 LLM）
        只匹配显式标记 [FS: xxx]，不匹配正文中无意的方括号内容。
        要求内容至少 4 个中文字符，过滤误匹配。
        """
        results = []
        # 提取 [FS: xxx] 标记，要求内容至少 2 个中文字符（允许短伏笔如"破局"）
        results.extend(_FS_EXTRACT_1.findall(content))
        results.extend(_FS_EXTRACT_2.findall(content))
        results.extend(_FS_EXTRACT_3.findall(content))
        return list(set(results))

    def save_chapter(self, chapter: int, title: str, content: str, output_dir: str = None):
        out_dir = Path(output_dir or self.ctx.output_dir)
        chapters_dir = out_dir / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)
        chapter_path = chapters_dir / f"chapter_{chapter:03d}.md"
        atomic_write_text(chapter_path, f"# 第{chapter}章 {title}\n\n{content}")

    def load_chapter(self, chapter: int, output_dir: str = None) -> str:
        out_dir = Path(output_dir or self.ctx.output_dir)
        chapter_path = out_dir / "chapters" / f"chapter_{chapter:03d}.md"
        if chapter_path.exists():
            with open(chapter_path, "r", encoding="utf-8") as f:
                return f.read()
        return ""
