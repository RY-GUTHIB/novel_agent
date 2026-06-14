"""
planner_agent.py - 大纲规划 Agent

职责：
1. 接收用户的小说设定（类型、风格、核心创意）
2. 生成完整大纲（世界观、人物表、情节主线/支线、章节规划）
3. 初始化 memory.py、continuity.py、foreshadow.py 的数据
"""

from typing import Dict, List
from novel_agent.core.memory import MemoryManager, CharacterProfile, LocationProfile, WorldSetting
from novel_agent.core.continuity import ContinuityGuard, SpaceNode
from novel_agent.core.foreshadow import ForeshadowTracker
from novel_agent.llm.client import generate


# ---------- Prompt 模板 ----------

PLANNER_SYSTEM_PROMPT = """你是一位资深长篇网文策划编辑，擅长构建完整、自洽的超长篇故事框架（目标300-500章体量）。

请将用户的核心创意扩展为完整的长篇小说大纲，严格按以下 JSON 格式输出（不要输出其他内容）：

{
  "title": "小说标题",
  "genre": "类型",
  "style": "风格",
  "world_setting": {
    "description": "世界观总体描述",
    "rules": ["规则1", "规则2"],
    "power_system": "力量体系描述（列出所有境界，从低到高）",
    "factions": [{"name": "势力名", "type": "宗门/家族/王朝/散修联盟", "strength": "实力描述", "allies": ["盟友"], "enemies": ["敌对"], "key_members": ["核心成员"]}]
  },
  "characters": [
    {"name": "名", "gender": "性", "age": "龄", "appearance": "外貌", "personality": "性格", "background": "背景", "goals": "目标", "speaking_style": "语言风格", "abilities": ["能力1"], "relationships": {"他人": "关系"}}
  ],
  "locations": [
    {"name": "地名", "type": "city/mountain/sect/forest/dungeon", "description": "描述", "connected_to": ["相邻地"]}
  ],
  "plot_outline": {
    "beginning": "起始",
    "rising": "发展",
    "climax": "高潮",
    "falling": "回落",
    "ending": "结局"
  },
  "volumes": [
    {
      "volume": 1,
      "title": "卷名",
      "arc_summary": "本卷核心冲突和主角成长弧线",
      "power_range": "本卷主角修为范围（如：炼气→筑基）",
      "chapter_plan": [
        {"chapter": 1, "title": "标题", "summary": "摘要", "time_tag": "时间", "location": "地点", "characters": ["人物"], "foreshadows": ["伏笔"]}
      ]
    }
  ]
}

严格要求：
1. 【多卷制】至少规划4卷，每卷10-15章（后续可扩充），总章数至少40章
2. 【节奏控制】每卷主角只突破1-2个境界，严禁跳级或短期内连破数境
3. 【势力逻辑】factions 必须清晰列出势力关系，不能出现"A势力同时是B的靠山和C的靠山，但B和C是敌对"这种矛盾
4. 【逻辑自洽】每个势力的立场必须前后一致，人物的行为必须符合其势力归属
5. 【禁用自爆】结局不允许主角自爆/同归于尽，这是长篇小说，主角要活着继续成长
6. 【成长弧线】主角的成长必须是渐进式的：挫折→领悟→突破→新挑战，不能一路碾压
7. 【伏笔网络】每卷至少埋3条跨卷伏笔，贯穿全书
8. 每章 foreshadows 如果没有就留空数组
9. 人物关系要形成网络
10. 地点拓扑要合理
11. 必须输出完整 JSON，不要截断
"""

OUTLINE_REFINE_PROMPT = """基于以下已有大纲，请补充/修改：

{current_outline}

用户要求：
{user_request}

请输出完整的更新后大纲（JSON格式，同初始格式）。"""


# ---------- 主 Agent ----------

