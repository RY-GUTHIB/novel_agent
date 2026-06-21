"""
reviewer_agent.py - 审校 Agent

职责：
1. 检查生成章节的连续性（时间线/空间线/人物状态）
2. 检查伏笔回收情况
3. 评估章节质量（情节推进、人物塑造、文笔）
4. 给出修改建议
"""

import re
import json
import logging
from typing import Dict

import config
from novel_agent.core.memory import MemoryManager
from novel_agent.core.continuity import ContinuityGuard
from novel_agent.core.foreshadow import ForeshadowTracker
from novel_agent.llm.client import generate
from .prompts import REVIEWER_SYSTEM_PROMPT, REVIEWER_USER_PROMPT, ANTI_AI_WRITING_RULES


logger = logging.getLogger(__name__)


class ReviewerAgent:
    """审校 Agent"""

    def __init__(self, memory_mgr: MemoryManager,
                  continuity_guard: ContinuityGuard,
                  foreshadow_tracker: ForeshadowTracker):
        self.memory = memory_mgr
        self.continuity = continuity_guard
        self.foreshadow = foreshadow_tracker

    def _build_anti_ai_rules(self) -> str:
        if not config.ENABLE_ANTI_AI_MODE:
            return "（未启用）"
        cfg = config.ANTI_AI_CONFIG
        lines = [
            ANTI_AI_WRITING_RULES,
            f"\n> 当前密度红线：每 {cfg['check_window']} 字 ≤ {cfg['density_limit']} 次",
            f"> 高光场景慎用词：{'、'.join(cfg['high_stakes_words'])}",
        ]
        return "\n".join(lines)

    def review_chapter(self, chapter: int, title: str, content: str,
                        temperature: float = 0.3,
                        logic_constraints: str = "",
                        characters: list = None) -> Dict:
        # 构建空间位置上下文
        spatial_lines = []
        all_chars = set(cl.character for cl in self.continuity.character_locations)
        for char in sorted(all_chars):
            last_loc = self.continuity.get_character_location(char, chapter - 1)
            if last_loc:
                char_recs = [cl for cl in self.continuity.character_locations
                             if cl.character == char and cl.chapter <= chapter - 1]
                last_rec = sorted(char_recs, key=lambda x: (x.chapter, x.scene or ''))[-1] if char_recs else None
                note = f"（{last_rec.note}）" if last_rec and last_rec.note else ""
                spatial_lines.append(f"  {char}：{last_loc}{note}")

        # 构建状态快照（含承诺清单，从 continuity 取时间线事件）
        timeline_events = self.continuity.timeline if self.continuity else None
        state_snapshot = self.memory.build_state_snapshot(chapter, characters or [], timeline_events)

        anti_ai_rules = self._build_anti_ai_rules()
        user_prompt = REVIEWER_USER_PROMPT.format(
            chapter=chapter, title=title, content=content,
            continuity_prompt=self.continuity.generate_continuity_prompt(
                chapter,
                plot_rules_text=self.memory.get_active_rules_prompt(),
                character_knowledge_text=self.memory.get_character_knowledge_prompt(chapter=chapter),
            ),
            character_prompts=self.memory.get_all_characters_prompt() or "（无）",
            sect_factions=self.memory.get_sect_factions_prompt(),
            scene_events=self.memory.get_scene_events_prompt(chapter=chapter),
            spacemap_prompt=self.continuity.get_spacemap_prompt(),
            spatial_context="\n".join(spatial_lines) if spatial_lines else "（无记录）",
            foreshadow_summary=self.foreshadow.summarize(),
            style_prompt=self.memory.get_style_prompt(),
            logic_constraints=logic_constraints or "（无特殊逻辑约束）",
            state_snapshot=state_snapshot,
            anti_ai_rules=anti_ai_rules,
        )

        response = generate(
            system_prompt=REVIEWER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=4096,
        )

        return self._parse_review(response)

    def _parse_review(self, text: str) -> Dict:
        scores = {}
        overall_score = 0
        verdict = "需修改"

        # 优先：从末尾 JSON 块解析
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group(1))
                field_map = {
                    "continuity": "连续性", "cultivation": "修为连贯性", "spatial": "空间连续性",
                    "character": "人物一致性", "foreshadow": "伏笔管理", "plot": "情节推进",
                    "writing": "文笔质量", "rules": "规则一致性", "knowledge": "角色认知一致性",
                    "acquaintance": "角色相识一致性", "personality": "性格一致性",
                    "emotion": "情绪价值", "comparison": "实力对比逻辑", "recall": "前文回忆真实性",
                    "time": "时间一致性",
                    "style_consistency": "风格一致性",
                    "fact_check": "事实一致性",
                    "ai_density": "AI疲劳词汇密度",
                }
                for key, cn_name in field_map.items():
                    if key in parsed:
                        scores[cn_name] = int(parsed[key])
                overall_score = int(parsed.get("overall", 0))
                v = parsed.get("verdict", "")
                if v:
                    verdict = v
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                logger.warning(f"审校 JSON 解析失败，回退到正则: {e}")

        # Fallback：正则
        if not scores:
            for name, score in re.findall(r'-\s*(\S+?)\s*[：:]\s*(\d+)分', text):
                scores[name] = int(score)

        # 提取问题
        issues = []
        patches = []  # 定向修补用：{severity, description, location_keyword}
        # 匹配严重性标签：⚠️ [严重性：高] 或 ⚠️ 严重性：中
        for severity, desc in re.findall(r'⚠️\s*\[?严重性\s*[：:]\s*(\S+?)\]?\s*\n?(.*?)(?=\n⚠️|\n\n|$)', text, re.MULTILINE | re.DOTALL):
            desc_clean = desc.strip()
            issues.append({"severity": severity, "description": desc_clean})
            # 提取定位关键词
            kw_match = re.search(r'定位[：:]\s*关键词[「"](.+?)[」"]', desc_clean)
            if kw_match:
                patches.append({
                    "severity": severity,
                    "description": desc_clean,
                    "location_keyword": kw_match.group(1),
                })
        if not issues:
            for line in text.split("\n"):
                if "⚠️" in line or "警告" in line or "问题" in line:
                    issues.append({"severity": "中", "description": line.strip()})

        # 结论：优先以 JSON 中的 verdict 为准
        # JSON 未解析到 verdict 时，回退到正文关键词判断
        if not verdict:
            if "通过" in text and "不通过" not in text:
                verdict = "通过"
            elif "重写" in text or "需重写" in text:
                verdict = "需重写"
            else:
                verdict = "需修改"

        if scores and not overall_score:
            overall_score = sum(scores.values()) // max(len(scores), 1)

        return {
            "raw_text": text,
            "scores": scores,
            "overall_score": overall_score,
            "issues": issues,
            "patches": patches,
            "verdict": verdict,
            "passed": verdict == "通过",
        }

    def save_review_report(self, chapter: int, report: Dict, output_dir: str):
        from pathlib import Path
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        report_path = out_dir / f"review_chapter_{chapter:03d}.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"# 第{chapter}章 审校报告\n\n{report['raw_text']}")
