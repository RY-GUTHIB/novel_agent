"""
backfill_rules.py - 补录 Ch1-20 的剧情规则到 plot_rules.json
"""
import json
import sys
from pathlib import Path

import config

project_name = sys.argv[1] if len(sys.argv) > 1 else "苍穹独狼"
DATA_DIR = config.PROJECTS_ROOT / project_name / "data"

rules = [
    {
        "condition": "在天剑碑前领悟剑意",
        "consequence": "直接入内门",
        "rule_text": "凡能在天剑碑前领悟剑意者，可直接入内门",
        "chapter_introduced": 3,
        "source_character": "执事",
        "overridden": False,
        "override_reason": "",
    },
    {
        "condition": "未领悟剑意的新弟子",
        "consequence": "编入外门，半年后外门试炼优胜者方可进入内门",
        "rule_text": "其余人等，一律编入外门，半年后进行外门试炼，优胜者方可进入内门",
        "chapter_introduced": 3,
        "source_character": "执事",
        "overridden": False,
        "override_reason": "",
    },
    {
        "condition": "外门试炼前十名",
        "consequence": "进入内门",
        "rule_text": "外门试炼只有前十名才能进入内门",
        "chapter_introduced": 3,
        "source_character": "青玄上人",
        "overridden": False,
        "override_reason": "",
    },
]

# 读取已有的 plot_rules.json（如果存在）
plot_rules_path = DATA_DIR / "plot_rules.json"
existing = {}
if plot_rules_path.exists():
    with open(plot_rules_path, "r", encoding="utf-8") as f:
        existing = json.load(f)

# 写入新规则（按 condition 去重）
for rule in rules:
    key = rule["condition"]
    existing[key] = rule

with open(plot_rules_path, "w", encoding="utf-8") as f:
    json.dump(existing, f, ensure_ascii=False, indent=2)

print(f"已写入 {len(rules)} 条剧情规则到 {plot_rules_path}")
