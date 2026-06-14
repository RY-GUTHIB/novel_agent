"""
reviewer_agent.py - 审校 Agent

职责：
1. 检查生成章节的连续性（时间线/空间线/人物状态）
2. 检查伏笔回收情况
3. 评估章节质量（情节推进、人物塑造、文笔）
4. 给出修改建议
"""

from typing import Dict, List
from memory import MemoryManager
from continuity import ContinuityGuard
from foreshadow import ForeshadowTracker
from generator import generate
import config


REVIEWER_SYSTEM_PROMPT = """你是一位资深小说审校编辑，负责检查小说章节的质量和问题。

请从以下维度审校：

1. 【连续性】时间线、空间线、人物位置是否自洽？
2. 【修为连贯性】人物修为/境界描写是否与已有档案一致？有无前后矛盾（如：上一章还说是炼气期，本章突然出现筑基期能力却无突破描写）？
3. 【空间连续性】人物位置变化是否合理？如果人物从A地到了B地，是否有交代移动过程？有无瞬移？移动方式是否与修为匹配（如炼气期不该远距离御剑）？行程时间是否合理？
4. 【人物一致性】人物言行是否符合其性格和语言风格？
5. 【伏笔管理】有无埋下新伏笔？有无兑现旧伏笔？伏笔是否合理？
6. 【情节推进】本章是否有效推进了主线/支线情节？
7. 【文笔质量】文笔是否流畅？对话是否自然？描写是否生动？
8. 【规则一致性】角色行为是否违反了正文中已明确声明的规则/规矩/约定？例如：如果某角色宣布"凡领悟剑意者直接入内门"，那么任何领悟剑意的人都不应该还需要参加外门试炼。如果出现违反，必须列为高严重性问题。
9. 【角色认知一致性】角色对某信息的反应是否与其已知认知一致？例如：如果角色A在第3章已经知道叶青云是叶无痕的儿子，那么第4章角色A不应再对"叶青云是叶无痕的儿子"表现惊讶。如果角色A不知道某信息，也不应使用该信息做决策。如果出现矛盾，必须列为高严重性问题。

输出格式（严格按此格式）：

## 评分（1-10分）
- 连续性：X分
- 修为连贯性：X分
- 空间连续性：X分
- 人物一致性：X分
- 伏笔管理：X分
- 情节推进：X分
- 文笔质量：X分
- 规则一致性：X分
- 角色认知一致性：X分
- 总分：X分

## 问题列表
（列出所有发现的问题，每个问题一行，格式：⚠️ [严重性：高/中/低] 问题描述）

## 修改建议
（针对每个问题给出具体修改建议）

## 是否通过
通过 / 需修改 / 需重写
"""

REVIEWER_USER_PROMPT = """请审校第{chapter}章：{title}

## 审校重点提醒
- 【空间连续性】请逐一核对本章中所有人物的位置变化：①前一章末尾在A地，本章开头在B地，是否有交代移动过程？②本章内人物换场景，是否有过渡描写？③是否存在"瞬移"（两地不相邻且无传送手段）？④移动方式是否与人物修为匹配（如炼气期不能远距离御剑）？
- 【修为连贯性】请逐一核对本章中所有涉及人物修为/境界的描写，与"人物档案"中的修为记录对比。如果发现矛盾（如：档案记录某人物是炼气期，但本章描写其施展了只有筑基期才能用的招式），必须列为⚠️问题。
- 【规则一致性】请逐一核对本章中角色的行为/决定是否违反了"当前生效的剧情规则"。如果正文中已声明某规则（如"凡领悟剑意者直接入内门"），而本章角色的行为违反了该规则（如领悟了剑意却还需参加外门试炼），必须列为⚠️高严重性问题。
- 【角色认知一致性】请逐一核对本章中角色的反应是否与"角色已知信息"矛盾。如果某角色在前文已经知道了某件事，本章中该角色对这件事不应表现出惊讶、好奇或首次获知的反应。例如：角色A在第3章已知道叶青云是叶无痕的儿子，第4章角色A不应再说"你是叶无痕的儿子？"表现惊讶。如果发现矛盾，必须列为⚠️高严重性问题。
- 【连续性】时间线、空间线、人物位置是否自洽？
- 【人物一致性】人物言行是否符合其性格和语言风格？

## 本章正文
{content}

## 前文连续性摘要
{continuity_prompt}

## 人物档案（含当前修为记录）
{character_prompts}

## 人物空间位置记录（前一章末尾位置）
{spatial_context}

## 当前生效的剧情规则
{plot_rules}

## 角色已知信息
{character_knowledge}

## 伏笔状态
{foreshadow_summary}

请进行审校。"""


