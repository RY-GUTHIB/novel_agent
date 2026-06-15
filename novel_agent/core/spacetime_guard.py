"""
spacetime_guard.py - 时空守卫（生成前强制检查）

在 write_chapter 调用前执行，纯规则引擎，不调 LLM。
检查不通过 → 拒绝生成，直接报错。

职责：
1. 时间线守卫：检查时间顺序/季节/跨度是否自洽
2. 空间守卫：检查角色移动是否可达（通行时间 vs 章节时间间隔）
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class SpacetimeViolation:
    """时空违规记录"""
    type: str           # "time" | "space"
    severity: str       # "fatal" | "warning"
    chapter: int
    message: str


class SpacetimeGuard:
    """时空守卫 —— 生成前强制检查，不通过则拒绝"""

    def __init__(self, memory_manager, continuity_guard):
        self.memory = memory_manager
        self.continuity = continuity_guard

    def pre_check(self, chapter: int, time_tag: str, location: str,
                  characters: List[str]) -> List[str]:
        """
        生成前全量时空检查。
        返回错误字符串列表。如果有 fatal 级别违规，拒绝生成。
        """
        violations = []
        violations.extend(self._check_time_order(chapter, time_tag))
        violations.extend(self._check_season(chapter, time_tag))
        violations.extend(self._check_spatial_reachability(chapter, characters, location, time_tag))
        # 转为字符串列表
        errors = []
        for v in violations:
            if v.severity == "fatal":
                errors.append(f"[{v.type}] {v.message}")
        return errors

    # ====== 时间线检查 ======

    def _check_time_order(self, chapter: int, time_tag: str) -> List[SpacetimeViolation]:
        """检查时间是否倒流（本章 time_tag 必须晚于上一章）"""
        violations = []
        prev = None
        for e in reversed(self.continuity.timeline):
            if e.chapter < chapter:
                prev = e
                break

        if not prev or not prev.time_tag:
            return violations

        # 简单比较：如果 time_tag 看起来像数字日期，直接比
        prev_time = self._parse_time_value(prev.time_tag)
        curr_time = self._parse_time_value(time_tag)

        if prev_time is not None and curr_time is not None:
            if curr_time < prev_time:
                violations.append(SpacetimeViolation(
                    type="time", severity="fatal", chapter=chapter,
                    message=f"时间倒流：第{chapter}章时间「{time_tag}」早于第{prev.chapter}章时间「{prev.time_tag}」"
                ))
            elif curr_time == prev_time:
                violations.append(SpacetimeViolation(
                    type="time", severity="warning", chapter=chapter,
                    message=f"时间停滞：第{chapter}章与第{prev.chapter}章时间相同「{time_tag}」，如非倒叙请确认"
                ))

        return violations

    def _check_season(self, chapter: int, time_tag: str) -> List[SpacetimeViolation]:
        """检查季节是否跳变（如从夏直接到冬无过渡）"""
        violations = []
        prev = None
        for e in reversed(self.continuity.timeline):
            if e.chapter < chapter:
                prev = e
                break

        if not prev or not prev.season:
            return violations

        season_order = {"春": 1, "夏": 2, "秋": 3, "冬": 4}
        prev_s = prev.season

        # 找到上一章季节的序号
        prev_idx = None
        for s, idx in season_order.items():
            if s in prev_s:
                prev_idx = idx
                break

        if prev_idx is None:
            return violations

        # 检查当前章季节（从 time_tag 中提取）
        curr_idx = None
        for s, idx in season_order.items():
            if s in time_tag:
                curr_idx = idx
                break

        if curr_idx is not None:
            diff = curr_idx - prev_idx
            if diff > 1:
                violations.append(SpacetimeViolation(
                    type="time", severity="warning", chapter=chapter,
                    message=f"季节跳变：上一章为「{prev_s}」，本章为含「{time_tag}」的季节，"
                            f"跨度 {diff} 季，请确认有过渡描写。"
                ))
            elif diff < -2:  # 从冬到春算正常循环
                pass  # 跨年循环是正常的

        return violations

    def _parse_time_value(self, time_tag: str) -> Optional[int]:
        """
        尝试将 time_tag 解析为可比较的数值。
        支持格式：
        - "第3日" → 3
        - "第15日" → 15
        - "三日后" → 无法解析，返回 None
        - "第一章-春" → 无法解析，返回 None
        """
        import re
        # 匹配 "第N日"
        m = re.match(r'第\s*(\d+)\s*日', time_tag)
        if m:
            return int(m.group(1))
        # 匹配 "第N天"
        m = re.match(r'第\s*(\d+)\s*天', time_tag)
        if m:
            return int(m.group(1))
        # 匹配纯数字 "3" / "15"
        m = re.match(r'^(\d+)$', time_tag.strip())
        if m:
            return int(m.group(1))
        return None

    # ====== 空间检查 ======

    def _check_spatial_reachability(self, chapter: int, characters: List[str],
                                     target_location: str, time_tag: str) -> List[SpacetimeViolation]:
        """
        检查本章角色是否能从上一章位置到达本章位置。
        核心逻辑：如果空间地图中两地有记录的通行时间，
        且本章时间间隔小于通行时间 → fatal。
        """
        violations = []
        spacemap = self.continuity.spacemap

        for char in characters:
            last_loc = self.continuity.get_character_location(char, chapter - 1)
            if not last_loc or last_loc == target_location:
                continue

            # 检查两地是否不相邻且无通行时间
            if last_loc in spacemap:
                node = spacemap[last_loc]
                if target_location not in node.connected_to:
                    violations.append(SpacetimeViolation(
                        type="space", severity="fatal", chapter=chapter,
                        message=f"空间不可达：{char} 从「{last_loc}」到「{target_location}」无已知通道。"
                                f"请在空间地图中补充连通关系，或在大纲中调整本章地点。"
                    ))
                else:
                    # 有通道，检查通行时间是否合理
                    travel_time = node.travel_time.get(target_location, "")
                    if travel_time:
                        travel_days = self._parse_travel_days(travel_time)
                        chapter_days = self._parse_time_value(time_tag)
                        prev_days = self._get_prev_chapter_days(chapter)
                        if travel_days and chapter_days and prev_days is not None:
                            elapsed = chapter_days - prev_days
                            if elapsed < travel_days:
                                violations.append(SpacetimeViolation(
                                    type="space", severity="fatal", chapter=chapter,
                                    message=f"通行时间不足：{char} 从「{last_loc}」到「{target_location}」"
                                            f"需 {travel_time}（约{travel_days}日），"
                                            f"但本章距上一章仅 {elapsed} 日。"
                                            f"请调整时间标签或增加传送手段。"
                                ))

        return violations

    def _get_prev_chapter_days(self, chapter: int) -> Optional[int]:
        """获取上一章的时间数值"""
        for e in reversed(self.continuity.timeline):
            if e.chapter < chapter:
                return self._parse_time_value(e.time_tag)
        return None

    def _parse_travel_days(self, travel_time: str) -> Optional[int]:
        """解析通行时间字符串为天数"""
        import re
        travel_time = travel_time.strip()
        # "2日" / "2天"
        m = re.match(r'(\d+)\s*[日天]', travel_time)
        if m:
            return int(m.group(1))
        # "半日"
        if '半日' in travel_time or '半天' in travel_time:
            return 1
        # "1时辰" ≈ 2小时
        m = re.match(r'(\d+)\s*时辰', travel_time)
        if m:
            return 1  # 保守估计，1时辰按1日算
        # "3日骑马" → 3
        m = re.match(r'(\d+)', travel_time)
        if m:
            return int(m.group(1))
        return None

    def format_violations(self, violations: List[SpacetimeViolation]) -> str:
        """格式化违规报告"""
        if not violations:
            return ""
        fatal = [v for v in violations if v.severity == "fatal"]
        warn = [v for v in violations if v.severity == "warning"]

        lines = ["\n" + "=" * 60]
        lines.append("  ⛔ 时空守卫检查失败 —— 拒绝生成")
        lines.append("=" * 60)

        if fatal:
            lines.append(f"\n🔴 致命错误（{len(fatal)} 项）：")
            for v in fatal:
                lines.append(f"  ❌ {v.message}")

        if warn:
            lines.append(f"\n🟡 警告（{len(warn)} 项）：")
            for v in warn:
                lines.append(f"  ⚠️ {v.message}")

        if fatal:
            lines.append(f"\n💡 请先修复以上致命错误，再重新生成。")
            lines.append(f"   如需调整空间地图：编辑 data/spacemap.json")
            lines.append(f"   如需调整大纲时间：编辑 data/outline.json")
        else:
            lines.append(f"\n💡 以上为警告，生成将继续。")

        lines.append("=" * 60)
        return "\n".join(lines)