class PlannerAgent:
    """大纲规划 Agent"""

    def __init__(self, memory_mgr: MemoryManager,
                  continuity_guard: ContinuityGuard,
                  foreshadow_tracker: ForeshadowTracker):
        self.memory = memory_mgr
        self.continuity = continuity_guard
        self.foreshadow = foreshadow_tracker

    def generate_outline(self, user_idea: str,
                          genre: str = "玄幻",
                          style: str = "热血") -> Dict:
        """
        根据用户核心创意生成完整大纲
        :param user_idea: 用户的核心创意/设定
        :param genre: 小说类型
        :param style: 风格
        :return: 大纲字典（同JSON格式）
        """
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

        response = generate(
            system_prompt=PLANNER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.7,  # 规划用较低温度，保持逻辑性
            max_tokens=16384,
        )

        # 解析 JSON（容错处理）
        outline = self._extract_json(response)
        if outline is None:
            raise ValueError("大纲生成失败：LLM 返回格式错误，请重试")

        # 初始化各模块数据
        self._init_from_outline(outline)

        return outline

    def refine_outline(self, current_outline: Dict, user_request: str) -> Dict:
        """根据用户反馈修改大纲"""
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

        # 世界观
        ws = outline.get("world_setting", {})
        self.memory.add_world_setting(WorldSetting(
            key="世界观总览",
            value=ws.get("description", ""),
        ))
        for rule in ws.get("rules", []):
            self.memory.add_world_setting(WorldSetting(
                key=f"规则{ws['rules'].index(rule)+1}",
                value=rule,
            ))
        if ws.get("power_system"):
            self.memory.add_world_setting(WorldSetting(
                key="力量体系",
                value=ws["power_system"],
            ))

        # 人物
        for c_data in outline.get("characters", []):
            profile = CharacterProfile(
                name=c_data["name"],
                gender=c_data.get("gender", ""),
                age=c_data.get("age", ""),
                appearance=c_data.get("appearance", ""),
                personality=c_data.get("personality", ""),
                background=c_data.get("background", ""),
                goals=c_data.get("goals", ""),
                speaking_style=c_data.get("speaking_style", ""),
                abilities=c_data.get("abilities", []),
                relationships=c_data.get("relationships", {}),
            )
            self.memory.add_character(profile)

        # 地点
        for loc_data in outline.get("locations", []):
            node = SpaceNode(
                name=loc_data["name"],
                description=loc_data.get("description", ""),
                type=loc_data.get("type", "city"),
                connected_to=loc_data.get("connected_to", []),
            )
            self.continuity.add_location(node)
            self.memory.add_location(LocationProfile(
                name=loc_data["name"],
                description=loc_data.get("description", ""),
                type=loc_data.get("type", "city"),
                connected_to=loc_data.get("connected_to", []),
            ))

        # 势力信息
        for fac_data in ws.get("factions", []):
            fac_info = f"{fac_data['name']}（{fac_data.get('type', '')}）：实力{fac_data.get('strength', '')}"
            if fac_data.get("allies"):
                fac_info += f"；盟友：{', '.join(fac_data['allies'])}"
            if fac_data.get("enemies"):
                fac_info += f"；敌对：{', '.join(fac_data['enemies'])}"
            if fac_data.get("key_members"):
                fac_info += f"；核心成员：{', '.join(fac_data['key_members'])}"
            self.memory.add_world_setting(WorldSetting(
                key=f"势力-{fac_data['name']}",
                value=fac_info,
            ))

        # 章节计划 → 时间线 + 人物位置（支持 volumes 和 chapter_plan 两种格式）
        all_chapters = []
        volumes = outline.get("volumes", [])
        if volumes:
            for vol in volumes:
                vol_info = f"第{vol.get('volume', '?')}卷「{vol.get('title', '')}」：{vol.get('arc_summary', '')} | 修为范围：{vol.get('power_range', '')}"
                self.memory.add_world_setting(WorldSetting(
                    key=f"卷{vol.get('volume', '?')}-{vol.get('title', '')}",
                    value=vol_info,
                ))
                for ch_data in vol.get("chapter_plan", []):
                    all_chapters.append(ch_data)
        else:
            all_chapters = outline.get("chapter_plan", [])

        for ch_data in all_chapters:
            chapter = ch_data.get("chapter", 1)
            time_tag = ch_data.get("time_tag", f"第{chapter}章")
            summary = ch_data.get("summary", "")
            location = ch_data.get("location", "")
            characters = ch_data.get("characters", [])

            # 时间线
            self.continuity.add_event(
                chapter=chapter,
                time_tag=time_tag,
                event=summary,
                characters=characters,
                location=location,
                importance=3,  # 大纲事件默认中高重要性
            )

            # 人物位置
            for char in characters:
                self.continuity.add_character_location(
                    chapter=chapter,
                    character=char,
                    location=location,
                )

            # 伏笔（如有）
            for fs_content in ch_data.get("foreshadows", []):
                if fs_content:
                    self.foreshadow.plant(
                        chapter=chapter,
                        content=fs_content,
                        type="mystery",
                        related_characters=characters,
                        importance=3,
                    )

        # 保存所有数据
        self.memory.save_all()
        self.continuity.save_all()
        self.foreshadow._save()

    @staticmethod
    def _extract_json(text: str) -> Dict:
        """从 LLM 输出中提取 JSON（容错，支持截断修复）"""
        import json
        import re

        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试提取 ```json ... ``` 代码块
        match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试提取最外层 { ... }
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        # 截断修复：LLM 输出可能被 max_tokens 截断，尝试补全
        match = re.search(r'\{[\s\S]*', text)
        if match:
            partial = match.group(0)
            # 尝试逐步补全括号
            for _ in range(20):
                try:
                    return json.loads(partial)
                except json.JSONDecodeError:
                    # 计算缺少的右括号
                    open_braces = partial.count('{') - partial.count('}')
                    open_brackets = partial.count('[') - partial.count(']')
                    if open_braces <= 0 and open_brackets <= 0:
                        break
                    # 在最后一个完整值后截断并补全
                    # 尝试找最后一个逗号或冒号后截断
                    for trim_char in [',', ':']:
                        last_pos = partial.rfind(trim_char)
                        if last_pos > 0:
                            trimmed = partial[:last_pos]
                            # 补全缺失的右括号
                            needed_braces = trimmed.count('{') - trimmed.count('}')
                            needed_brackets = trimmed.count('[') - trimmed.count(']')
                            try:
                                return json.loads(trimmed + ']' * max(0, needed_brackets) + '}' * max(0, needed_braces))
                            except json.JSONDecodeError:
                                continue
                    break

        return None

    def save_outline_json(self, outline: Dict, filepath: str = None):
        """保存大纲到 JSON 文件"""
        import json as _json
        from pathlib import Path
        if filepath is None:
            filepath = self.memory.data_dir / "outline.json"
        else:
            filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            _json.dump(outline, f, ensure_ascii=False, indent=2)