class ReviewerAgent:
    """审校 Agent"""

    def __init__(self,
                  memory_mgr: MemoryManager,
                  continuity_guard: ContinuityGuard,
                  foreshadow_tracker: ForeshadowTracker):
        self.memory = memory_mgr
        self.continuity = continuity_guard
        self.foreshadow = foreshadow_tracker

    def review_chapter(self,
                       chapter: int,
                       title: str,
                       content: str,
                       temperature: float = 0.3) -> Dict:
        """
        审校章节，返回审校报告
        :return: {"scores": {...}, "issues": [...], "suggestions": [...], "verdict": "..."}
        """
        # 构建 prompt
        character_prompts = self.memory.get_all_characters_prompt()
        continuity_prompt = self.continuity.generate_continuity_prompt(
            chapter,
            plot_rules_text=self.memory.get_active_rules_prompt(),
            character_knowledge_text=self.memory.get_character_knowledge_prompt(chapter=chapter),
        )
        foreshadow_summary = self.foreshadow.summarize()

        # 构建空间位置上下文
        spatial_lines = []
        # 获取前一章末尾的人物位置
        all_chars = set()
        for cl in self.continuity.character_locations:
            all_chars.add(cl.character)
        for char in sorted(all_chars):
            last_loc = self.continuity.get_character_location(char, chapter - 1)
            if last_loc:
                # 找最近记录的移动方式
                char_recs = [cl for cl in self.continuity.character_locations
                           if cl.character == char and cl.chapter <= chapter - 1]
                last_rec = sorted(char_recs, key=lambda x: (x.chapter, x.scene or ''))[-1] if char_recs else None
                note = f"（{last_rec.note}）" if last_rec and last_rec.note else ""
                spatial_lines.append(f"  {char}：{last_loc}{note}")
        spatial_context = "\n".join(spatial_lines) if spatial_lines else "（无记录）"

        user_prompt = REVIEWER_USER_PROMPT.format(
            chapter=chapter,
            title=title,
            content=content,
            continuity_prompt=continuity_prompt,
            character_prompts=character_prompts if character_prompts else "（无）",
            spatial_context=spatial_context,
            plot_rules=self.memory.get_active_rules_prompt(),
            character_knowledge=self.memory.get_character_knowledge_prompt(chapter=chapter),
            foreshadow_summary=foreshadow_summary,
        )

        response = generate(
            system_prompt=REVIEWER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=temperature,  # 审校用低温度，保持客观
            max_tokens=4096,
        )

        # 解析审校报告
        report = self._parse_review(response)
        return report

    def _parse_review(self, text: str) -> Dict:
        """解析审校报告文本为结构化数据"""
        import re

        # 提取评分
        scores = {}
        score_match = re.findall(r'-\s*(\S+?)\s*[：:]\s*(\d+)分', text)
        for name, score in score_match:
            scores[name] = int(score)

        # 提取问题
        issues = []
        issue_matches = re.findall(r'⚠️\s*\[?严重性\s*[：:]\s*(\S+?)\]?\s*(.*?)(?=\n|$)', text, re.MULTILINE)
        for severity, desc in issue_matches:
            issues.append({"severity": severity, "description": desc.strip()})

        # 备选：直接找 ⚠️ 行
        if not issues:
            for line in text.split("\n"):
                if "⚠️" in line or "警告" in line or "问题" in line:
                    issues.append({"severity": "中", "description": line.strip()})

        # 提取结论
        verdict = "需修改"
        if "通过" in text and "不通过" not in text:
            verdict = "通过"
        elif "重写" in text or "需重写" in text:
            verdict = "需重写"

        # 计算总分
        overall_score = 0
        if scores:
            overall_score = sum(scores.values()) // max(len(scores), 1)

        return {
            "raw_text": text,
            "scores": scores,
            "overall_score": overall_score,
            "issues": issues,
            "verdict": verdict,
            "passed": verdict == "通过",
        }

    def save_review_report(self, chapter: int, report: Dict,
                           output_dir: str = None):
        """保存审校报告到文件"""
        from pathlib import Path
        out_dir = Path(output_dir or config.OUTPUT_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)

        report_path = out_dir / f"review_chapter_{chapter:03d}.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"# 第{chapter}章 审校报告\n\n")
            f.write(report["raw_text"])
