"""
validator.py - 生成后契约校验（不调 LLM，纯程序化检查）

在正文生成后、保存前运行，检测明显的契约违反：
1. 死人出场
2. 关系立场矛盾（敌对角色亲密互动 / 友好角色突然反目）
3. 认知矛盾（已知信息表现出惊讶）
4. 空间瞬移（换了地点但无移动描写）
5. 剧情规则违反（条件出现但结果不符）
"""

import re
from typing import List, Dict, Tuple
from .models import CharacterProfile, CharacterKnowledge, PlotRule
from .file_utils import parse_chinese_number


class ContractViolation:
    """契约违反记录"""
    def __init__(self, severity: str, category: str, message: str, evidence: str = ""):
        self.severity = severity      # "高" / "中" / "低"
        self.category = category      # "关系" / "认知" / "规则" / "空间" / "状态"
        self.message = message
        self.evidence = evidence      # 正文中的相关片段

    def __str__(self):
        evidence_tag = f' | 证据："{self.evidence[:40]}..."' if self.evidence else ""
        return f"⚠️ [{self.severity}·{self.category}] {self.message}{evidence_tag}"


class ContractValidator:
    """生成后契约校验器"""

    # 修为境界层级（从低到高）
    CULTIVATION_TIERS = [
        "凡人", "炼气", "筑基", "开光", "融合", "心动", "金丹", "元婴",
        "化神", "炼虚", "合体", "大乘", "渡劫", "真仙", "金仙", "大罗金仙", "圣人",
    ]

    # 预编译正则（热路径复用）
    _PARA_SPLIT = re.compile(r'\n\s*\n')
    _SURPRISE_PATTERNS = [
        re.compile(p) for p in [
            r'惊讶', r'震惊', r'大吃一惊', r'不敢相信', r'难以置信',
            r'瞪大了眼', r'目瞪口呆', r'倒吸一口冷气', r'什么[？?！!]',
            r'你.{0,5}(竟然|居然|原来)', r'(竟然|居然|原来)是',
            r'(不|没)想到', r'(不|没)曾想',
        ]
    ]
    _LOCATION_PATTERN = re.compile(r'(?:来到|抵达|到达|出现在|站在|坐在|走进|飞入)([^，。,.\n]{2,8})')
    _TIME_LOCATION_PATTERN = re.compile(r'(?:来到|抵达|到达|出现在|前往)([^，。,.\n]{2,6})')
    _CN_LAYER_PATTERN = re.compile(r'[第又]?([一二三四五六七八九十百零]+)[层重阶]')
    _DIGIT_LAYER_PATTERN = re.compile(r'(\d+)[层重阶]')
    _KNOWLEDGE_CLEAN = re.compile(r'[，。、的是了在有和与或]')
    _TIME_SPAN_PATTERNS = [
        (re.compile(r"(?:一天|一日|当天|同日|翌日|次日|第二天)"), 1),
        (re.compile(r"(?:半日|半天|几个时辰|半晌)"), 0.5),
        (re.compile(r"(?:一时辰|一个时辰|片刻)"), 0.08),
    ]

    @staticmethod
    def _parse_chinese_number(s: str):
        """解析中文数字字符串为整数"""
        if not s:
            return None
        return parse_chinese_number(s)

    def __init__(self):
        # 立场矛盾的关键词对
        self._hostile_keywords = ["敌", "仇", "杀", "恨", "怒目", "冷哼", "不屑", "嘲讽", "蔑视"]
        self._friendly_keywords = ["笑", "亲", "握", "拥", "温柔", "关切", "感激", "信任", "默契", "并肩"]

    def validate(self, content: str, chapter: int, characters: List[str],
                  memory_mgr, parsed_settings: dict = None,
                  continuity_guard=None,
                  foreshadow_tracker=None) -> List[ContractViolation]:
        """
        对生成的正文进行契约校验
        :param parsed_settings: 可选的 SETTINGS_JSON 解析结果，用于物品/场景同地/修为校验
        :param continuity_guard: 可选的 ContinuityGuard 实例，用于同地校验
        :return: 违反列表（空 = 无问题）
        """
        violations: List[ContractViolation] = []

        self._check_dead_characters(content, chapter, characters, memory_mgr, violations)
        self._check_relationship_stance(content, chapter, characters, memory_mgr, violations)
        self._check_knowledge_surprise(content, chapter, characters, memory_mgr, violations)
        self._check_plot_rules(content, chapter, memory_mgr, violations)
        self._check_spatial_teleport(content, chapter, characters, memory_mgr, violations)
        self._check_time_consistency(content, chapter, characters, memory_mgr, violations)

        if parsed_settings:
            self._check_item_consistency(parsed_settings, memory_mgr, violations)
            self._check_destroyed_item(parsed_settings, memory_mgr, violations)
            self._check_co_location(parsed_settings, continuity_guard, chapter, violations)
            self._check_power_level(parsed_settings, memory_mgr, violations)
            self._check_character_teleport_within_chapter(parsed_settings, violations)
            self._check_shared_scene_knowledge(parsed_settings, memory_mgr, continuity_guard, violations)
            self._check_season_transition(parsed_settings, continuity_guard, chapter, violations)
            self._check_task_completion(parsed_settings, memory_mgr, content, chapter, violations)
            self._check_personality_consistency(parsed_settings, memory_mgr, content, violations)

        return violations

    # ========== 1. 死人出场 ==========

    def _check_dead_characters(self, content, chapter, characters, mem, violations):
        for name in characters:
            if name not in mem.characters:
                continue
            char = mem.characters[name]
            if char.status == "dead":
                # 检查是否在正文中出现（排除回忆/提及）
                # 简单检查：名字出现在非引号上下文中且伴随动作词
                action_pattern = rf'{re.escape(name)}(?:说|道|笑|怒|走|站|坐|飞|拔|挥|喝|冷|热|点头|摇头)'
                matches = re.findall(action_pattern, content)
                if matches:
                    violations.append(ContractViolation(
                        severity="高", category="状态",
                        message=f"{name} 已标记死亡（status=dead），但本章有 {len(matches)} 处主动行为描写",
                        evidence=matches[0],
                    ))

    # ========== 2. 关系立场矛盾 ==========

    def _check_relationship_stance(self, content, chapter, characters, mem, violations):
        for i, a in enumerate(characters):
            for b in characters[i+1:]:
                if a not in mem.characters or b not in mem.characters:
                    continue
                char_a = mem.characters[a]
                if b not in char_a.relationships_detail:
                    continue
                detail = char_a.relationships_detail[b]
                stance = detail.get("stance", "neutral")

                # 找到正文中 a 和 b 同时出现的段落
                co_occurrences = self._find_co_occurrences(content, a, b)
                if not co_occurrences:
                    continue

                for para in co_occurrences:
                    if stance in ("hostile", "adversarial"):
                        # 敌对关系却出现友好描写
                        friendly_hits = [kw for kw in self._friendly_keywords if kw in para]
                        if len(friendly_hits) >= 2:
                            violations.append(ContractViolation(
                                severity="高", category="关系",
                                message=f"{a} 与 {b} 关系为「{detail.get('type', '敌对')}·敌对」，但正文出现友好互动（{', '.join(friendly_hits)}）",
                                evidence=para[:80],
                            ))
                    elif stance == "friendly":
                        # 友好关系却出现敌对描写
                        hostile_hits = [kw for kw in self._hostile_keywords if kw in para]
                        if len(hostile_hits) >= 2:
                            violations.append(ContractViolation(
                                severity="高", category="关系",
                                message=f"{a} 与 {b} 关系为「{detail.get('type', '友好')}·友好」，但正文出现敌对描写（{', '.join(hostile_hits)}）",
                                evidence=para[:80],
                            ))

    def _find_co_occurrences(self, content: str, a: str, b: str) -> List[str]:
        """找到 a 和 b 同时出现的段落"""
        paragraphs = self._PARA_SPLIT.split(content)
        results = []
        for para in paragraphs:
            if a in para and b in para and len(para) > 10:
                results.append(para)
        return results

    # ========== 3. 认知矛盾 ==========

    def _check_knowledge_surprise(self, content, chapter, characters, mem, violations):
        """检查角色是否对已知信息表现出惊讶"""
        for name in characters:
            if name not in mem.character_knowledge:
                continue
            known_items = [k for k in mem.character_knowledge[name] if k.chapter_learned < chapter]
            if not known_items:
                continue

            # 找到该角色的对话/行为段落
            char_paragraphs = self._find_character_paragraphs(content, name)
            for para in char_paragraphs:
                for knowledge in known_items:
                    # 提取知识的关键词（取核心名词，至少2字）
                    keywords = self._extract_keywords(knowledge.knowledge)
                    if not keywords:
                        continue

                    # 检查：段落中同时包含知识关键词和惊讶表达
                    has_keyword = any(kw in para for kw in keywords)
                    has_surprise = any(p.search(para) for p in self._SURPRISE_PATTERNS)

                    if has_keyword and has_surprise:
                        violations.append(ContractViolation(
                            severity="高", category="认知",
                            message=f"{name} 对已知信息「{knowledge.knowledge[:30]}」表现出惊讶（第{knowledge.chapter_learned}章已知）",
                            evidence=para[:80],
                        ))
                        break  # 每个角色每段只报一次

    def _find_character_paragraphs(self, content: str, name: str) -> List[str]:
        """找到包含某角色名字的段落"""
        paragraphs = self._PARA_SPLIT.split(content)
        return [p for p in paragraphs if name in p and len(p) > 10]

    def _extract_keywords(self, knowledge: str) -> List[str]:
        """从知识描述中提取关键词"""
        # 去掉常见虚词，取 2-4 字的核心名词
        knowledge = self._KNOWLEDGE_CLEAN.sub(' ', knowledge)
        words = [w.strip() for w in knowledge.split() if len(w.strip()) >= 2]
        return words[:5]  # 最多取 5 个关键词

    # ========== 4. 剧情规则违反 ==========

    def _check_plot_rules(self, content, chapter, mem, violations):
        """检查 IF-THEN 规则是否被违反"""
        active_rules = [r for r in mem.plot_rules.values() if not r.overridden]
        if not active_rules:
            return

        for rule in active_rules:
            condition_keywords = self._extract_keywords(rule.condition)
            consequence_keywords = self._extract_keywords(rule.consequence)
            if not condition_keywords or not consequence_keywords:
                continue

            # 检查：条件关键词出现，但结果关键词不出现
            condition_present = any(kw in content for kw in condition_keywords)
            consequence_present = any(kw in content for kw in consequence_keywords)

            if condition_present and not consequence_present:
                # 进一步检查：是否有否定结果的描写
                negation_patterns = [f"不{kw}" for kw in consequence_keywords[:3]]
                negation_patterns += [f"没有{kw}" for kw in consequence_keywords[:3]]
                has_negation = any(neg in content for neg in negation_patterns)

                if has_negation:
                    violations.append(ContractViolation(
                        severity="高", category="规则",
                        message=f"剧情规则违反：IF「{rule.condition[:30]}」应 THEN「{rule.consequence[:30]}」，但正文出现否定",
                        evidence=f"条件词：{condition_keywords[:3]}，结果词：{consequence_keywords[:3]}",
                    ))

    # ========== 5. 空间瞬移 ==========

    def _check_spatial_teleport(self, content, chapter, characters, mem, violations):
        """检查人物是否瞬移（换了地点但无移动描写）"""
        travel_keywords = [
            "御剑", "飞行", "飞往", "赶往", "前往", "来到", "抵达", "到达",
            "穿过", "走过", "翻过", "越过", "渡过", "传送阵", "遁术", "瞬移",
            "步行", "骑马", "坐船", "飞舟", "飞剑", "传送", "出发", "启程",
            "半日", "一日", "两日", "三日", "数日", "片刻后", "不久后",
        ]

        # 简单检查：如果正文中出现了 "在X" 且 X 不是上一章地点，但没有移动描写
        locations_mentioned = self._LOCATION_PATTERN.findall(content)

        if locations_mentioned:
            has_travel = any(kw in content for kw in travel_keywords)
            if not has_travel and len(locations_mentioned) >= 2:
                # 多个地点出现但无移动描写
                violations.append(ContractViolation(
                    severity="中", category="空间",
                    message=f"正文中提到 {len(locations_mentioned)} 个地点但未发现移动描写，可能存在瞬移",
                    evidence=f"地点：{', '.join(locations_mentioned[:3])}",
                ))

    # ========== 7. 物品一致性 ==========

    def _check_item_consistency(self, parsed_settings: dict, mem, violations: List):
        """检查 SETTINGS_JSON 中的物品变化是否与已存储的状态一致"""
        items = parsed_settings.get("items", [])
        if not items:
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "").strip()
            if not name:
                continue
            updates = item.get("updates", {})
            is_new = item.get("is_new", False)

            stored_item = mem.items.get(name) if hasattr(mem, 'items') else None

            if is_new:
                # 新物品：检查是否已存在同名物品
                if stored_item:
                    first_giver = updates.get("first_giver", "")
                    stored_giver = stored_item.first_giver
                    if first_giver and stored_giver and first_giver != stored_giver:
                        violations.append(ContractViolation(
                            severity="高", category="物品",
                            message=f"物品「{name}」已存在（原赋予者：{stored_giver}），但本章标记为 is_new 且有新的赋予者「{first_giver}」，可能重复创建",
                        ))
            else:
                # 已有物品更新：检查 current_holder 变化是否合理
                if stored_item:
                    new_holder = updates.get("current_holder", "")
                    old_holder = stored_item.current_holder
                    if new_holder and old_holder and new_holder != old_holder:
                        # 检测转移是否重复赠与
                        if hasattr(stored_item, 'first_giver') and stored_item.first_giver:
                            if new_holder == stored_item.first_giver:
                                violations.append(ContractViolation(
                                    severity="中", category="物品",
                                    message=f"物品「{name}」已由 {stored_item.first_giver} 赠予 {old_holder}，但本章又回到 {new_holder} 手中，可能不合逻辑",
                                ))

    # ========== 8. 同地校验 ==========

    def _check_co_location(self, parsed_settings: dict, continuity_guard, chapter: int, violations: List):
        """检查 scene_events 中同场出现的角色是否处于兼容的位置"""
        scene_events = parsed_settings.get("scene_events", [])
        if not scene_events or not continuity_guard:
            return
        for event in scene_events:
            if not isinstance(event, dict):
                continue
            location = event.get("location", "").strip()
            chars = event.get("characters", [])
            if len(chars) < 2 or not location:
                continue
            char_locations = {}
            for c in chars:
                loc = continuity_guard.get_character_location(c, chapter)
                if loc:
                    char_locations[c] = loc
            if len(char_locations) < 2:
                continue
            locs = set(char_locations.values())
            if len(locs) >= 2:
                locations_detail = "、".join(f"{c}在{loc}" for c, loc in char_locations.items())
                violations.append(ContractViolation(
                    severity="中", category="空间",
                    message=f"场景「{location}」中角色 {', '.join(chars)} 在 {locations_detail}，未全部对齐到同一地点",
                    evidence=f"场景地点={location}，角色分散在 {', '.join(locs)}",
                ))

    # ========== 9. 修为校验 ==========

    @staticmethod
    def _parse_cultivation_level(cultivation: str) -> tuple:
        """解析修为字符串为 (tier_index, layer) 元组，用于比较高低。
        如 '炼气三层' -> (1, 3), '金丹' -> (5, 0)"""
        if not cultivation:
            return (-1, 0)
        tier = -1
        for i, t in enumerate(ContractValidator.CULTIVATION_TIERS):
            if t in cultivation:
                tier = i
                break
        # 提取层数（如 "三层"、"九重"、"十二层"、"二十层"）
        layer_pattern = ContractValidator._CN_LAYER_PATTERN.search(cultivation)
        if layer_pattern:
            layer_str = layer_pattern.group(1)
            layer_num = ContractValidator._parse_chinese_number(layer_str)
            if layer_num is not None:
                return (tier, layer_num)
        # 提取数字层数（如 "9层"、"3重"）
        digit_pattern = ContractValidator._DIGIT_LAYER_PATTERN.search(cultivation)
        if digit_pattern:
            return (tier, int(digit_pattern.group(1)))
        return (tier, 0)

    def _check_power_level(self, parsed_settings: dict, mem, violations: List):
        """检查 SETTINGS_JSON 中角色修为更新是否严格递增"""
        characters = parsed_settings.get("characters", [])
        if not characters:
            return
        for char_entry in characters:
            if not isinstance(char_entry, dict):
                continue
            name = char_entry.get("name", "").strip()
            updates = char_entry.get("updates", {})
            new_cultivation = updates.get("cultivation", "")
            if not new_cultivation:
                continue
            if name not in mem.characters:
                continue
            old_cultivation = mem.characters[name].cultivation
            if not old_cultivation:
                continue

            old_tier, old_layer = self._parse_cultivation_level(old_cultivation)
            new_tier, new_layer = self._parse_cultivation_level(new_cultivation)

            if old_tier < 0 or new_tier < 0:
                continue  # 无法解析，跳过

            if new_tier < old_tier:
                violations.append(ContractViolation(
                    severity="高", category="状态",
                    message=f"{name} 修为从「{old_cultivation}」变为「{new_cultivation}」，境界降低（{ContractValidator.CULTIVATION_TIERS[old_tier]}→{ContractValidator.CULTIVATION_TIERS[new_tier]}），违反境界递增规则",
                    evidence=f"旧修为={old_cultivation}，新修为={new_cultivation}",
                ))
            elif new_tier == old_tier and old_layer > new_layer > 0:
                violations.append(ContractViolation(
                    severity="高", category="状态",
                    message=f"{name} 修为从「{old_cultivation}」变为「{new_cultivation}」，同境界内层数降低（{old_layer}→{new_layer}层），违反境界递增规则",
                    evidence=f"旧修为={old_cultivation}，新修为={new_cultivation}",
                ))

    # ========== 10. 同章分身检测 ==========

    def _check_character_teleport_within_chapter(self, parsed_settings: dict, violations: List):
        """检查同一章内角色在多个相距很远的地点出现但无移动记录"""
        scene_events = parsed_settings.get("scene_events", [])
        spatial_movements = parsed_settings.get("spatial_movements", [])
        if not scene_events:
            return

        # 收集有移动记录的角色（每个角色最后出现的场景位置）
        moved_chars = set()
        for m in spatial_movements:
            if isinstance(m, dict) and m.get("character"):
                moved_chars.add(m["character"])

        # 按角色分组所有场景
        char_scenes: Dict[str, list] = {}
        for event in scene_events:
            if not isinstance(event, dict):
                continue
            location = event.get("location", "").strip()
            chars = event.get("characters", [])
            if not location or not chars:
                continue
            for c in chars:
                if c not in char_scenes:
                    char_scenes[c] = []
                char_scenes[c].append(location)

        for char_name, locs in char_scenes.items():
            unique_locs = list(dict.fromkeys(locs))  # 去重但保持顺序
            if len(unique_locs) >= 2:
                if char_name not in moved_chars:
                    violations.append(ContractViolation(
                        severity="中", category="空间",
                        message=f"「{char_name}」在本章出现在多个地点（{' → '.join(unique_locs)}），但 spatial_movements 中无移动记录，可能分身或瞬移",
                        evidence=f"涉及地点：{', '.join(unique_locs)}",
                    ))

    # ========== 11. 已销毁/丢失物品复用检测 ==========

    def _check_destroyed_item(self, parsed_settings: dict, mem, violations: List):
        """检查 SETTINGS_JSON 中是否出现了已销毁/丢失的物品"""
        items = parsed_settings.get("items", [])
        if not items:
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "").strip()
            if not name:
                continue
            updates = item.get("updates", {})
            is_new = item.get("is_new", False)

            stored_item = mem.items.get(name) if hasattr(mem, 'items') else None
            if not stored_item:
                continue

            if stored_item.status in ("destroyed", "lost"):
                if is_new:
                    violations.append(ContractViolation(
                        severity="高", category="物品",
                        message=f"物品「{name}」已标记为 {stored_item.status}，但本章标记为 is_new，试图重新创建",
                    ))
                elif updates:
                    violations.append(ContractViolation(
                        severity="高", category="物品",
                        message=f"物品「{name}」已标记为 {stored_item.status}，但本章尝试更新其状态（{', '.join(updates.keys())}），已销毁/丢失的物品不应再被操作",
                    ))

    # ========== 12. 共同出场遗忘检测 ==========

    def _check_shared_scene_knowledge(self, parsed_settings: dict, mem, continuity_guard, violations: List):
        """检查 scene_events 中同场出现的角色，是否已在关系记录中标记为认识"""
        scene_events = parsed_settings.get("scene_events", [])
        if not scene_events or not continuity_guard:
            return
        for event in scene_events:
            if not isinstance(event, dict):
                continue
            chars = event.get("characters", [])
            if len(chars) < 2:
                continue
            for i, a in enumerate(chars):
                for b in chars[i+1:]:
                    if a not in mem.characters or b not in mem.characters:
                        continue
                    detail = mem.characters[a].relationships_detail.get(b)
                    if detail and detail.get("met_chapter", 0) > 0:
                        continue  # 已在关系记录中
                    # 检查反向关系
                    detail_b = mem.characters[b].relationships_detail.get(a)
                    if detail_b and detail_b.get("met_chapter", 0) > 0:
                        continue
                    # 检查是否在之前的场景事件中同时出现过
                    has_shared_scene = False
                    for prev_event in mem.scene_events:
                        if a in prev_event.characters and b in prev_event.characters:
                            has_shared_scene = True
                            break
                    if has_shared_scene:
                        violations.append(ContractViolation(
                            severity="中", category="关系",
                            message=f"「{a}」和「{b}」此前已在同一场景中出现过（check scene_events），但关系记录中 met_chapter 缺失，后续可能表现互不认识",
                            evidence=f"场景地点={event.get('location', '未知')}，同时出场角色={', '.join(chars)}",
                        ))

    # ========== 13. 跨章季节跳变检测 ==========

    def _check_season_transition(self, parsed_settings: dict, continuity_guard, chapter: int, violations: List):
        """检查 timeline_events 中季节是否跳变（无跨季过渡时警告）"""
        if not continuity_guard or not hasattr(continuity_guard, 'timeline'):
            return
        timeline_events = parsed_settings.get("timeline_events", [])
        if not timeline_events:
            return
        # 获取上一章的事件（取最新一条有 season 的）
        prev_season = None
        for e in continuity_guard.timeline:
            if e.chapter < chapter and e.season:
                prev_season = e.season
        if not prev_season:
            return
        # 检查本章 timeline_events 中的季节
        for evt in timeline_events:
            if not isinstance(evt, dict):
                continue
            season = evt.get("season", "")
            if not season:
                continue
            if season == prev_season:
                continue
            # 季节变了，检查 time_tag 是否有跨季过渡
            time_tag = evt.get("time_tag", "")
            cross_season_keywords = ["数月后", "半年", "一年", "次年", "来年", "转年", "冬去春来", "春去秋来",
                                     "过了", "时光飞逝", "岁月如梭", "转眼", "翌年"]
            has_transition = any(kw in (time_tag or "") for kw in cross_season_keywords)
            if not has_transition:
                violations.append(ContractViolation(
                    severity="中", category="时间",
                    message=f"上一章季节为「{prev_season}」，本章出现「{season}」季节特征，但 time_tag 中无跨季过渡描写（如「数月后」「次年春」）",
                    evidence=f"time_tag={time_tag}，prev_season={prev_season}，new_season={season}",
                ))

    # ========== 14. 任务条件检测 ==========

    def _check_task_completion(self, parsed_settings: dict, mem, content: str, chapter: int, violations: List):
        """检查正文中是否出现了任务完成条件，但 SETTINGS_JSON 中任务状态未更新为 completed"""
        # 获取活跃任务（仅 active，且当前章之前创建的）
        if not hasattr(mem, 'tasks') or not mem.tasks:
            return
        tasks_from_settings = parsed_settings.get("tasks", [])
        updated_task_ids = {t.get("id") for t in tasks_from_settings if isinstance(t, dict)}

        for tid, task in mem.tasks.items():
            if task.status != "active":
                continue
            if task.chapter_created >= chapter:
                continue
            # 如果已在 SETTINGS_JSON 中更新了，跳过
            if tid in updated_task_ids:
                continue
            # 从任务描述中提取关键名词，检查正文是否提及
            keywords = self._extract_keywords(task.description)
            if not keywords:
                continue
            # 检查正文是否包含这些关键词
            hit_count = sum(1 for kw in keywords if kw in content)
            # 如果超过半数关键词出现在正文中，可能是条件已满足但未更新
            if hit_count >= max(2, len(keywords) // 2):
                violations.append(ContractViolation(
                    severity="低", category="状态",
                    message=f"任务「{task.name}」（{tid}）的关键条件（{', '.join(keywords[:3])}）在正文中出现{hit_count}次，但 SETTINGS_JSON 中未更新状态，可能条件已满足但忘记更新",
                ))

    # ========== 15. OOC（性格矛盾）检测 ==========

    def _check_personality_consistency(self, parsed_settings: dict, mem, content: str, violations: List):
        """检查 SETTINGS_JSON 中角色的行为是否符合其性格设定"""
        characters = parsed_settings.get("characters", [])
        if not characters:
            return

        # 性格→矛盾行为关键词映射
        personality_contradictions = {
            "吝啬": ["慷慨解囊", "一掷千金", "大方", "施舍", "散尽家财"],
            "胆小": ["挺身而出", "悍不畏死", "冲锋在前", "毫不畏惧"],
            "冷酷": ["心软", "不忍", "怜悯", "同情", "流泪"],
            "暴躁": ["耐心", "忍气吞声", "和颜悦色", "温声细语"],
            "狡猾": ["坦诚", "直言不讳", "和盘托出", "推心置腹"],
            "懦弱": ["据理力争", "寸步不让", "针锋相对", "宁死不屈"],
            "粗鲁": ["彬彬有礼", "温文尔雅", "恭敬有加", "礼节周到"],
            "傲慢": ["低声下气", "卑躬屈膝", "虚心请教", "甘拜下风"],
            "多疑": ["深信不疑", "毫无保留地信任", "完全相信"],
            "优柔寡断": ["当机立断", "毫不犹豫", "斩钉截铁"],
            "善良": ["见死不救", "滥杀无辜", "草菅人命", "冷眼旁观"],
            "谨慎": ["鲁莽行事", "冒失", "轻举妄动", "不假思索"],
        }

        for char_entry in characters:
            if not isinstance(char_entry, dict):
                continue
            name = char_entry.get("name", "").strip()
            if not name or name not in mem.characters:
                continue
            personality = mem.characters[name].personality
            if not personality:
                continue

            # 只检查包含该角色名字的段落，避免误报其他角色的行为
            paragraphs = re.split(r'\n\s*\n', content)
            char_paragraphs = [p for p in paragraphs if name in p]

            # 检测性格关键词
            for trait, bad_actions in personality_contradictions.items():
                if trait not in personality:
                    continue
                for action in bad_actions:
                    for para in char_paragraphs:
                        if action in para:
                            violations.append(ContractViolation(
                                severity="中", category="关系",
                                message=f"「{name}」性格为「{personality}」，但本章含该角色的段落出现「{action}」行为，可能违反人物设定",
                                evidence=f"性格={personality}，矛盾行为={action}",
                            ))
                            break  # 每个角色每对(trait, action)只报一次

    # ========== 6. 时间一致性 ==========

    def _check_time_consistency(self, content, chapter, characters, mem, violations):
        """检查时间线矛盾：季节错乱、一天横跨大陆、事件顺序颠倒"""
        # 6a. 季节错乱检查
        season_keywords = {
            "春": ["春暖", "花开", "春风", "春雨", "桃花", "柳絮", "清明", "惊蛰", "立春"],
            "夏": ["酷暑", "炎热", "蝉鸣", "荷花", "烈日", "汗流", "盛夏", "三伏", "立夏"],
            "秋": ["落叶", "秋风", "凉爽", "桂花", "菊花", "丰收", "霜降", "中秋", "立秋"],
            "冬": ["寒", "雪", "冰", "冻", "凛冽", "刺骨", "腊月", "冬至", "立冬", "飘雪"],
        }
        seasons_found = set()
        for season, keywords in season_keywords.items():
            if any(kw in content for kw in keywords):
                seasons_found.add(season)

        if len(seasons_found) >= 2:
            # 冬+夏同时出现是强信号
            if "冬" in seasons_found and "夏" in seasons_found:
                violations.append(ContractViolation(
                    severity="高", category="时间",
                    message=f"正文中同时出现夏季和冬季特征描写，可能存在季节错乱",
                    evidence=f"检测到季节特征：{', '.join(sorted(seasons_found))}",
                ))
            elif len(seasons_found) >= 3:
                violations.append(ContractViolation(
                    severity="高", category="时间",
                    message=f"正文中出现3个以上季节特征，时间线严重混乱",
                    evidence=f"检测到季节特征：{', '.join(sorted(seasons_found))}",
                ))

        # 6b. 短时间内横跨远距离检查
        time_span_days = 0
        for pattern, days in self._TIME_SPAN_PATTERNS:
            if pattern.search(content):
                time_span_days = days
                break

        if time_span_days > 0:
            locations = self._TIME_LOCATION_PATTERN.findall(content)
            if len(locations) >= 2:
                has_travel_justification = any(kw in content for kw in [
                    "传送阵", "传送", "遁术", "瞬移", "飞舟", "飞剑",
                ])
                if not has_travel_justification:
                    violations.append(ContractViolation(
                        severity="中", category="时间",
                        message=f"正文时间跨度约{time_span_days}日，但出现{len(locations)}个地点变化（{', '.join(set(locations[:3]))}），且无传送/瞬移说明，可能空间距离不合理",
                        evidence=f"time_span={time_span_days}日，地点={', '.join(set(locations[:3]))}",
                    ))

        # 6c. 事件顺序颠倒（同角色：先死后生）
        death_indicators = ["死了", "陨落", "毙命", "丧命", "阵亡", "牺牲", "被杀", "倒下"]
        alive_indicators = ["站起", "醒来", "起身", "睁眼", "复活", "重生"]

        for char in characters:
            char_death = any(f"{char}{ind}" in content for ind in death_indicators)
            char_alive_after = any(f"{char}{ind}" in content for ind in alive_indicators)
            if char_death and char_alive_after:
                # 找到死亡描写和复活描写的相对位置
                death_pos = max(
                    (content.find(f"{char}{ind}") for ind in death_indicators if f"{char}{ind}" in content),
                    default=-1,
                )
                alive_pos = min(
                    (content.find(f"{char}{ind}") for ind in alive_indicators if f"{char}{ind}" in content),
                    default=-1,
                )
                if death_pos >= 0 and alive_pos >= 0 and death_pos < alive_pos:
                    violations.append(ContractViolation(
                        severity="高", category="时间",
                        message=f"{char} 先有死亡/倒下描写后有苏醒/站起描写，可能存在事件顺序矛盾",
                        evidence=f"死亡词位置={death_pos}，苏醒词位置={alive_pos}",
                    ))


def format_violations_report(violations: List[ContractViolation]) -> str:
    """格式化违反报告"""
    if not violations:
        return "✅ 契约校验通过，未发现违反"

    high = [v for v in violations if v.severity == "高"]
    mid = [v for v in violations if v.severity == "中"]
    low = [v for v in violations if v.severity == "低"]

    lines = [f"📋 契约校验：发现 {len(violations)} 个问题（高{len(high)} 中{len(mid)} 低{len(low)}）"]
    for v in violations:
        lines.append(f"  {v}")
    return "\n".join(lines)
