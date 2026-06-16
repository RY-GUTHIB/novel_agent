"""
planner_agent.py - 大纲规划 Agent

职责：
1. 接收用户的小说设定（类型、风格、核心创意）
2. 生成完整大纲（世界观、人物表、情节主线/支线、章节规划）
3. 初始化 memory.py、continuity.py、foreshadow.py 的数据
"""

import json
import re
import logging
from typing import Dict

from novel_agent.core.models import CharacterProfile, LocationProfile, WorldSetting
from novel_agent.core.memory import MemoryManager
from novel_agent.core.continuity import ContinuityGuard
from novel_agent.core.foreshadow import ForeshadowTracker
from novel_agent.llm.client import generate
from .prompts import PLANNER_SYSTEM_PROMPT, OUTLINE_REFINE_PROMPT

logger = logging.getLogger(__name__)


class PlannerAgent:
    """大纲规划 Agent"""

    def __init__(self, memory_mgr: MemoryManager,
                  continuity_guard: ContinuityGuard,
                  foreshadow_tracker: ForeshadowTracker):
        self.memory = memory_mgr
        self.continuity = continuity_guard
        self.foreshadow = foreshadow_tracker

    def generate_outline(self, user_idea: str, genre: str = "玄幻", style: str = "热血") -> Dict:
        user_prompt = f"""请为以下创意生成完整长篇小说大纲：

【类型】{genre}
【风格】{style}
【核心创意】{user_idea}

特别注意：
1. 这是超长篇小说（目标300章+），大纲先规划4卷，每卷10-15章，总共40-60章的框架
2. 势力关系必须逻辑自洽：如果A势力是B的靠山，那A不能同时又帮B的敌人
3. 主角成长要慢：每卷只突破1-2个境界，要有挫折、失败、领悟再突破的过程
4. 结局不能自爆/同归于尽，主角要活着继续成长
5. 每卷之间要有跨卷伏笔

请严格按照 JSON 格式输出。"""

        base_user_prompt = user_prompt  # 保存原始 prompt，不累积追加
        max_retries = 2
        current_temperature = 0.7
        current_max_tokens = 16384
        for attempt in range(max_retries + 1):
            # 重试时不累积追加文本，而是替换为精简提示 + 增大输出空间
            if attempt == 0:
                retry_hint = ""
            elif attempt == 1:
                retry_hint = "\n\n⚠️ 上次输出 JSON 格式错误。请只输出 JSON，不要加任何解释文字或 markdown 标记。"
                current_temperature = 0.5
                current_max_tokens = 20480
            else:
                retry_hint = "\n\n⚠️ 上次输出 JSON 被截断或格式错误。请精简内容、确保 JSON 完整闭合。只输出纯 JSON。"
                current_temperature = 0.3
                current_max_tokens = 24576

            response = generate(
                system_prompt=PLANNER_SYSTEM_PROMPT,
                user_prompt=base_user_prompt + retry_hint,
                temperature=current_temperature,
                max_tokens=current_max_tokens,
            )

            try:
                outline = self._extract_json(response)
            except ValueError as e:
                if attempt < max_retries:
                    print(f"  [WARN] {e}，重试 ({attempt+2}/{max_retries+1})...")
                    continue
                raise

            if outline is not None:
                self._init_from_outline(outline)
                return outline

            if attempt < max_retries:
                print(f"  [WARN] JSON 解析失败，重试 ({attempt+2}/{max_retries+1})...")

        raise ValueError("大纲生成失败：LLM 返回格式错误，已重试3次仍无法解析")

    def refine_outline(self, current_outline: Dict, user_request: str) -> Dict:
        user_prompt = OUTLINE_REFINE_PROMPT.format(
            current_outline=json.dumps(current_outline, ensure_ascii=False, indent=2),
            user_request=user_request,
        )
        response = generate(
            system_prompt=PLANNER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.7,
            max_tokens=8192,
        )
        new_outline = self._extract_json(response)
        if new_outline:
            self._init_from_outline(new_outline, clear=True)
        return new_outline

    def _init_from_outline(self, outline: Dict, clear: bool = True):
        """将大纲数据写入各管理模块"""
        if clear:
            self.memory.characters.clear()
            self.memory.locations.clear()
            self.memory.world_settings.clear()
            self.continuity.timeline.clear()
            self.continuity.spacemap.clear()
            self.continuity.character_locations.clear()
            self.foreshadow.foreshadows.clear()

        self._init_world_settings(outline)
        self._init_characters(outline)
        self._init_locations(outline)
        self._init_factions(outline)
        self._init_chapters(outline)

        self.memory.save_all()
        self.continuity.save_all()
        self.foreshadow._save()

    def _init_world_settings(self, outline: Dict):
        ws = outline.get("world_setting", {})
        self.memory.add_world_setting(WorldSetting(key="世界观总览", value=ws.get("description", "")))
        for i, rule in enumerate(ws.get("rules", []), 1):
            self.memory.add_world_setting(WorldSetting(key=f"规则{i}", value=rule))
        if ws.get("power_system"):
            self.memory.add_world_setting(WorldSetting(key="力量体系", value=ws["power_system"]))

    def _init_characters(self, outline: Dict):
        for c_data in outline.get("characters", []):
            self.memory.add_character(CharacterProfile(
                name=c_data["name"], gender=c_data.get("gender", ""),
                age=c_data.get("age", ""), appearance=c_data.get("appearance", ""),
                personality=c_data.get("personality", ""), background=c_data.get("background", ""),
                goals=c_data.get("goals", ""), speaking_style=c_data.get("speaking_style", ""),
                abilities=c_data.get("abilities", []), relationships=c_data.get("relationships", {}),
            ))

    def _init_locations(self, outline: Dict):
        for loc_data in outline.get("locations", []):
            profile = LocationProfile(
                name=loc_data["name"], description=loc_data.get("description", ""),
                type=loc_data.get("type", "city"), connected_to=loc_data.get("connected_to", []),
            )
            self.continuity.add_location(profile)
            self.memory.add_location(profile)

    def _init_factions(self, outline: Dict):
        ws = outline.get("world_setting", {})
        for fac_data in ws.get("factions", []):
            fac_info = f"{fac_data['name']}（{fac_data.get('type', '')}）：实力{fac_data.get('strength', '')}"
            if fac_data.get("allies"):
                fac_info += f"；盟友：{', '.join(fac_data['allies'])}"
            if fac_data.get("enemies"):
                fac_info += f"；敌对：{', '.join(fac_data['enemies'])}"
            if fac_data.get("key_members"):
                fac_info += f"；核心成员：{', '.join(fac_data['key_members'])}"
            self.memory.add_world_setting(WorldSetting(key=f"势力-{fac_data['name']}", value=fac_info))

    def _init_chapters(self, outline: Dict):
        all_chapters = []
        volumes = outline.get("volumes", [])
        if volumes:
            for vol in volumes:
                vol_info = (f"第{vol.get('volume', '?')}卷「{vol.get('title', '')}」："
                           f"{vol.get('arc_summary', '')} | 修为范围：{vol.get('power_range', '')}")
                self.memory.add_world_setting(WorldSetting(
                    key=f"卷{vol.get('volume', '?')}-{vol.get('title', '')}", value=vol_info,
                ))
                all_chapters.extend(vol.get("chapter_plan", []))
        else:
            all_chapters = outline.get("chapter_plan", [])

        for ch_data in all_chapters:
            chapter = ch_data.get("chapter", 1)
            time_tag = ch_data.get("time_tag", f"第{chapter}章")
            summary = ch_data.get("summary", "")
            location = ch_data.get("location", "")
            characters = ch_data.get("characters", [])

            self.continuity.add_event(
                chapter=chapter, time_tag=time_tag, event=summary,
                characters=characters, location=location, importance=3,
            )
            for char in characters:
                self.continuity.add_character_location(chapter=chapter, character=char, location=location)

            for fs_content in ch_data.get("foreshadows", []):
                if fs_content:
                    self.foreshadow.plant(chapter=chapter, content=fs_content, type="mystery",
                                          related_characters=characters, importance=3)

        # 如果预埋伏笔超过30条，只保留每卷前5条（控制预埋量）
        total_fs = len(self.foreshadow.foreshadows)
        if total_fs > 30:
            # 按章节分组
            by_chapter = {}
            for fs in self.foreshadow.foreshadows:
                ch = fs.chapter_planted
                if ch not in by_chapter:
                    by_chapter[ch] = []
                by_chapter[ch].append(fs)

            # 按卷分组（使用 volumes 的章节范围）
            kept = []
            volumes = outline.get("volumes", [])
            if volumes:
                for vol in volumes:
                    vol_chs = [c["chapter"] for c in vol.get("chapter_plan", []) if c.get("chapter") in by_chapter]
                    vol_fs = [fs for ch in vol_chs for fs in by_chapter[ch]]
                    kept_for_vol = vol_fs[:5]  # 每卷保留前5条
                    kept.extend(kept_for_vol)
            else:
                # 无 volumes 信息，按章节顺序取前5条
                all_chs = sorted(by_chapter.keys())
                vol_fs = [fs for ch in all_chs for fs in by_chapter[ch]]
                kept = vol_fs[:5]

            # 去重
            seen = set()
            final = []
            for fs in kept:
                if fs.id not in seen:
                    seen.add(fs.id)
                    final.append(fs)
            self.foreshadow.foreshadows = final
            print(f"  📌 预埋伏笔从 {total_fs} 条精简至 {len(final)} 条（每卷保留≤5条）")

    @staticmethod
    def _extract_json(text: str) -> Dict:
        """从 LLM 输出中提取 JSON，多层 fallback + 截断检测 + 修复尝试"""
        # 第1层：直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 第2层：提取 markdown 代码块
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # 第3层：提取最外层大括号（贪婪匹配到最后一个 }）
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        # 第4层：检测截断并尝试修复
        match = re.search(r'\{[\s\S]*', text)
        if match:
            partial = match.group(0)
            # 用栈精确计算括号平衡
            stack = []
            for ch in partial:
                if ch in '{[':
                    stack.append(ch)
                elif ch == '}':
                    if stack and stack[-1] == '{':
                        stack.pop()
                    else:
                        stack.append(ch)
                elif ch == ']':
                    if stack and stack[-1] == '[':
                        stack.pop()
                    else:
                        stack.append(ch)
            open_braces = sum(1 for c in stack if c == '{')
            open_brackets = sum(1 for c in stack if c == '[')
            if open_braces > 0 or open_brackets > 0:
                # 尝试补全闭合括号后重新解析
                repaired = partial + '}' * open_braces + ']' * open_brackets
                try:
                    return json.loads(repaired)
                except json.JSONDecodeError:
                    raise ValueError(
                        f"大纲 JSON 被截断（缺少 {open_braces} 个闭合花括号, {open_brackets} 个闭合方括号），"
                        f"自动补全后仍无法解析。请增大 max_tokens 后重试。"
                    )
        return None

    def save_outline_json(self, outline: Dict, filepath: str = None):
        from pathlib import Path
        if filepath is None:
            filepath = self.memory.data_dir / "outline.json"
        else:
            filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(outline, f, ensure_ascii=False, indent=2)
