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

    def __init__(self):
        # 立场矛盾的关键词对
        self._hostile_keywords = ["敌", "仇", "杀", "恨", "怒目", "冷哼", "不屑", "嘲讽", "蔑视"]
        self._friendly_keywords = ["笑", "亲", "握", "拥", "温柔", "关切", "感激", "信任", "默契", "并肩"]

    def validate(self, content: str, chapter: int, characters: List[str],
                  memory_mgr, foreshadow_tracker=None) -> List[ContractViolation]:
        """
        对生成的正文进行契约校验
        :return: 违反列表（空 = 无问题）
        """
        violations: List[ContractViolation] = []

        self._check_dead_characters(content, chapter, characters, memory_mgr, violations)
        self._check_relationship_stance(content, chapter, characters, memory_mgr, violations)
        self._check_knowledge_surprise(content, chapter, characters, memory_mgr, violations)
        self._check_plot_rules(content, chapter, memory_mgr, violations)
        self._check_spatial_teleport(content, chapter, characters, memory_mgr, violations)

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
                action_pattern = rf'{re.escape(name)}(?:说|道|笑|怒|走|站|坐|飞|拔|挥|喝|笑|冷|热|点头|摇头)'
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
        paragraphs = re.split(r'\n\s*\n', content)
        results = []
        for para in paragraphs:
            if a in para and b in para and len(para) > 10:
                results.append(para)
        return results

    # ========== 3. 认知矛盾 ==========

    def _check_knowledge_surprise(self, content, chapter, characters, mem, violations):
        """检查角色是否对已知信息表现出惊讶"""
        surprise_patterns = [
            r'惊讶', r'震惊', r'大吃一惊', r'不敢相信', r'难以置信',
            r'瞪大了眼', r'目瞪口呆', r'倒吸一口冷气', r'什么[？?！!]',
            r'你.{0,5}(竟然|居然|原来)', r'(竟然|居然|原来)是',
            r'(不|没)想到', r'(不|没)曾想',
        ]

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
                    has_surprise = any(re.search(p, para) for p in surprise_patterns)

                    if has_keyword and has_surprise:
                        violations.append(ContractViolation(
                            severity="高", category="认知",
                            message=f"{name} 对已知信息「{knowledge.knowledge[:30]}」表现出惊讶（第{knowledge.chapter_learned}章已知）",
                            evidence=para[:80],
                        ))
                        break  # 每个角色每段只报一次

    def _find_character_paragraphs(self, content: str, name: str) -> List[str]:
        """找到包含某角色名字的段落"""
        paragraphs = re.split(r'\n\s*\n', content)
        return [p for p in paragraphs if name in p and len(p) > 10]

    def _extract_keywords(self, knowledge: str) -> List[str]:
        """从知识描述中提取关键词"""
        # 去掉常见虚词，取 2-4 字的核心名词
        knowledge = re.sub(r'[，。、的是了在有和与或]', ' ', knowledge)
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
        location_pattern = r'(?:来到|抵达|到达|出现在|站在|坐在|走进|飞入)([^，。,.\n]{2,8})'
        locations_mentioned = re.findall(location_pattern, content)

        if locations_mentioned:
            has_travel = any(kw in content for kw in travel_keywords)
            if not has_travel and len(locations_mentioned) >= 2:
                # 多个地点出现但无移动描写
                violations.append(ContractViolation(
                    severity="中", category="空间",
                    message=f"正文中提到 {len(locations_mentioned)} 个地点但未发现移动描写，可能存在瞬移",
                    evidence=f"地点：{', '.join(locations_mentioned[:3])}",
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
