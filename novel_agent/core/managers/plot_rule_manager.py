from pathlib import Path
from typing import Dict

from ..models import PlotRule
from ..file_utils import JsonRepositoryMixin


class PlotRuleManager(JsonRepositoryMixin):
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self._rules: Dict[str, PlotRule] = {}
        self._load()

    def _load(self):
        data = self._load_json("plot_rules.json")
        if isinstance(data, list):
            data = {r.get("condition", f"rule_{i}"): r for i, r in enumerate(data) if isinstance(r, dict)}
        self._rules = {}
        for key, d in data.items():
            self._rules[key] = PlotRule(**d)

    def save(self):
        data = {k: v.__dict__ if hasattr(v, '__dict__') else {} for k, v in self._rules.items()}
        self._save_json("plot_rules.json", data)

    def all(self) -> Dict[str, PlotRule]:
        return self._rules

    def add(self, rule: PlotRule):
        self._rules[rule.condition] = rule
        self.save()

    def get_active_prompt(self) -> str:
        active_rules = [r for r in self._rules.values() if not r.overridden]
        if not active_rules:
            return "（无特殊剧情规则）"
        lines = ["【当前生效的剧情规则（角色行为必须遵守）】"]
        for r in active_rules:
            source = f"（{r.source_character}于第{r.chapter_introduced}章声明）" if r.source_character else f"（第{r.chapter_introduced}章声明）"
            lines.append(f"  ⚖️ IF「{r.condition}」→ THEN「{r.consequence}」{source}")
            lines.append(f"     原文：「{r.rule_text}」")
        lines.append("\n⚠️ 以上规则已被正文明确声明，后续章节中角色行为必须遵守，不得违反。如需修改规则，必须在正文中给出合理解释并标记覆盖。")
        return "\n".join(lines)
