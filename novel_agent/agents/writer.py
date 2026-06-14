"""
writer_agent.py - 章节写作 Agent

职责：
1. 根据大纲生成本章内容
2. 注入前文摘要、人物状态、伏笔提醒（通过 RAG + continuity）
3. 将生成结果存入 RAG 向量库
4. 更新 continuity 和 foreshadow 状态
"""

import json
import re
import config
from pathlib import Path
from typing import Dict, List

from novel_agent.llm.client import generate
from novel_agent.core.memory import MemoryManager
from novel_agent.core.continuity import ContinuityGuard, SpaceNode
from novel_agent.core.foreshadow import ForeshadowTracker
from novel_agent.core.rag import RAGStore


# ---------- Prompt 模板 ----------

CHAPTER_WRITER_SYSTEM_PROMPT = """你是一位顶尖的长篇小说作家，擅长创作{genre}类作品，文风{style}。

写作要求：
1. 严格遵循本章大纲，不要偏离剧情
2. 人物言行必须符合其性格和语言风格
3. 保持章节结尾留有悬念/期待感
4. 字数目标：{word_target}字左右
5. 使用中文写作，文笔流畅，对话生动
6. 不要使用"本文X"、"故事讲述了"等元叙述语言
7. 直接开始正文，不要加"第一章 XXX"标题（标题由系统统一管理）

特别注意：
- 检查并遵守【前文连续性摘要】，确保时间线/空间线不矛盾
- 检查并遵守【人物档案】，确保人物言行一致
- 检查并遵守【伏笔提醒】，本章可考虑兑现1-2个伏笔
- 如埋下新伏笔，请在章末用 [FS: 伏笔内容] 标注
- ⚠️【空间过渡】人物换场景时，必须交代移动过程（哪怕一句话：如"他御剑飞行半日，终于抵达天剑城"）。绝不许人物瞬移。
- ⚠️【空间过渡】如果人物在上一章末尾位于A地，本章开头却在B地，必须在段落开头交代如何从A到B
- ⚠️【剧情规则】严格遵守【当前生效的剧情规则】！如果正文中已声明"凡满足X条件者→Y结果"，则后续角色行为必须遵守，不得违反。若需打破规则，必须在正文中给出合理解释。
- ⚠️【角色认知一致性】严格遵守【角色已知信息】！如果某角色在前文已经知道了某件事，后续章节中该角色对这件事不应再表现出惊讶、好奇或首次获知的反应。角色只能基于已知信息做决策，不能使用未知信息。
- ⚠️【角色相识一致性】严格遵守【人物关系详细记录】！如果两个角色已认识，不应表现出初次见面的反应。如果两个角色从未认识，不应表现出老友般的默契。
- ⚠️【性格一致性】人物的性格必须与【人物档案】中的性格描述保持一致！档案写"阴险狡诈"的角色不能突然表现"正直磊落"，除非有充分的剧情铺垫和转变过程。
"""

CHAPTER_WRITER_USER_PROMPT = """请创作第{chapter}章：{title}

## 本章大纲
{summary}

## 时间设定
{time_tag}

## 主要场景地点
{location}

## 出场人物
{characters}

## ⚠️ 一致性契约（写作前必须逐条确认，不可违反）
{generation_contract}

## 前文连续性摘要
{continuity_prompt}

## 人物档案
{character_prompts}

## 世界观设定
{world_settings}

## 势力/宗派档案
{sect_factions}

## 当前生效的剧情规则
{plot_rules}

## 角色已知信息
{character_knowledge}

## 人物关系详细记录
{relationship_details}

## 场景事件记录
{scene_events}

## 伏笔提醒
{foreshadow_prompt}

## 相关前文片段（RAG检索）
{rag_context}

请开始创作本章正文。"""

# ---------- 修订 Prompt 模板 ----------

CHAPTER_REVISER_SYSTEM_PROMPT = """你是一位顶尖的长篇小说作家，正在根据审校反馈修订章节。
你是修订专家，擅长根据审校意见精准修改小说章节，修复连续性错误、人物一致性问题、伏笔管理问题等。

修订要求：
1. 逐条修复审校报告中列出的所有问题（高、中、低严重性都要处理）
2. 严格保持章节核心剧情和事件不变，只修改有问题的部分
3. 人物言行必须符合其性格和语言风格
4. 修复后重新输出完整的修订章节正文
5. 字数目标：{word_target}字左右
6. 使用中文写作，文笔流畅，对话生动
7. 不要使用"本文X"、"故事讲述了"等元叙述语言
8. 直接开始正文，不要加"第一章 XXX"标题（标题由系统统一管理）

特别注意：
- 检查并遵守【前文连续性摘要】，确保时间线/空间线不矛盾
- 检查并遵守【人物档案】，确保人物言行一致
- 检查并遵守【人物关系详细记录】，确保角色相识关系正确
- 如埋下新伏笔，请在章末用 [FS: 伏笔内容] 标注
"""

