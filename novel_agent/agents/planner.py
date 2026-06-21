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
from pathlib import Path
from typing import Dict

import config
from novel_agent.core.models import CharacterProfile, LocationProfile, WorldSetting
from novel_agent.core.memory import MemoryManager
from novel_agent.core.continuity import ContinuityGuard
from novel_agent.core.foreshadow import ForeshadowTracker
from novel_agent.core.file_utils import atomic_write_json
from novel_agent.llm.client import generate, parse_json
from .prompts import PLANNER_SYSTEM_PROMPT, OUTLINE_REFINE_PROMPT

logger = logging.getLogger(__name__)


class PlannerAgent:
    """大纲规划 Agent"""

    def __init__(self, memory_mgr: MemoryManager,
                  continuity_guard: ContinuityGuard,
                  foreshadow_tracker: ForeshadowTracker,
                  ctx: config.ProjectContext):
        self.memory = memory_mgr
        self.continuity = continuity_guard
        self.foreshadow = foreshadow_tracker
        self.ctx = ctx

    def generate_outline(self, user_idea: str, genre: str = "玄幻", style: str = "热血") -> Dict:
        user_prompt = f"""请为以下创意生成完整长篇小说大纲：

【类型】{genre}
【风格】{style}
【核心创意】{user_idea}

特别注意：
1. 这是超长篇小说（目标300章+），大纲先规划5卷，每卷15-20章，总共至少50章。逻辑递进合理即可，不需要强制写结局（后续可续写）。
2. 前10章通过对话自然交代力量体系，不要旁白大段说明
3. 势力关系必须满足传递性无冲突，每个势力输出 alliance_chain
4. 主角成长要慢，每卷突破非强制要求，大境界突破占用一整卷核心事件
5. 被压制后本卷内必须反杀，破而后立：3章内遇机缘→7章内完成
6. 暂退需8章内重返清算
7. 结局不能自爆/同归于尽，主角要活着继续成长
8. 每卷至少1条跨卷伏笔（type: "cross_volume"），伏笔总量不超过30条
9. 每卷必须有 arc 四节点（setback/insight/breakthrough/new_challenge）
10. 所有关键人物必须有 first_appearance 和 exit_point
11. 所有关键物品 giver 必须唯一，禁止同一物品多个赠与者
12. 伏笔跨卷不超过2卷未回收

请严格按照 JSON 格式输出，不要加任何解释文字。"""

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
                if outline is not None:
                    self._init_from_outline(outline)
                    return outline
            except ValueError as e:
                if attempt < max_retries:
                    logger.warning("%s，重试 (%d/%d)...", e, attempt + 2, max_retries + 1)
                    continue
                raise

            if attempt < max_retries:
                logger.warning("JSON 解析失败，重试 (%d/%d)...", attempt + 2, max_retries + 1)

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
            try:
                self._init_from_outline(new_outline, clear=True)
            except ValueError as e:
                logger.warning("大纲精炼结构检查失败: %s", e)
                raise
        return new_outline

    def _validate_outline_structure(self, outline: dict):
        """检查大纲关键字段类型，不符合则抛 ValueError 触发 LLM 重试"""
        required = {
            "meta": dict,
            "volumes": list,
            "characters": list,
            "locations": list,
            "factions": list,
            "key_items": list,
            "foreshadows": list,
        }
        for key, expected in required.items():
            val = outline.get(key)
            if val is not None and not isinstance(val, expected):
                raise ValueError(
                    f"大纲字段 '{key}' 类型错误: 期望 {expected.__name__}，实际 {type(val).__name__}，触发重试"
                )
        # volumes 里的每个元素必须是 dict
        for vol in outline.get("volumes", []):
            if not isinstance(vol, dict):
                raise ValueError(f"volumes 中的元素不是对象，触发重试")
            arc = vol.get("arc")
            if arc is not None and not isinstance(arc, dict):
                raise ValueError(f"卷 {vol.get('volume', '?')} 的 arc 应为对象，实际为 {type(arc).__name__}，触发重试")
            for ch in vol.get("chapters", []):
                if not isinstance(ch, dict):
                    raise ValueError(f"卷 {vol.get('volume', '?')} 的 chapters 中存在非对象元素，触发重试")

    def _init_from_outline(self, outline: Dict, clear: bool = True):
        """将大纲数据写入各管理模块"""
        self._validate_outline_structure(outline)
        if clear:
            self.memory.characters.clear()
            self.memory.locations.clear()
            self.memory.world_settings.clear()
            self.continuity.timeline.clear()
            self.continuity.spacemap.clear()
            self.continuity.character_locations.clear()
            self.continuity.absolute_day = 0
            self.continuity._time_updated_chapters = set()
            self.foreshadow.foreshadows.clear()

        self._init_world_settings(outline)
        self._init_power_system(outline)
        self._init_protector_network(outline)
        self._init_characters(outline)
        self._init_locations(outline)
        self._init_factions(outline)
        self._init_key_items(outline)
        self._init_chapters(outline)

        # 自检清单
        self._run_self_check(outline)

        self.memory.save_all()
        self.continuity.save_all()
        self.foreshadow.save()

    def _init_world_settings(self, outline: Dict):
        meta = outline.get("meta", {})
        self.memory.add_world_setting(WorldSetting(key="世界观总览", value=meta.get("setting", "")))

    def _init_power_system(self, outline: Dict):
        power_system = outline.get("power_system", [])
        if power_system:
            levels_text = " → ".join(f"L{p['level']}.{p['name']}" for p in power_system)
            self.memory.add_world_setting(WorldSetting(key="力量体系", value=levels_text))

    def _init_protector_network(self, outline: Dict):
        pn = outline.get("protector_network", {})
        if pn.get("direct"):
            d = pn["direct"]
            self.memory.add_world_setting(WorldSetting(
                key="保护者-直接", value=f"{d.get('name', '')}（境界层数:{d.get('level', '')}，首次出场:第{d.get('first_appearance_volume', '?')}卷）"
            ))
        if pn.get("indirect"):
            ind = pn["indirect"]
            self.memory.add_world_setting(WorldSetting(
                key="保护者-间接", value=f"{ind.get('name', '')}（势力:{ind.get('faction', '')}，原因:{ind.get('reason', '')}，首次出场:第{ind.get('first_appearance_volume', '?')}卷）"
            ))
        if pn.get("boss_kryptonite"):
            self.memory.add_world_setting(WorldSetting(key="Boss弱点线索", value=pn["boss_kryptonite"]))

    def _init_characters(self, outline: Dict):
        for c_data in outline.get("characters", []):
            # 解析 first_appearance 中的数字
            first_app = 1
            fa_str = c_data.get("first_appearance", "第1章")
            fa_match = re.search(r'(\d+)', fa_str)
            if fa_match:
                first_app = int(fa_match.group(1))

            self.memory.add_character(CharacterProfile(
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
                core_values=c_data.get("core_values", c_data.get("core_value", "")),
                core_desire=c_data.get("core_desire", ""),
                core_fear=c_data.get("core_fear", ""),
                flaw=c_data.get("core_flaw", ""),
                alignment=c_data.get("alignment", ""),
                first_appeared=first_app,
                arc=c_data.get("exit_point", ""),
                cultivation=c_data.get("cultivation", ""),
                current_location=c_data.get("current_location", ""),
            ))
            # 同步初始位置到连续性模块
            loc = c_data.get("current_location", "")
            if loc:
                self.continuity.add_character_location(
                    chapter=first_app, character=c_data["name"], location=loc,
                    note="大纲初始位置",
                )

    def _init_locations(self, outline: Dict):
        for loc_data in outline.get("locations", []):
            profile = LocationProfile(
                name=loc_data["name"], description=loc_data.get("description", ""),
                type=loc_data.get("type", "city"), connected_to=loc_data.get("connected_to", []),
            )
            self.continuity.add_location(profile)
            self.memory.add_location(profile)

    def _init_factions(self, outline: Dict):
        """加载势力设定到 world_settings，支持大纲格式和 factions.json 格式"""
        # 优先处理 factions.json 格式（新格式，更详细）
        factions_path = self.ctx.data_dir / "factions.json"
        if factions_path.exists():
            try:
                with open(factions_path, "r", encoding="utf-8") as f:
                    factions_data = json.load(f)
                for key, fac_data in factions_data.items():
                    if isinstance(fac_data, dict) and "value" in fac_data:
                        # factions.json 格式: {key, value, chapter_introduced}
                        self.memory.add_world_setting(WorldSetting(
                            key=f"势力-{key}",
                            value=fac_data["value"],
                            chapter_introduced=fac_data.get("chapter_introduced", 1)
                        ))
            except Exception as e:
                logger.warning(f"加载 factions.json 失败: {e}")
            return  # 如果 factions.json 存在，不再处理大纲中的 factions 数组，避免重复

        # 处理大纲中的 factions 数组（旧格式，兼容）
        for fac_data in outline.get("factions", []):
            fac_info = f"{fac_data['name']}（{fac_data.get('level', '')}）：首领 {fac_data.get('leader', '')}"
            if fac_data.get("allies"):
                fac_info += f"；盟友：{', '.join(fac_data['allies'])}"
            if fac_data.get("enemies"):
                fac_info += f"；敌对：{', '.join(fac_data['enemies'])}"
            if fac_data.get("alliance_chain"):
                fac_info += f"；庇护链：{' → '.join(fac_data['alliance_chain'])}"
            self.memory.add_world_setting(WorldSetting(key=f"势力-{fac_data['name']}", value=fac_info))

    def _init_key_items(self, outline: Dict):
        """写入大纲物品，校验 giver 唯一性"""
        items = outline.get("key_items", [])
        seen_givers = {}
        deduped = []
        for item in items:
            name = item.get("item_name", "")
            giver = item.get("giver", "")
            if name and giver:
                if name in seen_givers:
                    if seen_givers[name] != giver:
                        logger.warning(f"物品'{name}'重复赠与（giver={giver} vs {seen_givers[name]}），合并为最早giver")
                        continue  # 跳过重复记录
                else:
                    seen_givers[name] = giver
            deduped.append(item)

        for item in deduped:
            self.memory.add_world_setting(WorldSetting(
                key=f"物品-{item.get('item_name', '')}",
                value=f"首次出场:第{item.get('first_chapter', 0)}章，赠与者:{item.get('giver', '')}，接受者:{item.get('receiver', '')}，用途:{item.get('purpose', '')}"
            ))

    def _init_chapters(self, outline: Dict):
        all_chapters = []
        volumes = outline.get("volumes", [])
        if volumes:
            for vol in volumes:
                vol_num = vol.get('volume', '?')
                vol_title = vol.get('title', '')
                arc = vol.get('arc', {})
                arc_info = (f"第{vol_num}卷「{vol_title}」"
                           f" | 挫折:{arc.get('setback_chapter', '?')}"
                           f" 领悟:{arc.get('insight_chapter', '?')}"
                           f" 突破:{arc.get('breakthrough_chapter', '?')}"
                           f" 新挑战:{arc.get('new_challenge_chapter', '?')}")
                self.memory.add_world_setting(WorldSetting(
                    key=f"卷{vol_num}-{vol_title}", value=arc_info,
                ))
                chapters = vol.get("chapters", [])
                all_chapters.extend(chapters)
        else:
            all_chapters = outline.get("chapter_plan", [])

        for ch_data in all_chapters:
            chapter = ch_data.get("chapter", 1)
            time_tag = ch_data.get("time", f"第{chapter}章")
            summary = ch_data.get("summary", "")
            location = ch_data.get("location", "")
            characters = ch_data.get("characters", [])

            self.continuity.add_event(
                chapter=chapter, time_tag=time_tag, event=summary,
                characters=characters, location=location, importance=3,
            )
            for char in characters:
                self.continuity.add_character_location(chapter=chapter, character=char, location=location)

            # 章节级伏笔（仅种植章有内容，普通章节留空）
            for fs_entry in ch_data.get("foreshadows", []):
                if isinstance(fs_entry, str) and fs_entry:
                    self.foreshadow.plant(chapter=chapter, content=fs_entry, type="mystery",
                                          related_characters=characters, importance=3)

        # 处理顶层 foreshadows 数组（新格式：含 id/plant_chapter/harvest_chapter/type）
        fs_list = outline.get("foreshadows", [])
        if fs_list:
            for fs_data in fs_list:
                if isinstance(fs_data, dict) and fs_data.get("content"):
                    fs_id = self.foreshadow.plant(
                        chapter=fs_data.get("plant_chapter", 1),
                        content=fs_data["content"],
                        type=fs_data.get("type", "cross_volume"),
                        related_characters=[],
                        importance=3,
                    )
                    harvest_ch = fs_data.get("harvest_chapter")
                    if harvest_ch:
                        for fs in self.foreshadow.foreshadows:
                            if fs.id == fs_id:
                                fs.chapter_resolved = harvest_ch
                                fs.status = "resolved"
                                fs.resolution = f"第{harvest_ch}章自动回收"
                                break

            # 伏笔总量 > 30 时自动精简：仅保留跨卷伏笔 + 最近 2 卷的当卷伏笔
            total_fs = len(self.foreshadow.foreshadows)
            if total_fs > 30:
                vol_ranges = []
                for vol in volumes:
                    chs = vol.get("chapters", [])
                    if chs:
                        vol_ranges.append((chs[0]["chapter"], chs[-1]["chapter"]))
                last_vol = vol_ranges[-1] if vol_ranges else (0, 9999)
                second_last_vol = vol_ranges[-2] if len(vol_ranges) >= 2 else (0, 0)

                kept = []
                for fs in self.foreshadow.foreshadows:
                    ch = fs.chapter_planted
                    harvest = fs.chapter_resolved
                    is_cross = harvest and harvest > (last_vol[1] if last_vol else ch)
                    is_recent = (second_last_vol[0] <= ch <= last_vol[1])
                    if is_cross or is_recent:
                        kept.append(fs)

                seen = set()
                final = []
                for fs in kept:
                    if fs.id not in seen:
                        seen.add(fs.id)
                        final.append(fs)
                self.foreshadow.foreshadows = final
                logger.info("伏笔从 %d 条精简至 %d 条（仅保留跨卷+最近2卷）", total_fs, len(final))

    def _run_self_check(self, outline: Dict):
        """生成完成后强制自检"""
        issues = []
        volumes = outline.get("volumes", [])
        issues.extend(self._check_chapter_count(volumes))
        issues.extend(self._check_volume_arcs(volumes))
        issues.extend(self._check_power_system(outline))
        issues.extend(self._check_factions(outline))
        issues.extend(self._check_characters(outline))
        issues.extend(self._check_items(outline))
        issues.extend(self._check_foreshadows(outline, volumes))
        issues.extend(self._check_ending(outline, volumes))
        issues.extend(self._check_defeat_recovery(outline, volumes))
        issues.extend(self._check_side_quests(outline))
        if issues:
            logger.info("大纲自检发现问题：")
            for issue in issues:
                logger.info("  - %s", issue)
        else:
            logger.info("大纲自检全部通过")

    def _check_chapter_count(self, volumes: list) -> list:
        """检查总章数≥50，每卷15-20章"""
        issues = []
        all_vol_chs = []
        for vol in volumes:
            chs = vol.get("chapters", [])
            all_vol_chs.extend(chs)
            if len(chs) < 15 or len(chs) > 20:
                issues.append(f"第{vol.get('volume','?')}卷章节数={len(chs)}，不在15-20范围")
        if len(all_vol_chs) < 50:
            issues.append(f"实际总章数={len(all_vol_chs)}，未达 ≥50")
        return issues

    def _check_volume_arcs(self, volumes: list) -> list:
        """检查每卷arc四节点和挫折反杀"""
        issues = []
        for vol in volumes:
            arc = vol.get("arc", {})
            for key in ("setback_chapter", "insight_chapter", "breakthrough_chapter", "new_challenge_chapter"):
                if not arc.get(key):
                    issues.append(f"第{vol.get('volume','?')}卷缺少 arc.{key}")
            setback = arc.get("setback_chapter", 0)
            if setback == 0:
                issues.append(f"第{vol.get('volume','?')}卷无挫折（被压制）章节")
            else:
                insight = arc.get("insight_chapter", 0)
                breakthrough = arc.get("breakthrough_chapter", 0)
                new_challenge = arc.get("new_challenge_chapter", 0)
                has_comeback = any(x > setback for x in (insight, breakthrough, new_challenge) if x > 0)
                if not has_comeback:
                    issues.append(f"第{vol.get('volume','?')}卷挫折章{setback}后本卷内无反杀节点")
        return issues

    def _check_power_system(self, outline: dict) -> list:
        """检查力量体系和保护者"""
        issues = []
        ps = outline.get("power_system", [])
        if len(ps) > 10:
            issues.append(f"境界数={len(ps)}，超过10")
        pn = outline.get("protector_network", {})
        if pn.get("direct") and ps:
            protector_lv = pn["direct"].get("level", 0)
            min_required = len(ps) - 2
            if protector_lv < min_required:
                issues.append(f"直接保护者境界={protector_lv}，不足{min_required}（总境界-2）")
        return issues

    def _check_factions(self, outline: dict) -> list:
        """检查势力冲突"""
        issues = []
        for f in outline.get("factions", []):
            allies = set(f.get("allies", []))
            enemies = set(f.get("enemies", []))
            conflict = allies & enemies
            if conflict:
                issues.append(f"势力'{f.get('name','')}'的盟友和敌对列表冲突：{conflict}")
        return issues

    def _check_characters(self, outline: dict) -> list:
        """检查人物exit_point"""
        issues = []
        for c in outline.get("characters", []):
            if not c.get("exit_point"):
                issues.append(f"人物'{c.get('name','')}'缺少 exit_point")
        return issues

    def _check_items(self, outline: dict) -> list:
        """检查物品giver唯一性"""
        issues = []
        givers = {}
        for item in outline.get("key_items", []):
            name = item.get("item_name", "")
            giver = item.get("giver", "")
            if name and giver:
                if name in givers and givers[name] != giver:
                    issues.append(f"物品'{name}'重复赠与（{giver} vs {givers[name]}）")
                givers[name] = giver
        return issues

    def _check_foreshadows(self, outline: dict, volumes: list) -> list:
        """检查伏笔：总数≤30、每卷跨卷伏笔、跨卷不超过2卷"""
        issues = []
        fs_count = len(self.foreshadow.foreshadows)
        if fs_count > 30:
            issues.append(f"伏笔总数={fs_count}，超过30")
        total_vols = len(volumes)
        for i, vol in enumerate(volumes):
            if i + 1 == total_vols:
                continue
            vol_chs = [c["chapter"] for c in vol.get("chapters", [])]
            has_cross = any(
                fs.get("type") == "cross_volume" and fs.get("plant_chapter", 0) in vol_chs
                for fs in outline.get("foreshadows", [])
            )
            if not has_cross:
                issues.append(f"第{i+1}卷缺少跨卷伏笔")
        if len(volumes) >= 3:
            vol1_chs = [c["chapter"] for c in volumes[0].get("chapters", [])]
            vol3_last = max(c["chapter"] for c in volumes[2].get("chapters", [])) if volumes[2].get("chapters") else 0
            for fs in outline.get("foreshadows", []):
                if fs.get("plant_chapter", 0) in vol1_chs:
                    if fs.get("harvest_chapter", 0) > vol3_last:
                        issues.append(f"伏笔{fs.get('id','?')}（plant={fs.get('plant_chapter')}）在第3卷末（ch{vol3_last}）仍未回收，跨卷超过2卷")
        return issues

    def _check_ending(self, outline: dict, volumes: list) -> list:
        """检查无自爆结局"""
        issues = []
        last_vol = volumes[-1] if volumes else {}
        last_chs = last_vol.get("chapters", [])
        if last_chs:
            last_summary = last_chs[-1].get("summary", "")
            if any(kw in last_summary for kw in ("自爆", "同归于尽", "自爆身亡", "引爆")):
                issues.append("结局疑似自爆/同归于尽")
        return issues

    @staticmethod
    def _check_defeat_recovery(outline: dict, volumes: list) -> list:
        """检查破而后立：真败→3章内机缘→7章内恢复"""
        issues = []
        true_defeat_kw = ("修为被废", "被废修为", "经脉尽断", "丹田破碎", "沦为废人", "功力全失")
        chance_kw = ("机缘", "传承", "觉醒", "奇遇", "获得", "发现", "遇到", "传授", "认主")
        recovery_kw = ("重修", "突破", "破而后立", "重塑", "涅槃", "浴火", "恢复修为", "突破至", "踏入")
        all_chapters_flat = []
        for vol in volumes:
            all_chapters_flat.extend(vol.get("chapters", []))
        for i, ch in enumerate(all_chapters_flat):
            summary = ch.get("summary", "")
            for kw in true_defeat_kw:
                if kw not in summary:
                    continue
                ch_num = ch.get("chapter", 0)
                met_chance = any(
                    any(ck in all_chapters_flat[j].get("summary", "") for ck in chance_kw)
                    for j in range(i + 1, min(i + 4, len(all_chapters_flat)))
                )
                fully_recovered = any(
                    any(rk in all_chapters_flat[j].get("summary", "") for rk in recovery_kw)
                    for j in range(i + 1, min(i + 8, len(all_chapters_flat)))
                )
                if not met_chance:
                    issues.append(f"第{ch_num}章出现'{kw}'但后续3章内未遇到机缘（传承/觉醒/奇遇等）")
                elif not fully_recovered:
                    issues.append(f"第{ch_num}章出现'{kw}'，3章内遇到了机缘但7章内未完成破而后立")
        return issues

    def _check_side_quests(self, outline: dict) -> list:
        """检查支线：占比、主线接入、间隔、产出、关联"""
        issues = []
        side_quests = outline.get("side_quests", [])
        if not side_quests:
            return issues
        meta = outline.get("meta", {})
        total_chapters = meta.get("total_chapters", 0)
        sq_chapters = sum(
            sq.get("end_chapter", sq.get("start_chapter", 0)) - sq.get("start_chapter", 0) + 1
            for sq in side_quests
        )
        if total_chapters > 0:
            sq_ratio = sq_chapters / total_chapters
            if sq_ratio < 0.10:
                issues.append(f"支线占比={sq_ratio:.1%}，不足10%")
            elif sq_ratio > 0.35:
                issues.append(f"支线占比={sq_ratio:.1%}，超过35%")
        for sq in side_quests:
            end_ch = sq.get("end_chapter", 0)
            connects = sq.get("connects_to_main", "")
            if not connects:
                issues.append(f"支线{sq.get('id','?')}缺少 connects_to_main（如何接入主线）")
            elif end_ch > 0 and "第" in connects:
                conn_ch_match = re.search(r'第\s*(\d+)', connects)
                if conn_ch_match:
                    conn_ch = int(conn_ch_match.group(1))
                    if conn_ch > end_ch + 3:
                        issues.append(f"支线{sq.get('id','?')}结束于第{end_ch}章，但 connects_to_main 提到第{conn_ch}章（超出3章窗口）")
            output = sq.get("output", {})
            if not output.get("items") and not output.get("characters") and not output.get("rewards"):
                issues.append(f"支线{sq.get('id','?')}无任何产出物（items/characters/rewards均为空）")
            summary = sq.get("summary", "")
            main_hooks = ("为后续主线", "铺垫主线", "指向主线", "引出", "为卷末", "为下一阶段",
                          "主线", "主角", "第", "章", "剧情", "推进")
            if not connects and not any(hook in summary for hook in main_hooks):
                issues.append(f"支线{sq.get('id','?')}疑似脱离主线（connects_to_main为空且summary无主线关联词）")
        large_sqs = [sq for sq in side_quests
                    if sq.get("end_chapter", 0) - sq.get("start_chapter", 0) + 1 > 10]
        large_sqs.sort(key=lambda x: x.get("start_chapter", 0))
        for i in range(1, len(large_sqs)):
            gap = large_sqs[i].get("start_chapter", 0) - large_sqs[i-1].get("end_chapter", 0) - 1
            if gap < 5:
                issues.append(f"大型支线{large_sqs[i-1].get('id','?')}和{large_sqs[i].get('id','?')}之间仅隔{gap}章主线，需≥5章")
        return issues

    @staticmethod
    def _extract_json(text: str) -> Dict:
        """从 LLM 输出中提取 JSON 对象"""
        result = parse_json(text)
        if isinstance(result, dict):
            return result
        raise ValueError(
            "大纲 JSON 解析失败：无法从 LLM 输出中提取有效的 JSON 对象。"
            "请检查 LLM 输出格式是否正确。"
        )

    def save_outline_json(self, outline: Dict, filepath: str = None):
        if filepath is None:
            filepath = self.memory.data_dir / "outline.json"
        else:
            filepath = Path(filepath)
        atomic_write_json(filepath, outline, indent=2)

