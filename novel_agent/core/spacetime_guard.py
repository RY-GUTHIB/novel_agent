"""
spacetime_guard.py - 时空守卫（生成前强制检查）

在 write_chapter 调用前执行，纯规则引擎，不调 LLM。
检查不通过 → 拒绝生成，直接报错。

职责：
1. 时间线守卫：检查时间顺序/季节/跨度是否自洽
2. 空间守卫：检查角色移动是否可达（通行时间 vs 章节时间间隔）
"""

import re
from dataclasses import dataclass
from typing import List, Optional

from novel_agent.core.models import LocationProfile


@dataclass
class SpacetimeViolation:
    """时空违规记录"""
    type: str           # "time" | "space"
    severity: str       # "fatal" | "warning"
    chapter: int
    message: str


@dataclass
class AutoFixChannel:
    """自动补通道记录"""
    from_location: str
    to_location: str


@dataclass
class PreCheckResult:
    """时空检查结果"""
    fatal_errors: list      # List[str] — 致命错误，拒绝生成
    warnings: list          # List[str] — 警告信息
    auto_fix_channels: list # List[AutoFixChannel] — 需自动补的双向通道


class SpacetimeGuard:
    """时空守卫 —— 生成前强制检查，不通过则拒绝"""

    def __init__(self, memory_manager, continuity_guard):
        self.memory = memory_manager
        self.continuity = continuity_guard

    def pre_check(self, chapter: int, time_tag: str, location: str,
                  characters: List[str]) -> PreCheckResult:
        """
        生成前全量时空检查。
        返回 PreCheckResult：
        - fatal_errors: 致命错误（时间倒流、通行时间不足等），拒绝生成
        - warnings: 警告信息（空间不可达等，自动修复）
        - auto_fix_channels: 需自动补的双向通道列表
        """
        violations = []
        violations.extend(self._check_time_order(chapter, time_tag))
        violations.extend(self._check_season(chapter, time_tag))
        violations.extend(self._check_spatial_reachability(chapter, characters, location, time_tag))
        violations.extend(self._check_character_consistency(chapter, characters))

        fatal_errors = []
        warnings = []
        auto_fix_channels = []

        for v in violations:
            if v.severity == "fatal":
                fatal_errors.append(f"[{v.type}] {v.message}")
            elif v.type == "space" and "空间不可达" in v.message:
                m = re.search(r"从「(.+?)」到「(.+?)」", v.message)
                if m:
                    auto_fix_channels.append(AutoFixChannel(
                        from_location=m.group(1),
                        to_location=m.group(2),
                    ))
                warnings.append(f"[{v.type}] {v.message}")
            else:
                warnings.append(f"[{v.type}] {v.message}")

        return PreCheckResult(
            fatal_errors=fatal_errors,
            warnings=warnings,
            auto_fix_channels=auto_fix_channels,
        )

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

    # ====== 人物一致性检查 ======

    def _check_character_consistency(self, chapter: int,
                                      characters: List[str]) -> List[SpacetimeViolation]:
        """检查人物状态一致性：同名必须同人，禁止一个人物两套信息"""
        violations = []
        for char_name in characters:
            if char_name not in self.memory.characters:
                continue
            c = self.memory.characters[char_name]
            # 死亡人物不得出场
            if c.status == "dead":
                violations.append(SpacetimeViolation(
                    type="character", severity="fatal", chapter=chapter,
                    message=f"{char_name} 已标记为「死亡」（第{c.first_appeared}章出场），"
                            f"本章不得作为活人出场。如需回忆/幻象，请在 characters 列表中注明。"
                ))
            # 失踪人物不得直接出场
            if c.status == "missing":
                violations.append(SpacetimeViolation(
                    type="character", severity="warning", chapter=chapter,
                    message=f"{char_name} 已标记为「失踪」，本章如需出场必须先交代行踪。"
                ))
        return violations

    # ====== 空间检查 ======

    def _check_spatial_reachability(self, chapter: int, characters: List[str],
                                     target_location: str, time_tag: str) -> List[SpacetimeViolation]:
        """
        检查本章角色是否能从上一章位置到达本章位置。
        核心逻辑：如果空间地图中两地有记录的通行时间，
        且本章时间间隔小于通行时间 → fatal。
        空间不可达时降级为 warning（允许自动补通道）。
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
                    # 空间不可达 → 降级为 warning，由调用方自动补双向通道
                    violations.append(SpacetimeViolation(
                        type="space", severity="warning", chapter=chapter,
                        message=f"空间不可达：{char} 从「{last_loc}」到「{target_location}」无已知通道，"
                                f"将自动建立双向连通。"
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
        travel_time = travel_time.strip()
        # "2日" / "2天"
        m = re.match(r'(\d+)\s*[日天]', travel_time)
        if m:
            return int(m.group(1))
        # "半日"
        if '半日' in travel_time or '半天' in travel_time:
            return 1
        # "1时辰" ≈ 2小时 ≈ 0.25日
        m = re.match(r'(\d+)\s*时辰', travel_time)
        if m:
            return max(1, int(m.group(1)) // 4)  # 4时辰≈1日
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

    @staticmethod
    def auto_fix_spacemap(continuity, channels: list):
        """自动补双向通道到 spacemap。
        根据已有空间地图信息和地点类型估算通行时间，而非固定"半日"。

        估算逻辑（优先级从高到低）：
        1. 两个地点中任意一个已有到其他地点的通行时间 → 取平均值
        2. 按地点类型推算（sect↔sect=3日, sect↔city=半日, city↔city=1日, wild↔*=半日, dungeon↔*=2日）
        3. 兜底：半日

        channels: List[AutoFixChannel]
        """
        if not channels:
            return

        for ch in channels:
            from_loc = ch.from_location
            to_loc = ch.to_location

            # 确保两个地点都存在于 spacemap 中
            from_node = continuity.spacemap.get(from_loc)
            to_node = continuity.spacemap.get(to_loc)

            if from_node is None:
                from_node = LocationProfile(name=from_loc, type="unknown")
                continuity.spacemap[from_loc] = from_node
            if to_node is None:
                to_node = LocationProfile(name=to_loc, type="unknown")
                continuity.spacemap[to_loc] = to_node

            # 补双向通道
            if to_loc not in from_node.connected_to:
                from_node.connected_to.append(to_loc)
            if from_loc not in to_node.connected_to:
                to_node.connected_to.append(from_loc)

            # 估算通行时间
            est_time = SpacetimeGuard._estimate_travel_time(
                continuity.spacemap, from_node, to_node
            )

            # 补通行时间（仅当不存在时）
            if to_loc not in from_node.travel_time:
                from_node.travel_time[to_loc] = est_time
            if from_loc not in to_node.travel_time:
                to_node.travel_time[from_loc] = est_time

        continuity._save_spacemap()

    @staticmethod
    def _estimate_travel_time(spacemap: dict, from_node: LocationProfile,
                               to_node: LocationProfile) -> str:
        """根据已有空间地图信息和地点类型，估算两个新连通的通道的通行时间。

        优先级：
        1. 从已有 travel_time 取平均值（如果有的话）
        2. 按地点类型组合推算
        3. 兜底：半日
        """
        # ---- 优先级1：已有通行时间的平均值 ----
        existing_times = []

        def collect_travel_days(node, other_loc):
            """从 node 的 travel_time 中收集到其他地点的天数（排除对方）"""
            for dest, tt in node.travel_time.items():
                if dest != other_loc:
                    days = SpacetimeGuard._parse_travel_days_static(tt)
                    if days is not None:
                        existing_times.append(days)

        collect_travel_days(from_node, to_node.name)
        collect_travel_days(to_node, from_node.name)

        if existing_times:
            avg = sum(existing_times) / len(existing_times)
            days = max(1, round(avg))
            return SpacetimeGuard._format_travel_days(days)

        # ---- 优先级2：按地点类型推算 ----
        # 类型映射：同类型 / 不同类型
        # 定义类型层级：sect(宗门/修炼地) > city(城市) > wild(野外) > dungeon(秘境/深渊)
        TYPE_TRAVEL = {
            ("sect", "sect"): 3,       # 宗门之间距离远
            ("sect", "city"): 1,       # 宗门附近常有城市
            ("sect", "wild"): 1,       # 宗门后山/秘境
            ("sect", "dungeon"): 2,    # 秘境在宗门管辖范围内
            ("city", "city"): 1,       # 城际一般1日
            ("city", "wild"): 1,       # 城外即野外
            ("city", "dungeon"): 2,    # 秘境较远
            ("wild", "wild"): 1,       # 野外连野外
            ("wild", "dungeon"): 1,    # 秘境常在野外
            ("dungeon", "dungeon"): 3, # 秘境间不互通
        }

        t1 = from_node.type or "unknown"
        t2 = to_node.type or "unknown"
        key = tuple(sorted([t1, t2]))
        days = TYPE_TRAVEL.get(key, 1)

        return SpacetimeGuard._format_travel_days(days)

    @staticmethod
    def _parse_travel_days_static(travel_time: str) -> Optional[int]:
        """与 _parse_travel_days 相同的逻辑，静态版本供 auto_fix 使用。
        但"半日"返回 0.5 而非 1，以便更精确地估算平均通行时间。
        """
        travel_time = travel_time.strip()
        m = re.match(r'(\d+)\s*[日天]', travel_time)
        if m:
            return int(m.group(1))
        if '半日' in travel_time or '半天' in travel_time:
            return 0.5
        m = re.match(r'(\d+)\s*时辰', travel_time)
        if m:
            return 0.5
        m = re.match(r'(\d+)', travel_time)
        if m:
            return int(m.group(1))
        return None

    @staticmethod
    def _format_travel_days(days: float) -> str:
        """将天数转为中文通行时间字符串"""
        if days <= 0.5:
            return "半日"
        elif days <= 1:
            return "1日"
        else:
            return f"{int(days)}日"