CHAPTER_REVISER_USER_PROMPT = """请修订第{chapter}章：{title}

## 审校报告（必须逐条修复）
{review_report}

## 原章节正文（修订基础）
{original_content}

## 本章大纲（核心剧情不能变）
{summary}

## 时间设定
{time_tag}

## 主要场景地点
{location}

## 出场人物
{characters}

## ⚠️ 一致性契约（修订时必须逐条确认，不可违反）
{generation_contract}

## 前文连续性摘要
{continuity_prompt}

## 人物档案
{character_prompts}

## 世界观设定
{world_settings}

## 势力/宗派档案
{sect_factions}

## 当前生效的剧情规则
{plot_rules}

## 角色已知信息
{character_knowledge}

## 人物关系详细记录
{relationship_details}

## 场景事件记录
{scene_events}

## 伏笔提醒
{foreshadow_prompt}

请输出修订后的完整章节正文。"""


# ---------- 主 Agent ----------

class WriterAgent:
    """章节写作 Agent"""

    def __init__(self,
                  memory_mgr: MemoryManager,
                  continuity_guard: ContinuityGuard,
                  foreshadow_tracker: ForeshadowTracker,
                  rag_store: RAGStore = None,
                  genre: str = "玄幻",
                  style: str = "热血"):
        self.memory = memory_mgr
        self.continuity = continuity_guard
        self.foreshadow = foreshadow_tracker
        self.rag = rag_store
        self.genre = genre
        self.style = style

    def write_chapter(self,
                       chapter: int,
                       title: str,
                       summary: str,
                       time_tag: str,
                       location: str,
                       characters: List[str],
                      temperature: float = config.TEMPERATURE) -> str:
        """
        生成并返回本章正文
        """
        # 1. 冲突检测
        char_loc_map = {char: location for char in characters}
        warnings = self.continuity.check_continuity(chapter, char_loc_map, time_tag)
        warning_text = "\n".join(warnings) if warnings else "无冲突"

        # 1.5 预检 + 生成前一致性契约
        pre_warnings = self.memory.validate_chapter_characters(chapter, characters)
        if pre_warnings:
            print("  [预检] 发现潜在问题：")
            for w in pre_warnings:
                print(f"    {w}")
        generation_contract = self.memory.get_generation_contract(chapter, characters)

        # 2. 构建 prompt
        system_prompt = CHAPTER_WRITER_SYSTEM_PROMPT.format(
            genre=self.genre,
            style=self.style,
            word_target=config.CHAPTER_WORD_TARGET,
        )

        # 人物 prompt
        character_prompts = "\n\n".join(
            self.memory.get_character_prompt(char)
            for char in characters
            if char in self.memory.characters
        )

        # 连续性 prompt（注入剧情规则 + 角色认知）
        continuity_prompt = self.continuity.generate_continuity_prompt(
            chapter,
            plot_rules_text=self.memory.get_active_rules_prompt(),
            character_knowledge_text=self.memory.get_character_knowledge_prompt(chapter=chapter),
        )

        # 伏笔 prompt
        foreshadow_prompt = self.foreshadow.generate_foreshadow_prompt(chapter)

        # RAG 检索相关前文（可选）
        rag_context = "（无相关前文片段）"
        if self.rag:
            try:
                rag_query = f"{title} {summary} {' '.join(characters)}"
                rag_results = self.rag.search(rag_query, filter_chapter_lt=chapter)
                if rag_results:
                    rag_context = "\n\n---\n\n".join(
                        r["document"] for r in rag_results
                    )
            except Exception:
                pass  # RAG 失败时继续使用空上下文

        user_prompt = CHAPTER_WRITER_USER_PROMPT.format(
            chapter=chapter,
            title=title,
            summary=summary,
            time_tag=time_tag,
            location=location,
            characters="、".join(characters),
            generation_contract=generation_contract,
            continuity_prompt=continuity_prompt,
            character_prompts=character_prompts if character_prompts else "（无）",
            world_settings=self.memory.get_world_settings_prompt(),
            sect_factions=self.memory.get_sect_factions_prompt(),
            plot_rules=self.memory.get_active_rules_prompt(),
            character_knowledge=self.memory.get_character_knowledge_prompt(chapter=chapter),
            relationship_details=self.memory.get_all_relationships_prompt(),
            scene_events=self.memory.get_scene_events_prompt(chapter=chapter),
            foreshadow_prompt=foreshadow_prompt,
            rag_context=rag_context,
        )

        # 3. 调用 LLM 生成
        content = generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=config.MAX_TOKENS,
        )

        # 4. 后处理：提取伏笔标注
        new_foreshadows = self._extract_foreshadows(content, chapter)
        for fs_content in new_foreshadows:
            self.foreshadow.plant(
                chapter=chapter,
                content=fs_content,
                type="mystery",
                related_characters=characters,
                importance=2,
            )

        # 5. 更新连续性记录
        self.continuity.add_event(
            chapter=chapter,
            time_tag=time_tag,
            event=summary,
            characters=characters,
            location=location,
            importance=3,
        )
        # 注意：character_locations 不再在此处写入，改由 _extract_and_save_world_settings 提取场景级数据
        # 但如果设定提取失败，回退到粗粒度记录
        for char in characters:
            existing_recs = [cl for cl in self.continuity.character_locations
                           if cl.chapter == chapter and cl.character == char]
            if not existing_recs:
                self.continuity.add_character_location(
                    chapter=chapter,
                    character=char,
                    location=location,
                    scene="",
                    note="粗粒度回退",
                )
            # 更新人物状态：当前位置
            if char in self.memory.characters:
                self.memory.update_character_status(
                    char,
                    notes=f"第{chapter}章出现于{location}"
                )

        # 6. 存入 RAG（可选）
        if self.rag:
            try:
                self.rag.add_chapter(chapter, title, content)
            except Exception:
                pass

        # 7. 保存更新
        self.continuity.save_all()
        self.foreshadow._save()

        # 8. 提取并回写世界设定
        self._extract_and_save_world_settings(content, chapter)

        # 9. 更新伏笔总览文件
        try:
            self.foreshadow.export_to_markdown()
        except Exception:
            pass

        return content

    # ---------- 修订方法 ----------

    def revise_chapter(self,
                         chapter: int,
                         title: str,
                         original_content: str,
                         review_report: str,
                         summary: str,
                         time_tag: str,
                         location: str,
                         characters: List[str],
                         temperature: float = 0.3) -> str:
        """
        根据审校报告修订章节，返回修订后的正文
        会自动提取审校报告中的问题并逐一修复
        """
        # 1. 构建修订 prompt
        system_prompt = CHAPTER_REVISER_SYSTEM_PROMPT.format(
            word_target=config.CHAPTER_WORD_TARGET,
        )

        # 人物 prompt
        character_prompts = "\n\n".join(
            self.memory.get_character_prompt(char)
            for char in characters
            if char in self.memory.characters
        )

        # 连续性 prompt（注入剧情规则 + 角色认知）
        continuity_prompt = self.continuity.generate_continuity_prompt(
            chapter,
            plot_rules_text=self.memory.get_active_rules_prompt(),
            character_knowledge_text=self.memory.get_character_knowledge_prompt(chapter=chapter),
        )

        # 伏笔 prompt
        foreshadow_prompt = self.foreshadow.generate_foreshadow_prompt(chapter)

        # 一致性契约
        generation_contract = self.memory.get_generation_contract(chapter, characters)

        user_prompt = CHAPTER_REVISER_USER_PROMPT.format(
            chapter=chapter,
            title=title,
            review_report=review_report,
            original_content=original_content,
            summary=summary,
            time_tag=time_tag,
            location=location,
            characters="、".join(characters),
            generation_contract=generation_contract,
            continuity_prompt=continuity_prompt,
            character_prompts=character_prompts if character_prompts else "（无）",
            world_settings=self.memory.get_world_settings_prompt(),
            sect_factions=self.memory.get_sect_factions_prompt(),
            plot_rules=self.memory.get_active_rules_prompt(),
            character_knowledge=self.memory.get_character_knowledge_prompt(chapter=chapter),
            relationship_details=self.memory.get_all_relationships_prompt(),
            scene_events=self.memory.get_scene_events_prompt(chapter=chapter),
            foreshadow_prompt=foreshadow_prompt,
        )

        # 2. 调用 LLM 生成修订版
        content = generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=config.MAX_TOKENS,
        )

        # 3. 后处理：提取伏笔标注（同 write_chapter）
        new_foreshadows = self._extract_foreshadows(content, chapter)
        for fs_content in new_foreshadows:
            self.foreshadow.plant(
                chapter=chapter,
                content=fs_content,
                type="mystery",
                related_characters=characters,
                importance=2,
            )

        # 4. 更新连续性记录（覆盖式，同 write_chapter）
        self.continuity.add_event(
            chapter=chapter,
            time_tag=time_tag,
            event=summary,
            characters=characters,
            location=location,
            importance=3,
        )
        # character_locations 由 _extract_and_save_world_settings 处理场景级数据
        # 回退：如果提取失败则用粗粒度
        for char in characters:
            existing_recs = [cl for cl in self.continuity.character_locations
                           if cl.chapter == chapter and cl.character == char]
            if not existing_recs:
                self.continuity.add_character_location(
                    chapter=chapter,
                    character=char,
                    location=location,
                    scene="",
                    note="粗粒度回退",
                )
            if char in self.memory.characters:
                self.memory.update_character_status(
                    char,
                    notes=f"第{chapter}章出现于{location}"
                )

        # 5. 提取并回写世界设定
        self._extract_and_save_world_settings(content, chapter)

        # 6. 保存更新
        self.continuity.save_all()
        self.foreshadow._save()
        try:
            self.foreshadow.export_to_markdown()
        except Exception:
            pass

        return content

    def _extract_foreshadows(self, content: str, chapter: int) -> List[str]:
        """从正文中提取伏笔（两种方式：手动标注 + LLM自动扫描）"""
        import json as _json
        results = []

        # 方式1：手动标注（支持 [FS: ...] 和 FS：... 两种格式）
        # 英文格式
        matches_en = re.findall(r'\[FS:\s*(.*?)\s*\]', content)
        results.extend(matches_en)
        # 中文格式（文章末尾写 FS：描述）
        matches_cn = re.findall(r'FS：\s*(.*?)(?:\r?\n|$)', content)
        results.extend(matches_cn)
        # 也支持 [FS：...] 格式
        matches_cn_bracket = re.findall(r'\[FS：\s*(.*?)\s*\]', content)
        results.extend(matches_cn_bracket)

        # 方式2：LLM 自动扫描（从正文中提取潜在伏笔）
        try:
            scan_prompt = """请从以下小说章节内容中，提取所有伏笔（悬念、暗示、未解之谜、神秘物品、预言等）。
伏笔特征：
- 出现神秘物品/文字（如神秘铜钱、古籍、符文）
- 人物提到未说明的过去/仇人/秘密
- 异常现象/能力（如"窥天者死"）
- 暗示未来会发生的事件
- 人物的隐藏身份/目的

输出格式（严格 JSON 数组）：
[{"content": "伏笔描述", "type": "item|mystery|prophecy|character", "importance": 1-5, "related_characters": ["人物1"]}]

只输出 JSON，不要其他内容。如果未发现明显伏笔，输出 []。

章节内容：
""" + content[-2000:]  # 只扫描最后2000字（伏笔常在章节末尾）

            scan_result = generate(
                system_prompt="你是伏笔分析专家，擅长从小说中识别伏笔。",
                user_prompt=scan_prompt,
                temperature=0.3,
                max_tokens=512,
            )

            # 解析 LLM 返回
            try:
                # 尝试直接解析
                fs_list = _json.loads(scan_result)
            except _json.JSONDecodeError:
                # 尝试提取 ```json ... ``` 代码块
                match = re.search(r'```json\s*([\s\S]*?)\s*```', scan_result)
                if match:
                    try:
                        fs_list = _json.loads(match.group(1))
                    except _json.JSONDecodeError:
                        fs_list = []
                else:
                    fs_list = []

            # 将 LLM 提取的伏笔转换为描述字符串
            for fs in fs_list:
                if isinstance(fs, dict) and "content" in fs:
                    results.append(fs["content"])
        except Exception as e:
            print(f"  [WARN] LLM 伏笔扫描失败: {e}")

        return list(set(results))  # 去重

    def _extract_and_save_world_settings(self, content: str, chapter: int):
        """从章节正文中提取新增设定，分类写入对应文件：
        - 人物设定 → characters.json
        - 势力/功法/物品等设定 → world_settings.json
        - 地点特征 → locations.json
        """
        import json as _json

        # 已有数据，用于去重和更新判断
        existing_char_names = set(self.memory.characters.keys())
        existing_ws_keys = set(self.memory.world_settings.keys())
        existing_loc_names = set(self.memory.locations.keys())

        try:
            # 构建已有人物摘要（帮助 LLM 判断是新增还是更新）
            char_summaries = []
            for name, c in self.memory.characters.items():
                abilities_str = ", ".join(c.abilities)
                rels_str = ", ".join(f"{k}({v})" for k, v in c.relationships.items())
                char_summaries.append(
                    f"  {name}：{c.gender}，{c.age}，修为={c.cultivation}，能力[{abilities_str}]，关系[{rels_str}]，状态={c.status}"
                )
            char_summary_text = "\n".join(char_summaries) if char_summaries else "（无）"

            existing_ws_text = ', '.join(sorted(existing_ws_keys)) if existing_ws_keys else '（无）'
            existing_loc_text = ', '.join(sorted(existing_loc_names)) if existing_loc_names else '（无）'
            existing_sect_names = set(self.memory.sect_factions.keys())
            existing_sect_text = ', '.join(sorted(existing_sect_names)) if existing_sect_names else '（无）'

            # JSON 格式示例（单独定义，避免 f-string 花括号转义地狱）
            json_format_example = json.dumps({
                "characters": [
                    {"name": "人物名", "is_new": True, "updates": {"abilities": ["新功法"], "cultivation": "新修为境界（如：筑基中期）", "relationships": {"他人": "关系类型"}, "relationship_contexts": {"他人": {"type": "关系类型（对手/师徒/盟友/宿敌/亲友等）", "stance": "立场（friendly/neutral/hostile/adversarial）", "met_chapter": 0, "met_context": "认识的场景描述", "key_events": ["关键事件1", "关键事件2"]}}, "appearance": "新外貌描述", "personality": "性格描述", "status": "新状态", "notes": "备注"}}
                ],
                "world_settings": [
                    {"key": "设定名（如'天孤剑诀'）", "value": "设定详细描述"}
                ],
                "sect_factions": [
                    {"name": "势力名", "is_new": True, "updates": {"type": "宗门/家族/王朝/教派", "description": "描述", "strength": "整体实力", "hierarchy": ["层级1", "层级2"], "key_members": ["成员1"], "allies": ["盟友1"], "enemies": ["敌人1"], "location": "所在地", "rules": ["门规1"]}}
                ],
                "locations": [
                    {"name": "地点名", "is_new": False, "updates": {"description": "新描述追加", "notable_characters": ["常驻人物"]}}
                ],
                "scene_events": [
                    {"location": "地点名", "scene": "场景标识（开场/中段/结尾）", "event": "发生了什么", "characters": ["参与人物"], "importance": 3}
                ],
                "spatial_movements": [
                    {"character": "人物名", "from_location": "起始地点", "to_location": "目标地点", "scene": "场景标识（如开场/中段/结尾）", "travel_method": "移动方式（如御剑飞行/步行/传送阵）", "travel_time": "耗时（如半日/三天）", "note": "补充说明"}
                ],
                "spacemap_updates": [
                    {"from_location": "地点A", "to_location": "地点B", "travel_time": "行程时间", "is_bidirectional": True}
                ],
                "plot_rules": [
                    {"condition": "触发条件（如：在天剑碑前领悟剑意）", "consequence": "结果（如：直接入内门）", "rule_text": "原文引用", "source_character": "声明此规则的角色名（如无则留空）"}
                ],
                "character_knowledge": [
                    {"character": "角色名", "knowledge": "知道了什么（如：叶青云是叶无痕的儿子）", "source": "怎么知道的（亲眼看到/听人说/推理得出/自我发现）", "detail": "补充说明（如：看到叶青云施展天孤剑诀后推断）"}
                ]
            }, ensure_ascii=False, indent=2)

            extract_prompt = f"""请从以下小说章节中，提取所有【新增的标志性设定】，分类输出。

## 需要提取的类型

### 1. 人物设定（新人物 or 已有人物的新信息）
包括：
- 新出场人物（姓名、性别、年龄、外貌、性格、背景、能力、关系）
- 已有人物的更新（新获得的能力/功法、修为境界变化、关系变化、外貌变化、状态变化如死亡/失踪/受伤）
- ⚠️ 关系变化时，必须同时提取 relationship_contexts（在什么地点、什么情况下认识的、做了什么），这对后续审校中判断角色是否认识至关重要

已有人物（不需要重复提取基础信息，只提取本章新增的变化）：
{char_summary_text}

### 2. 世界设定（势力/功法/物品/规则等）
包括：
- 势力标识（族徽、旗帜、信物、等级划分）
- 修炼功法/招式（名称、效果、等级、修炼条件）
- 独特物品/法宝（名称、外观、功能、来历）
- 社会规则/习俗（等级制度、礼仪、禁忌）
- 种族/族群特征、称号/尊称定义

已有世界设定（不需要重复提取）：
{existing_ws_text}

### 3. 地点特征（新地点 or 已有地点的新特征）
包括：
- 新地点（名称、类型、描述、相邻地点）
- 已有地点的新特征（建筑细节、结界、特殊区域等）

已有地点：
{existing_loc_text}

### 4. 空间移动（人物在章节内的场景变化）
包括：
- 人物从一个地点移动到另一个地点的记录（必须提取，这对连续性至关重要）
- 移动方式（御剑、步行、传送阵、飞行法器等）
- 移动耗时

### 5. 地点连通关系（新发现的地点间路径）
包括：
- 正文中提到两地之间的行程时间（如"天剑城到玄月城需三日"）
- 新发现的路径/通道

### 6. 剧情规则（IF-THEN 条件规则）
包括：
- 正文中角色明确声明的规则、规矩、约定（如"凡领悟剑意者可直接入内门"、"外门试炼前十名方可进入内门"）
- 宗门/势力/家族的明文规定
- 比/试/考的规则说明
⚠️ 这类规则极为重要！后续章节中角色行为必须遵守这些规则，违反则构成剧情矛盾。请务必仔细提取。

### 7. 角色认知变化（谁在这一章新知道了什么）
包括：
- 角色通过亲眼看到、听人说、推理得出等方式，新获知了某个重要信息
- 例如：角色A看到叶青云施展天孤剑诀后推断他是叶无痕的儿子
- 例如：角色B从别人口中得知了某条规则
- 例如：角色C发现了某个秘密
⚠️ 这类认知变化极为重要！后续章节中角色对已知信息不应再表现出惊讶。请务必仔细提取。
仅提取【重要的、可能影响后续剧情的】认知变化，不要提取日常琐事（如"知道今天吃什么"）。

### 8. 势力/宗派（新势力 or 已有势力的新信息）
包括：
- 新出现的势力/宗派/家族/组织（名称、类型、实力、层级结构、核心成员、盟友、敌对势力、所在地、门规）
- 已有势力的新变化（新增成员、实力变化、盟友/敌人关系变化、门规修改等）

已有势力/宗派：
{existing_sect_text}

### 9. 场景事件（本章在各场景发生了什么重要事件）
包括：
- 本章中每个场景发生的关键事件（如：在演武场举行了外门试炼、在密室中发现了血煞教卧底）
- 参与人物和事件重要性
⚠️ 这对后续审校检查事件发生地点是否正确至关重要。

## 输出格式（严格 JSON，不要其他内容）

{json_format_example}

如果某类没有新增，该字段输出空数组。如果完全没有新增设定，所有字段都输出空数组。

章节内容：
""" + content

            extract_result = generate(
                system_prompt="你是小说设定分析专家，擅长从正文中分类提取标志性设定（人物/势力/功法/物品/地点），确保不遗漏重要细节。",
                user_prompt=extract_prompt,
                temperature=0.2,
                max_tokens=2048,
            )

            # 解析 LLM 返回
            parsed = None
            try:
                parsed = _json.loads(extract_result)
            except _json.JSONDecodeError:
                match = re.search(r'```json\s*([\s\S]*?)\s*```', extract_result)
                if match:
                    try:
                        parsed = _json.loads(match.group(1))
                    except _json.JSONDecodeError:
                        parsed = None
                # 也尝试提取第一个 { ... } 块
                if parsed is None:
                    match = re.search(r'\{[\s\S]*\}', extract_result)
                    if match:
                        try:
                            parsed = _json.loads(match.group(0))
                        except _json.JSONDecodeError:
                            parsed = None

            if not parsed:
                print("  [设定提取] 未能解析 LLM 输出，跳过")
                return

            # ---- 1. 写入人物设定 → characters.json ----
            char_items = parsed.get("characters", [])
            new_char_count = 0
            updated_char_count = 0
            for item in char_items:
                if not isinstance(item, dict):
                    continue
                name = item.get("name", "").strip()
                is_new = item.get("is_new", False)
                updates = item.get("updates", {})

                if is_new:
                    # 新增人物
                    from novel_agent.core.memory import CharacterProfile
                    new_char = CharacterProfile(
                        name=name,
                        gender=updates.get("gender", ""),
                        age=updates.get("age", ""),
                        appearance=updates.get("appearance", ""),
                        personality=updates.get("personality", ""),
                        background=updates.get("background", ""),
                        goals=updates.get("goals", ""),
                        speaking_style=updates.get("speaking_style", ""),
                        abilities=updates.get("abilities", []),
                        relationships=updates.get("relationships", {}),
                        status=updates.get("status", "alive"),
                        first_appeared=chapter,
                        arc=updates.get("arc", ""),
                        notes=updates.get("notes", ""),
                    )
                    # 处理关系详细上下文
                    rel_contexts = updates.get("relationship_contexts", {})
                    for other, ctx in rel_contexts.items():
                        if isinstance(ctx, dict):
                            new_char.relationships_detail[other] = ctx
                    self.memory.add_character(new_char)
                    new_char_count += 1
                else:
                    # 更新已有人物
                    if name in self.memory.characters:
                        char = self.memory.characters[name]
                        # 更新能力列表（追加，不覆盖）
                        new_abilities = updates.get("abilities", [])
                        for ab in new_abilities:
                            if ab and ab not in char.abilities:
                                char.abilities.append(ab)
                        # 更新关系（追加或修改）
                        new_rels = updates.get("relationships", {})
                        for other, rel in new_rels.items():
                            if other and rel:
                                char.relationships[other] = rel
                        # 更新关系详细上下文（追加或修改）
                        new_rel_contexts = updates.get("relationship_contexts", {})
                        for other, ctx in new_rel_contexts.items():
                            if isinstance(ctx, dict) and other:
                                if other in char.relationships_detail:
                                    # 合并：更新非空字段，追加 key_events
                                    existing_ctx = char.relationships_detail[other]
                                    for k, v in ctx.items():
                                        if k == "key_events" and isinstance(v, list):
                                            existing_events = existing_ctx.get("key_events", [])
                                            for evt in v:
                                                if evt not in existing_events:
                                                    existing_events.append(evt)
                                            existing_ctx["key_events"] = existing_events
                                        elif v:
                                            existing_ctx[k] = v
                                else:
                                    char.relationships_detail[other] = ctx
                        # 更新其他字段（非空才更新）
                        for field_name in ["cultivation", "appearance", "personality", "status", "goals", "notes"]:
                            val = updates.get(field_name, "")
                            if val:
                                setattr(char, field_name, val)
                        updated_char_count += 1

            if new_char_count > 0 or updated_char_count > 0:
                self.memory._save_characters()
                parts = []
                if new_char_count > 0:
                    parts.append(f"新增 {new_char_count} 个人物")
                if updated_char_count > 0:
                    parts.append(f"更新 {updated_char_count} 个人物")
                print(f"  [设定提取·人物] {', '.join(parts)}")

            # ---- 2. 写入世界设定 → world_settings.json ----
            ws_items = parsed.get("world_settings", [])
            new_ws_count = 0
            for item in ws_items:
                if not isinstance(item, dict):
                    continue
                key = item.get("key", "").strip()
                value = item.get("value", "").strip()
                if not key or not value:
                    continue
                if key in existing_ws_keys:
                    # 已存在则追加
                    old = self.memory.world_settings[key].value
                    if value not in old:
                        self.memory.world_settings[key].value = old + "；" + value
                else:
                    from novel_agent.core.memory import WorldSetting
                    self.memory.add_world_setting(WorldSetting(
                        key=key,
                        value=value,
                        chapter_introduced=chapter,
                    ))
                    new_ws_count += 1

            if new_ws_count > 0:
                self.memory._save_world_settings()
                print(f"  [设定提取·世界] 新增 {new_ws_count} 条世界设定")

            # ---- 3. 写入地点设定 → locations.json ----
            loc_items = parsed.get("locations", [])
            new_loc_count = 0
            updated_loc_count = 0
            for item in loc_items:
                if not isinstance(item, dict):
                    continue
                name = item.get("name", "").strip()
                is_new = item.get("is_new", False)
                updates = item.get("updates", {})

                if is_new:
                    from novel_agent.core.memory import LocationProfile
                    new_loc = LocationProfile(
                        name=name,
                        description=updates.get("description", ""),
                        type=updates.get("type", "city"),
                        connected_to=updates.get("connected_to", []),
                        first_appeared=chapter,
                        notable_characters=updates.get("notable_characters", []),
                        notes=updates.get("notes", ""),
                    )
                    self.memory.add_location(new_loc)
                    new_loc_count += 1
                else:
                    # 更新已有地点
                    if name in self.memory.locations:
                        loc = self.memory.locations[name]
                        desc_append = updates.get("description", "")
                        if desc_append and desc_append not in loc.description:
                            loc.description = loc.description.rstrip("。") + "；" + desc_append
                        new_notable = updates.get("notable_characters", [])
                        for nc in new_notable:
                            if nc and nc not in loc.notable_characters:
                                loc.notable_characters.append(nc)
                        notes_append = updates.get("notes", "")
                        if notes_append:
                            loc.notes = (loc.notes + "；" + notes_append) if loc.notes else notes_append
                        updated_loc_count += 1

            if new_loc_count > 0 or updated_loc_count > 0:
                self.memory._save_locations()
                parts = []
                if new_loc_count > 0:
                    parts.append(f"新增 {new_loc_count} 个地点")
                if updated_loc_count > 0:
                    parts.append(f"更新 {updated_loc_count} 个地点")
                print(f"  [设定提取·地点] {', '.join(parts)}")

            # ---- 4. 写入空间移动 → character_locations.json ----
            spatial_items = parsed.get("spatial_movements", [])
            movement_count = 0
            for item in spatial_items:
                if not isinstance(item, dict):
                    continue
                char_name = item.get("character", "").strip()
                to_loc = item.get("to_location", "").strip()
                if not char_name or not to_loc:
                    continue
                scene = item.get("scene", "")
                travel_method = item.get("travel_method", "")
                travel_time = item.get("travel_time", "")
                note_parts = []
                if travel_method:
                    note_parts.append(travel_method)
                if travel_time:
                    note_parts.append(travel_time)
                if item.get("note", ""):
                    note_parts.append(item["note"])
                note = "，".join(note_parts)
                self.continuity.add_character_location(
                    chapter=chapter,
                    character=char_name,
                    location=to_loc,
                    scene=scene,
                    note=note,
                )
                movement_count += 1

            if movement_count > 0:
                self.continuity._save_character_locations()
                print(f"  [设定提取·空间] 记录 {movement_count} 条人物移动")

            # ---- 5. 更新地点连通 → spacemap.json ----
            spacemap_items = parsed.get("spacemap_updates", [])
            spacemap_count = 0
            for item in spacemap_items:
                if not isinstance(item, dict):
                    continue
                from_loc = item.get("from_location", "").strip()
                to_loc = item.get("to_location", "").strip()
                if not from_loc or not to_loc:
                    continue
                travel_time = item.get("travel_time", "")
                is_bidir = item.get("is_bidirectional", True)

                # 更新 from_loc 的连接
                if from_loc in self.continuity.spacemap:
                    node = self.continuity.spacemap[from_loc]
                    if to_loc not in node.connected_to:
                        node.connected_to.append(to_loc)
                    if travel_time:
                        node.travel_time[to_loc] = travel_time
                else:
                    self.continuity.add_location(SpaceNode(
                        name=from_loc,
                        connected_to=[to_loc],
                        travel_time={to_loc: travel_time} if travel_time else {},
                    ))

                # 双向则也更新 to_loc 的连接
                if is_bidir:
                    if to_loc in self.continuity.spacemap:
                        node = self.continuity.spacemap[to_loc]
                        if from_loc not in node.connected_to:
                            node.connected_to.append(from_loc)
                        if travel_time:
                            node.travel_time[from_loc] = travel_time
                    else:
                        self.continuity.add_location(SpaceNode(
                            name=to_loc,
                            connected_to=[from_loc],
                            travel_time={from_loc: travel_time} if travel_time else {},
                        ))
                spacemap_count += 1

            if spacemap_count > 0:
                self.continuity._save_spacemap()
                print(f"  [设定提取·连通] 更新 {spacemap_count} 条地点连通")

            # ---- 6. 写入剧情规则 → plot_rules.json ----
            rule_items = parsed.get("plot_rules", [])
            rule_count = 0
            for item in rule_items:
                if not isinstance(item, dict):
                    continue
                condition = item.get("condition", "").strip()
                consequence = item.get("consequence", "").strip()
                rule_text = item.get("rule_text", "").strip()
                if not condition or not consequence:
                    continue
                from novel_agent.core.memory import PlotRule
                rule = PlotRule(
                    condition=condition,
                    consequence=consequence,
                    rule_text=rule_text if rule_text else f"若{condition}，则{consequence}",
                    chapter_introduced=chapter,
                    source_character=item.get("source_character", "").strip(),
                )
                self.memory.add_plot_rule(rule)
                rule_count += 1

            if rule_count > 0:
                print(f"  [设定提取·规则] 新增 {rule_count} 条剧情规则")

            # ---- 7. 写入角色认知 → character_knowledge.json ----
            knowledge_items = parsed.get("character_knowledge", [])
            knowledge_count = 0
            for item in knowledge_items:
                if not isinstance(item, dict):
                    continue
                char_name = item.get("character", "").strip()
                knowledge_text = item.get("knowledge", "").strip()
                source = item.get("source", "").strip()
                detail = item.get("detail", "").strip()
                if not char_name or not knowledge_text:
                    continue
                from novel_agent.core.memory import CharacterKnowledge
                k = CharacterKnowledge(
                    character=char_name,
                    chapter_learned=chapter,
                    knowledge=knowledge_text,
                    source=source if source else "未知",
                    detail=detail,
                )
                self.memory.add_character_knowledge(k)
                knowledge_count += 1

            if knowledge_count > 0:
                print(f"  [设定提取·认知] 新增 {knowledge_count} 条角色认知")

            # ---- 8. 写入势力/宗派 → sect_factions.json ----
            sect_items = parsed.get("sect_factions", [])
            new_sect_count = 0
            updated_sect_count = 0
            for item in sect_items:
                if not isinstance(item, dict):
                    continue
                name = item.get("name", "").strip()
                is_new = item.get("is_new", False)
                updates = item.get("updates", {})
                if not name:
                    continue
                if is_new or name not in self.memory.sect_factions:
                    from novel_agent.core.memory import SectFaction
                    faction = SectFaction(
                        name=name,
                        type=updates.get("type", ""),
                        description=updates.get("description", ""),
                        strength=updates.get("strength", ""),
                        hierarchy=updates.get("hierarchy", []),
                        key_members=updates.get("key_members", []),
                        allies=updates.get("allies", []),
                        enemies=updates.get("enemies", []),
                        location=updates.get("location", ""),
                        rules=updates.get("rules", []),
                        first_appeared=chapter,
                        notes=updates.get("notes", ""),
                    )
                    self.memory.add_sect_faction(faction)
                    new_sect_count += 1
                else:
                    # 更新已有势力
                    self.memory.update_sect_faction(name, **{
                        k: v for k, v in updates.items() if v
                    })
                    updated_sect_count += 1

            if new_sect_count > 0 or updated_sect_count > 0:
                parts = []
                if new_sect_count > 0:
                    parts.append(f"新增 {new_sect_count} 个势力")
                if updated_sect_count > 0:
                    parts.append(f"更新 {updated_sect_count} 个势力")
                print(f"  [设定提取·势力] {', '.join(parts)}")

            # ---- 9. 写入场景事件 → scene_events.json ----
            scene_items = parsed.get("scene_events", [])
            scene_count = 0
            for item in scene_items:
                if not isinstance(item, dict):
                    continue
                location = item.get("location", "").strip()
                event = item.get("event", "").strip()
                if not location or not event:
                    continue
                from novel_agent.core.memory import SceneEvent
                scene_event = SceneEvent(
                    chapter=chapter,
                    location=location,
                    scene=item.get("scene", ""),
                    event=event,
                    characters=item.get("characters", []),
                    importance=item.get("importance", 1),
                )
                self.memory.add_scene_event(scene_event)
                scene_count += 1

            if scene_count > 0:
                print(f"  [设定提取·场景] 新增 {scene_count} 条场景事件")

        except Exception as e:
            print(f"  [WARN] 设定提取失败: {e}")

    def save_chapter(self, chapter: int, title: str, content: str,
                      output_dir: str = None):
        """保存章节到文件"""
        out_dir = Path(output_dir or config.OUTPUT_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        chapters_dir = out_dir / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)

        # 追加模式写入 novel.md
        novel_path = out_dir / "novel.md"
        with open(novel_path, "a", encoding="utf-8") as f:
            f.write(f"\n\n## 第{chapter}章 {title}\n\n")
            f.write(content)
            f.write("\n\n")

        # 单独保存本章（存入 chapters/ 子目录）
        chapter_path = chapters_dir / f"chapter_{chapter:03d}.md"
        with open(chapter_path, "w", encoding="utf-8") as f:
            f.write(f"# 第{chapter}章 {title}\n\n")
            f.write(content)

    def load_chapter(self, chapter: int, output_dir: str = None) -> str:
        """读取已生成的章节"""
        out_dir = Path(output_dir or config.OUTPUT_DIR)
        chapters_dir = out_dir / "chapters"
        chapter_path = chapters_dir / f"chapter_{chapter:03d}.md"
        if chapter_path.exists():
            with open(chapter_path, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def get_chapter_summary(self, content: str, max_length: int = 200) -> str:
        """生成章节摘要（用于连续性记录）"""
        # 简单截取开头
        return content[:max_length].replace("\n", " ").strip() + "..."
