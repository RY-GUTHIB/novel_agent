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

from novel_agent.llm.client import generate, generate_stream, parse_json, parse_json_array
from novel_agent.core.models import (
    validate_settings_json, generate_settings_json_example,
    TaskProfile,
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
    ANTI_AI_WRITING_RULES,
    ANTI_AI_REWRITE_SYSTEM_PROMPT, ANTI_AI_REWRITE_USER_PROMPT,
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
                       logic_constraints: str = "",
                       on_token: callable = None) -> tuple:
        """返回 (content, settings_json) 以便审校通过后调用 finalize_chapter 回写设定
        on_token: 可选回调，每收到一段文本时调用 on_token(text) 用于流式显示
        """
        if temperature is None:
            temperature = config.TEMPERATURE
        # 1. 冲突检测 + 预检
        char_loc_map = {char: location for char in characters}
        warnings = self.continuity.check_continuity(chapter, char_loc_map, time_tag)
        pre_warnings = self.memory.validate_chapter_characters(chapter, characters)
        if pre_warnings:
            for w in pre_warnings:
                logger.warning("%s", w)
        generation_contract = self.memory.get_generation_contract(chapter, characters)

        # 2. 构建 prompt
        anti_ai_rules = self._build_anti_ai_rules()
        system_prompt = CHAPTER_WRITER_SYSTEM_PROMPT.format(
            genre=self.genre, style=self.style, word_target=config.CHAPTER_WORD_TARGET,
            anti_ai_rules=anti_ai_rules,
        )
        user_prompt = self._build_writer_user_prompt(
            chapter, title, summary, time_tag, location, characters, generation_contract,
            logic_constraints=logic_constraints,
        )

        print(f"  [Prompt] system={len(system_prompt)}字, user={len(user_prompt)}字, 总计={len(system_prompt)+len(user_prompt)}字")

        # 3. 调用 LLM（流式 or 非流式）
        if on_token:
            chunks = []
            for token in generate_stream(system_prompt=system_prompt, user_prompt=user_prompt,
                                          temperature=temperature, max_tokens=config.MAX_TOKENS):
                chunks.append(token)
                on_token(token)
            raw_output = "".join(chunks)
        else:
            raw_output = generate(system_prompt=system_prompt, user_prompt=user_prompt,
                                  temperature=temperature, max_tokens=config.MAX_TOKENS)

        # 4. 解析：分离正文，统一走后端补充提取
        content, _ = self._split_output_and_settings(raw_output)

        # DEBUG: 打印原始返回内容（便于排查 LLM 返回过短问题）
        logger.debug("LLM raw_output (前500字): %s", raw_output[:500] if raw_output else "(空)")
        logger.debug("解析后 content 长度: %d", len(content) if content else 0)

        if not content or len(content.strip()) < 50:
            logger.warning("LLM 返回内容过短，原始内容前200字: %s", raw_output[:200] if raw_output else "(空)")
            raise RuntimeError(f"LLM 返回内容过短（{len(content) if content else 0} 字），请重试")

        # 统一走补充提取
        settings_json = self._supplementary_extract_settings(content, chapter, title, characters)
        if settings_json:
            logger.info("补充提取设定成功")
        else:
            logger.warning("补充提取设定失败，设定将缺失")

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
        anti_ai_rules = self._build_anti_ai_rules()
        system_prompt = CHAPTER_REVISER_SYSTEM_PROMPT.format(
            word_target=config.CHAPTER_WORD_TARGET,
            anti_ai_rules=anti_ai_rules,
        )
        user_prompt = self._build_reviser_user_prompt(
            chapter, title, review_report, original_content, summary,
            time_tag, location, characters, generation_contract,
            logic_constraints=logic_constraints,
        )

        raw_output = generate(system_prompt=system_prompt, user_prompt=user_prompt,
                              temperature=temperature, max_tokens=config.MAX_TOKENS)

        content, _ = self._split_output_and_settings(raw_output)

        # 统一走补充提取
        settings_json = self._supplementary_extract_settings(content, chapter, title, characters)
        if settings_json:
            logger.info("补充提取设定成功")
        else:
            logger.warning("补充提取设定失败，设定将缺失")

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
            scene_events=self.memory.get_scene_events_prompt(chapter=chapter),
            spacemap_prompt=self.continuity.get_spacemap_prompt(),
            outline_context=self.memory.get_outline_context_prompt(chapter),
            foreshadow_prompt=self.foreshadow.generate_foreshadow_prompt(chapter),
            rag_context=rag_context,
            state_snapshot=state_snapshot,
            rhythm=self._get_rhythm_for_chapter(chapter),
            beat_type=self._get_beat_type_for_chapter(chapter),
            hook_type=self._get_hook_type_for_chapter(chapter),
        )

    def _build_anti_ai_rules(self) -> str:
        if not config.ENABLE_ANTI_AI_MODE:
            return ""
        cfg = config.ANTI_AI_CONFIG
        lines = [ANTI_AI_WRITING_RULES]
        lines.append(f"\n> 当前密度红线：每 {cfg['check_window']} 字 ≤ {cfg['density_limit']} 次｜高光场景慎用词：{'、'.join(cfg['high_stakes_words'])}")
        return "\n".join(lines)

    def _build_existing_tasks_text(self, chapter: int) -> str:
        tasks = self.memory.get_active_tasks(current_chapter=chapter)
        if not tasks:
            return "（无）"
        lines = []
        for t in tasks:
            status_icon = "✅" if t.status == "completed" else "🔄" if t.status == "active" else "⏳"
            lines.append(f"- {status_icon} {t.id}：{t.name}（{t.status}，进度：{t.progress}）")
            if t.related_characters:
                lines.append(f"  - 涉及人物：{', '.join(t.related_characters)}")
            if t.related_items:
                lines.append(f"  - 涉及物品：{', '.join(t.related_items)}")
        return "\n".join(lines)

    def _auto_check_tasks(self, content: str, chapter: int):
        """关键词检测：活跃任务是否可能在本章被自然完成（仅告警，不自动标记）"""
        active = self.memory.get_active_tasks(current_chapter=chapter, limit=20)
        kw_pattern = re.compile(r'[\u4e00-\u9fff]{3,10}')
        for task in active:
            text = f"{task.name} {task.description}"
            keywords = kw_pattern.findall(text)
            keywords = [k for k in keywords if len(k) >= 3]
            keywords = list(set(keywords))
            if not keywords:
                continue
            match_count = sum(1 for kw in keywords if kw in content)
            threshold = max(len(keywords) * 2 // 3, 2)
            if match_count >= threshold:
                logger.info(
                    "任务 [%s] %s 可能在本章完成（关键词命中 %d/%d），"
                    "请确认 SETTINGS_JSON 的 task status 是否正确标记为 completed",
                    task.id, task.name, match_count, len(keywords),
                )

    def de_ai_rewrite(self, chapter: int, content: str) -> str:
        """反高潮二创：对已生成的章节做去AI味改写。
        
        注意：此函数仅为 CLI `de-ai` 命令提供，不接入自动写章/审校管线。
        如需在 future 自动调用，需确认改写后的内容不会破坏 SETTINGS_JSON 回写一致性。
        """
        from novel_agent.llm.client import generate
        system_prompt = ANTI_AI_REWRITE_SYSTEM_PROMPT
        user_prompt = ANTI_AI_REWRITE_USER_PROMPT.format(content=content)
        raw = generate(
            system_prompt=system_prompt, user_prompt=user_prompt,
            temperature=0.6, max_tokens=config.MAX_TOKENS,
        )
        if not raw:
            print("  [WARN] 去AI改写失败，保留原章节")
            return content
        # 保存改写前后的对比
        out_dir = self.ctx.output_dir
        import datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = out_dir / f"chapter_{chapter:03d}_pre_deai_{ts}.md"
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(content)
        # 保存改写后的版本
        chapter_path = out_dir / "chapters" / f"chapter_{chapter:03d}.md"
        with open(chapter_path, "w", encoding="utf-8") as f:
            f.write(raw)
        print(f"  [OK] 去AI改写完成，原版备份: {backup_path.name}")
        return raw

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

    def _get_prev_chapters_content(self, chapter: int, max_chapters: int = 2, max_chars_per: int = 2400) -> str:
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
            scene_events=self.memory.get_scene_events_prompt(chapter=chapter),
            outline_context=self.memory.get_outline_context_prompt(chapter),
            state_snapshot=state_snapshot,
        )

    def _get_rag_context(self, chapter, title, summary, characters) -> str:
        if not self.rag:
            logger.debug("RAG 未配置，跳过检索")
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

            logger.debug("RAG 注入日志: 第%d章, 标题=%s, 检索到 %d 条去重结果",
                         chapter, title, len(unique_results))

            if unique_results:
                parts = []
                for r in unique_results[:8]:  # 最多8条，避免prompt过长
                    meta = r.get("metadata", {})
                    ch = meta.get("chapter", "?")
                    parts.append(f"  [第{ch}章片段] {r['document'][:300]}")
                context_str = "## 🔍 前文相关片段（RAG检索，请据此避免重复情节）\n" + "\n---\n".join(parts)
                logger.debug("RAG 注入内容 (前500字): %s", context_str[:500])
                return context_str
        except (IOError, OSError, json.JSONDecodeError, ValueError) as e:
            logger.warning("RAG 检索失败: %s", e)
        return "（无相关前文片段）"

    # ========== 最终回写 ==========

    def finalize_chapter(self, chapter: int, content: str, summary: str,
                         time_tag: str, location: str, characters: list,
                         title: str = "", settings_json: str = None):
        """审校通过/审校上限后的统一设定回写入口。
        所有人物/物品/地理位置/连续性/伏笔/世界设定等不可逆操作都在这里执行，
        确保错误内容不会被写入数据层。
        以后有新的设定回写需求，统一加在这个方法里。

        注意：先保存章节文件到磁盘（第0步），再回写设定和事件，
        防止中途崩溃导致时间线事件存在但章节文件丢失。
        """
        self.save_chapter(chapter, title, content)

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

        # 3. 伏笔提取/回收（统一管线：正则显式 + LLM 隐式 + 融合去重）
        explicit_fs = self._extract_foreshadows(content, chapter)
        if config.FORESHADOW_DEEP_SCAN_INTERVAL > 0 and chapter % config.FORESHADOW_DEEP_SCAN_INTERVAL == 0:
            implicit_fs = self._scan_implicit_foreshadows(content)
        else:
            implicit_fs = []
        all_fs = self._merge_foreshadows(explicit_fs, implicit_fs, chapter)
        fs_planted = 0
        for fs in all_fs:
            self.foreshadow.plant(
                chapter=chapter, content=fs["content"],
                type=fs.get("type", "mystery"),
                related_characters=fs.get("related_characters", []),
                related_items=fs.get("related_items", []),
                planted_how=f"第{chapter}章{'显式标记' if fs.get('source') == 'explicit' else '隐式扫描'}",
                importance=fs.get("importance", 2),
            )
            fs_planted += 1
        resolved_count = self.foreshadow.auto_resolve(content, chapter)
        self.foreshadow.save()

        # 提取统计日志
        task_count = 0
        if parsed and isinstance(parsed, dict):
            task_count = len(parsed.get("tasks", []))
        logger.info(
            "第%d章 提取统计：伏笔 显式 %d 条 / 隐式 %d 条 / 合计 %d 条 | 已回收 %d 个 | 任务 %d 条",
            chapter, len(explicit_fs), len(implicit_fs), fs_planted, resolved_count, task_count,
        )

        # 4. 任务自动完成检测（关键词级，仅告警不自动标记）
        self._auto_check_tasks(content, chapter)

        # 5. RAG 存储（审校通过后才写入向量库，防止失败章节污染检索）
        if self.rag:
            try:
                self.rag.add_chapter(chapter, title, content)
            except (IOError, OSError, json.JSONDecodeError, ValueError) as e:
                print(f"  [WARN] RAG 存储失败: {e}")

        # 5. 更新伏笔总览
        try:
            self.foreshadow.export_to_markdown(output_dir=self.ctx.output_dir)
        except (IOError, OSError) as e:
            logger.warning("伏笔总览导出失败: %s", e)

    def review_loop(self, reviewer, chapter, title, content, summary, time_tag, location, characters, settings_json=None, logic_constraints=""):
        max_revisions = config.MAX_REVIEW_REVISIONS
        prev_score = None
        no_improvement_count = 0
        last_report = None
        for rev in range(max_revisions + 1):
            report = reviewer.review_chapter(chapter, title, content,
                                              logic_constraints=logic_constraints,
                                              characters=characters)
            last_report = report
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
                    new_settings = self._supplementary_extract_settings(
                        chapter=chapter, title=title, content=content, characters=characters,
                    )
                    if new_settings:
                        import json
                        settings_json = json.dumps(new_settings, ensure_ascii=False)
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
            title=title, settings_json=settings_json,
        )

        # 审校报告解析：提取待办任务和伏笔，避免"建议后续交代"类内容丢失
        if last_report and last_report.get("raw_text"):
            self._extract_review_action_items(last_report["raw_text"], chapter, title)

        return content, settings_json

    # ========== 审校报告解析 ==========

    def _extract_review_action_items(self, report_text: str, chapter: int, title: str) -> dict:
        """从审校报告中提取待办任务和伏笔，自动写入 tasks/foreshadow。

        审校通过后或强制接受前调用，避免报告中'建议后续交代'类内容丢失。
        用一次小 LLM 调用解析报告文本，提取：
          - tasks：需要后续章节解决/交代的问题
          - foreshadows：报告中指出的悬念/伏笔
        """
        system_prompt = """你是小说审校报告解析助手。从审校报告中提取两类内容：

1. tasks（待办任务）：需要后续章节解决、交代或回收的内容。
   例如：某角色身世未交代、某物品用途未说明、某承诺未履行、某伏笔未回收。
   只有确实需要在后续章节处理的内容才提取，不要捏造。

2. foreshadows（伏笔）：报告中明确指出的悬念、暗示或未解之谜。
   例如：此处暗示某事件、留下悬念、读者会好奇XXX、需要后续揭示。

输出严格 JSON，不要有其他内容。如果某类没有可提取的内容，输出空数组。"""

        user_prompt = (
            f"## 审校报告（第{chapter}章《{title}》）\n"
            f"{report_text[:4000]}\n\n"
            f"## 输出格式（严格 JSON，不要其他内容）\n"
            f'{{"tasks": [{{"name": "任务名（简短）", "description": "具体描述", '
            f'"related_characters": ["角色名"], "related_items": []}}],\n'
            f'"foreshadows": [{{"content": "伏笔内容（简短）", "type": "mystery", '
            f'"related_characters": ["角色名"], "importance": 2}}]}}\n\n'
            f"只输出JSON，不要其他内容。如果没有可提取的内容，输出 "
            f'{{"tasks": [], "foreshadows": []}}。'
        )

        try:
            raw = generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.2,
                max_tokens=2048,
            )
            result = parse_json(raw)
            if not isinstance(result, dict):
                logger.warning("审校报告解析：JSON 解析失败（不是对象），跳过")
                return {"tasks": 0, "foreshadows": 0}

            task_count = 0
            for t in result.get("tasks", []):
                import uuid
                task_id = f"T_{chapter:03d}_{uuid.uuid4().hex[:6]}"
                self.memory.add_task(TaskProfile(
                    id=task_id,
                    name=t.get("name", "未命名任务")[:50],
                    description=t.get("description", "")[:200],
                    chapter_created=chapter,
                    related_characters=t.get("related_characters", []),
                    related_items=t.get("related_items", []),
                ))
                task_count += 1

            fs_count = 0
            for fs in result.get("foreshadows", []):
                self.foreshadow.plant(
                    chapter=chapter,
                    content=fs.get("content", "")[:200],
                    type=fs.get("type", "mystery"),
                    related_characters=fs.get("related_characters", []),
                    related_items=fs.get("related_items", []),
                    planted_how=f"审校报告自动提取（第{chapter}章）",
                    importance=fs.get("importance", 2),
                )
                fs_count += 1

            if task_count or fs_count:
                logger.info("审校→任务/伏笔: 新增 %d 个任务，%d 个伏笔", task_count, fs_count)
                self.memory.save_tasks()
                self.foreshadow.save()
            else:
                logger.debug("审校→任务/伏笔: 无新增内容")

            return {"tasks": task_count, "foreshadows": fs_count}

        except Exception as e:
            logger.warning("审校报告解析失败: %s", e)
            return {"tasks": 0, "foreshadows": 0}

    # ========== 输出解析 ==========

    def _split_output_and_settings(self, raw_output: str) -> tuple:
        """从 LLM 输出中分离正文和设定 JSON，同时剥离 PRE_FLIGHT_CHECK 自检段。
        LLM 输出结构：===PRE_FLIGHT_CHECK=== → 自检 → 正文 → ===SETTINGS_JSON=== → JSON
        """
        flight_marker = "===PRE_FLIGHT_CHECK==="
        settings_marker = "===SETTINGS_JSON==="

        text = raw_output

        # 剥离 PRE_FLIGHT_CHECK 段：取 flight_marker 之后的内容
        if flight_marker in text:
            _, after_flight = text.split(flight_marker, 1)
            text = after_flight

        # 从剩余文本中分离正文和 settings JSON
        if settings_marker in text:
            content_part, _, settings_text = text.partition(settings_marker)
            settings_text = settings_text.strip()
            settings_text = re.sub(r'^```json\s*', '', settings_text)
            settings_text = re.sub(r'\s*```$', '', settings_text)
            settings_json = parse_json(settings_text)
            if settings_json:
                logger.info("正文 %d 字，设定 JSON 解析成功", len(content_part.strip()))
                return content_part.strip(), settings_json
            else:
                self._save_failed_settings(settings_text)
                logger.warning("正文 %d 字，设定 JSON 解析失败，已保存原始文本到 debug_settings.txt", len(content_part.strip()))
                return content_part.strip(), None
        else:
            logger.info("未找到 SETTINGS_JSON 分隔符，正文 %d 字", len(text.strip()))
            return text.strip(), None

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

    # ========== 补充设定提取 ==========

    def _supplementary_extract_settings(self, content: str, chapter: int,
                                          title: str, characters: list) -> dict:
        """正文写完但未输出 SETTINGS_JSON 时，补充提取设定"""
        from novel_agent.agents.prompts import SETTINGS_EXTRACT_SYSTEM_PROMPT

        char_summary_text = self._build_char_summary(characters)
        existing_ws_text = ", ".join(sorted(self.memory.world_settings.keys())) if self.memory.world_settings else "（无）"
        existing_loc_text = ", ".join(sorted(self.memory.locations.keys())) if self.memory.locations else "（无）"
        existing_sect_text = ", ".join(sorted(self.memory.sect_factions.keys())) if self.memory.sect_factions else "（无）"
        existing_items_text = ", ".join(sorted(self.memory.items.keys())) if self.memory.items else "（无）"
        existing_tasks_text = self._build_existing_tasks_text(chapter)

        system_prompt = SETTINGS_EXTRACT_SYSTEM_PROMPT
        user_prompt = (
            f"请从以下第{chapter}章《{title}》正文中，提取所有新增的标志性设定。\n\n"
            f"出场人物：{'、'.join(characters)}\n\n"
            f"## 已有人物（只提取本章新增变化）\n{char_summary_text}\n\n"
            f"## 已有世界设定\n{existing_ws_text}\n\n"
            f"## 已有地点\n{existing_loc_text}\n\n"
            f"## 已有势力\n{existing_sect_text}\n\n"
            f"## 已有物品\n{existing_items_text}\n\n"
            f"## 已有任务\n{existing_tasks_text}\n\n"
            f"## 输出格式（严格 JSON，不要其他内容）\n"
            f"{generate_settings_json_example()}\n\n"
            f"如果某类没有新增，该字段输出空数组。\n\n"
            f"⚠️ 注意：如果正文出现'在XX以东/以西/以南/以北/东南/西北N里处'，必须提取到 spacemap_updates 的 direction 字段（如 "
            "{'from_location':'青云宗','to_location':'药王谷','travel_time':'三日','direction':'东三百里'}）。\n\n"
            f"## 章节正文\n{content}"
        )

        try:
            raw = generate(
                system_prompt=system_prompt, user_prompt=user_prompt,
                temperature=0.3, max_tokens=4096,
            )
            settings = parse_json(raw)
            if settings:
                logger.info("补充提取设定成功")
                return settings
            else:
                logger.warning("补充提取设定：JSON 解析失败")
                return None
        except Exception as e:
            logger.warning("补充提取设定失败: %s", e)
            return None

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

    def _scan_implicit_foreshadows(self, content: str) -> List[dict]:
        """用 LLM 扫描正文中未标记的隐式伏笔（不依赖显式 [FS: xxx] 标记）"""
        from novel_agent.agents.prompts import FORESHADOW_SCAN_PROMPT, FORESHADOW_SCAN_SYSTEM_PROMPT

        prompt = FORESHADOW_SCAN_PROMPT.format(content=content)
        raw = self._call_llm(
            system=FORESHADOW_SCAN_SYSTEM_PROMPT,
            user=prompt,
            temperature=0.1,
            max_tokens=1000,
        )
        if not raw:
            return []
        raw = raw.strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            result = json.loads(raw)
            if isinstance(result, list):
                return result
            return []
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning("隐式伏笔扫描 LLM 返回非 JSON：%s", raw[:200])
            return []

    def _call_llm(self, system: str, user: str, temperature: float = 0.1, max_tokens: int = 1000):
        """统一 LLM 调用包装，用于隐式扫描等辅助调用"""
        try:
            return generate(system_prompt=system, user_prompt=user,
                            temperature=temperature, max_tokens=max_tokens)
        except Exception as e:
            logger.warning("LLM 辅助调用失败: %s", e)
            return None

    def _merge_foreshadows(self, explicit: List[str], implicit: List[dict], chapter: int) -> List[dict]:
        """融合显式 + 隐式伏笔，按 content 去重"""
        seen = set()
        result = []
        for fs_text in explicit:
            normalized = re.sub(r'\s+', '', fs_text)
            if normalized not in seen:
                seen.add(normalized)
                result.append({"content": fs_text, "type": "mystery", "importance": 2,
                               "related_characters": [], "source": "explicit"})
        for fs in implicit:
            content = fs.get("content", "")
            normalized = re.sub(r'\s+', '', content)
            if normalized and normalized not in seen:
                seen.add(normalized)
                fs["source"] = "implicit"
                result.append(fs)
        return result

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
